"""schemas.py — Modelos Pydantic de entrada/salida de la API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, field_validator, model_validator

from .database import Source
from .parsers import parse_amount_string


class WebhookExpenseIn(BaseModel):
    """Body de POST /webhook/expense. Forma laxa a propósito:

    - source=wallet trae merchant/amount ya estructurados desde el Atajo.
    - source=email_bank / email_paypal traen solo raw_text; el resto se
      rellena en engine.ingest_webhook() vía parsers.py.

    `amount` acepta str ADEMÁS de float: la variable "Importe" que manda
    el Atajo de Transacción de Wallet llega con formato de moneda ("46,98
    €", confirmado en producción), no como float puro — sin esto, Pydantic
    rechazaba la petición entera con 422 antes de que ingest_webhook
    llegara siquiera a intentar guardar el gasto (bug real: al menos dos
    compras, KFC y Mercadona, se perdieron así, sin quedar ni needs_review).
    """

    source: Source
    raw_text: str | None = None
    merchant: str | None = None
    amount: str | float | None = None
    occurred_at: datetime

    @field_validator("amount", mode="before")
    @classmethod
    def _normalize_amount(cls, value):
        if value is None or isinstance(value, float | int):
            return value
        parsed = parse_amount_string(value)
        if parsed is None:
            # Sigue siendo una entrada inválida real si esto pasa (no
            # "12.99", no "46,98 €", sino algo irreconocible) — se deja
            # que la validación normal de Pydantic la rechace con 422 en
            # vez de silenciarla como None.
            raise ValueError(f"amount inválido: {value!r}")
        return parsed


class ManualExpenseIn(BaseModel):
    """Body de POST /expenses (alta manual)."""

    merchant: str
    amount: float
    currency: str = "EUR"
    occurred_at: datetime
    category: str | None = None


class ExpensePatch(BaseModel):
    """Body de PATCH /expenses/{id} — corrección manual, todo opcional."""

    category: str | None = None
    amount: float | None = None
    merchant: str | None = None
    needs_review: bool | None = None


class BudgetSetIn(BaseModel):
    """Body de PUT /budgets/{category}. limit_amount None o 0 = quitar el límite."""

    limit_amount: float | None = None


class ResetAllIn(BaseModel):
    """Body de POST /expenses/reset-all. `confirm` debe ser exactamente
    "BORRAR" — es la salvaguarda contra un borrado accidental de todo el
    historial, no una validación de forma."""

    confirm: str


class BudgetOut(BaseModel):
    """Una de las 7 categorías, con su límite (si hay) y el gasto real del mes.

    `spent` y `remaining` son calculados en engine.get_budgets_for_month,
    nunca almacenados — ver ese docstring para por qué needs_review=True
    queda excluido de `spent`.
    """

    category: str
    month: str
    limit_amount: float | None
    spent: float
    remaining: float | None


class DiscardedMessageOut(BaseModel):
    """Una fila de auditoría de DiscardedMessage — nunca lleva raw_text,
    el modelo de BD no lo tiene en absoluto."""

    id: int
    source: Source
    reason: str
    discarded_at: datetime

    class Config:
        from_attributes = True


class CalendarNoteIn(BaseModel):
    """Body de POST /calendar/notes. Exactamente uno de note_date /
    recurring_day debe venir relleno — nunca ambos, nunca ninguno. No se
    deja ambiguo: se valida aquí, no se asume un valor por defecto."""

    text: str
    note_date: date | None = None
    recurring_day: int | None = None

    @model_validator(mode="after")
    def _exactly_one_date_kind(self):
        has_date = self.note_date is not None
        has_recurring = self.recurring_day is not None
        if has_date == has_recurring:
            raise ValueError(
                "especifica exactamente uno de note_date o recurring_day, no ambos ni ninguno"
            )
        if has_recurring and not 1 <= self.recurring_day <= 31:
            raise ValueError("recurring_day debe estar entre 1 y 31")
        return self


class CalendarNoteOut(BaseModel):
    id: int
    text: str
    note_date: date | None
    recurring_day: int | None
    created_at: datetime | None

    class Config:
        from_attributes = True


class ExpenseOut(BaseModel):
    id: int
    source: Source
    merged_source: Source | None
    merchant: str | None
    amount: float | None
    currency: str
    category: str | None
    category_confidence: float | None
    needs_review: bool
    raw_text: str | None
    occurred_at: datetime
    created_at: datetime | None

    class Config:
        from_attributes = True
