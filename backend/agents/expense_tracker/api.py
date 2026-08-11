"""api.py — Endpoints FastAPI del Expense Tracker."""

# Deliberadamente SIN `from __future__ import annotations`: con
# fastapi==0.115.6 (el pin en requirements.txt), get_typed_signature()
# resuelve anotaciones-string usando call.__globals__ sin eval_str ni
# inspect.unwrap(). El decorador @limiter.limit de slowapi envuelve las
# rutas con functools.wraps, que NO reasigna __globals__ — así que con
# anotaciones diferidas, FastAPI intentaría resolver "WebhookExpenseIn"
# contra el namespace de slowapi.extension (donde no existe) en vez del de
# este módulo, y trataría `payload` como query param en vez de body. Sin
# el future import, las anotaciones ya son objetos reales en el momento de
# definir la función, así que no hay nada que resolver contra el
# __globals__ equivocado.

import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from . import engine
from .database import get_db
from .schemas import ExpenseOut, ExpensePatch, ManualExpenseIn, WebhookExpenseIn
from .security import verify_app_token, verify_webhook_signature

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/expense-tracker", tags=["expense-tracker"])

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _rate_limit_key(request: Request) -> str:
    """Clave de rate limiting por IP real del cliente.

    El backend vive detrás de Cloudflare, así que `get_remote_address` de
    slowapi (que lee la IP de la conexión TCP directa) siempre vería la IP
    del proxy de Cloudflare, no la del cliente — el límite se aplicaría de
    forma agregada a TODO el tráfico que pasa por el túnel en vez de a un
    atacante concreto. `CF-Connecting-IP` es la cabecera que Cloudflare
    añade con la IP real del visitante; se cae a la IP de conexión directa
    solo si esa cabecera no está presente (p. ej. en local, sin Cloudflare
    delante).
    """
    return request.headers.get("CF-Connecting-IP") or (
        request.client.host if request.client else "unknown"
    )


limiter = Limiter(key_func=_rate_limit_key)


def setup_rate_limiting(app) -> None:
    """Registra el limiter y su exception handler en la app FastAPI.

    Mismo patrón que mount_static: se llama desde main.py junto al resto de
    setup del expense tracker, para no meter lógica de slowapi ahí.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@router.post(
    "/webhook/expense", response_model=ExpenseOut, dependencies=[Depends(verify_webhook_signature)]
)
@limiter.limit("20/minute")
def webhook_expense(request: Request, payload: WebhookExpenseIn, db: Session = Depends(get_db)):
    # `request: Request` no se usa para parsear el payload (FastAPI lo
    # inyecta normalmente vía `payload`) — slowapi's @limiter.limit lo
    # requiere en la firma para poder aplicar el rate limit sobre esta ruta.
    try:
        expense = engine.ingest_webhook(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return expense


@router.get("/expenses", dependencies=[Depends(verify_app_token)])
def list_expenses(
    granularity: str = "month",
    date: str | None = None,
    db: Session = Depends(get_db),
):
    from datetime import date as date_cls

    date = date or date_cls.today().isoformat()
    try:
        result = engine.aggregate(db, granularity, date)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return {
        **{k: v for k, v in result.items() if k != "expenses"},
        "expenses": [ExpenseOut.model_validate(e) for e in result["expenses"]],
    }


@router.get(
    "/expenses/review", response_model=list[ExpenseOut], dependencies=[Depends(verify_app_token)]
)
def review_queue(db: Session = Depends(get_db)):
    return engine.list_review_queue(db)


@router.get(
    "/expenses/{expense_id}", response_model=ExpenseOut, dependencies=[Depends(verify_app_token)]
)
def get_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = engine.get_expense(db, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


@router.patch(
    "/expenses/{expense_id}", response_model=ExpenseOut, dependencies=[Depends(verify_app_token)]
)
def patch_expense(expense_id: int, patch: ExpensePatch, db: Session = Depends(get_db)):
    expense = engine.update_expense(db, expense_id, patch)
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


@router.post("/expenses", response_model=ExpenseOut, dependencies=[Depends(verify_app_token)])
def create_manual_expense(payload: ManualExpenseIn, db: Session = Depends(get_db)):
    return engine.create_manual_expense(db, payload)


@router.get("/demo")
def serve_demo():
    return FileResponse(STATIC_DIR / "index.html")


def mount_static(app) -> None:
    """Monta el shell de la PWA (index.html, manifest.json, service-worker.js,
    icons, app.js/app.css) directamente bajo /expense-tracker/.

    Se monta en `app`, no en `router`, porque APIRouter no soporta combinar
    un prefix con un Mount en la ruta raíz ("/"). Debe llamarse DESPUÉS de
    app.include_router(router): Starlette prueba las rutas en el orden en
    que se registraron, así que los endpoints explícitos (/expenses,
    /webhook/expense...) siguen respondiendo primero y el mount solo
    atiende lo que ninguna ruta explícita reclama (app.css, manifest.json,
    icons/, la propia index.html en la raíz).
    """
    if STATIC_DIR.exists():
        app.mount(
            router.prefix,
            StaticFiles(directory=str(STATIC_DIR), html=True),
            name="expense-tracker-static",
        )
