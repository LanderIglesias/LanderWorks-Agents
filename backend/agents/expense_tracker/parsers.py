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
# Dos formatos soportados:
#
# 1. "importe de X EUR" / "en X por importe" — el formato asumido
#    originalmente, nunca confirmado contra un mensaje real. Se mantiene
#    por si acaso, pero no hay evidencia de que el banco lo use así.
#
# 2. El SMS real confirmado en producción (16/08/2026), formato distinto
#    por completo:
#      "16/08 07:49 pago 1,60eur tarjeta 450827******6010 en EasyPark
#       Espana S.L.U.e. Para bloquear tarjeta envia BLK al 217377"
#    Importe pegado a "eur" sin espacio ("1,60eur"), y el comercio va
#    entre "en" y el pie fijo antifraude "Para bloquear tarjeta envia BLK
#    al <número>" — ese pie parece constante en los SMS transaccionales
#    de Laboral Kutxa, así que se usa como límite derecho de la captura.
#    "pago"/"cobro" (mismas palabras que engine.looks_like_transaction)
#    aparecen justo antes del importe, pero no hace falta anclarse ahí:
#    "en ... Para bloquear" ya delimita el comercio sin ambigüedad.

_BANK_AMOUNT_RE = re.compile(
    r"importe\s+de\s+([\d.]+,\d{2})\s*(?:EUR|€)",
    re.IGNORECASE,
)
_BANK_MERCHANT_RE = re.compile(
    r"\ben\s+(.+?)\s+por\s+importe",
    re.IGNORECASE,
)

_BANK_SMS_AMOUNT_RE = re.compile(
    r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*eur\b",
    re.IGNORECASE,
)
_BANK_SMS_MERCHANT_RE = re.compile(
    r"\ben\s+(.+?)\s+para\s+bloquear\b",
    re.IGNORECASE,
)

# Corta el comercio capturado en el primer sufijo de forma jurídica o país
# que aparezca — "EasyPark Espana S.L.U.e." -> "EasyPark". Distinta de
# _MERCHANT_SUFFIX_PATTERNS (engine.py, usada por _normalize_merchant para
# COMPARAR similitud entre nombres ya cortos): aquí se necesita CORTAR una
# cadena más larga con ruido detrás (el país, la forma jurídica completa
# con puntos sueltos tipo "S.L.U.e."), no solo limpiar un nombre aislado
# para comparar — por eso una lista separada en vez de reutilizar esa.
_MERCHANT_TRAILING_NOISE_RE = re.compile(
    r"\s+(?:espa[nñ]a|s\.?a\.?|s\.?l\.?u?\.?|inc\.?|ltd\.?|llc|corp\.?)(?=[\s.]|$).*",
    re.IGNORECASE | re.DOTALL,
)


def parse_bank_email(raw_text: str | None) -> ParsedExpense | None:
    """Parsea un aviso de movimiento de Laboral Kutxa (email o SMS).

    Devuelve None (nunca lanza) si raw_text es vacío/None o si ningún
    formato conocido encuentra match — p. ej. porque el banco cambió la
    redacción de la plantilla.
    """
    if not raw_text or not raw_text.strip():
        return None

    amount_match = _BANK_AMOUNT_RE.search(raw_text)
    merchant_match = _BANK_MERCHANT_RE.search(raw_text)
    if amount_match and merchant_match:
        amount = _parse_spanish_decimal(amount_match.group(1))
        merchant = merchant_match.group(1).strip()
        if amount is not None and merchant:
            return ParsedExpense(merchant=merchant, amount=amount)

    sms_amount_match = _BANK_SMS_AMOUNT_RE.search(raw_text)
    sms_merchant_match = _BANK_SMS_MERCHANT_RE.search(raw_text)
    if sms_amount_match and sms_merchant_match:
        amount = _parse_spanish_decimal(sms_amount_match.group(1))
        merchant = _MERCHANT_TRAILING_NOISE_RE.sub("", sms_merchant_match.group(1)).strip()
        if amount is not None and merchant:
            return ParsedExpense(merchant=merchant, amount=amount)

    return None


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
