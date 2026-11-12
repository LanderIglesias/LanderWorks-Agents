import shutil
import threading

import pytest

from backend.agents.tech_debt_agent.findings import Family
from backend.agents.tech_debt_agent.scanners import sast
from tests.tech_debt_agent.conftest import PLANTED

FAMILIES = (Family.SAST, Family.ERRORS, Family.DEBUG)


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep no instalado")
def test_semgrep_detecta_plantados(vibe_repo):
    results = {r.family: r for r in sast.scan_sast(vibe_repo, [], threading.Event())}
    assert all(r.status == "ok" for r in results.values())
    for family in FAMILIES:
        found = results[family].findings
        for file, line in PLANTED[family]:
            assert any(f.file == file and abs(f.line_start - line) <= 1 for f in found), (
                family,
                file,
                line,
            )
    everything = [f for r in results.values() for f in r.findings]
    assert not [f for f in everything if f.file == "app/clean.py"]
    assert all(f.source == "semgrep" for f in everything)
    evals = [
        f for f in results[Family.SAST].findings if f.file == "app/utils.py" and f.line_start == 8
    ]
    assert any(f.severity == "critical" for f in evals)


def test_reglas_tienen_metadata_valida():
    import yaml

    rules = []
    for path in sast.RULES_DIR.glob("*.yml"):
        rules += yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]
    assert rules
    for rule in rules:
        meta = rule["metadata"]
        assert Family(meta["family"]) in (*FAMILIES, Family.AI_TELLS), rule["id"]
        assert meta["why"] and meta["fix"], rule["id"]
        assert rule["severity"] in ("ERROR", "WARNING", "INFO"), rule["id"]


def test_semgrep_ausente_da_not_analyzed(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    results = sast.scan_sast(tmp_path, [], threading.Event())
    assert {r.family for r in results} == {*FAMILIES, Family.AI_TELLS}
    assert all(
        r.status == "not_analyzed" and str(tmp_path) not in (r.reason or "") for r in results
    )


def test_salida_malformada_da_not_analyzed(monkeypatch, tmp_path):
    for bad in ('{"results": [{"path": 1}]}', "[]", '{"results": [{"extra": null}]}'):
        monkeypatch.setattr(sast, "run_tool", lambda *a, _b=bad, **k: _write(a, _b))
        results = sast.scan_sast(tmp_path, [], threading.Event())
        assert all(r.status == "not_analyzed" for r in results), bad


def _write(args, content):
    from pathlib import Path

    Path(args[0][args[0].index("--output") + 1]).write_text(content, encoding="utf-8")
    return ""
