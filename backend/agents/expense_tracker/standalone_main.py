"""standalone_main.py — Entrypoint ASGI de expense_tracker en solitario.

Existe porque `backend.main` importa TODOS los agentes del monorepo (dental,
job_matcher, tech_debt, etc.) — levantarlo entero para servir solo
expense_tracker en la imagen ligera de producción sería exactamente el
acoplamiento que esa imagen busca evitar. Este archivo replica únicamente el
cableado que expense_tracker necesita en `backend/main.py` (init_db en el
lifespan, router, estáticos de la PWA, rate limiting) sin tocar nada de los
demás agentes — expense_tracker no importa código de fuera de su propia
carpeta, así que no hace falta nada más.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.agents.expense_tracker.api import mount_static, router, setup_rate_limiting
from backend.agents.expense_tracker.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        print("[EXPENSE_TRACKER] Base de datos inicializada")
    except Exception as e:
        print(f"[EXPENSE_TRACKER] fallo al inicializar BD: {e}")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)
mount_static(app)
setup_rate_limiting(app)
