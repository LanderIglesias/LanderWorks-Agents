"""Checks de las defensas del BI agent: sandbox de exec() y allowlist de execute_sql."""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from backend.agents.bi_agent import code_executor
from backend.agents.bi_agent.sqlite_store import execute_sql


def test_escape_por_atributos_bloqueado():
    r = code_executor.execute("().__class__.__bases__[0].__subclasses__()", pd.DataFrame())
    assert r["success"] is False
    assert "disallowed pattern" in r["error"]


def test_codigo_normal_se_ejecuta():
    r = code_executor.execute("result = df.shape[0]", pd.DataFrame({"a": [1, 2]}))
    assert r["success"] is True
    assert r["result"] == 2


def test_bucle_infinito_se_corta(monkeypatch):
    monkeypatch.setattr(code_executor, "EXECUTION_TIMEOUT_SECONDS", 1)
    r = code_executor.execute("while True:\n    pass", pd.DataFrame())
    assert r["success"] is False
    assert "exceeded" in r["error"]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    return str(path)


def test_attach_rechazado(db_path, tmp_path):
    with pytest.raises(ValueError):
        execute_sql(db_path, f"ATTACH DATABASE '{tmp_path / 'x.db'}' AS x")
    assert not (tmp_path / "x.db").exists()


def test_select_con_comentario_inicial(db_path):
    df = execute_sql(db_path, "-- total\nSELECT COUNT(*) AS n FROM t")
    assert df["n"].iloc[0] == 1
