import json
import shutil
import threading

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
    assert "rotar" in hits[0].why
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
