"""Tests de la pestaña Calendario: gastos agrupados por día + notas
puntuales/recurrentes (GET /calendar, POST/DELETE /calendar/notes).
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
from backend.agents.expense_tracker.database import Base, CalendarNote, Expense, Source, get_db

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


def _calendar(client, month="2026-08"):
    return client.get("/expense-tracker/calendar", params={"month": month}, headers=_auth())


def _add_expense(db, *, category="comida", amount=10.0, occurred_at):
    expense = Expense(
        source=Source.MANUAL,
        merchant="Test",
        amount=amount,
        category=category,
        category_confidence=1.0,
        needs_review=False,
        occurred_at=datetime.fromisoformat(occurred_at),
    )
    db.add(expense)
    db.commit()
    return expense


def _create_note(client, *, text, note_date=None, recurring_day=None):
    body = {"text": text}
    if note_date is not None:
        body["note_date"] = note_date
    if recurring_day is not None:
        body["recurring_day"] = recurring_day
    return client.post("/expense-tracker/calendar/notes", json=body, headers=_auth())


def _day(body, date_str):
    return next(d for d in body["days"] if d["date"] == date_str)


# ── Estructura general ────────────────────────────────────────────────────


def test_calendar_returns_one_entry_per_day_of_month(client):
    body = _calendar(client, "2026-08").json()
    assert len(body["days"]) == 31  # agosto tiene 31 días
    assert body["days"][0]["date"] == "2026-08-01"
    assert body["days"][-1]["date"] == "2026-08-31"


def test_calendar_requires_app_token(client):
    response = client.get("/expense-tracker/calendar", params={"month": "2026-08"})
    assert response.status_code == 401


def test_calendar_invalid_month_returns_422(client):
    response = client.get(
        "/expense-tracker/calendar", params={"month": "not-a-month"}, headers=_auth()
    )
    assert response.status_code == 422


# ── Notas: creación y validación exactamente-uno-de-los-dos ──────────────


def test_create_note_requires_exactly_one_of_note_date_or_recurring_day(client):
    # Ninguno de los dos.
    response = _create_note(client, text="Sin fecha")
    assert response.status_code == 422

    # Los dos a la vez.
    response = client.post(
        "/expense-tracker/calendar/notes",
        json={"text": "Ambos", "note_date": "2026-08-15", "recurring_day": 15},
        headers=_auth(),
    )
    assert response.status_code == 422


def test_create_note_recurring_day_out_of_range_rejected(client):
    response = _create_note(client, text="Día inválido", recurring_day=32)
    assert response.status_code == 422


# ── Nota puntual ───────────────────────────────────────────────────────────


def test_punctual_note_appears_only_on_its_exact_date(client):
    response = _create_note(client, text="Cita médica", note_date="2026-08-15")
    assert response.status_code == 200

    body = _calendar(client, "2026-08").json()
    day_15 = _day(body, "2026-08-15")
    assert len(day_15["notes"]) == 1
    assert day_15["notes"][0]["text"] == "Cita médica"

    day_16 = _day(body, "2026-08-16")
    assert day_16["notes"] == []


def test_punctual_note_does_not_appear_in_other_months(client):
    _create_note(client, text="Cita médica", note_date="2026-08-15")

    body = _calendar(client, "2026-09").json()
    for day in body["days"]:
        assert day["notes"] == []


# ── Nota recurrente ─────────────────────────────────────────────────────────


def test_recurring_note_appears_on_same_day_every_month(client):
    response = _create_note(client, text="Pago alquiler", recurring_day=5)
    assert response.status_code == 200

    for month in ("2026-08", "2026-09", "2026-10"):
        body = _calendar(client, month).json()
        day_5 = _day(body, f"{month}-05")
        assert len(day_5["notes"]) == 1
        assert day_5["notes"][0]["text"] == "Pago alquiler"


def test_recurring_day_31_clamps_to_last_day_in_short_month(client):
    _create_note(client, text="Fin de mes", recurring_day=31)

    # Septiembre tiene 30 días -> debe aparecer el día 30, no saltarse el mes.
    body = _calendar(client, "2026-09").json()
    day_30 = _day(body, "2026-09-30")
    assert len(day_30["notes"]) == 1
    assert day_30["notes"][0]["text"] == "Fin de mes"

    # Febrero 2026 (no bisiesto) tiene 28 días -> debe aparecer el día 28.
    body_feb = _calendar(client, "2026-02").json()
    day_28 = _day(body_feb, "2026-02-28")
    assert len(day_28["notes"]) == 1

    # Agosto tiene 31 días -> el día 31 normal, sin clamp.
    body_aug = _calendar(client, "2026-08").json()
    day_31 = _day(body_aug, "2026-08-31")
    assert len(day_31["notes"]) == 1


# ── Gastos + notas combinados ────────────────────────────────────────────


def test_day_with_both_expenses_and_notes_returns_both(client):
    db = TestingSessionLocal()
    try:
        _add_expense(db, category="comida", amount=25.50, occurred_at="2026-08-10T10:00:00")
    finally:
        db.close()
    _create_note(client, text="Cumpleaños", note_date="2026-08-10")

    body = _calendar(client, "2026-08").json()
    day_10 = _day(body, "2026-08-10")
    assert len(day_10["expenses"]) == 1
    assert day_10["expenses"][0]["amount"] == 25.50
    assert len(day_10["notes"]) == 1
    assert day_10["notes"][0]["text"] == "Cumpleaños"
    assert day_10["total_day"] == 25.50


# ── Borrado ──────────────────────────────────────────────────────────────


def test_delete_recurring_note_removes_it_from_all_months(client):
    create_response = _create_note(client, text="Suscripción", recurring_day=1)
    note_id = create_response.json()["id"]

    delete_response = client.delete(f"/expense-tracker/calendar/notes/{note_id}", headers=_auth())
    assert delete_response.status_code == 200

    for month in ("2026-08", "2026-09", "2026-10"):
        body = _calendar(client, month).json()
        day_1 = _day(body, f"{month}-01")
        assert day_1["notes"] == []


def test_delete_nonexistent_note_returns_404(client):
    response = client.delete("/expense-tracker/calendar/notes/99999", headers=_auth())
    assert response.status_code == 404


def test_delete_note_requires_app_token(client):
    response = client.delete("/expense-tracker/calendar/notes/1")
    assert response.status_code == 401


def test_calendar_notes_never_persist_if_db_constraint_bypassed_check():
    # Constancia de que el CHECK constraint existe a nivel de BD (defensa
    # en profundidad, no solo la validación de Pydantic) — insertar una
    # fila ambigua directo contra la sesión debe fallar.
    from sqlalchemy.exc import IntegrityError

    db = TestingSessionLocal()
    try:
        note = CalendarNote(text="Ambigua", note_date=None, recurring_day=None)
        db.add(note)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()
