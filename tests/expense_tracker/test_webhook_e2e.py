"""Tests end-to-end de POST /webhook/expense contra el endpoint real.

Cubre el bug de producción del 2026-08-11: un email de banco cuyo raw_text
no matchea ningún regex de parsers.py se guarda correctamente en BD
(needs_review=True, amount=None — comportamiento documentado y deseado en
README_expense_tracker.md), pero la respuesta HTTP devolvía 500
(ResponseValidationError) porque ExpenseOut.amount estaba declarado como
`float` obligatorio en vez de `float | None`, en contra de la nullability
real de la columna en database.py. El guardado nunca falló — solo la
serialización de la respuesta.
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
from backend.agents.expense_tracker.database import Base, get_db

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


def _webhook_headers(timestamp: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WEBHOOK_SECRET}",
        "X-Timestamp": timestamp,
    }


def test_webhook_unmatched_bank_email_returns_200_with_null_amount(client):
    """El banco cambió la redacción y el regex no matchea nada."""
    payload = {
        "source": "email_bank",
        "raw_text": "Se ha realizado un movimiento con su tarjeta. Consulte el detalle en la app.",
        "occurred_at": "2026-08-11T09:00:00",
    }
    body = json.dumps(payload)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    response = client.post(
        "/expense-tracker/webhook/expense", content=body, headers=_webhook_headers(timestamp)
    )

    assert response.status_code == 200
    data = response.json()
    assert data["needs_review"] is True
    assert data["amount"] is None
    assert data["merchant"] is None
    assert data["raw_text"] == payload["raw_text"]
