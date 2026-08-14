"""Tests de DELETE /expenses/{id} (rechazo de la cola de revisión) y
POST /expenses/reset-all (borrado destructivo con salvaguarda de confirm).

Contra el endpoint real vía TestClient — mismo patrón que test_budgets.py.
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
from backend.agents.expense_tracker.database import Base, Budget, Expense, Source, get_db

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


def _add_expense(db, *, needs_review=True, category="otros", amount=10.0):
    expense = Expense(
        source=Source.MANUAL,
        merchant="Test",
        amount=amount,
        category=category,
        category_confidence=1.0,
        needs_review=needs_review,
        occurred_at=datetime.fromisoformat("2026-08-05T12:00:00"),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


# ── DELETE /expenses/{id} ──────────────────────────────────────────────


def test_delete_existing_needs_review_expense_returns_200_and_removed_from_review(client):
    db = TestingSessionLocal()
    try:
        expense = _add_expense(db, needs_review=True)
        expense_id = expense.id
    finally:
        db.close()

    response = client.delete(f"/expense-tracker/expenses/{expense_id}", headers=_auth())
    assert response.status_code == 200

    review = client.get("/expense-tracker/expenses/review", headers=_auth())
    assert review.json() == []


def test_delete_nonexistent_expense_returns_404(client):
    response = client.delete("/expense-tracker/expenses/99999", headers=_auth())
    assert response.status_code == 404


def test_delete_requires_app_token(client):
    response = client.delete("/expense-tracker/expenses/1")
    assert response.status_code == 401


# ── POST /expenses/reset-all ───────────────────────────────────────────


def test_reset_all_with_wrong_confirm_returns_400_and_keeps_data(client):
    db = TestingSessionLocal()
    try:
        _add_expense(db, needs_review=False)
    finally:
        db.close()

    response = client.post(
        "/expense-tracker/expenses/reset-all",
        headers=_auth(),
        json={"confirm": "borrar"},  # minúscula, no coincide
    )
    assert response.status_code == 400

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).count() == 1
    finally:
        db.close()


def test_reset_all_with_correct_confirm_clears_expenses_but_not_budgets(client):
    db = TestingSessionLocal()
    try:
        _add_expense(db, needs_review=False)
        _add_expense(db, needs_review=True)
        db.add(Budget(category="comida", month="2026-08", limit_amount=100.0))
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/expense-tracker/expenses/reset-all",
        headers=_auth(),
        json={"confirm": "BORRAR"},
    )
    assert response.status_code == 200

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).count() == 0
        assert db.query(Budget).count() == 1
    finally:
        db.close()


def test_reset_all_requires_app_token(client):
    response = client.post("/expense-tracker/expenses/reset-all", json={"confirm": "BORRAR"})
    assert response.status_code == 401
