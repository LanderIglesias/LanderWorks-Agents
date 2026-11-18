import json
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
    # La inyección plantada interpola un parámetro: sql-param-por-string la marca crítica.
    sql = [
        f for f in results[Family.SAST].findings if f.file == "app/main.py" and f.line_start == 17
    ]
    assert any(f.severity == "critical" for f in sql)


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep no instalado")
def test_semgrepignore_del_repo_no_oculta_hallazgos(vibe_repo):
    (vibe_repo / ".semgrepignore").write_text("*\n", encoding="utf-8")
    results = {r.family: r for r in sast.scan_sast(vibe_repo, [], threading.Event())}
    assert any(f.file == "app/utils.py" for f in results[Family.SAST].findings)


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


def _fake_report(monkeypatch, payload: dict):
    monkeypatch.setattr(sast, "run_tool", lambda *a, **k: _write(a, json.dumps(payload)) or "")


def _item(**extra):
    base = {
        "check_id": "rules.regla-falsa",
        "path": "app/a.py",
        "start": {"line": 1},
        "end": {"line": 1},
        "extra": {
            "severity": "ERROR",
            "message": "m",
            "metadata": {"family": 2, "why": "w", "fix": "f"},
        },
    }
    base["extra"].update(extra)
    return base


def test_errores_de_semgrep_dan_analisis_parcial(monkeypatch, tmp_path):
    payload = {
        "results": [_item()],
        "errors": [{"level": "warn", "path": "app/rota.py", "message": "Syntax error"}],
        "paths": {"scanned": ["app/a.py", "app/rota.py"]},
    }
    _fake_report(monkeypatch, payload)
    results = sast.scan_sast(tmp_path, [], threading.Event())
    assert all(r.status == "ok" and "análisis parcial: 1 archivos" in r.reason for r in results)
    assert len(results[0].findings) == 1


def test_todos_los_archivos_fallidos_da_not_analyzed(monkeypatch, tmp_path):
    payload = {
        "results": [],
        "errors": [{"level": "error", "path": "app/rota.py", "message": "timeout"}],
        "paths": {"scanned": ["app/rota.py"]},
    }
    _fake_report(monkeypatch, payload)
    assert all(r.status == "not_analyzed" for r in sast.scan_sast(tmp_path, [], threading.Event()))


def test_item_malformado_se_descarta_y_severidad_desconocida_es_low(monkeypatch, tmp_path):
    payload = {"results": [{"path": 1}, _item(severity="EXPERIMENTAL")]}
    _fake_report(monkeypatch, payload)
    results = sast.scan_sast(tmp_path, [], threading.Event())
    [finding] = results[0].findings
    assert finding.severity == "low" and results[0].status == "ok"


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep no instalado")
def test_tests_y_min_js_se_analizan(vibe_repo):
    (vibe_repo / "tests").mkdir(exist_ok=True)
    py_code = "def f(x):\n    return eval(x)\n"
    (vibe_repo / "tests" / "test_x.py").write_text(py_code, encoding="utf-8")
    js_code = "function f(x){return eval(x)}\n"
    (vibe_repo / "web" / "a.min.js").write_text(js_code, encoding="utf-8")
    results = {r.family: r for r in sast.scan_sast(vibe_repo, [], threading.Event())}
    files = {f.file for f in results[Family.SAST].findings}
    assert {"tests/test_x.py", "web/a.min.js"} <= files


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep no instalado")
def test_reglas_pasan_sus_tests_anotados():
    import subprocess

    proc = subprocess.run(
        [
            "semgrep",
            "--test",
            "--config",
            str(sast.RULES_DIR),
            str(sast.RULES_DIR.parent / "rule_tests"),
            "--metrics=off",
            "--disable-version-check",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]


def test_mismas_exclusiones_y_tope_que_el_listado(monkeypatch, tmp_path):
    from backend.agents.tech_debt_agent.repo_fetcher import EXCLUDED_DIRS, MAX_FILE_BYTES

    seen = {}
    monkeypatch.setattr(
        sast, "run_tool", lambda args, **k: seen.update(args=args) or _write((args,), "{}")
    )
    sast.scan_sast(tmp_path, [], threading.Event())
    args = seen["args"]
    excluded = {args[i + 1] for i, a in enumerate(args) if a == "--exclude"}
    assert excluded == EXCLUDED_DIRS
    assert args[args.index("--max-target-bytes") + 1] == str(MAX_FILE_BYTES)


def test_rule_es_el_id_corto_de_semgrep():
    item = {
        "check_id": "backend.agents.tech_debt_agent.rules.debug-true",
        "path": "a.py",
        "start": {"line": 3},
        "end": {"line": 3},
        "extra": {
            "message": "m",
            "severity": "WARNING",
            "metadata": {"family": 6, "why": "w", "fix": "f"},
        },
    }
    assert sast._finding(item).rule == "debug-true"
