import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

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
    ai = _finding(Family.AI_TELLS, Severity.LOW, line=5)
    ai_hi = _finding(Family.AI_TELLS, Severity.MEDIUM, line=5)
    merged = engine.merge_results(
        [
            FamilyResult(Family.SAST, "ok", None, [lo, other]),
            FamilyResult(Family.SAST, "ok", "nota", [hi]),
            FamilyResult(Family.SAST, "not_analyzed", "semgrep ausente"),
            FamilyResult(Family.CVE, "not_analyzed", "a"),
            FamilyResult(Family.CVE, "not_analyzed", "b"),
            FamilyResult(Family.AI_TELLS, "ok", None, [ai, ai_hi]),
        ]
    )
    by = {r.family: r for r in merged}
    sast = by[Family.SAST]
    assert sast.status == "ok"
    assert [f.severity for f in sast.findings] == [Severity.HIGH, Severity.LOW]
    assert "semgrep ausente" in sast.reason and "nota" in sast.reason
    assert by[Family.CVE].status == "not_analyzed"
    assert by[Family.AI_TELLS].status == "not_analyzed"
    assert [f.severity for f in by[Family.AI_TELLS].findings] == [Severity.MEDIUM]


def test_familia_8_estado_del_llm_hallazgos_de_ambos():
    sem = FamilyResult(
        Family.AI_TELLS, "not_analyzed", "pendiente", [_finding(Family.AI_TELLS, Severity.LOW)]
    )
    llm_f = _finding(Family.AI_TELLS, Severity.HIGH, line=9)
    down = engine.combine_ai_tells(
        sem, FamilyResult(Family.AI_TELLS, "not_analyzed", "no disponible")
    )
    assert down.status == "not_analyzed" and len(down.findings) == 1
    assert "1 hallazgos de reglas automáticas" in down.reason
    up = engine.combine_ai_tells(sem, FamilyResult(Family.AI_TELLS, "ok", None, [llm_f]))
    assert up.status == "ok" and len(up.findings) == 2
    assert engine.combine_ai_tells(sem, None).status == "not_analyzed"


def test_emit_roto_no_aborta(tmp_path, monkeypatch, tmp_dirs):
    monkeypatch.setattr(engine, "clone_repo", _clone_from(_py_repo(tmp_path)))
    _fast_scanners(monkeypatch)

    def broken(_e):
        raise RuntimeError("cola cerrada")

    report, _ = engine.run_analysis(META, threading.Event(), broken, FakeClient())
    assert len(report["families"]) == 8


def test_hallazgo_de_diseno_del_llm_va_a_familia_5(tmp_path, monkeypatch, tmp_dirs):
    monkeypatch.setattr(engine, "clone_repo", _clone_from(_py_repo(tmp_path)))
    _fast_scanners(monkeypatch)
    design = _finding(Family.MONOLITH, Severity.MEDIUM, file="a.py", line=1)

    def fake_review(*_a, **_kw):
        return SimpleNamespace(
            family_results=[
                FamilyResult(Family.AI_TELLS, "ok", None, []),
                FamilyResult(Family.MONOLITH, "ok", None, [design]),
            ],
            executive_summary=None,
            cost_usd=0.01,
        )

    monkeypatch.setattr(engine, "review", fake_review)
    report, _ = engine.run_analysis(META, threading.Event(), lambda _e: None, FakeClient())
    fam5 = next(f for f in report["families"] if f["id"] == 5)
    assert fam5["status"] == "ok" and [x["line_start"] for x in fam5["findings"]] == [1]


def test_diseno_no_convierte_familia_5_en_ok():
    llm = [FamilyResult(Family.MONOLITH, "ok", None, [_finding(Family.MONOLITH, Severity.LOW)])]
    out = engine.attach_design([FamilyResult(Family.MONOLITH, "not_analyzed", "sin lizard")], llm)
    assert out[0].status == "not_analyzed" and len(out[0].findings) == 1
    assert "1 hallazgos de la revisión con IA" in out[0].reason


def test_revisor_que_lanza_factura_el_maximo(tmp_path, monkeypatch, tmp_dirs):
    # review() puede fallar tras la llamada pagada: el coste nunca puede quedar en 0
    monkeypatch.setattr(engine, "clone_repo", _clone_from(_py_repo(tmp_path)))
    _fast_scanners(monkeypatch)

    def boom(*_a, **_kw):
        raise ValueError("salida rara del modelo")

    monkeypatch.setattr(engine, "review", boom)
    _, cost = engine.run_analysis(META, threading.Event(), lambda _e: None, FakeClient())
    assert cost == pytest.approx(engine.max_cost_usd())
