"""database.py — Conexión a PostgreSQL y modelo de datos del Expense Tracker."""

from __future__ import annotations

import enum
import os

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.sql import func

load_dotenv(override=False)

# ── Conexión ────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "EXPENSE_TRACKER_DATABASE_URL",
    "postgresql://lander:lander123@localhost:5434/expense_tracker_db",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Modelo de datos ─────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Clase base de la que heredan todos los modelos."""

    pass


class Source(str, enum.Enum):
    WALLET = "wallet"
    EMAIL_BANK = "email_bank"
    EMAIL_PAYPAL = "email_paypal"
    MANUAL = "manual"
    BIZUM = "bizum"


SourceEnum = Enum(Source, name="expense_source")

# "bizum" es un valor válido de Expense.category (columna String(50) sin
# enum real a nivel de BD) para dinero RECIBIDO, no un gasto — se guarda
# con amount negativo (ver engine.ingest_webhook) para que reste del
# total en vez de sumar. Deliberadamente FUERA de categorizer.CATEGORIES
# (las 7 categorías de Presupuestos): engine.get_budgets_for_month itera
# solo esa lista, así que las filas "bizum" quedan excluidas de
# Presupuestos automáticamente, sin ninguna comprobación especial.
BIZUM_CATEGORY = "bizum"


class Expense(Base):
    """
    Una fila = un gasto.

    `merged_source` queda null salvo que este gasto haya sido detectado por
    dos canales independientes (típicamente Wallet + email del banco para la
    misma compra con Apple Pay) y fusionado en una sola fila por
    engine.merge_duplicate(). `source` conserva siempre el canal que creó la
    fila originalmente; `merged_source` es el canal que confirmó el mismo
    gasto después. Ver engine.py para el porqué de esta fusión.
    """

    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)

    source = Column(SourceEnum, nullable=False)
    merged_source = Column(SourceEnum, nullable=True)

    merchant = Column(Text, nullable=True)
    # nullable pese a la spec original: si el regex de parsers.py no
    # encuentra ni siquiera el importe, la fila se guarda igual con
    # needs_review=True y raw_text intacto en vez de perderse (ver
    # engine.ingest_webhook). NOT NULL habría forzado a inventar un 0.0
    # que se mezclaría con gastos reales de 0€ en los totales agregados.
    amount = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="EUR", server_default="EUR")

    category = Column(String(50), nullable=True)
    category_confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, nullable=False, default=False, server_default="false")

    raw_text = Column(Text, nullable=True)

    occurred_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_expenses_occurred_at", "occurred_at"),
        Index("ix_expenses_needs_review", "needs_review"),
    )


class DiscardedMessage(Base):
    """Registro de auditoría de un mensaje descartado por los filtros de
    ingest_webhook (OTP o "no parece una transacción") — separada de
    `expenses` porque NO es un gasto, es la constancia de que algo se
    descartó.

    NUNCA guarda raw_text ni ningún contenido del mensaje — igual que el
    log de stdout que sustituye/complementa, solo el hecho, el motivo y
    el momento. Persistente en Postgres a propósito: el log de stdout del
    contenedor se pierde en cada redeploy, justo cuando más se necesita
    poder auditar un descarte.
    """

    __tablename__ = "discarded_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)

    source = Column(SourceEnum, nullable=False)
    reason = Column(String(50), nullable=False)  # "verification_code" | "not_a_transaction"

    discarded_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_discarded_messages_discarded_at", "discarded_at"),)


class Budget(Base):
    """Límite de gasto de una categoría en un mes concreto.

    Ajustable mes a mes a propósito, no un límite fijo global: cada fila es
    (category, month), así que subir el presupuesto de "ocio" en diciembre
    no toca noviembre ni enero. La ausencia de fila para una
    (category, month) significa "sin límite fijado" — nunca se rellena con
    un 0 por defecto, que sería indistinguible de "límite de gastar cero".
    """

    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, autoincrement=True)

    category = Column(String(50), nullable=False)
    month = Column(String(7), nullable=False)  # "YYYY-MM"
    limit_amount = Column(Numeric(10, 2), nullable=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("category", "month", name="uq_budgets_category_month"),)


class CalendarNote(Base):
    """Una nota del Calendario — puntual (fecha exacta) o recurrente
    mensual (mismo día de cada mes). Exactamente una de las dos
    (note_date, recurring_day) debe estar rellena, nunca las dos ni
    ninguna — validado en schemas.CalendarNoteIn (a nivel de API) y
    reforzado aquí con un CHECK constraint (a nivel de BD, para que no
    quede una fila ambigua si algo escribe directo sin pasar por la API).

    Meses cortos con recurring_day=31 (o 29/30/31 en febrero, abril...):
    se muestra el ÚLTIMO día del mes en vez de saltarse el mes o fallar —
    ver engine.get_calendar_month, que hace el clamp al construir la
    vista de cada mes. No se guarda un "31 efectivo" distinto por mes;
    recurring_day guarda siempre el valor original tal como lo escribió
    el usuario.
    """

    __tablename__ = "calendar_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)

    text = Column(Text, nullable=False)

    note_date = Column(Date, nullable=True)
    recurring_day = Column(Integer, nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "(note_date IS NOT NULL AND recurring_day IS NULL) OR "
            "(note_date IS NULL AND recurring_day IS NOT NULL)",
            name="ck_calendar_notes_exactly_one_date_kind",
        ),
        CheckConstraint(
            "recurring_day IS NULL OR (recurring_day >= 1 AND recurring_day <= 31)",
            name="ck_calendar_notes_recurring_day_range",
        ),
        Index("ix_calendar_notes_note_date", "note_date"),
        Index("ix_calendar_notes_recurring_day", "recurring_day"),
    )


# ── Inicialización ──────────────────────────────────────────────────────────


def init_db() -> None:
    """Crea las tablas si no existen. Se llama al arrancar el servidor (lifespan)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Generador de sesión por petición HTTP, para usar con Depends(get_db)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
