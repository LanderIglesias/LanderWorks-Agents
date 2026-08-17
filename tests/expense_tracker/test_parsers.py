"""Tests de parsers.py — la pieza más frágil del sistema (regex sobre
texto de email que ni el banco ni PayPal garantizan mantener estable).

Regla que se está verificando en todos los casos "malos": nunca lanzar una
excepción sin controlar, devolver siempre None ante formato inesperado.
"""

from backend.agents.expense_tracker.parsers import parse_bank_email, parse_paypal_email

# ── Laboral Kutxa ────────────────────────────────────────────────────────


def test_parse_bank_email_well_formed():
    raw_text = (
        "Le informamos de un movimiento con su tarjeta terminada en 1234.\n"
        "Movimiento con tarjeta ...1234 en MERCADONA por importe de 23,45 EUR "
        "el 10/08/2026 a las 12:31.\n"
        "Si no reconoce este movimiento, contacte con su oficina."
    )

    result = parse_bank_email(raw_text)

    assert result is not None
    assert result.merchant == "MERCADONA"
    assert result.amount == 23.45


def test_parse_bank_email_thousands_separator():
    raw_text = "Movimiento con tarjeta ...5678 en EL CORTE INGLES por importe de 1.234,56 EUR"

    result = parse_bank_email(raw_text)

    assert result is not None
    assert result.merchant == "EL CORTE INGLES"
    assert result.amount == 1234.56


def test_parse_bank_sms_real_production_format():
    # Texto EXACTO capturado en producción (source=email_bank,
    # needs_review=True hasta este ajuste) el 16/08/2026 — sin alterar ni
    # un carácter. Formato real de SMS de Laboral Kutxa, distinto del
    # "importe de X EUR" originalmente asumido y nunca confirmado.
    raw_text = (
        "16/08 07:49 pago 1,60eur tarjeta 450827******6010 en EasyPark "
        "Espana S.L.U.e. Para bloquear tarjeta envia BLK al 217377"
    )

    result = parse_bank_email(raw_text)

    assert result is not None
    assert result.merchant == "EasyPark"
    assert result.amount == 1.60


def test_parse_bank_sms_generalizes_to_thousands_amount_and_different_legal_suffix():
    raw_text = (
        "18/08 08:15 pago 1.234,56eur tarjeta 450827******6010 en EL CORTE "
        "INGLES S.A. Para bloquear tarjeta envia BLK al 217377"
    )

    result = parse_bank_email(raw_text)

    assert result is not None
    assert result.merchant == "EL CORTE INGLES"
    assert result.amount == 1234.56


def test_parse_bank_sms_generalizes_to_cobro_and_merchant_without_legal_suffix():
    raw_text = (
        "17/08 12:03 cobro 9,99eur tarjeta 450827******6010 en NETFLIX.COM "
        "Para bloquear tarjeta envia BLK al 217377"
    )

    result = parse_bank_email(raw_text)

    assert result is not None
    assert result.merchant == "NETFLIX.COM"
    assert result.amount == 9.99


def test_parse_bank_email_unexpected_shape_returns_none():
    # El banco cambió la redacción: ya no dice "por importe de".
    raw_text = "Se ha realizado un cargo de 23,45 EUR en MERCADONA con su tarjeta."

    result = parse_bank_email(raw_text)

    assert result is None


def test_parse_bank_email_empty_or_corrupt_returns_none():
    assert parse_bank_email("") is None
    assert parse_bank_email(None) is None
    assert parse_bank_email("   ") is None
    assert parse_bank_email("\x00\x01 texto corrupto sin sentido �") is None


# ── PayPal ───────────────────────────────────────────────────────────────


def test_parse_paypal_email_well_formed_spanish():
    raw_text = "Hola,\n\nHas pagado 12,00 EUR a NETFLIX.\n\nGracias por usar PayPal."

    result = parse_paypal_email(raw_text)

    assert result is not None
    assert result.merchant == "NETFLIX"
    assert result.amount == 12.00


def test_parse_paypal_email_well_formed_english():
    raw_text = "Hi,\n\nYou paid €45.90 to SPOTIFY.\n\nThanks for using PayPal."

    result = parse_paypal_email(raw_text)

    assert result is not None
    assert result.merchant == "SPOTIFY"
    assert result.amount == 45.90


def test_parse_paypal_email_unexpected_shape_returns_none():
    # PayPal cambió a "Pagaste" en vez de "Has pagado".
    raw_text = "Pagaste 12,00 EUR a NETFLIX."

    result = parse_paypal_email(raw_text)

    assert result is None


def test_parse_paypal_email_empty_or_corrupt_returns_none():
    assert parse_paypal_email("") is None
    assert parse_paypal_email(None) is None
    assert parse_paypal_email("###broken###") is None


def test_parse_paypal_email_malformed_amount_returns_none():
    # Importe con formato imposible de interpretar como número.
    raw_text = "Has pagado XX,XX EUR a NETFLIX."

    result = parse_paypal_email(raw_text)

    assert result is None
