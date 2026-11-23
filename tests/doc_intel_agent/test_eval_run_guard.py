"""La evaluación nunca debe tocar la base de datos de producción (DATABASE_URL del .env)."""

import importlib
import sys

import pytest

RUN_EVAL = "backend.agents.doc_intel_agent.eval.run_eval"
DATABASE = "backend.agents.doc_intel_agent.database"


def _check(url):
    return importlib.import_module(RUN_EVAL).check_eval_db_url(url)


def test_rejects_missing_url():
    with pytest.raises(SystemExit):
        _check("")


def test_rejects_remote_host():
    with pytest.raises(SystemExit):
        _check("postgresql://u:p@db.example.com:5432/x")


def test_rejects_local_db_not_named_eval():
    with pytest.raises(SystemExit):
        _check("postgresql://u:p@localhost:5432/doc_intel")


def test_rejects_query_string_host_override():
    with pytest.raises(SystemExit):
        _check("postgresql://u:p@localhost:5436/doc_intel_eval?host=db.example.com")


def test_accepts_localhost():
    for url in (
        "postgresql://u:p@localhost:5433/doc_intel_eval",
        "postgresql://u:p@127.0.0.1:5433/doc_intel_eval",
    ):
        assert _check(url) == url


def test_partial_run_is_named_partial():
    name = importlib.import_module(RUN_EVAL).results_name
    assert name(72, 72, "20261121_100000") == "results_20261121_100000.json"
    assert name(14, 72, "20261121_100000") == "results_partial_20261121_100000.json"


def test_import_does_not_touch_database_module(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delitem(sys.modules, DATABASE, raising=False)
    monkeypatch.delitem(sys.modules, RUN_EVAL, raising=False)
    importlib.import_module(RUN_EVAL)
    assert DATABASE not in sys.modules
