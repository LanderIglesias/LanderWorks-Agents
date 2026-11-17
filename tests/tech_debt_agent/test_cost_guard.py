import math
import sqlite3
import threading
from contextlib import closing, nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from backend.agents.tech_debt_agent import cost_guard
from backend.agents.tech_debt_agent.cost_guard import (
    BUDGET_MSG,
    DAILY_MSG,
    CostGuard,
    LimitExceeded,
    cache_key,
    default_db_path,
)

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def make(tmp_path, **kw):
    return CostGuard(tmp_path / "g.sqlite3", **kw)


def test_vigesimo_primero_del_dia_lanza(tmp_path):
    g = make(tmp_path)
    for _ in range(20):
        g.reserve(0.01, T0)
    with pytest.raises(LimitExceeded) as e:
        g.reserve(0.01, T0)
    assert e.value.message == DAILY_MSG


def test_cupo_se_reinicia_en_dia_utc_nuevo(tmp_path):
    g = make(tmp_path, daily_limit=1)
    g.reserve(0.01, datetime(2026, 11, 12, 23, 59, tzinfo=UTC))
    with pytest.raises(LimitExceeded):
        g.reserve(0.01, datetime(2026, 11, 12, 23, 59, 30, tzinfo=UTC))
    g.reserve(0.01, datetime(2026, 11, 13, 0, 1, tzinfo=UTC))


def test_presupuesto_reserva_el_maximo(tmp_path):
    g = make(tmp_path, eur_per_usd=1.0)
    g.settle(g.reserve(15, T0), 15)
    with pytest.raises(LimitExceeded) as e:
        g.reserve(6, T0)
    assert e.value.message == BUDGET_MSG
    g.reserve(4, T0)


def test_rechazo_por_presupuesto_no_consume_cupo(tmp_path):
    g = make(tmp_path, eur_per_usd=1.0, daily_limit=2)
    with pytest.raises(LimitExceeded):
        g.reserve(25, T0)
    g.reserve(1, T0)
    g.reserve(1, T0)


def test_settle_ajusta_al_coste_real(tmp_path):
    g = make(tmp_path, eur_per_usd=1.0)
    g.settle(g.reserve(10, T0), 1)
    g.reserve(18, T0)


def test_release_libera_presupuesto_y_cupo(tmp_path):
    # un análisis que falla antes del LLM no gasta: no debe agotar el cupo diario de todos
    g = make(tmp_path, eur_per_usd=1.0, daily_limit=1)
    rid = g.reserve(20, T0)
    g.release(rid)
    g.release(rid)  # repetido: no devuelve la plaza dos veces
    g.settle(g.reserve(20, T0), 0)
    with pytest.raises(LimitExceeded) as e:
        g.reserve(1, T0)
    assert e.value.message == DAILY_MSG


def test_settle_y_release_desconocidos_o_repetidos_son_noop(tmp_path):
    g = make(tmp_path, eur_per_usd=1.0)
    g.settle("nope", 1)
    g.release("nope")
    rid = g.reserve(10, T0)
    g.settle(rid, 1)
    g.release(rid)
    g.settle(rid, 9)
    g.reserve(19, T0)


def test_mes_nuevo_reinicia_presupuesto(tmp_path):
    g = make(tmp_path, eur_per_usd=1.0)
    g.settle(g.reserve(20, T0), 20)
    with pytest.raises(LimitExceeded):
        g.reserve(1, T0)
    g.reserve(20, datetime(2026, 12, 1, 0, 1, tzinfo=UTC))


def test_cache_24h(tmp_path):
    g = make(tmp_path)
    g.put_cached("k", {"a": [1, "é"]}, T0)
    assert g.get_cached("k", T0 + timedelta(hours=23)) == {"a": [1, "é"]}
    assert g.get_cached("k", T0 + timedelta(hours=25)) is None
    assert g.get_cached("otra", T0) is None


def test_persiste_tras_reabrir(tmp_path):
    make(tmp_path, daily_limit=2).reserve(0.01, T0)
    g = make(tmp_path, daily_limit=2)
    g.reserve(0.01, T0)
    with pytest.raises(LimitExceeded):
        g.reserve(0.01, T0)


def test_concurrencia_atomica(tmp_path):
    for _ in range(19):
        make(tmp_path).reserve(0.01, T0)
    ok, fail, errors = [], [], []

    def work():
        try:
            make(tmp_path).reserve(0.01, T0)
            ok.append(1)
        except LimitExceeded:
            fail.append(1)
        except Exception as exc:
            errors.append(exc)

    ts = [threading.Thread(target=work) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert len(ok) == 1 and len(fail) == 9


def test_wal_activo(tmp_path):
    g = make(tmp_path)
    with closing(sqlite3.connect(g.db_path)) as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_cache_key_normaliza():
    assert cache_key("Foo", "BAR", "abc") == cache_key("foo", "bar", "abc")
    assert cache_key("foo", "bar", "abc") != cache_key("foo", "bar", "abd")


def test_default_db_path(monkeypatch):
    monkeypatch.delenv("TECH_DEBT_DB_PATH", raising=False)
    p = default_db_path()
    assert p.is_absolute() and p.name == "tech_debt.sqlite3" and p.parent.name == "data"
    monkeypatch.setenv("TECH_DEBT_DB_PATH", "/x/y.sqlite3")
    assert default_db_path().name == "y.sqlite3"


def test_concurrencia_atomica_solo_con_transaccion_sqlite(tmp_path, monkeypatch):
    guards = [make(tmp_path) for _ in range(10)]
    for _ in range(19):
        guards[0].reserve(0.01, T0)
    monkeypatch.setattr(cost_guard, "_LOCK", nullcontext())
    ok, fail, errors = [], [], []
    barrier = threading.Barrier(10)

    def work(g):
        barrier.wait()
        try:
            g.reserve(0.01, T0)
            ok.append(1)
        except LimitExceeded:
            fail.append(1)
        except Exception as exc:
            errors.append(exc)

    ts = [threading.Thread(target=work, args=(g,)) for g in guards]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert len(ok) == 1 and len(fail) == 9


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0])
def test_costes_invalidos_lanzan_valueerror(tmp_path, bad):
    g = make(tmp_path)
    with pytest.raises(ValueError):
        g.reserve(bad, T0)
    rid = g.reserve(1, T0)
    with pytest.raises(ValueError):
        g.settle(rid, bad)


def test_datetime_naive_se_asume_utc(tmp_path):
    g = make(tmp_path, daily_limit=1)
    g.reserve(0.01, datetime(2026, 11, 12, 23, 30))
    with pytest.raises(LimitExceeded):
        g.reserve(0.01, datetime(2026, 11, 12, 23, 40, tzinfo=UTC))
    g.put_cached("k", {"a": 1}, datetime(2026, 11, 12, 10, 0))
    assert g.get_cached("k", T0 + timedelta(hours=1)) == {"a": 1}


def test_cache_expira_exactamente_a_24h(tmp_path):
    g = make(tmp_path)
    g.put_cached("k", {"a": 1}, T0)
    assert g.get_cached("k", T0 + timedelta(hours=24)) is None
    assert g.get_cached("k", T0 + timedelta(hours=24) - timedelta(seconds=1)) == {"a": 1}
