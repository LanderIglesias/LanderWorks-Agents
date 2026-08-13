"""Tests de presupuestos mensuales por categoría (GET/PUT /budgets).

Contra el endpoint real vía TestClient (no solo engine.py en aislado) —
mismo motivo que test_webhook_e2e.py: cubre también el wiring de FastAPI,
no solo la lógica de cálculo.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agents.expense_tracker import api as et_api
from backend.agents.expense_tracker import engine as et_engine
from backend.agents.expense_tracker.database import Base, Expense, Source, get_db

APP_TOKEN = "test-app-token"
MONTH = "2026-08"

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


def _auth():
    return {"Authorization": f"Bearer {APP_TOKEN}"}


def _add_expense(db, *, category, amount, needs_review=False, occurred_at="2026-08-05T12:00:00"):
    expense = Expense(
        source=Source.MANUAL,
        merchant="Test",
        amount=amount,
        category=category,
        category_confidence=1.0,
        needs_review=needs_review,
        occurred_at=datetime.fromisoformat(occurred_at),
    )
    db.add(expense)
    db.commit()
    return expense


def test_set_budget_reflected_in_get(client):
    response = client.put(
        f"/expense-tracker/budgets/comida?month={MONTH}",
        json={"limit_amount": 200},
        headers=_auth(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "comida"
    assert body["limit_amount"] == 200.0
    assert body["spent"] == 0.0
    assert body["remaining"] == 200.0

    listed = client.get(f"/expense-tracker/budgets?month={MONTH}", headers=_auth()).json()
    comida = next(b for b in listed if b["category"] == "comida")
    assert comida["limit_amount"] == 200.0

    # Actualizar el mismo (category, month) es un upsert, no una fila nueva.
    response2 = client.put(
        f"/expense-tracker/budgets/comida?month={MONTH}",
        json={"limit_amount": 150},
        headers=_auth(),
    )
    assert response2.json()["limit_amount"] == 150.0
    listed2 = client.get(f"/expense-tracker/budgets?month={MONTH}", headers=_auth()).json()
    assert sum(1 for b in listed2 if b["category"] == "comida") == 1
    assert next(b for b in listed2 if b["category"] == "comida")["limit_amount"] == 150.0


def test_confirmed_expense_counts_as_spent(client):
    db = TestingSessionLocal()
    try:
        _add_expense(db, category="transporte", amount=45.0, needs_review=False)
    finally:
        db.close()

    listed = client.get(f"/expense-tracker/budgets?month={MONTH}", headers=_auth()).json()
    transporte = next(b for b in listed if b["category"] == "transporte")
    assert transporte["spent"] == 45.0


def test_needs_review_expense_does_not_count_as_spent(client):
    db = TestingSessionLocal()
    try:
        # needs_review=True con category asignada por baja confianza: no
        # es una categorización confirmada, no debe contar para nadie.
        _add_expense(db, category="ocio", amount=999.0, needs_review=True)
    finally:
        db.close()

    listed = client.get(f"/expense-tracker/budgets?month={MONTH}", headers=_auth()).json()
    ocio = next(b for b in listed if b["category"] == "ocio")
    assert ocio["spent"] == 0.0


def test_category_without_budget_has_null_limit_and_remaining_but_real_spent(client):
    db = TestingSessionLocal()
    try:
        _add_expense(db, category="salud", amount=12.5, needs_review=False)
    finally:
        db.close()

    listed = client.get(f"/expense-tracker/budgets?month={MONTH}", headers=_auth()).json()
    salud = next(b for b in listed if b["category"] == "salud")
    assert salud["limit_amount"] is None
    assert salud["remaining"] is None
    assert salud["spent"] == 12.5


def test_list_budgets_returns_all_seven_categories(client):
    listed = client.get(f"/expense-tracker/budgets?month={MONTH}", headers=_auth()).json()
    assert {b["category"] for b in listed} == {
        "comida",
        "transporte",
        "suscripciones",
        "ocio",
        "salud",
        "hogar",
        "otros",
    }


def test_zero_limit_removes_budget(client):
    client.put(
        f"/expense-tracker/budgets/hogar?month={MONTH}", json={"limit_amount": 100}, headers=_auth()
    )
    response = client.put(
        f"/expense-tracker/budgets/hogar?month={MONTH}", json={"limit_amount": 0}, headers=_auth()
    )
    assert response.json()["limit_amount"] is None

    listed = client.get(f"/expense-tracker/budgets?month={MONTH}", headers=_auth()).json()
    assert next(b for b in listed if b["category"] == "hogar")["limit_amount"] is None


def test_budgets_require_app_token(client):
    response = client.get(f"/expense-tracker/budgets?month={MONTH}")
    assert response.status_code == 401

    response2 = client.put(
        f"/expense-tracker/budgets/comida?month={MONTH}", json={"limit_amount": 50}
    )
    assert response2.status_code == 401
