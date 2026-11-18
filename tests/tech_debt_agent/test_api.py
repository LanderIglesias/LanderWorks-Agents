import asyncio
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agents.tech_debt_agent import api
from backend.agents.tech_debt_agent.cost_guard import BUDGET_MSG, DAILY_MSG, CostGuard
from backend.agents.tech_debt_agent.repo_fetcher import FetchError, RepoMeta

URL = "https://github.com/octo/demo"
META = RepoMeta("octo", "demo", 100, "main", "a" * 40)
REPORT = {"score": 90, "grade": "A", "markdown": "# ok", "families": [], "top": []}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TECH_DEBT_DB_PATH", str(tmp_path / "td.sqlite3"))
    monkeypatch.setattr(api, "get_repo_meta", lambda o, r, client=None: META)
    api.limiter.reset()
    api._meta_cache.clear()
    calls = []

    def fake_run(meta, cancel, emit, llm_client=None):
        calls.append(meta)
        emit({"step": "llm_review", "message": "x", "progress": 80})
        return dict(REPORT), 0.01

    monkeypatch.setattr(api, "run_analysis", fake_run)
    app = FastAPI()
    app.include_router(api.router)
    api.setup_rate_limiting(app)
    return TestClient(app, raise_server_exceptions=False), calls, tmp_path / "td.sqlite3"


def post(client, url=URL, path="/tech-debt/analyze"):
    return client.post(path, json={"github_url": url})


def test_url_invalida_400(env):
    client, calls, _ = env
    r = post(client, "https://evil.com/a/b")
    assert r.status_code == 400
    assert calls == []


def test_exito_y_cache_hit_no_llama_al_engine_ni_consume_cupo(env):
    client, calls, db = env
    first = post(client)
    assert first.status_code == 200 and first.json()["cached"] is False
    second = post(client)
    assert second.status_code == 200 and second.json()["cached"] is True
    assert len(calls) == 1
    assert CostGuard(db).reserve(0.01)


def test_informe_degradado_no_se_cachea(env, monkeypatch):
    client, calls, _ = env
    degraded = {
        **REPORT,
        "families": [{"status": "not_analyzed", "reason": "El escáner SAST falló"}],
    }
    monkeypatch.setattr(
        api,
        "run_analysis",
        lambda m, c, e, llm_client=None: (calls.append(m) or dict(degraded), 0.01),
    )
    assert post(client).json()["cached"] is False
    assert post(client).json()["cached"] is False
    assert len(calls) == 2
    permanent = {**REPORT, "families": [{"status": "not_analyzed", "reason": "sin código fuente"}]}
    monkeypatch.setattr(
        api, "run_analysis", lambda m, c, e, llm_client=None: (dict(permanent), 0.01)
    )
    post(client)
    assert post(client).json()["cached"] is True


def test_cf_connecting_ip_solo_con_proxy_de_confianza(monkeypatch):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(b"cf-connecting-ip", b"9.9.9.9")],
        "client": ("1.2.3.4", 1),
    }
    monkeypatch.delenv("TECH_DEBT_TRUST_CF_HEADER", raising=False)
    assert api._client_ip(Request(scope)) == "1.2.3.4"
    monkeypatch.setenv("TECH_DEBT_TRUST_CF_HEADER", "1")
    assert api._client_ip(Request(scope)) == "9.9.9.9"


def test_cupo_diario_429_mensaje_exacto(env):
    client, calls, db = env
    guard = CostGuard(db)
    for _ in range(20):
        guard.settle(guard.reserve(0.01), 0.01)
    r = post(client)
    assert r.status_code == 429 and r.json()["detail"] == DAILY_MSG
    assert calls == []


def test_presupuesto_429_no_llama_al_engine(env, monkeypatch):
    client, calls, db = env
    CostGuard(db).settle(CostGuard(db).reserve(0.01), 100.0)
    r = post(client)
    assert r.status_code == 429 and r.json()["detail"] == BUDGET_MSG
    assert calls == []


def test_error_interno_sin_rutas(env, monkeypatch):
    client, _, db = env

    def boom(*a, **k):
        raise RuntimeError("/tmp/tech_debt_x/secret")

    monkeypatch.setattr(api, "run_analysis", boom)
    r = post(client)
    assert r.status_code == 500
    assert "/tmp" not in r.text and "secret" not in r.text
    assert CostGuard(db).reserve(0.01)


def test_fetch_error_400_y_libera_reserva(env, monkeypatch):
    client, _, db = env

    def fail(*a, **k):
        raise FetchError("El repositorio no existe o es privado")

    monkeypatch.setattr(api, "run_analysis", fail)
    r = post(client)
    assert r.status_code == 400 and "privado" in r.json()["detail"]
    with __import__("contextlib").closing(CostGuard(db)._connect()) as c:
        assert c.execute("SELECT settled_usd FROM reservations").fetchall() == [(0.0,)]


def test_fallo_tras_llm_liquida_al_maximo(env, monkeypatch):
    client, _, db = env

    def late(meta, cancel, emit, llm_client=None):
        emit({"step": "llm_review", "message": "x", "progress": 80})
        raise RuntimeError("x")

    monkeypatch.setattr(api, "run_analysis", late)
    assert post(client).status_code == 500
    with __import__("contextlib").closing(CostGuard(db)._connect()) as c:
        (settled,) = c.execute("SELECT settled_usd FROM reservations").fetchone()
    assert settled == pytest.approx(api.max_cost_usd())


def test_concurrencia_503(env, monkeypatch):
    client, calls, _ = env
    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    monkeypatch.setattr(api, "_SEM", sem)
    r = post(client)
    assert r.status_code == 503 and r.json()["detail"] == api.BUSY_MSG
    assert calls == []


def test_rate_limit_por_ip(env):
    client, _, _ = env
    codes = [post(client, "https://evil.com/a/b").status_code for _ in range(6)]
    assert codes[-1] == 429 and set(codes[:5]) == {400}


def test_stream_done_trae_report(env):
    client, _, _ = env
    r = post(client, path="/tech-debt/analyze/stream")
    assert r.status_code == 200
    events = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
    import json

    last = json.loads(events[-1])
    assert last["step"] == "done" and last["report"]["score"] == 90 and last["cached"] is False
    assert json.loads(events[0])["step"] == "llm_review"


def test_stream_url_invalida_evento_error(env):
    client, _, _ = env
    r = post(client, "nope", path="/tech-debt/analyze/stream")
    import json

    last = json.loads(r.text.strip().splitlines()[-1][6:])
    assert last["step"] == "error" and last["status"] == 400


class FakeRequest:
    def __init__(self, disconnect_after: float | None = None):
        self._t0 = time.monotonic()
        self._after = disconnect_after

    async def is_disconnected(self):
        return self._after is not None and time.monotonic() - self._t0 >= self._after


def _blocking_run(monkeypatch, state):
    def run(meta, cancel, emit, llm_client=None):
        emit({"step": "clone", "message": "x", "progress": 5})
        state["got_cancel"] = cancel.wait(8)
        state["t"] = time.monotonic()
        from backend.agents.tech_debt_agent.tools import Cancelled

        raise Cancelled()

    monkeypatch.setattr(api, "run_analysis", run)


@pytest.mark.parametrize("mode", ["aclose", "disconnect"])
def test_stream_desconexion_cancela(env, monkeypatch, mode):
    _, _, db = env
    state: dict = {}
    _blocking_run(monkeypatch, state)

    async def main():
        req = FakeRequest(0.3 if mode == "disconnect" else None)
        gen = api.event_stream(req, URL)
        first = await gen.__anext__()
        assert '"clone"' in first
        t0 = time.monotonic()
        if mode == "aclose":
            await gen.aclose()
        else:
            async for _ in gen:
                pass
        return t0

    t0 = asyncio.run(main())
    assert state["got_cancel"] is True and state["t"] - t0 < 3
    import contextlib

    with contextlib.closing(CostGuard(db)._connect()) as c:
        assert c.execute("SELECT settled_usd FROM reservations").fetchall() == [(0.0,)]


def test_convive_con_el_limiter_del_expense_tracker():
    from backend.main import app

    r = TestClient(app).post("/tech-debt/analyze", json={"github_url": "https://evil.com/a/b"})
    assert r.status_code in (400, 429)
    assert hasattr(app.state, "limiter")


def _spend(db):
    import contextlib

    with contextlib.closing(CostGuard(db)._connect()) as c:
        return c.execute("SELECT settled_usd FROM reservations").fetchall()


def test_exito_liquida_el_coste_real(env):
    client, _, db = env
    assert post(client).status_code == 200
    assert _spend(db) == [(0.01,)]


def test_stream_done_liquida_y_cachea(env):
    client, calls, db = env
    post(client, path="/tech-debt/analyze/stream")
    assert _spend(db) == [(0.01,)]
    assert post(client).json()["cached"] is True
    assert len(calls) == 1


def test_meta_cache_ttl_evita_llamadas_a_github(env, monkeypatch):
    client, _, _ = env
    n = []

    def meta(o, r, client=None):
        n.append((o, r))
        return META

    monkeypatch.setattr(api, "get_repo_meta", meta)
    post(client)
    post(client, "https://github.com/OCTO/Demo")
    assert len(n) == 1
    api._meta_cache.clear()
    post(client)
    assert len(n) == 2


def test_demo_tiene_descarga_json(env):
    client, _, _ = env
    html = client.get("/tech-debt/demo").text
    assert 'id="downloadJsonBtn"' in html
    assert "application/json" in html and "-tech-debt.json" in html
