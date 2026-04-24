"""
generate_sample_data.py — Dataset sintético de métricas SaaS

Genera 6 meses de datos realistas de una empresa SaaS ficticia.
Al ejecutarlo, crea backend/agents/bi_agent/data/saas_metrics.csv

Estructura del CSV:
- date: fecha del snapshot (diario)
- user_id: identificador único del usuario
- plan: free, pro, enterprise
- mrr: monthly recurring revenue (0 si está en trial o churned)
- status: active, churned, trial
- country: país del usuario
- signup_date: cuándo se registró

Patrones incluidos:
- ~500 usuarios únicos a lo largo de 180 días
- Churn mensual realista: ~20% free, ~8% pro, ~3% enterprise
- Upgrades ocasionales de free → pro → enterprise
- Distribución inicial de planes: 60% free, 30% pro, 10% enterprise
- Tras churn, el usuario genera 30 días de filas churned (snapshot histórico)
  para que las preguntas de churn tengan datos suficientes

Cómo ejecutar:
    python backend/agents/bi_agent/generate_sample_data.py
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# Semilla fija → dataset reproducible
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ── Configuración del dataset ────────────────────────────────────────────────

START_DATE = datetime(2025, 10, 1)
END_DATE = datetime(2026, 3, 31)  # 6 meses

TOTAL_USERS = 500
COUNTRIES = ["USA", "Spain", "UK", "Germany", "France", "Mexico", "Brazil", "Japan"]
COUNTRY_WEIGHTS = [0.35, 0.15, 0.10, 0.10, 0.08, 0.08, 0.08, 0.06]

PLANS = ["free", "pro", "enterprise"]
PLAN_DISTRIBUTION = [0.60, 0.30, 0.10]
PLAN_MRR = {"free": 0, "pro": 29, "enterprise": 299}

# Churn mensual por plan — ratios realistas de SaaS B2B
# Free: ~20%/mes (típico), Pro: ~8%/mes, Enterprise: ~3%/mes
CHURN_RATES_MONTHLY = {"free": 0.20, "pro": 0.08, "enterprise": 0.03}

# Probabilidad de upgrade (diaria)
UPGRADE_PROB = {"free": 0.004, "pro": 0.0015, "enterprise": 0.0}

# Días que mantenemos un churned user en el dataset después de churnear
# (para que las queries de churn tengan suficientes filas para análisis)
CHURN_RETENTION_DAYS = 45


# ── Generación del dataset ───────────────────────────────────────────────────


def generate_users() -> list[dict]:
    """Genera los 500 usuarios con sus fechas de signup."""
    users = []
    for i in range(1, TOTAL_USERS + 1):
        # Distribución de signups sesgada: más usuarios al principio del periodo
        days_offset = int(np.random.beta(2, 5) * 180)
        signup = START_DATE + timedelta(days=days_offset)

        initial_plan = np.random.choice(PLANS, p=PLAN_DISTRIBUTION)
        country = np.random.choice(COUNTRIES, p=COUNTRY_WEIGHTS)

        users.append(
            {
                "user_id": f"u{i:04d}",
                "signup_date": signup,
                "initial_plan": initial_plan,
                "country": country,
            }
        )
    return users


def simulate_user_journey(user: dict) -> list[dict]:
    """
    Simula la vida de un usuario día a día desde su signup.
    Genera una fila por día incluso después de churnear (hasta CHURN_RETENTION_DAYS).
    """
    rows = []
    current_plan = user["initial_plan"]
    status = "trial" if random.random() < 0.15 else "active"
    current_date = user["signup_date"]
    churn_date = None  # fecha en la que el usuario churneó, si aplica

    while current_date <= END_DATE:
        days_since_signup = (current_date - user["signup_date"]).days

        # Trial se convierte a active o churned después de 14 días
        if status == "trial" and days_since_signup >= 14:
            if random.random() < 0.55:  # 55% de trials convierten
                status = "active"
            else:
                status = "churned"
                churn_date = current_date

        # Check de churn diario (solo para active)
        if status == "active":
            # Convertir churn mensual a diario
            daily_churn = CHURN_RATES_MONTHLY[current_plan] / 30
            if random.random() < daily_churn:
                status = "churned"
                churn_date = current_date

            # Check de upgrade
            if current_plan == "free" and random.random() < UPGRADE_PROB["free"]:
                current_plan = "pro"
            elif current_plan == "pro" and random.random() < UPGRADE_PROB["pro"]:
                current_plan = "enterprise"

        # MRR según plan y status
        mrr = PLAN_MRR[current_plan] if status == "active" else 0

        rows.append(
            {
                "date": current_date.date(),
                "user_id": user["user_id"],
                "plan": current_plan,
                "mrr": mrr,
                "status": status,
                "country": user["country"],
                "signup_date": user["signup_date"].date(),
            }
        )

        # Si churneó, seguimos generando filas churned durante CHURN_RETENTION_DAYS
        if status == "churned" and churn_date is not None:
            days_churned = (current_date - churn_date).days
            if days_churned >= CHURN_RETENTION_DAYS:
                break

        current_date += timedelta(days=1)

    return rows


def generate_dataset() -> pd.DataFrame:
    """Genera el dataset completo."""
    print(f"[Generator] Creando {TOTAL_USERS} usuarios...")
    users = generate_users()

    print("[Generator] Simulando journey de cada usuario...")
    all_rows = []
    for user in users:
        all_rows.extend(simulate_user_journey(user))

    df = pd.DataFrame(all_rows)
    df = df.sort_values(["date", "user_id"]).reset_index(drop=True)

    print(f"[Generator] Dataset generado: {len(df)} filas")
    print(f"[Generator] Rango de fechas: {df['date'].min()} → {df['date'].max()}")
    print(f"[Generator] Usuarios únicos: {df['user_id'].nunique()}")
    print(f"[Generator] Distribución de planes:\n{df['plan'].value_counts()}")
    print(f"[Generator] Estados:\n{df['status'].value_counts()}")

    # Stats de churn — útil para verificar que el dataset es realista
    churned_users = df[df["status"] == "churned"]["user_id"].nunique()
    total_users = df["user_id"].nunique()
    churn_pct = churned_users / total_users * 100
    print(f"[Generator] Usuarios que churnearon: {churned_users}/{total_users} ({churn_pct:.1f}%)")

    return df


def main():
    output_dir = Path(__file__).resolve().parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "saas_metrics.csv"

    df = generate_dataset()
    df.to_csv(output_path, index=False)

    print(f"\n[Generator] ✓ CSV guardado en: {output_path}")
    print(f"[Generator] Tamaño: {output_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
