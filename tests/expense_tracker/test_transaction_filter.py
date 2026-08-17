"""Tests de los dos filtros de mensajes no guardables en POST /webhook/expense
(source=email_bank): is_verification_code (OTP, lista negra acotada,
se evalúa primero) y looks_like_transaction (lista blanca, todo lo demás).

Laboral Kutxa manda avisos de movimiento por el mismo remitente/canal que
códigos de inicio de sesión u otros SMS no transaccionales. En vez de
reconocer cada tipo de mensaje a excluir, se exige evidencia positiva de
que ES un movimiento real ("pago"/"cobro" + un importe en formato "EUR")
antes de guardar nada — cualquier mensaje no reconocido se descarta por
defecto, salvo que matchee primero el detector de OTP, más específico.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agents.expense_tracker import api as et_api
from backend.agents.expense_tracker import engine as et_engine
from backend.agents.expense_tracker.database import Base, DiscardedMessage, Expense, get_db

WEBHOOK_SECRET = "test-webhook-secret"
APP_TOKEN = "test-app-token"

test_engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("EXPENSE_TRACKER_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("EXPENSE_TRACKER_APP_TOKEN", APP_TOKEN)
    monkeypatch.setattr(
        et_engine.categorizer,
        "categorize",
        lambda merchant, amount: {"category": "otros", "confidence": 1.0},
    )


@pytest.fixture(autouse=True)
def _clean_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(et_api.router)
    et_api.setup_rate_limiting(app)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _webhook_headers(timestamp: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WEBHOOK_SECRET}",
        "X-Timestamp": timestamp,
    }


def _post_webhook(client, raw_text: str):
    payload = {
        "source": "email_bank",
        "raw_text": raw_text,
        "occurred_at": "2026-08-14T09:00:00",
    }
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return client.post(
        "/expense-tracker/webhook/expense",
        content=json.dumps(payload),
        headers=_webhook_headers(timestamp),
    )


# ── engine.looks_like_transaction (unidad) ───────────────────────────────


@pytest.mark.parametrize(
    "raw_text",
    [
        "Ha realizado un pago de 34,18 EUR en MERCADONA con su tarjeta.",
        "Cobro de EUR 12,50 en AMAZON con su tarjeta.",
        # Orden inverso número/EUR y palabra en otra posición de la frase.
        "Aviso: pago realizado. Importe: EUR 8,20. Comercio no identificado.",
    ],
)
def test_looks_like_transaction_true_with_pago_or_cobro_and_eur_amount(raw_text):
    assert et_engine.looks_like_transaction(raw_text) is True


@pytest.mark.parametrize(
    "raw_text",
    [
        # Tiene importe en EUR pero ni "pago" ni "cobro".
        "Movimiento con tarjeta ...1234 por 34,18 EUR en MERCADONA.",
        # Tiene "pago" pero el símbolo €, no el texto "EUR".
        "Ha realizado un pago de 34,18 € en MERCADONA.",
        # Ninguna de las dos señales.
        "Descubre las ventajas de tu nueva tarjeta Laboral Kutxa. Más info en la app.",
        None,
        "",
    ],
)
def test_looks_like_transaction_false_without_both_signals(raw_text):
    assert et_engine.looks_like_transaction(raw_text) is False


# ── engine.is_verification_code (unidad) ─────────────────────────────────


def test_is_verification_code_true_for_otp():
    assert (
        et_engine.is_verification_code(
            "Tu código de verificación es 483920. No compartas este código con nadie."
        )
        is True
    )


# ── POST /webhook/expense end-to-end ─────────────────────────────────────


def test_webhook_pago_with_eur_amount_creates_row(client):
    response = _post_webhook(
        client, "Ha realizado un pago de 34,18 EUR en MERCADONA con su tarjeta."
    )

    assert response.status_code == 200
    data = response.json()
    assert data["needs_review"] is True

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).count() == 1
    finally:
        db.close()


def test_webhook_cobro_with_eur_amount_creates_row(client):
    response = _post_webhook(client, "Cobro de EUR 12,50 en AMAZON con su tarjeta.")

    assert response.status_code == 200
    data = response.json()
    assert data["needs_review"] is True

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).count() == 1
    finally:
        db.close()


def test_webhook_without_pago_or_cobro_keyword_ignored_without_row(client):
    response = _post_webhook(client, "Movimiento con tarjeta ...1234 por 34,18 EUR en MERCADONA.")

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": "not_a_transaction"}

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).count() == 0
    finally:
        db.close()


def test_webhook_verification_code_ignored_by_otp_detector_not_transaction_filter(client):
    response = _post_webhook(
        client, "Tu código de verificación es 483920. No compartas este código con nadie."
    )

    assert response.status_code == 200
    # reason=verification_code_detected, no not_a_transaction — confirma que
    # el detector de OTP (más específico) se evalúa antes que la whitelist.
    assert response.json() == {"status": "ignored", "reason": "verification_code_detected"}

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).count() == 0
    finally:
        db.close()


# ── Auditoría persistente de descartes (DiscardedMessage) ────────────────


def test_verification_code_discard_creates_audit_row_without_raw_text(client):
    raw_text = "Tu código de verificación es 483920. No compartas este código con nadie."
    _post_webhook(client, raw_text)

    db = TestingSessionLocal()
    try:
        rows = db.query(DiscardedMessage).all()
        assert len(rows) == 1
        assert rows[0].source.value == "email_bank"
        assert rows[0].reason == "verification_code"
        assert rows[0].discarded_at is not None
        # DiscardedMessage no tiene columna raw_text en absoluto.
        assert not hasattr(rows[0], "raw_text")
    finally:
        db.close()


def test_not_a_transaction_discard_creates_audit_row_without_raw_text(client):
    raw_text = "Descubre las ventajas de tu nueva tarjeta Laboral Kutxa. Más info en la app."
    _post_webhook(client, raw_text)

    db = TestingSessionLocal()
    try:
        rows = db.query(DiscardedMessage).all()
        assert len(rows) == 1
        assert rows[0].source.value == "email_bank"
        assert rows[0].reason == "not_a_transaction"
        assert not hasattr(rows[0], "raw_text")
    finally:
        db.close()


def test_discarded_messages_endpoint_lists_both_discard_reasons(client):
    _post_webhook(client, "Tu código de verificación es 483920. No compartas este código.")
    _post_webhook(client, "Descubre las ventajas de tu nueva tarjeta Laboral Kutxa.")
    # Un mensaje real NO debe aparecer en el historial de descartes.
    _post_webhook(client, "Ha realizado un pago de 34,18 EUR en MERCADONA con su tarjeta.")

    response = client.get(
        "/expense-tracker/expenses/discarded", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401  # token de app equivocado en este test a propósito

    response = client.get(
        "/expense-tracker/expenses/discarded", headers={"Authorization": f"Bearer {APP_TOKEN}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    reasons = {row["reason"] for row in data}
    assert reasons == {"verification_code", "not_a_transaction"}
    for row in data:
        assert "raw_text" not in row


def test_discarded_messages_requires_app_token(client):
    response = client.get("/expense-tracker/expenses/discarded")
    assert response.status_code == 401
