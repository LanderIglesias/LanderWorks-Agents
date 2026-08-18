"""Tests del bug real de producción: el Atajo de Transacción de Wallet manda
la variable "Importe" con formato de moneda ("46,98 €", confirmado en
producción con capturas reales de KFC y Mercadona), no como float puro.
WebhookExpenseIn.amount exigía float estricto, así que Pydantic rechazaba
la petición con 422 antes de que ingest_webhook llegara a guardar nada —
ni siquiera como needs_review. Ver schemas.py (WebhookExpenseIn._normalize_amount)
y parsers.py (parse_amount_string).
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
from backend.agents.expense_tracker.database import Base, Expense, get_db
from backend.agents.expense_tracker.parsers import parse_amount_string

WEBHOOK_SECRET = "test-webhook-secret"

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


def _post_wallet(client, merchant: str, amount):
    payload = {
        "source": "wallet",
        "merchant": merchant,
        "amount": amount,
        "occurred_at": "2026-08-19T13:45:00",
    }
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return client.post(
        "/expense-tracker/webhook/expense",
        content=json.dumps(payload),
        headers=_webhook_headers(timestamp),
    )


# ── parsers.parse_amount_string (unidad) ─────────────────────────────────


def test_parse_amount_string_with_space_before_symbol():
    # Formato EXACTO confirmado en producción (KFC/Mercadona).
    assert parse_amount_string("46,98 €") == 46.98


def test_parse_amount_string_without_space():
    assert parse_amount_string("3,50€") == 3.50


def test_parse_amount_string_plain_decimal_point():
    assert parse_amount_string("12.99") == 12.99


def test_parse_amount_string_nonsense_returns_none():
    assert parse_amount_string("texto sin sentido") is None


# ── POST /webhook/expense end-to-end (source=wallet) ─────────────────────


def test_wallet_amount_with_space_before_symbol_is_accepted_and_saved(client):
    # Compra real de KFC, formato exacto confirmado en producción.
    response = _post_wallet(client, "KFC", "46,98 €")

    assert response.status_code == 200
    data = response.json()
    assert data["amount"] == 46.98
    assert data["merchant"] == "KFC"

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).count() == 1
    finally:
        db.close()


def test_wallet_amount_without_space_before_symbol_is_accepted(client):
    response = _post_wallet(client, "Mercadona", "3,50€")

    assert response.status_code == 200
    assert response.json()["amount"] == 3.50


def test_wallet_amount_plain_decimal_point_still_accepted(client):
    response = _post_wallet(client, "Amazon", "12.99")

    assert response.status_code == 200
    assert response.json()["amount"] == 12.99


def test_wallet_amount_already_float_unchanged(client):
    response = _post_wallet(client, "Netflix", 3.5)

    assert response.status_code == 200
    assert response.json()["amount"] == 3.5


def test_wallet_amount_nonsense_string_still_rejected_with_422(client):
    response = _post_wallet(client, "Comercio", "texto sin sentido")

    assert response.status_code == 422

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).count() == 0
    finally:
        db.close()
