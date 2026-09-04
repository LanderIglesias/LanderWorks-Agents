"""Tests de `backend.main._flatten_routes` -- hallazgo real: FastAPI
envuelve las rutas incluidas vía `include_router()` en un objeto
`_IncludedRouter` sin atributo `.path` propio, y el prefijo de un
`include_router(..., prefix=...)` anidado NO viene ya aplicado en
`.original_router.routes` (vive en `.include_context.prefix`). Ambos
hallazgos surgieron construyendo el Hub Personal de Agentes, que usa
`/admin/routes` para saber qué rutas responden de verdad."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.main import _flatten_routes, app


def test_flatten_routes_ve_las_rutas_de_un_router_incluido():
    """Reproduce el bug real: sin aplanar `_IncludedRouter`, una ruta
    de un sub-router aparecía con `path` vacío en vez del real."""
    sub_app = FastAPI()
    router = APIRouter(prefix="/ejemplo")

    @router.get("/demo")
    def demo():
        return {"ok": True}

    sub_app.include_router(router)

    paths = {r["path"] for r in _flatten_routes(sub_app.routes)}
    assert "/ejemplo/demo" in paths


def test_flatten_routes_aplica_el_prefijo_del_include_router_anidado():
    """Hallazgo real de la revisión de código: la primera versión de
    `_flatten_routes` no acumulaba el `prefix=` de un `include_router`
    exterior, así que reportaría `/interno/demo` en vez de la ruta real
    servida, `/externo/interno/demo` -- una ruta fantasma que 404
    de verdad si alguien la usara."""
    sub_app = FastAPI()
    inner = APIRouter(prefix="/interno")

    @inner.get("/demo")
    def demo():
        return {"ok": True}

    outer = APIRouter()
    outer.include_router(inner)
    sub_app.include_router(outer, prefix="/externo")

    paths = {r["path"] for r in _flatten_routes(sub_app.routes)}
    assert "/externo/interno/demo" in paths
    assert "/interno/demo" not in paths


def test_admin_routes_responde_con_rutas_reales_del_proceso():
    """Test de humo contra la app real -- confirma que el endpoint
    real sigue respondiendo 200 con una lista no vacía tras el fix
    (no solo que `_flatten_routes` funciona en aislamiento)."""
    client = TestClient(app)
    resp = client.get("/admin/routes")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(r["path"] == "/admin/routes" for r in data)
