"""Tests de detección de gastos recurrentes (GET /expenses/recurring).

Los 3 meses objetivo se calculan en vivo con
engine._last_n_calendar_months (los mismos "últimos 3 meses calendario
completos" que usa detect_recurring), en vez de fechas fijas — así el test
no depende de en qué fecha real se ejecute la suite.
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
from backend.agents.expense_tracker.engine import _last_n_calendar_months

APP_TOKEN = "test-app-token"
MONTHS = _last_n_calendar_months(3)  # ej. ["2026-05", "2026-06", "2026-07"]

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


def _add(db, *, merchant, amount, month, day=5, needs_review=False):
    expense = Expense(
        source=Source.MANUAL,
        merchant=merchant,
        amount=amount,
        category="suscripciones",
        category_confidence=1.0,
        needs_review=needs_review,
        occurred_at=datetime.fromisoformat(f"{month}-{day:02d}T12:00:00"),
    )
    db.add(expense)
    db.commit()
    return expense


def _recurring(client):
    return client.get("/expense-tracker/expenses/recurring", headers=_auth())


def test_exact_merchant_and_amount_detected_as_recurring(client):
    db = TestingSessionLocal()
    try:
        for month in MONTHS:
            _add(db, merchant="Netflix", amount=13.99, month=month)
    finally:
        db.close()

    body = _recurring(client).json()
    assert len(body) == 1
    assert body[0]["merchant_representative"] == "Netflix"
    assert body[0]["amount_avg"] == 13.99
    assert len(body[0]["occurrences"]) == 3
    assert {o["month"] for o in body[0]["occurrences"]} == set(MONTHS)


def test_similar_merchant_names_grouped_as_same_recurring(client):
    db = TestingSessionLocal()
    try:
        _add(db, merchant="Netflix", amount=13.99, month=MONTHS[0])
        _add(db, merchant="Netflix.com", amount=13.99, month=MONTHS[1])
        _add(db, merchant="NETFLIX INTL", amount=13.99, month=MONTHS[2])
    finally:
        db.close()

    body = _recurring(client).json()
    assert len(body) == 1
    assert len(body[0]["occurrences"]) == 3


def test_amount_variation_over_15_percent_not_grouped_as_recurring(client):
    db = TestingSessionLocal()
    try:
        _add(db, merchant="Gimnasio", amount=30.0, month=MONTHS[0])
        _add(db, merchant="Gimnasio", amount=30.0, month=MONTHS[1])
        _add(db, merchant="Gimnasio", amount=45.0, month=MONTHS[2])  # +50%, fuera de tolerancia
    finally:
        db.close()

    body = _recurring(client).json()
    assert body == []


def test_only_two_of_three_months_not_marked_recurring(client):
    db = TestingSessionLocal()
    try:
        _add(db, merchant="Spotify", amount=9.99, month=MONTHS[0])
        _add(db, merchant="Spotify", amount=9.99, month=MONTHS[1])
        # Nada en MONTHS[2].
    finally:
        db.close()

    body = _recurring(client).json()
    assert body == []


def test_needs_review_excluded_even_with_matching_merchant(client):
    db = TestingSessionLocal()
    try:
        _add(db, merchant="Disney Plus", amount=8.99, month=MONTHS[0])
        _add(db, merchant="Disney Plus", amount=8.99, month=MONTHS[1])
        # Mismo merchant/importe en el tercer mes, pero needs_review=True:
        # no debe contar, así que solo quedan 2 de los 3 meses cubiertos.
        _add(db, merchant="Disney Plus", amount=8.99, month=MONTHS[2], needs_review=True)
    finally:
        db.close()

    body = _recurring(client).json()
    assert body == []


def test_distinct_merchants_not_grouped_by_coincidence(client):
    db = TestingSessionLocal()
    try:
        for month in MONTHS:
            _add(db, merchant="Repsol", amount=50.0, month=month)
            _add(db, merchant="Cepsa", amount=50.0, month=month)
    finally:
        db.close()

    body = _recurring(client).json()
    assert len(body) == 2
    representatives = {r["merchant_representative"] for r in body}
    assert representatives == {"Repsol", "Cepsa"}
    for r in body:
        assert len(r["occurrences"]) == 3


def test_recurring_requires_app_token(client):
    response = client.get("/expense-tracker/expenses/recurring")
    assert response.status_code == 401
