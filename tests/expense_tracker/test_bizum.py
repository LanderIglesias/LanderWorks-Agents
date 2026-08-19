"""Tests de Bizum recibido (source=bizum): categoría fija "bizum", sin
categorizador de IA, amount SIEMPRE negativo para que reste del total en
vez de sumar. Ver parsers.parse_bizum_sms y engine._ingest_bizum.
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
from backend.agents.expense_tracker.database import Base, Expense, Source, get_db
from backend.agents.expense_tracker.parsers import parse_bizum_sms

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
    # Si el categorizador de IA llegara a llamarse para un Bizum, el test
    # debe fallar de forma ruidosa, no degradar en silencio a "otros".
    monkeypatch.setattr(
        et_engine.categorizer,
        "categorize",
        lambda merchant, amount: (_ for _ in ()).throw(
            AssertionError("categorizer.categorize no debería llamarse para source=bizum")
        ),
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


def _webhook_headers(timestamp: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WEBHOOK_SECRET}",
        "X-Timestamp": timestamp,
    }


def _post_bizum(client, raw_text: str, occurred_at: str = "2026-08-19T13:45:00"):
    payload = {"source": "bizum", "raw_text": raw_text, "occurred_at": occurred_at}
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return client.post(
        "/expense-tracker/webhook/expense",
        content=json.dumps(payload),
        headers=_webhook_headers(timestamp),
    )


def _add_expense(db, *, category, amount, source=Source.MANUAL, needs_review=False, occurred_at):
    expense = Expense(
        source=source,
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


# ── parsers.parse_bizum_sms (unidad) ─────────────────────────────────────


def test_parse_bizum_sms_real_production_format():
    # Texto EXACTO de la captura real.
    raw_text = "Has recibido un BIZUM de 9.50 EUR de SONIA por Mercadona"

    result = parse_bizum_sms(raw_text)

    assert result is not None
    assert result.merchant == "SONIA"
    assert result.amount == 9.50


def test_parse_bizum_sms_without_concept_still_parses():
    raw_text = "Has recibido un BIZUM de 25.00 EUR de MARIA"

    result = parse_bizum_sms(raw_text)

    assert result is not None
    assert result.merchant == "MARIA"
    assert result.amount == 25.00


def test_parse_bizum_sms_thousands_amount():
    raw_text = "Has recibido un BIZUM de 1.234,00 EUR de JUAN PEREZ por alquiler"

    result = parse_bizum_sms(raw_text)

    assert result is not None
    assert result.merchant == "JUAN PEREZ"
    assert result.amount == 1234.00


def test_parse_bizum_sms_unexpected_shape_returns_none():
    result = parse_bizum_sms("Movimiento con tarjeta ...1234 en MERCADONA por importe de 23,45 EUR")
    assert result is None


def test_parse_bizum_sms_empty_or_corrupt_returns_none():
    assert parse_bizum_sms("") is None
    assert parse_bizum_sms(None) is None
    assert parse_bizum_sms("   ") is None


# ── POST /webhook/expense end-to-end (source=bizum) ──────────────────────


def test_bizum_webhook_creates_expense_with_negative_amount_and_fixed_category(client):
    response = _post_bizum(client, "Has recibido un BIZUM de 9.50 EUR de SONIA por Mercadona")

    assert response.status_code == 200
    data = response.json()
    assert data["merchant"] == "SONIA"
    assert data["amount"] == -9.50
    assert data["category"] == "bizum"
    assert data["needs_review"] is False

    db = TestingSessionLocal()
    try:
        row = db.query(Expense).one()
        assert row.source == Source.BIZUM
        assert float(row.amount) == -9.50
    finally:
        db.close()


def test_bizum_webhook_unparseable_sms_falls_back_to_needs_review(client):
    """No hay "needs_review=False incondicional" — si el SMS no matchea,
    la fila debe seguir siendo encontrable en la cola de Revisión (mismo
    principio que el resto de fuentes: nunca perder el dato en silencio)."""
    response = _post_bizum(client, "Este SMS no tiene el formato esperado de Bizum")

    assert response.status_code == 200
    data = response.json()
    assert data["needs_review"] is True
    assert data["amount"] is None
    assert data["category"] is None

    db = TestingSessionLocal()
    try:
        assert db.query(Expense).filter(Expense.needs_review.is_(True)).count() == 1
    finally:
        db.close()


def test_bizum_requires_app_token_not_applicable_webhook_uses_signature(client):
    # El webhook usa verify_webhook_signature, no verify_app_token — sin
    # cabeceras válidas debe rechazar igual que cualquier otro source.
    response = client.post(
        "/expense-tracker/webhook/expense",
        content=json.dumps(
            {
                "source": "bizum",
                "raw_text": "Has recibido un BIZUM de 9.50 EUR de SONIA por Mercadona",
                "occurred_at": "2026-08-19T13:45:00",
            }
        ),
    )
    assert response.status_code == 401


# ── El total resta, no suma (aggregate + comparison) ─────────────────────


def test_month_total_subtracts_bizum_not_adds(client):
    db = TestingSessionLocal()
    try:
        _add_expense(db, category="comida", amount=50.00, occurred_at="2026-08-05T10:00:00")
        _add_expense(
            db,
            category="bizum",
            amount=-9.50,
            source=Source.BIZUM,
            occurred_at="2026-08-06T10:00:00",
        )
    finally:
        db.close()

    response = client.get(
        "/expense-tracker/expenses",
        params={"granularity": "month", "date": "2026-08-05"},
        headers=_auth(),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 40.50


def test_month_comparison_total_also_subtracts_bizum(client):
    db = TestingSessionLocal()
    try:
        _add_expense(db, category="comida", amount=50.00, occurred_at="2026-08-05T10:00:00")
        _add_expense(
            db,
            category="bizum",
            amount=-9.50,
            source=Source.BIZUM,
            occurred_at="2026-08-06T10:00:00",
        )
    finally:
        db.close()

    response = client.get(
        "/expense-tracker/expenses/comparison", params={"month": "2026-08"}, headers=_auth()
    )
    assert response.status_code == 200
    assert response.json()["total_actual"] == 40.50


def test_budgets_never_include_bizum_category(client):
    db = TestingSessionLocal()
    try:
        _add_expense(
            db,
            category="bizum",
            amount=-9.50,
            source=Source.BIZUM,
            occurred_at="2026-08-06T10:00:00",
        )
    finally:
        db.close()

    response = client.get("/expense-tracker/budgets", params={"month": "2026-08"}, headers=_auth())
    assert response.status_code == 200
    categories = {row["category"] for row in response.json()}
    assert categories == {
        "comida",
        "transporte",
        "suscripciones",
        "ocio",
        "salud",
        "hogar",
        "otros",
    }
    assert "bizum" not in categories
