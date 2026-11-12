"""api.py — endpoints FastAPI del Technical Debt Analyzer (público: límites, caché y SSE cancelable)."""

from __future__ import annotations

import asyncio
import json
import logging
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .cost_guard import CostGuard, LimitExceeded, cache_key, default_db_path
from .demo_template import demo_html
from .engine import run_analysis
from .llm_reviewer import max_cost_usd
from .repo_fetcher import FetchError, get_repo_meta, normalize_github_url
from .tools import Cancelled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tech-debt", tags=["tech-debt"])

MAX_CONCURRENT = 2
RATE_LIMIT = "5/minute;30/day"
BUSY_MSG = "Demasiados análisis en curso, inténtalo en un minuto"
INTERNAL_MSG = "Error interno al analizar el repositorio"
JOIN_TIMEOUT_S = 10

_SEM = threading.BoundedSemaphore(MAX_CONCURRENT)
_guards: dict[str, CostGuard] = {}
_guards_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    # Detrás de Cloudflare la IP de conexión es la del proxy; CF-Connecting-IP trae la real.
    return request.headers.get("CF-Connecting-IP") or (
        request.client.host if request.client else "unknown"
    )


limiter = Limiter(key_func=_client_ip)


def setup_rate_limiting(app) -> None:
    """Registra el handler 429 y deja `app.state.limiter` si nadie lo puso ya.

    El decorador de slowapi usa la instancia propia del router; app.state.limiter solo lo
    leen el handler y el middleware, así que puede convivir con el del expense tracker.
    """
    if not hasattr(app.state, "limiter"):
        app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _get_guard() -> CostGuard:
    path = str(default_db_path())
    with _guards_lock:
        if path not in _guards:
            _guards[path] = CostGuard(default_db_path())
        return _guards[path]


class AnalyzeRequest(BaseModel):
    github_url: str


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _run_billed(meta, cancel: threading.Event, emit) -> tuple[dict, float]:
    if not _SEM.acquire(blocking=False):
        raise ApiError(503, BUSY_MSG)
    try:
        guard = _get_guard()
        try:
            rid = guard.reserve(max_cost_usd())
        except LimitExceeded as exc:
            raise ApiError(429, exc.message) from exc
        llm_reached = False

        def tracked_emit(event: dict) -> None:
            nonlocal llm_reached
            if event.get("step") == "llm_review":
                llm_reached = True
            emit(event)

        cost: float | None = None
        try:
            report, cost = run_analysis(meta, cancel, tracked_emit)
            return report, cost
        finally:
            # exactamente una de las dos: settle con el coste real, o con el máximo si el LLM
            # pudo llamarse y no hay coste conocido; release si falló antes del LLM
            if cost is not None:
                guard.settle(rid, cost)
            elif llm_reached:
                guard.settle(rid, max_cost_usd())
            else:
                guard.release(rid)
    finally:
        _SEM.release()


def _analyze(url: str, cancel: threading.Event, emit) -> tuple[dict, bool]:
    """Flujo completo y bloqueante; lanza ApiError con mensajes aptos para el cliente."""
    try:
        owner, repo = normalize_github_url(url)
        meta = get_repo_meta(owner, repo)
        guard = _get_guard()
        key = cache_key(owner, repo, meta.head_sha)
        cached = guard.get_cached(key)
        if cached is not None:
            return cached, True
        report, _ = _run_billed(meta, cancel, emit)
        guard.put_cached(key, report)
        return report, False
    except ApiError:
        raise
    except FetchError as exc:
        raise ApiError(400, str(exc)) from exc
    except Cancelled as exc:
        raise ApiError(500, "Análisis cancelado") from exc
    except Exception as exc:
        logger.exception("fallo inesperado en el análisis")
        raise ApiError(500, INTERNAL_MSG) from exc


@router.post("/analyze")
@limiter.limit(RATE_LIMIT)
def analyze(request: Request, payload: AnalyzeRequest):
    try:
        report, cached = _analyze(payload.github_url, threading.Event(), lambda _e: None)
    except ApiError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {**report, "cached": cached}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def event_stream(request: Request, url: str):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    cancel = threading.Event()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def work() -> None:
        try:
            report, cached = _analyze(url, cancel, emit)
            final = {
                "step": "done",
                "message": "Análisis completado",
                "progress": 100,
                "report": report,
                "cached": cached,
            }
        except ApiError as exc:
            final = {"step": "error", "status": exc.status, "message": exc.message}
        emit(final)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), 1.0)
            except TimeoutError:
                event = None
            if event is not None:
                yield _sse(event)
                if event["step"] in ("done", "error"):
                    break
            if await request.is_disconnected():
                break
    finally:
        cancel.set()
        await asyncio.to_thread(worker.join, JOIN_TIMEOUT_S)


@router.post("/analyze/stream")
@limiter.limit(RATE_LIMIT)
async def analyze_stream(request: Request, payload: AnalyzeRequest):
    return StreamingResponse(
        event_stream(request, payload.github_url),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.get("/demo", response_class=HTMLResponse)
def serve_demo():
    return HTMLResponse(content=demo_html())
