"""schemas.py — Modelos Pydantic de entrada/salida de la API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .database import Source


class WebhookExpenseIn(BaseModel):
    """Body de POST /webhook/expense. Forma laxa a propósito:

    - source=wallet trae merchant/amount ya estructurados desde el Atajo.
    - source=email_bank / email_paypal traen solo raw_text; el resto se
      rellena en engine.ingest_webhook() vía parsers.py.
    """

    source: Source
    raw_text: str | None = None
    merchant: str | None = None
    amount: float | None = None
    occurred_at: datetime


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
