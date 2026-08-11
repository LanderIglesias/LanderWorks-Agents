"""Tests de security.py — Bearer token + timestamp del webhook, y token de
la PWA.

Los casos del webhook se ejercitan contra el endpoint real POST
/webhook/expense (no solo contra verify_webhook_signature en aislado), para
verificar también que una petición válida efectivamente crea una fila y que
una rechazada no crea ninguna.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agents.expense_tracker import api as et_api
from backend.agents.expense_tracker import engine as et_engine
from backend.agents.expense_tracker.database import Base, Expense, get_db

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
    # Evita llamadas reales a Claude durante ingest_webhook.
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


def _webhook_headers(timestamp: str, token: str = WEBHOOK_SECRET) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Timestamp": timestamp,
    }


def _webhook_payload() -> dict:
    return {
        "source": "wallet",
        "merchant": "MERCADONA",
        "amount": 12.34,
        "occurred_at": "2026-08-10T12:00:00",
    }


def _row_count(db) -> int:
    return db.query(Expense).count()


# ── Autenticación del webhook (Bearer token + timestamp) ────────────────


def test_webhook_valid_token_within_window_creates_row(client):
    body = json.dumps(_webhook_payload())
    timestamp = str(int(time.time()))

    response = client.post(
        "/expense-tracker/webhook/expense", content=body, headers=_webhook_headers(timestamp)
    )

    assert response.status_code == 200
    db = TestingSessionLocal()
    try:
        assert _row_count(db) == 1
    finally:
        db.close()


def test_webhook_wrong_token_rejected_and_no_row_created(client):
    body = json.dumps(_webhook_payload())
    timestamp = str(int(time.time()))

    response = client.post(
        "/expense-tracker/webhook/expense",
        content=body,
        headers=_webhook_headers(timestamp, token="wrong-token"),
    )

    assert response.status_code == 401
    db = TestingSessionLocal()
    try:
        assert _row_count(db) == 0
    finally:
        db.close()


def test_webhook_correct_token_expired_timestamp_rejected(client):
    body = json.dumps(_webhook_payload())
    timestamp = str(int(time.time()) - 120)  # 2 minutos atrás, fuera de la ventana de 60s

    response = client.post(
        "/expense-tracker/webhook/expense", content=body, headers=_webhook_headers(timestamp)
    )

    assert response.status_code == 401
    db = TestingSessionLocal()
    try:
        assert _row_count(db) == 0
    finally:
        db.close()


def test_webhook_correct_token_future_timestamp_rejected(client):
    body = json.dumps(_webhook_payload())
    timestamp = str(int(time.time()) + 120)  # 2 minutos por delante, fuera de la ventana de 60s

    response = client.post(
        "/expense-tracker/webhook/expense", content=body, headers=_webhook_headers(timestamp)
    )

    assert response.status_code == 401
    db = TestingSessionLocal()
    try:
        assert _row_count(db) == 0
    finally:
        db.close()


def test_webhook_missing_headers_rejected(client):
    body = json.dumps(_webhook_payload())

    response = client.post(
        "/expense-tracker/webhook/expense",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401


# ── Token de la PWA ──────────────────────────────────────────────────────


def test_app_token_missing_rejected(client):
    response = client.get("/expense-tracker/expenses/review")

    assert response.status_code == 401


def test_app_token_wrong_rejected(client):
    response = client.get(
        "/expense-tracker/expenses/review", headers={"Authorization": "Bearer wrong-token"}
    )

    assert response.status_code == 401


def test_app_token_correct_accepted(client):
    response = client.get(
        "/expense-tracker/expenses/review", headers={"Authorization": f"Bearer {APP_TOKEN}"}
    )

    assert response.status_code == 200
