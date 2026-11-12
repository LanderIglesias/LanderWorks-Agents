import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from backend.agents.tech_debt_agent.findings import Family
from backend.agents.tech_debt_agent.scanners import deps, secrets

SECRET = "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks no instalado")
def test_gitleaks_encuentra_secreto_en_historial(vibe_repo):
    [res] = secrets.scan_secrets(vibe_repo, [], threading.Event())
    assert res.family == Family.SECRETS and res.status == "ok"
    hits = [f for f in res.findings if f.file == "app/config.py"]
    assert hits and all(f.severity == "critical" for f in hits)
    assert "solo en el historial" in hits[0].why
    assert SECRET not in json.dumps([f.to_dict() for f in res.findings])


@pytest.mark.skipif(shutil.which("osv-scanner") is None, reason="osv-scanner no instalado")
def test_osv_encuentra_cves(vibe_repo):
    [res] = deps.scan_deps(vibe_repo, [], threading.Event())
    assert res.family == Family.CVE and res.status == "ok"
    assert {f.file for f in res.findings} <= {"requirements.txt", "web/package-lock.json"}
    titles = " ".join(f.title.lower() for f in res.findings)
    assert "pyyaml" in titles or "requests" in titles
    assert "lodash" in titles


@pytest.mark.parametrize("mod,fn", [(secrets, "scan_secrets"), (deps, "scan_deps")])
def test_binario_ausente_da_not_analyzed(monkeypatch, tmp_path, mod, fn):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    [res] = getattr(mod, fn)(tmp_path, [], threading.Event())
    assert res.status == "not_analyzed" and res.reason and str(tmp_path) not in res.reason


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks no instalado")
def test_gitleaks_secreto_vigente_en_codigo_actual(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "cfg.py").write_text(f'KEY = "{SECRET}"\n', encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@e.x"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-qm", "i"], cwd=repo, check=True, capture_output=True)
    [res] = secrets.scan_secrets(repo, [], threading.Event())
    assert res.findings and "código actual del repo" in res.findings[0].why


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks no instalado")
def test_gitleaks_ignora_config_del_repo(vibe_repo):
    cfg = "[allowlist]\npaths = ['''app/config.py''']\n"
    (vibe_repo / ".gitleaks.toml").write_text(cfg, encoding="utf-8")
    [res] = secrets.scan_secrets(vibe_repo, [], threading.Event())
    assert any(f.file == "app/config.py" for f in res.findings)


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks no instalado")
def test_gitleaks_repo_limpio_es_ok(tmp_path):
    [res] = secrets.scan_secrets(tmp_path, [], threading.Event())
    assert res.status == "ok" and res.findings == []


@pytest.mark.parametrize("exc", [RuntimeError("x"), ValueError("x")])
def test_gitleaks_error_es_not_analyzed(monkeypatch, tmp_path, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(secrets, "run_tool", boom)
    [res] = secrets.scan_secrets(tmp_path, [], threading.Event())
    assert res.status == "not_analyzed" and res.reason


@pytest.mark.parametrize("report", ["null", "{}", "[1]", "[null]", "no es json"])
def test_gitleaks_forma_malformada_es_not_analyzed(monkeypatch, tmp_path, report):
    def fake(args, **k):
        Path(args[args.index("--report-path") + 1]).write_text(report, encoding="utf-8")
        return ""

    monkeypatch.setattr(secrets, "run_tool", fake)
    [res] = secrets.scan_secrets(tmp_path, [], threading.Event())
    assert res.status == "not_analyzed"


@pytest.mark.parametrize(
    "out",
    ["null", "[]", "[1]", "no json", '{"results": [1]}', '{"results": [{"source": null}]}'],
)
def test_osv_forma_malformada_es_not_analyzed(monkeypatch, tmp_path, out):
    monkeypatch.setattr(deps, "run_tool", lambda *a, **k: out)
    [res] = deps.scan_deps(tmp_path, [], threading.Event())
    assert res.status == "not_analyzed"


def test_osv_source_path_vacio_se_ignora(monkeypatch, tmp_path):
    pkg = '{"package": {"name": "a"}, "groups": [{}]}'
    out = '{"results": [{"source": {"path": ""}, "packages": [' + pkg + "]}]}"
    monkeypatch.setattr(deps, "run_tool", lambda *a, **k: out)
    [res] = deps.scan_deps(tmp_path, [], threading.Event())
    assert res.status == "ok" and res.findings == []


@pytest.mark.skipif(shutil.which("osv-scanner") is None, reason="osv-scanner no instalado")
def test_osv_sin_manifiestos_es_ok(tmp_path):
    [res] = deps.scan_deps(tmp_path, [], threading.Event())
    assert res.status == "ok" and res.findings == []
    assert res.reason == "sin manifiestos de dependencias"


@pytest.mark.parametrize(
    "out",
    [
        '{"results": [{}]}',
        '{"results": [{"source": {}}]}',
        '{"results": [{"source": {"path": "x"}, "packages": [{"groups": [{}]}]}]}',
        '{"results": [{"source": {"path": "x"}, "packages": [{"package": {}, "groups": [{"ids": []}]}]}]}',
        '{"results": [{"source": {"path": "x"}, "packages": [1]}]}',
    ],
)
def test_osv_formas_incompletas_son_not_analyzed(monkeypatch, tmp_path, out):
    (tmp_path / "x").write_text("", encoding="utf-8")
    out = out.replace('"path": "x"', '"path": ' + json.dumps(str(tmp_path / "x")))
    monkeypatch.setattr(deps, "run_tool", lambda *a, **k: out)
    [res] = deps.scan_deps(tmp_path, [], threading.Event())
    assert res.status == "not_analyzed"


def test_osv_salida_vacia_con_manifiesto_es_not_analyzed(monkeypatch, tmp_path):
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(deps, "run_tool", lambda *a, **k: "")
    [res] = deps.scan_deps(tmp_path, [], threading.Event())
    assert res.status == "not_analyzed"
