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
