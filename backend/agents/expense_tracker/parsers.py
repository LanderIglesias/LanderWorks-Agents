"""parsers.py — Extracción de merchant/amount desde el texto crudo de emails.

Es la pieza más frágil del sistema (ver README_expense_tracker.md): cada
regex está atado al formato exacto de una plantilla de email que ni
Laboral Kutxa ni PayPal garantizan mantener estable. Por eso ambas funciones
siguen la misma regla: si el regex no encuentra un match limpio, devuelven
None en vez de lanzar una excepción o adivinar un valor a medias. Quien
llama (engine.ingest_webhook) es responsable de guardar el raw_text con
needs_review=True cuando esto pasa — el dato nunca se pierde, solo queda
sin parsear.

Los patrones de abajo están escritos sobre el formato típico documentado de
cada remitente. En cuanto tengas emails reales guardados, ajusta los regex
contra esos ejemplos exactos (ese es justamente el propósito de
tests/expense_tracker/test_parsers.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Resultado común ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedExpense:
    merchant: str
    amount: float


# ── Laboral Kutxa (postamail@laboralkutxa.com) ──────────────────────────
#
# Formato típico de aviso de movimiento con tarjeta:
#   "Movimiento con tarjeta ...1234 en MERCADONA por importe de 23,45 EUR"
# El importe usa coma decimal (formato español); el comercio es todo lo que
# hay entre "en" y "por importe de".

_BANK_AMOUNT_RE = re.compile(
    r"importe\s+de\s+([\d.]+,\d{2})\s*(?:EUR|€)",
    re.IGNORECASE,
)
_BANK_MERCHANT_RE = re.compile(
    r"\ben\s+(.+?)\s+por\s+importe",
    re.IGNORECASE,
)


def parse_bank_email(raw_text: str | None) -> ParsedExpense | None:
    """Parsea un email de aviso de movimiento de Laboral Kutxa.

    Devuelve None (nunca lanza) si raw_text es vacío/None o si alguno de
    los dos regex no encuentra match — p. ej. porque el banco cambió la
    redacción de la plantilla del email.
    """
    if not raw_text or not raw_text.strip():
        return None

    amount_match = _BANK_AMOUNT_RE.search(raw_text)
    merchant_match = _BANK_MERCHANT_RE.search(raw_text)
    if not amount_match or not merchant_match:
        return None

    amount = _parse_spanish_decimal(amount_match.group(1))
    if amount is None:
        return None

    merchant = merchant_match.group(1).strip()
    if not merchant:
        return None

    return ParsedExpense(merchant=merchant, amount=amount)


# ── PayPal ───────────────────────────────────────────────────────────────
#
# Formato típico de aviso de pago:
#   "Has pagado 12,00 EUR a NETFLIX"
# o la variante en inglés "You paid €12.00 to NETFLIX" — cubrimos ambas
# porque PayPal manda el idioma según la configuración de la cuenta.

_PAYPAL_ES_RE = re.compile(
    r"has\s+pagado\s+([\d.]+,\d{2})\s*(?:EUR|€)\s+a\s+(.+?)(?:[.\n]|$)",
    re.IGNORECASE,
)
_PAYPAL_EN_RE = re.compile(
    r"you\s+paid\s+(?:€|EUR\s*)?(\d+\.\d{2})\s+to\s+(.+?)(?:[.\n]|$)",
    re.IGNORECASE,
)


def parse_paypal_email(raw_text: str | None) -> ParsedExpense | None:
    """Parsea un email de aviso de pago de PayPal (ES o EN).

    Igual que parse_bank_email: None ante cualquier formato inesperado o
    texto vacío, nunca una excepción sin controlar.
    """
    if not raw_text or not raw_text.strip():
        return None

    match = _PAYPAL_ES_RE.search(raw_text)
    if match:
        amount = _parse_spanish_decimal(match.group(1))
    else:
        match = _PAYPAL_EN_RE.search(raw_text)
        amount = _parse_english_decimal(match.group(1)) if match else None

    if not match or amount is None:
        return None

    merchant = match.group(2).strip()
    if not merchant:
        return None

    return ParsedExpense(merchant=merchant, amount=amount)


# ── Helpers de formato numérico ──────────────────────────────────────────


def _parse_spanish_decimal(value: str) -> float | None:
    """ "1.234,56" o "23,45" -> float. None si no es un número válido."""
    try:
        return float(value.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_english_decimal(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None
