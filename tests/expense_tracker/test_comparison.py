"""Tests de comparativa mes a mes (GET /expenses/comparison).

Contra el endpoint real vía TestClient, mismo patrón que el resto de
tests de expense_tracker.
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
from backend.agents.expense_tracker.database import Base, Expense, Source, get_db

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
    monkeypatch.setenv("EXPENSE_TRACKER_APP_TOKEN", APP_TOKEN)


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


def _add(db, *, category, amount, needs_review=False, occurred_at):
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


def _comparison(client, month="2026-08"):
    return client.get(
        "/expense-tracker/expenses/comparison", params={"month": month}, headers=_auth()
    )


def test_variation_pct_correct_with_data_in_both_periods(client):
    db = TestingSessionLocal()
    try:
        # Agosto: 150. Julio: 100. Subida del 50%.
        _add(db, category="comida", amount=100, occurred_at="2026-08-05T10:00:00")
        _add(db, category="transporte", amount=50, occurred_at="2026-08-06T10:00:00")
        _add(db, category="comida", amount=100, occurred_at="2026-07-05T10:00:00")
    finally:
        db.close()

    body = _comparison(client, "2026-08").json()
    assert body["month"] == "2026-08"
    assert body["previous_month"] == "2026-07"
    assert body["total_actual"] == 150.0
    assert body["total_anterior"] == 100.0
    assert body["variacion_pct"] == 50.0


def test_previous_month_with_no_expenses_gives_null_variation_not_error(client):
    db = TestingSessionLocal()
    try:
        _add(db, category="comida", amount=42, occurred_at="2026-08-05T10:00:00")
        # Nada en julio.
    finally:
        db.close()

    response = _comparison(client, "2026-08")
    assert response.status_code == 200
    body = response.json()
    assert body["total_anterior"] == 0.0
    assert body["variacion_pct"] is None

    comida = next(c for c in body["por_categoria"] if c["category"] == "comida")
    assert comida["anterior"] == 0.0
    assert comida["variacion_pct"] is None


def test_needs_review_expenses_excluded_from_both_months(client):
    db = TestingSessionLocal()
    try:
        _add(db, category="ocio", amount=100, occurred_at="2026-08-05T10:00:00")
        _add(db, category="ocio", amount=999, needs_review=True, occurred_at="2026-08-06T10:00:00")
        _add(db, category="ocio", amount=80, occurred_at="2026-07-05T10:00:00")
        _add(db, category="ocio", amount=999, needs_review=True, occurred_at="2026-07-06T10:00:00")
    finally:
        db.close()

    body = _comparison(client, "2026-08").json()
    ocio = next(c for c in body["por_categoria"] if c["category"] == "ocio")
    assert ocio["actual"] == 100.0
    assert ocio["anterior"] == 80.0
    assert body["total_actual"] == 100.0
    assert body["total_anterior"] == 80.0


def test_breakdown_by_category_with_multiple_categories(client):
    db = TestingSessionLocal()
    try:
        _add(db, category="comida", amount=120, occurred_at="2026-08-05T10:00:00")
        _add(db, category="comida", amount=100, occurred_at="2026-07-05T10:00:00")
        _add(db, category="transporte", amount=20, occurred_at="2026-08-05T10:00:00")
        _add(db, category="transporte", amount=40, occurred_at="2026-07-05T10:00:00")
    finally:
        db.close()

    body = _comparison(client, "2026-08").json()
    categories = {c["category"]: c for c in body["por_categoria"]}
    assert set(categories) == {
        "comida",
        "transporte",
        "suscripciones",
        "ocio",
        "salud",
        "hogar",
        "otros",
    }

    comida = categories["comida"]
    assert comida["actual"] == 120.0
    assert comida["anterior"] == 100.0
    assert comida["variacion_pct"] == 20.0

    transporte = categories["transporte"]
    assert transporte["actual"] == 20.0
    assert transporte["anterior"] == 40.0
    assert transporte["variacion_pct"] == -50.0


def test_january_compares_against_previous_december(client):
    db = TestingSessionLocal()
    try:
        _add(db, category="comida", amount=10, occurred_at="2026-01-05T10:00:00")
        _add(db, category="comida", amount=5, occurred_at="2025-12-05T10:00:00")
    finally:
        db.close()

    body = _comparison(client, "2026-01").json()
    assert body["previous_month"] == "2025-12"
    assert body["total_anterior"] == 5.0


def test_comparison_requires_app_token(client):
    response = client.get("/expense-tracker/expenses/comparison", params={"month": "2026-08"})
    assert response.status_code == 401
