import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from backend.agents.tech_debt_agent import engine
from backend.agents.tech_debt_agent.findings import Family, FamilyResult, Finding, Severity
from backend.agents.tech_debt_agent.repo_fetcher import FetchError, RepoMeta
from backend.agents.tech_debt_agent.tools import Cancelled, run_tool
from tests.tech_debt_agent.conftest import PLANTED

META = RepoMeta("octo", "demo", 10, "main", "abc123")
BINARIES = ("gitleaks", "osv-scanner", "semgrep", "ruff", "lizard")


class FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = self

    def with_options(self, **_kw):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        raise RuntimeError("sin red")


def _clone_from(src: Path):
    def fake(meta, dest, cancel, *_a, **_kw):
        shutil.copytree(src, dest)

    return fake


def _finding(family, sev, file="a.py", line=1, why="x"):
    return Finding(family, sev, file, line, line, "t", why, "f", "src")


@pytest.fixture
def tmp_dirs(monkeypatch):
    created = []
    real = tempfile.mkdtemp

    def spy(*a, **kw):
        p = real(*a, **kw)
        created.append(Path(p))
        return p

    monkeypatch.setattr(engine.tempfile, "mkdtemp", spy)
    return created


@pytest.mark.skipif(
    any(shutil.which(b) is None for b in BINARIES), reason="faltan binarios de análisis"
)
def test_pipeline_completo_sobre_fixture(vibe_repo, monkeypatch, tmp_dirs):
    monkeypatch.setattr(engine, "clone_repo", _clone_from(vibe_repo))
    events = []
    report, cost = engine.run_analysis(META, threading.Event(), events.append, FakeClient())
    fams = {f["id"]: f for f in report["families"]}
    for family, planted in PLANTED.items():
        got = {(x["file"], x["line_start"]) for x in fams[int(family)]["findings"]}
        missing = [p for p in planted if p not in got]
        assert not missing, (family, missing)
    assert report["security_gate_applied"] is True
    assert report["score"] <= 40
    for fid in range(1, 8):
        assert not [x for x in fams[fid]["findings"] if x["file"] == "app/clean.py"]
    assert fams[8]["status"] == "not_analyzed"
    assert cost > 0
    assert not tmp_dirs[0].exists()


def test_repo_sin_codigo(tmp_path, monkeypatch, tmp_dirs):
    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("hola\n", encoding="utf-8")
    monkeypatch.setattr(engine, "clone_repo", _clone_from(src))
    client = FakeClient()
    report, cost = engine.run_analysis(META, threading.Event(), lambda _e: None, client)
    assert len(report["families"]) == 8
    assert all(f["status"] == "not_analyzed" for f in report["families"])
    assert client.calls == [] and cost == 0.0
    assert not tmp_dirs[0].exists()


def _py_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    return src


def _fast_scanners(monkeypatch, **overrides):
    for name, (_fn, fams) in list(engine.SCANNERS.items()):
        fn = overrides.get(name) or (
            lambda _r, _f, _c, fams=fams: [FamilyResult(f, "ok", None, []) for f in fams]
        )
        monkeypatch.setitem(engine.SCANNERS, name, (fn, fams))


def test_cancelacion_limpia(tmp_path, monkeypatch, tmp_dirs):
    monkeypatch.setattr(engine, "clone_repo", _clone_from(_py_repo(tmp_path)))

    def sleeper(root, _files, cancel):
        run_tool([sys.executable, "-c", "import time; time.sleep(30)"], root, 60, cancel)
        return []

    _fast_scanners(monkeypatch, secrets=sleeper)
    cancel = threading.Event()
    client = FakeClient()
    threading.Timer(0.5, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(Cancelled):
        engine.run_analysis(META, cancel, lambda _e: None, client)
    assert time.monotonic() - t0 < 5
    assert tmp_dirs and not tmp_dirs[0].exists()
    assert client.calls == []


def test_fetch_error_limpia(tmp_path, monkeypatch, tmp_dirs):
    def boom(meta, dest, cancel, *_a, **_kw):
        dest.mkdir()
        raise FetchError("no")

    monkeypatch.setattr(engine, "clone_repo", boom)
    with pytest.raises(FetchError):
        engine.run_analysis(META, threading.Event(), lambda _e: None, FakeClient())
    assert not tmp_dirs[0].exists()


def test_escaner_que_falla_da_not_analyzed(tmp_path, monkeypatch, tmp_dirs):
    monkeypatch.setattr(engine, "clone_repo", _clone_from(_py_repo(tmp_path)))

    def bad(*_a):
        raise RuntimeError("XYZ_DETALLE /ruta/interna")

    events = []
    _fast_scanners(monkeypatch, secrets=bad)
    report, _ = engine.run_analysis(META, threading.Event(), events.append, FakeClient())
    fams = {f["id"]: f for f in report["families"]}
    assert fams[1]["status"] == "not_analyzed"
    assert fams[1]["reason"] == "error interno del analizador"
    assert fams[3]["status"] == "ok"
    assert "XYZ_DETALLE" not in str(events) and "/ruta" not in str(events)
    assert "XYZ_DETALLE" not in report["markdown"]


def test_emite_progreso_en_orden(tmp_path, monkeypatch, tmp_dirs):
    monkeypatch.setattr(engine, "clone_repo", _clone_from(_py_repo(tmp_path)))
    _fast_scanners(monkeypatch)
    events = []
    engine.run_analysis(META, threading.Event(), events.append, FakeClient())
    assert events[0]["step"] == "clone" and events[-1]["step"] == "report"
    assert events[-1]["progress"] == 100
    prog = [e["progress"] for e in events]
    assert prog == sorted(prog)
    assert all(set(e) == {"step", "message", "progress"} for e in events)
    assert str(tmp_dirs[0]) not in str(events)


def test_fusion_por_familia():
    hi = _finding(Family.SAST, Severity.HIGH)
    lo = _finding(Family.SAST, Severity.LOW)
    other = _finding(Family.SAST, Severity.LOW, line=2)
    merged = engine.merge_results(
        [
            FamilyResult(Family.SAST, "ok", None, [lo, other]),
            FamilyResult(Family.SAST, "ok", "nota", [hi]),
            FamilyResult(Family.SAST, "not_analyzed", "semgrep ausente"),
            FamilyResult(Family.CVE, "not_analyzed", "a"),
            FamilyResult(Family.CVE, "not_analyzed", "b"),
            FamilyResult(Family.AI_TELLS, "ok", None, []),
        ]
    )
    by = {r.family: r for r in merged}
    sast = by[Family.SAST]
    assert sast.status == "ok"
    assert [f.severity for f in sast.findings] == [Severity.HIGH, Severity.LOW]
    assert "semgrep ausente" in sast.reason and "nota" in sast.reason
    assert by[Family.CVE].status == "not_analyzed"
    assert Family.AI_TELLS not in by
