"""Tests de búsqueda/filtro de gastos (GET /expenses/search).

Contra el endpoint real vía TestClient, mismo patrón que
test_budgets.py/test_webhook_e2e.py.
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


def _add(
    db,
    *,
    merchant=None,
    raw_text=None,
    amount=None,
    category=None,
    needs_review=False,
    occurred_at="2026-08-05T12:00:00",
    source=Source.MANUAL,
):
    expense = Expense(
        source=source,
        merchant=merchant,
        raw_text=raw_text,
        amount=amount,
        category=category,
        category_confidence=1.0 if category else None,
        needs_review=needs_review,
        occurred_at=datetime.fromisoformat(occurred_at),
    )
    db.add(expense)
    db.commit()
    return expense


def _search(client, **params):
    return client.get("/expense-tracker/expenses/search", params=params, headers=_auth())


def test_query_finds_by_merchant(client):
    db = TestingSessionLocal()
    try:
        _add(db, merchant="Netflix", amount=13.99, category="suscripciones")
        _add(db, merchant="Mercadona", amount=34.18, category="comida")
    finally:
        db.close()

    response = _search(client, query="netflix")
    body = response.json()
    assert body["total"] == 1
    assert body["expenses"][0]["merchant"] == "Netflix"


def test_query_finds_by_raw_text_when_merchant_is_null(client):
    db = TestingSessionLocal()
    try:
        _add(
            db,
            merchant=None,
            raw_text="Has pagado 12,00 EUR a NETFLIX sin identificar bien el comercio.",
            amount=None,
            needs_review=True,
        )
        _add(db, merchant="Mercadona", amount=34.18, category="comida")
    finally:
        db.close()

    response = _search(client, query="netflix")
    body = response.json()
    assert body["total"] == 1
    assert body["expenses"][0]["merchant"] is None
    assert "NETFLIX" in body["expenses"][0]["raw_text"]


def test_category_and_date_range_combine_as_intersection(client):
    db = TestingSessionLocal()
    try:
        _add(
            db,
            merchant="Mercadona",
            amount=20,
            category="comida",
            occurred_at="2026-08-05T10:00:00",
        )
        _add(
            db,
            merchant="Carrefour",
            amount=25,
            category="comida",
            occurred_at="2026-07-05T10:00:00",
        )
        _add(
            db,
            merchant="Cabify",
            amount=15,
            category="transporte",
            occurred_at="2026-08-06T10:00:00",
        )
    finally:
        db.close()

    response = _search(client, category="comida", date_from="2026-08-01", date_to="2026-08-31")
    body = response.json()
    assert body["total"] == 1
    assert body["expenses"][0]["merchant"] == "Mercadona"


def test_amount_range_is_inclusive_on_both_ends(client):
    db = TestingSessionLocal()
    try:
        _add(db, merchant="A", amount=10.0)
        _add(db, merchant="B", amount=50.0)
        _add(db, merchant="C", amount=9.99)
        _add(db, merchant="D", amount=50.01)
    finally:
        db.close()

    response = _search(client, amount_min=10, amount_max=50)
    merchants = {e["merchant"] for e in response.json()["expenses"]}
    assert merchants == {"A", "B"}


def test_date_from_after_date_to_returns_422_not_empty_result(client):
    response = _search(client, date_from="2026-08-31", date_to="2026-08-01")
    assert response.status_code == 422


def test_amount_min_greater_than_amount_max_returns_422(client):
    response = _search(client, amount_min=100, amount_max=10)
    assert response.status_code == 422


def test_pagination_returns_correct_pages_without_gaps_or_duplicates(client):
    db = TestingSessionLocal()
    try:
        for i in range(5):
            _add(
                db, merchant=f"Merchant{i}", amount=10, occurred_at=f"2026-08-{10 + i:02d}T10:00:00"
            )
    finally:
        db.close()

    page1 = _search(client, limit=2, offset=0).json()
    page2 = _search(client, limit=2, offset=2).json()
    page3 = _search(client, limit=2, offset=4).json()

    assert page1["total"] == 5
    ids_page1 = [e["id"] for e in page1["expenses"]]
    ids_page2 = [e["id"] for e in page2["expenses"]]
    ids_page3 = [e["id"] for e in page3["expenses"]]

    # Orden: occurred_at descendente, más reciente primero.
    assert len(ids_page1) == 2
    assert len(ids_page2) == 2
    assert len(ids_page3) == 1
    all_ids = ids_page1 + ids_page2 + ids_page3
    assert len(all_ids) == len(set(all_ids)) == 5  # sin duplicados, sin huecos


def test_search_requires_app_token(client):
    response = client.get("/expense-tracker/expenses/search")
    assert response.status_code == 401
