"""engine.py — Orquestación: webhook -> parseo -> dedup -> categorización -> persistencia.

También agrega los gastos por día/mes/año para GET /expenses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import categorizer
from .categorizer import CONFIDENCE_THRESHOLD
from .database import Expense, Source
from .parsers import parse_bank_email, parse_paypal_email
from .schemas import ExpensePatch, ManualExpenseIn, WebhookExpenseIn

logger = logging.getLogger(__name__)

# Wallet y el email del banco llegan casi en tiempo real para la misma
# compra real con Apple Pay. Una ventana más ancha (p. ej. 5 minutos)
# aumenta la probabilidad de fusionar dos compras legítimas distintas
# (mismo importe, mismo comercio, pocos minutos de diferencia — dos cafés
# seguidos) en una sola fila, perdiendo una sin dejar rastro. 90s cubre el
# caso normal de latencia entre los dos canales sin ese riesgo.
DEDUP_WINDOW_SECONDS = 90

# Qué canal se busca como posible duplicado del que acaba de llegar.
# Solo Wallet <-> email del banco se cruzan: son las dos formas en que la
# MISMA compra con Apple Pay/tarjeta Laboral Kutxa se notifica dos veces.
# PayPal y el alta manual nunca disparan el otro canal, así que no entran
# en este mapa y no pasan por deduplicación.
_DEDUP_COUNTERPART = {
    Source.WALLET: Source.EMAIL_BANK,
    Source.EMAIL_BANK: Source.WALLET,
}


# ── Webhook ──────────────────────────────────────────────────────────────


def ingest_webhook(db: Session, payload: WebhookExpenseIn) -> Expense:
    if payload.source == Source.WALLET:
        merchant, amount, raw_text, parse_failed = _resolve_wallet(payload)
    elif payload.source in (Source.EMAIL_BANK, Source.EMAIL_PAYPAL):
        merchant, amount, raw_text, parse_failed = _resolve_email(payload)
    else:
        raise ValueError(
            f"ingest_webhook no soporta source={payload.source!r}; usa create_manual_expense"
        )

    if not parse_failed and payload.source in _DEDUP_COUNTERPART:
        candidate = find_duplicate_candidate(
            db,
            source=payload.source,
            amount=amount,
            occurred_at=payload.occurred_at,
            merchant=merchant,
        )
        if candidate is not None:
            return merge_duplicate(
                db,
                existing=candidate,
                incoming_source=payload.source,
                incoming_merchant=merchant,
                incoming_raw_text=raw_text,
            )

    if parse_failed:
        expense = Expense(
            source=payload.source,
            merchant=merchant,
            amount=amount,
            raw_text=raw_text,
            occurred_at=payload.occurred_at,
            needs_review=True,
        )
    else:
        result = categorizer.categorize(merchant, amount)
        expense = Expense(
            source=payload.source,
            merchant=merchant,
            amount=amount,
            category=result["category"],
            category_confidence=result["confidence"],
            raw_text=raw_text,
            occurred_at=payload.occurred_at,
            needs_review=result["confidence"] < CONFIDENCE_THRESHOLD,
        )

    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def _resolve_wallet(payload: WebhookExpenseIn) -> tuple[str | None, float | None, None, bool]:
    """El Atajo de Wallet ya manda merchant/amount estructurados: se guarda directo."""
    if payload.amount is None:
        # Sin importe no hay nada útil que guardar como "estructurado";
        # se trata igual que un parseo fallido para no perder el evento.
        return payload.merchant, None, None, True
    return payload.merchant, round(payload.amount, 2), None, False


def _resolve_email(payload: WebhookExpenseIn) -> tuple[str | None, float | None, str | None, bool]:
    """email_bank / email_paypal traen solo raw_text; se parsea con regex específico."""
    parser = parse_bank_email if payload.source == Source.EMAIL_BANK else parse_paypal_email
    parsed = parser(payload.raw_text)
    if parsed is None:
        return None, None, payload.raw_text, True
    return parsed.merchant, parsed.amount, payload.raw_text, False


# ── Deduplicación ────────────────────────────────────────────────────────


def find_duplicate_candidate(
    db: Session,
    source: Source,
    amount: float,
    occurred_at: datetime,
    merchant: str | None,
) -> Expense | None:
    """Busca una fila ya existente que sea, casi con certeza, el mismo gasto
    real visto por el otro canal (Wallet <-> email del banco).

    Filtra por: canal contrario, mismo importe exacto, dentro de
    DEDUP_WINDOW_SECONDS, y merged_source todavía null (para no volver a
    fusionar una fila que ya es la fusión de un par anterior). Si hay más
    de un candidato en la ventana, se desempata por similitud de texto del
    comercio y se deja constancia en el log de cuál se descartó y por qué,
    porque una fusión equivocada no queda marcada needs_review en ningún
    sitio — es el único fallo del sistema que sería invisible sin este log.
    """
    counterpart = _DEDUP_COUNTERPART.get(source)
    if counterpart is None:
        return None

    window_start = occurred_at - timedelta(seconds=DEDUP_WINDOW_SECONDS)
    window_end = occurred_at + timedelta(seconds=DEDUP_WINDOW_SECONDS)

    candidates = list(
        db.execute(
            select(Expense).where(
                Expense.source == counterpart,
                Expense.amount == amount,
                Expense.merged_source.is_(None),
                Expense.occurred_at >= window_start,
                Expense.occurred_at <= window_end,
            )
        )
        .scalars()
        .all()
    )

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    scored = sorted(
        ((c, _merchant_similarity(c.merchant, merchant)) for c in candidates),
        key=lambda pair: pair[1],
        reverse=True,
    )
    chosen, chosen_score = scored[0]
    logger.info(
        "[ExpenseTracker] multiple dedup candidates for source=%s amount=%s window=%ds: "
        "candidate_ids=%s chosen_id=%s chosen_score=%.2f (tiebreak=merchant_similarity) "
        "discarded=%s",
        source.value,
        amount,
        DEDUP_WINDOW_SECONDS,
        [c.id for c, _ in scored],
        chosen.id,
        chosen_score,
        [(c.id, round(score, 2)) for c, score in scored[1:]],
    )
    return chosen


def merge_duplicate(
    db: Session,
    existing: Expense,
    incoming_source: Source,
    incoming_merchant: str | None,
    incoming_raw_text: str | None,
) -> Expense:
    """Fusiona un evento entrante con una fila ya guardada del mismo gasto real.

    Por qué existe: pagar con Apple Pay usando la tarjeta de Laboral Kutxa
    dispara DOS notificaciones independientes para la MISMA compra — el
    trigger de Transacción de Wallet y el email del banco. Sin esta fusión,
    cada compra con esa tarjeta generaría dos filas en `expenses` e
    inflaría el total gastado. Esta función hace que el segundo evento en
    llegar actualice la fila del primero en vez de crear una nueva.

    incoming_source queda registrado en merged_source: source nunca cambia
    (sigue siendo el canal que creó la fila), pero merged_source != None
    es la señal de que el gasto está confirmado por dos canales
    independientes.
    """
    merchant_before = existing.merchant

    if incoming_merchant and (
        not existing.merchant or len(incoming_merchant) > len(existing.merchant)
    ):
        existing.merchant = incoming_merchant

    if incoming_raw_text and not existing.raw_text:
        existing.raw_text = incoming_raw_text

    existing.merged_source = incoming_source

    # Solo re-categorizamos si la categoría previa no era fiable: si ya
    # había una categoría con confianza suficiente, cambiar solo el
    # comercio (p. ej. de un texto genérico de Wallet a uno más completo
    # del email) no merece gastar otra llamada a Claude.
    if existing.category_confidence is None or existing.category_confidence < CONFIDENCE_THRESHOLD:
        if existing.amount is not None:
            result = categorizer.categorize(existing.merchant, float(existing.amount))
            existing.category = result["category"]
            existing.category_confidence = result["confidence"]
            existing.needs_review = result["confidence"] < CONFIDENCE_THRESHOLD

    db.commit()
    db.refresh(existing)

    logger.info(
        "[ExpenseTracker] merged duplicate: existing_id=%s existing_source=%s "
        "incoming_source=%s amount=%s occurred_at=%s merchant_before=%r merchant_after=%r",
        existing.id,
        existing.source.value,
        incoming_source.value,
        existing.amount,
        existing.occurred_at.isoformat(),
        merchant_before,
        existing.merchant,
    )
    return existing


def _merchant_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ── Alta manual ──────────────────────────────────────────────────────────


def create_manual_expense(db: Session, payload: ManualExpenseIn) -> Expense:
    if payload.category:
        category, confidence, needs_review = payload.category, 1.0, False
    else:
        result = categorizer.categorize(payload.merchant, payload.amount)
        category, confidence = result["category"], result["confidence"]
        needs_review = confidence < CONFIDENCE_THRESHOLD

    expense = Expense(
        source=Source.MANUAL,
        merchant=payload.merchant,
        amount=round(payload.amount, 2),
        currency=payload.currency,
        category=category,
        category_confidence=confidence,
        needs_review=needs_review,
        occurred_at=payload.occurred_at,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


# ── Lectura / edición ────────────────────────────────────────────────────


def get_expense(db: Session, expense_id: int) -> Expense | None:
    return db.get(Expense, expense_id)


def update_expense(db: Session, expense_id: int, patch: ExpensePatch) -> Expense | None:
    expense = db.get(Expense, expense_id)
    if expense is None:
        return None

    if patch.merchant is not None:
        expense.merchant = patch.merchant
    if patch.amount is not None:
        expense.amount = round(patch.amount, 2)
    if patch.category is not None:
        expense.category = patch.category
        expense.needs_review = False
    if patch.needs_review is not None:
        expense.needs_review = patch.needs_review

    db.commit()
    db.refresh(expense)
    return expense


def list_review_queue(db: Session) -> list[Expense]:
    return (
        db.query(Expense)
        .filter(Expense.needs_review.is_(True))
        .order_by(Expense.occurred_at.desc())
        .all()
    )


# ── Agregación ───────────────────────────────────────────────────────────


def aggregate(db: Session, granularity: str, date: str) -> dict:
    """Total, nº de transacciones y lista de gastos del periodo indicado.

    granularity: "day" | "month" | "year". date: "YYYY-MM-DD" — solo se
    usan los componentes relevantes (p. ej. granularity=year ignora el día).
    """
    start, end = _period_bounds(granularity, date)

    rows = (
        db.query(Expense)
        .filter(Expense.occurred_at >= start, Expense.occurred_at < end)
        .order_by(Expense.occurred_at.desc())
        .all()
    )

    total = sum((float(r.amount) for r in rows if r.amount is not None), 0.0)

    return {
        "granularity": granularity,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "total": round(total, 2),
        "count": len(rows),
        "expenses": rows,
    }


def _period_bounds(granularity: str, date: str) -> tuple[datetime, datetime]:
    d = datetime.strptime(date, "%Y-%m-%d")

    if granularity == "day":
        start = datetime(d.year, d.month, d.day)
        end = start + timedelta(days=1)
    elif granularity == "month":
        start = datetime(d.year, d.month, 1)
        end = datetime(d.year + 1, 1, 1) if d.month == 12 else datetime(d.year, d.month + 1, 1)
    elif granularity == "year":
        start = datetime(d.year, 1, 1)
        end = datetime(d.year + 1, 1, 1)
    else:
        raise ValueError(f"granularity inválida: {granularity!r} (usa day|month|year)")

    return start, end
