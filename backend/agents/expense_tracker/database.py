"""database.py — Conexión a PostgreSQL y modelo de datos del Expense Tracker."""

from __future__ import annotations

import enum
import os

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
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


SourceEnum = Enum(Source, name="expense_source")


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
