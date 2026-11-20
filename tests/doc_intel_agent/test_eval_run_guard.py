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


def test_accepts_localhost():
    for url in (
        "postgresql://u:p@localhost:5433/doc_intel_eval",
        "postgresql://u:p@127.0.0.1:5433/doc_intel_eval",
    ):
        assert _check(url) == url


def test_import_does_not_touch_database_module(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delitem(sys.modules, DATABASE, raising=False)
    monkeypatch.delitem(sys.modules, RUN_EVAL, raising=False)
    importlib.import_module(RUN_EVAL)
    assert DATABASE not in sys.modules
