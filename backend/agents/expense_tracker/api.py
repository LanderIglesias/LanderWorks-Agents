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
from .schemas import (
    BudgetOut,
    BudgetSetIn,
    CalendarNoteIn,
    CalendarNoteOut,
    DiscardedMessageOut,
    ExpenseOut,
    ExpensePatch,
    ManualExpenseIn,
    ResetAllIn,
    WebhookExpenseIn,
)
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


@router.post("/webhook/expense", dependencies=[Depends(verify_webhook_signature)])
@limiter.limit("20/minute")
def webhook_expense(request: Request, payload: WebhookExpenseIn, db: Session = Depends(get_db)):
    # `request: Request` no se usa para parsear el payload (FastAPI lo
    # inyecta normalmente vía `payload`) — slowapi's @limiter.limit lo
    # requiere en la firma para poder aplicar el rate limit sobre esta ruta.
    #
    # Sin response_model=ExpenseOut a propósito: engine.ingest_webhook
    # puede devolver un dict {"status": "ignored", ...} cuando descarta un
    # código de verificación en vez de un Expense — forzar ExpenseOut aquí
    # rompería esa respuesta (200, no un gasto real que serializar).
    try:
        result = engine.ingest_webhook(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if isinstance(result, dict):
        return result
    return ExpenseOut.model_validate(result)


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


# Registrado ANTES de /expenses/{expense_id} a propósito — igual que
# /expenses/review arriba: si fuera después, FastAPI intentaría convertir
# "search" al tipo int de expense_id y devolvería 422 en vez de llegar
# aquí (Starlette resuelve rutas en orden de registro, no compara
# especificidad).
@router.get("/expenses/search", dependencies=[Depends(verify_app_token)])
def search_expenses(
    query: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    try:
        result = engine.search_expenses(
            db,
            query=query,
            category=category,
            date_from=date_from,
            date_to=date_to,
            amount_min=amount_min,
            amount_max=amount_max,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return {
        "total": result["total"],
        "expenses": [ExpenseOut.model_validate(e) for e in result["expenses"]],
    }


# Registrado ANTES de /expenses/{expense_id} por el mismo motivo que
# /expenses/search y /expenses/review de arriba.
@router.get("/expenses/comparison", dependencies=[Depends(verify_app_token)])
def get_comparison(month: str | None = None, db: Session = Depends(get_db)):
    from datetime import date as date_cls

    month = month or date_cls.today().strftime("%Y-%m")
    try:
        return engine.get_month_comparison(db, month)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# Registrado ANTES de /expenses/{expense_id} por el mismo motivo que las
# demás rutas literales de /expenses/* de arriba.
@router.get("/expenses/recurring", dependencies=[Depends(verify_app_token)])
def list_recurring(db: Session = Depends(get_db)):
    return engine.detect_recurring(db)


# Registrado ANTES de /expenses/{expense_id} por el mismo motivo que las
# demás rutas literales de /expenses/* de arriba (aunque aquí no colisiona
# por método — reset-all es POST y {expense_id} solo expone GET/PATCH/
# DELETE — se mantiene aquí por consistencia con el resto de rutas
# literales).
@router.post("/expenses/reset-all", dependencies=[Depends(verify_app_token)])
def reset_all_expenses(payload: ResetAllIn, db: Session = Depends(get_db)):
    if payload.confirm != "BORRAR":
        raise HTTPException(status_code=400, detail="confirm debe ser exactamente 'BORRAR'")
    engine.reset_all_expenses(db)
    return {"status": "ok"}


# Registrado ANTES de /expenses/{expense_id} por el mismo motivo que las
# demás rutas literales de /expenses/* de arriba.
@router.get(
    "/expenses/discarded",
    response_model=list[DiscardedMessageOut],
    dependencies=[Depends(verify_app_token)],
)
def list_discarded_messages(since: str | None = None, db: Session = Depends(get_db)):
    from datetime import date as date_cls

    since_date = None
    if since is not None:
        try:
            since_date = date_cls.fromisoformat(since)
        except ValueError as e:
            raise HTTPException(
                status_code=422, detail=f"since inválida: {since!r} (usa YYYY-MM-DD)"
            ) from e
    return engine.list_discarded_messages(db, since=since_date)


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


@router.delete("/expenses/{expense_id}", dependencies=[Depends(verify_app_token)])
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    deleted = engine.delete_expense(db, expense_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"status": "ok"}


@router.post("/expenses", response_model=ExpenseOut, dependencies=[Depends(verify_app_token)])
def create_manual_expense(payload: ManualExpenseIn, db: Session = Depends(get_db)):
    return engine.create_manual_expense(db, payload)


@router.get("/budgets", response_model=list[BudgetOut], dependencies=[Depends(verify_app_token)])
def list_budgets(month: str | None = None, db: Session = Depends(get_db)):
    from datetime import date as date_cls

    month = month or date_cls.today().strftime("%Y-%m")
    try:
        return engine.get_budgets_for_month(db, month)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.put(
    "/budgets/{category}", response_model=BudgetOut, dependencies=[Depends(verify_app_token)]
)
def upsert_budget(
    category: str, payload: BudgetSetIn, month: str | None = None, db: Session = Depends(get_db)
):
    from datetime import date as date_cls

    month = month or date_cls.today().strftime("%Y-%m")
    try:
        engine.set_budget(db, category, month, payload.limit_amount)
        budgets = engine.get_budgets_for_month(db, month)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return next(b for b in budgets if b.category == category)


@router.get("/calendar", dependencies=[Depends(verify_app_token)])
def get_calendar(month: str | None = None, db: Session = Depends(get_db)):
    from datetime import date as date_cls

    month = month or date_cls.today().strftime("%Y-%m")
    try:
        result = engine.get_calendar_month(db, month)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return {
        "month": result["month"],
        "days": [
            {
                "date": day["date"],
                "expenses": [ExpenseOut.model_validate(e) for e in day["expenses"]],
                "notes": [CalendarNoteOut.model_validate(n) for n in day["notes"]],
                "total_day": day["total_day"],
            }
            for day in result["days"]
        ],
    }


@router.post(
    "/calendar/notes", response_model=CalendarNoteOut, dependencies=[Depends(verify_app_token)]
)
def create_calendar_note(payload: CalendarNoteIn, db: Session = Depends(get_db)):
    return engine.create_calendar_note(db, payload)


@router.delete("/calendar/notes/{note_id}", dependencies=[Depends(verify_app_token)])
def delete_calendar_note(note_id: int, db: Session = Depends(get_db)):
    deleted = engine.delete_calendar_note(db, note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Calendar note not found")
    return {"status": "ok"}


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
