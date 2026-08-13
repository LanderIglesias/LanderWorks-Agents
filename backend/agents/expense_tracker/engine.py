"""engine.py — Orquestación: webhook -> parseo -> dedup -> categorización -> persistencia.

También agrega los gastos por día/mes/año para GET /expenses.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import categorizer
from .categorizer import CATEGORIES, CONFIDENCE_THRESHOLD
from .database import Budget, Expense, Source
from .parsers import parse_bank_email, parse_paypal_email
from .schemas import BudgetOut, ExpensePatch, ManualExpenseIn, WebhookExpenseIn

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


# ── Búsqueda y filtro ────────────────────────────────────────────────────


def search_expenses(
    db: Session,
    query: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Lista plana filtrada de gastos — vista distinta de aggregate(), que
    agrupa por día/mes/año. Todos los filtros son opcionales y se combinan
    con AND.

    `query` busca coincidencia parcial case-insensitive en merchant O en
    raw_text: un gasto needs_review sin merchant identificado (el regex de
    parsers.py no encontró comercio) sigue siendo encontrable si el texto
    crudo del email contiene lo buscado — ej. buscar "netflix" debe
    encontrar tanto los ya categorizados como los que quedaron sin
    parsear pero mencionan "Netflix" en el cuerpo del email.

    amount_min/amount_max son inclusive en ambos extremos a propósito: un
    usuario que filtra "entre 10 y 50" espera que un gasto de exactamente
    10€ o 50€ aparezca, no que quede fuera por un límite exclusivo.
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"category inválida: {category!r} (usa una de {CATEGORIES})")

    date_from_d = _parse_date(date_from, "date_from") if date_from else None
    date_to_d = _parse_date(date_to, "date_to") if date_to else None
    if date_from_d is not None and date_to_d is not None and date_from_d > date_to_d:
        raise ValueError("date_from no puede ser posterior a date_to")

    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        raise ValueError("amount_min no puede ser mayor que amount_max")

    if not 1 <= limit <= 200:
        raise ValueError("limit debe estar entre 1 y 200")
    if offset < 0:
        raise ValueError("offset no puede ser negativo")

    filters = []
    if query:
        like_pattern = f"%{query.lower()}%"
        filters.append(
            or_(
                func.lower(Expense.merchant).like(like_pattern),
                func.lower(Expense.raw_text).like(like_pattern),
            )
        )
    if category is not None:
        filters.append(Expense.category == category)
    if date_from_d is not None:
        filters.append(Expense.occurred_at >= datetime.combine(date_from_d, datetime.min.time()))
    if date_to_d is not None:
        # date_to es inclusive: el límite real es el inicio del día SIGUIENTE.
        filters.append(
            Expense.occurred_at
            < datetime.combine(date_to_d, datetime.min.time()) + timedelta(days=1)
        )
    if amount_min is not None:
        filters.append(Expense.amount >= amount_min)
    if amount_max is not None:
        filters.append(Expense.amount <= amount_max)

    base = db.query(Expense).filter(*filters)
    total = base.order_by(None).count()
    rows = base.order_by(Expense.occurred_at.desc()).offset(offset).limit(limit).all()

    return {"total": total, "expenses": rows}


def _parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"{field_name} inválida: {value!r} (usa YYYY-MM-DD)") from e


# ── Presupuestos ─────────────────────────────────────────────────────────


def _spent_by_category(db: Session, month: str) -> dict[str, float]:
    """Gasto real por categoría en `month`, excluyendo needs_review=True.

    Compartida por get_budgets_for_month y get_month_comparison a
    propósito: ambas necesitan exactamente el mismo criterio de "qué
    cuenta como gastado", y duplicar la query sería una forma fácil de
    que un día diverjan sin querer.
    """
    start, end = _month_bounds(month)
    rows = (
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(
            Expense.occurred_at >= start,
            Expense.occurred_at < end,
            Expense.needs_review.is_(False),
            Expense.amount.isnot(None),
        )
        .group_by(Expense.category)
        .all()
    )
    return {category: float(total) for category, total in rows if category}


def get_budgets_for_month(db: Session, month: str) -> list[BudgetOut]:
    """Las 7 categorías con su límite (si hay) y el gasto real del mes.

    `spent` excluye explícitamente needs_review=True: una fila con
    categoría asignada por baja confianza (o sin parsear en absoluto) no
    es una categorización confirmada — dejarla contar inflaría o
    infracontaría el presupuesto con un dato del que el propio sistema no
    se fía todavía. Empieza a contar solo cuando el usuario la confirma
    (needs_review pasa a False vía PATCH /expenses/{id} o al "Confirmar"
    de la cola de revisión). Esto es una decisión de producto — no un
    descuido — coherente con que needs_review ya excluye esas filas de
    cualquier otro cálculo que dependa de la categoría.
    """
    budgets_by_category = {
        b.category: b for b in db.query(Budget).filter(Budget.month == month).all()
    }
    spent_by_category = _spent_by_category(db, month)

    results = []
    for category in CATEGORIES:
        budget = budgets_by_category.get(category)
        spent = round(spent_by_category.get(category, 0.0), 2)
        limit_amount = float(budget.limit_amount) if budget else None
        remaining = round(limit_amount - spent, 2) if limit_amount is not None else None
        results.append(
            BudgetOut(
                category=category,
                month=month,
                limit_amount=limit_amount,
                spent=spent,
                remaining=remaining,
            )
        )
    return results


def set_budget(db: Session, category: str, month: str, limit_amount: float | None) -> None:
    """Crea, actualiza o borra el límite de `category` para `month` (upsert).

    limit_amount None o 0 borra la fila (si existe) en vez de guardar un
    0 — un 0 real sería indistinguible de "presupuesto de gastar cero",
    y lo que pide la spec es "sin límite fijado", que es la ausencia de
    fila, no un límite de 0€.
    """
    if category not in CATEGORIES:
        raise ValueError(f"category inválida: {category!r} (usa una de {CATEGORIES})")
    _month_bounds(month)  # valida el formato "YYYY-MM"; lanza ValueError si no lo es

    existing = db.query(Budget).filter(Budget.category == category, Budget.month == month).first()

    if not limit_amount:
        if existing is not None:
            db.delete(existing)
            db.commit()
        return

    if existing is not None:
        existing.limit_amount = round(limit_amount, 2)
    else:
        db.add(Budget(category=category, month=month, limit_amount=round(limit_amount, 2)))
    db.commit()


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    d = datetime.strptime(month, "%Y-%m")
    start = datetime(d.year, d.month, 1)
    end = datetime(d.year + 1, 1, 1) if d.month == 12 else datetime(d.year, d.month + 1, 1)
    return start, end


def _previous_month(month: str) -> str:
    d = datetime.strptime(month, "%Y-%m")
    prev = datetime(d.year - 1, 12, 1) if d.month == 1 else datetime(d.year, d.month - 1, 1)
    return prev.strftime("%Y-%m")


# ── Comparativa mes a mes ─────────────────────────────────────────────────


def get_month_comparison(db: Session, month: str) -> dict:
    """Compara `month` contra el mes calendario INMEDIATAMENTE anterior
    (si month=2026-08, anterior=2026-07 completo — no "los últimos 30
    días" ni "el mismo día del mes pasado").

    Misma exclusión que get_budgets_for_month: needs_review=True no
    cuenta en ninguno de los dos meses, por la misma razón — una
    categoría sin confirmar no debería mover ni el presupuesto ni la
    comparativa.
    """
    _month_bounds(month)  # valida el formato "YYYY-MM"; lanza ValueError si no lo es
    previous = _previous_month(month)

    spent_current = _spent_by_category(db, month)
    spent_previous = _spent_by_category(db, previous)

    total_actual = round(sum(spent_current.values()), 2)
    total_anterior = round(sum(spent_previous.values()), 2)

    por_categoria = [
        {
            "category": category,
            "actual": round(spent_current.get(category, 0.0), 2),
            "anterior": round(spent_previous.get(category, 0.0), 2),
            "variacion_pct": _variacion_pct(
                spent_current.get(category, 0.0), spent_previous.get(category, 0.0)
            ),
        }
        for category in CATEGORIES
    ]

    return {
        "month": month,
        "previous_month": previous,
        "total_actual": total_actual,
        "total_anterior": total_anterior,
        "variacion_pct": _variacion_pct(total_actual, total_anterior),
        "por_categoria": por_categoria,
    }


def _variacion_pct(actual: float, anterior: float) -> float | None:
    """% de variación de `actual` sobre `anterior`. Positivo = ha subido.

    None (no 0, no infinito) cuando `anterior` es 0 — típicamente el
    primer mes de uso de la app, donde el mes anterior no tiene ningún
    gasto registrado. Una división por cero no tiene un resultado
    matemático razonable, y un "+inf%" o un 0% inventado confundirían al
    usuario más que la ausencia explícita del dato: no hay base sobre la
    que calcular ninguna variación real.
    """
    if anterior <= 0:
        return None
    return round((actual - anterior) / anterior * 100, 1)


# ── Gastos recurrentes ───────────────────────────────────────────────────

# Sufijos comerciales/legales comunes a limpiar del merchant antes de
# comparar similitud — ES/EN, no pretende ser exhaustiva. Ampliable según
# vayan apareciendo más formatos reales en Wallet/emails (ej. "GmbH",
# "Ltda", "Corp"...).
_MERCHANT_SUFFIX_PATTERNS = [
    r"\.com\b",
    r"\bs\.?a\.?\b",
    r"\bs\.?l\.?\b",
    r"\binc\.?\b",
    r"\bltd\.?\b",
    r"\bllc\b",
    r"\bintl\b",
    r"\binternational\b",
    r"\bco\b",
]

RECURRING_SIMILARITY_THRESHOLD = 0.7  # mismo umbral que el desempate de dedup
RECURRING_AMOUNT_TOLERANCE_PCT = 0.15
RECURRING_MONTHS_REQUIRED = 3


def _normalize_merchant(merchant: str | None) -> str:
    """Minúsculas, sin sufijos comerciales comunes, sin puntuación, sin
    dígitos sueltos (número de tienda, referencia de tarjeta...) — para
    que "Netflix.com", "NETFLIX INTL" y "Netflix" normalicen al mismo
    texto antes de compararlos con _merchant_similarity.

    Los sufijos se quitan ANTES de despuntuar (así ".com"/"S.L." siguen
    reconocibles por el patrón); despuntuar antes rompería esos patrones.
    """
    if not merchant:
        return ""
    normalized = merchant.lower()
    for pattern in _MERCHANT_SUFFIX_PATTERNS:
        normalized = re.sub(pattern, " ", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized)  # puntuación restante
    normalized = re.sub(r"\b\d+\b", " ", normalized)  # dígitos sueltos
    return re.sub(r"\s+", " ", normalized).strip()


def _last_n_calendar_months(n: int, reference: date | None = None) -> list[str]:
    """Los últimos `n` meses calendario COMPLETOS antes de `reference`
    (hoy si no se indica) — el mes en curso no cuenta como completo y
    queda excluido. Orden cronológico ascendente, ej. con hoy=2026-08-13
    y n=3: ["2026-05", "2026-06", "2026-07"].
    """
    ref = reference or date.today()
    year, month = ref.year, ref.month
    months = []
    for _ in range(n):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
        months.append(f"{year:04d}-{month:02d}")
    return list(reversed(months))


def _group_by_merchant_similarity(expenses: list[Expense]) -> list[list[Expense]]:
    """Agrupa expenses por similitud de merchant normalizado, reutilizando
    _merchant_similarity (el mismo SequenceMatcher que ya usa
    find_duplicate_candidate para desempatar duplicados) en vez de
    duplicar la comparación.

    Agrupamiento voraz de una sola pasada: cada expense se compara contra
    el merchant normalizado que abrió cada grupo existente, no contra
    todos sus miembros — suficiente para el volumen de datos de un solo
    usuario; no pretende ser un clustering completo.
    """
    groups: list[list[Expense]] = []
    group_keys: list[str] = []

    for expense in expenses:
        normalized = _normalize_merchant(expense.merchant)
        if not normalized:
            continue
        for i, key in enumerate(group_keys):
            if _merchant_similarity(normalized, key) >= RECURRING_SIMILARITY_THRESHOLD:
                groups[i].append(expense)
                break
        else:
            groups.append([expense])
            group_keys.append(normalized)

    return groups


def detect_recurring(db: Session) -> list[dict]:
    """Detecta gastos recurrentes (suscripciones) entre los gastos de los
    últimos 3 meses calendario completos.

    Misma exclusión que presupuestos/comparativa: needs_review=True queda
    fuera — un merchant o importe sin confirmar no debería alimentar una
    detección automática. Un grupo cuenta como recurrente solo si tiene AL
    MENOS una aparición en CADA UNO de los 3 meses (no basta con 3
    apariciones repartidas en 2 meses) y todos sus importes caen dentro de
    ±15% de la media del grupo.
    """
    months = _last_n_calendar_months(RECURRING_MONTHS_REQUIRED)
    start, _ = _month_bounds(months[0])
    _, end = _month_bounds(months[-1])

    rows = (
        db.query(Expense)
        .filter(
            Expense.occurred_at >= start,
            Expense.occurred_at < end,
            Expense.needs_review.is_(False),
            Expense.amount.isnot(None),
            Expense.merchant.isnot(None),
        )
        .order_by(Expense.occurred_at.asc())
        .all()
    )

    results = []
    for group in _group_by_merchant_similarity(rows):
        months_present = {e.occurred_at.strftime("%Y-%m") for e in group}
        if not all(m in months_present for m in months):
            continue  # falta al menos uno de los 3 meses

        amounts = [float(e.amount) for e in group]
        avg_amount = sum(amounts) / len(amounts)
        if avg_amount <= 0:
            continue
        if any(abs(a - avg_amount) / avg_amount > RECURRING_AMOUNT_TOLERANCE_PCT for a in amounts):
            continue  # importes demasiado dispersos para ser la misma suscripción

        # Mismo criterio que merge_duplicate para el merchant "más
        # descriptivo": el más largo del grupo.
        representative = max((e.merchant for e in group), key=len)

        results.append(
            {
                "merchant_representative": representative,
                "amount_avg": round(avg_amount, 2),
                "occurrences": [
                    {
                        "id": e.id,
                        "month": e.occurred_at.strftime("%Y-%m"),
                        "amount": round(float(e.amount), 2),
                    }
                    for e in group
                ],
                "total_monthly_estimate": round(avg_amount, 2),
            }
        )

    return results


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
