import threading

import pytest

from backend.agents.tech_debt_agent.findings import Family
from backend.agents.tech_debt_agent.repo_fetcher import list_source_files
from backend.agents.tech_debt_agent.scanners import complexity, python_lint
from backend.agents.tech_debt_agent.tools import find_executable

needs_ruff = pytest.mark.skipif(find_executable("ruff") is None, reason="ruff no instalado")
needs_lizard = pytest.mark.skipif(find_executable("lizard") is None, reason="lizard no instalado")


def _lint(repo):
    results = python_lint.scan_python_lint(repo, list_source_files(repo), threading.Event())
    return {r.family: r for r in results}


def _cx(repo):
    results = complexity.scan_complexity(repo, list_source_files(repo), threading.Event())
    assert len(results) == 1 and results[0].family == Family.MONOLITH
    return results[0]


def test_versiones_fijadas():
    assert python_lint.RUFF_VERSION == "0.17.4"
    assert complexity.LIZARD_VERSION == "1.26.0"


@needs_ruff
def test_ruff_detecta_plantados(vibe_repo):
    r = _lint(vibe_repo)
    assert all(x.status == "ok" for x in r.values())
    debug = r[Family.DEBUG].findings
    assert any(f.file == "app/main.py" and f.line_start == 14 for f in debug)
    sast = r[Family.SAST].findings
    evals = [f for f in sast if f.file == "app/utils.py" and f.line_start == 8]
    assert evals and all(f.severity == "critical" for f in evals)
    assert any(
        f.file == "app/main.py" and f.line_start == 17 and f.severity == "high" for f in sast
    )
    errors = r[Family.ERRORS].findings
    assert any(f.file == "app/utils.py" and f.line_start in (24, 25) for f in errors)
    # S110 (try-except-pass) va a la familia 4, no a la 2
    assert not [f for f in sast if "S110" in f.title]
    everything = [f for x in r.values() for f in x.findings]
    assert not [f for f in everything if f.file == "app/clean.py"]
    assert all(f.source == "ruff" for f in everything)
    assert all("\\" not in f.file and ":" not in f.file for f in everything)


@needs_ruff
def test_ruff_ignora_config_y_noqa_del_repo(tmp_path):
    (tmp_path / "ruff.toml").write_text('[lint]\nignore = ["ALL"]\n', encoding="utf-8")
    (tmp_path / "a.py").write_text("# ruff: noqa\nprint('x')  # noqa\n", encoding="utf-8")
    r = _lint(tmp_path)
    assert 2 in [f.line_start for f in r[Family.DEBUG].findings]


def test_ruff_sin_python_es_not_analyzed(tmp_path):
    (tmp_path / "App.tsx").write_text("export default 1\n", encoding="utf-8")
    r = _lint(tmp_path)
    assert set(r) == {Family.SAST, Family.ERRORS, Family.DEBUG}
    assert all(x.status == "not_analyzed" and "sin archivos Python" in x.reason for x in r.values())


@pytest.mark.parametrize("out", ["no es json", "{}", '[{"code": "S307"}]', "[1]"])
def test_ruff_salida_malformada_es_not_analyzed(monkeypatch, tmp_path, out):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(python_lint, "run_tool", lambda *a, **k: out)
    r = _lint(tmp_path)
    assert all(x.status == "not_analyzed" for x in r.values())


def test_ruff_ausente_es_not_analyzed(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(python_lint, "find_executable", lambda _n: None)
    r = _lint(tmp_path)
    assert all(x.status == "not_analyzed" and "no disponible" in x.reason for x in r.values())


def test_ruff_cancelacion_se_propaga(monkeypatch, tmp_path):
    from backend.agents.tech_debt_agent.tools import Cancelled

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    def boom(*a, **k):
        raise Cancelled("ruff")

    monkeypatch.setattr(python_lint, "run_tool", boom)
    with pytest.raises(Cancelled):
        _lint(tmp_path)


@needs_lizard
def test_lizard_detecta_plantados(vibe_repo):
    res = _cx(vibe_repo)
    assert res.status == "ok" and res.reason is None
    found = res.findings
    big = [f for f in found if f.file == "app/god_module.py" and f.line_start == 1]
    assert big and big[0].severity == "medium" and "mezcla responsabilidades" in big[0].why
    cc = [f for f in found if f.file == "app/god_module.py" and f.line_start == 30]
    assert cc and cc[0].severity == "high"
    dup = [f for f in found if "duplicado" in f.title.lower()]
    assert {(f.file, f.line_start) for f in dup} >= {
        ("app/god_module.py", 4),
        ("app/god_module.py", 58),
    }
    assert all(f.severity == "medium" for f in dup)
    assert not [f for f in found if f.file == "app/clean.py"]
    assert all(f.source == "lizard" for f in found)


def test_lizard_sin_fuentes_es_not_analyzed(tmp_path):
    (tmp_path / "README.md").write_text("hola\n", encoding="utf-8")
    (res,) = complexity.scan_complexity(tmp_path, [tmp_path / "README.md"], threading.Event())
    assert res.status == "not_analyzed"


def _fake(csv_out, dup_out):
    def fake(args, **k):
        return dup_out if "-Eduplicate" in args else csv_out

    return fake


def test_lizard_csv_malformado_es_not_analyzed(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(complexity, "run_tool", _fake("1,2,3\nx,y,z,a,b,c,d,e,f,g,h\n", ""))
    (res,) = complexity.scan_complexity(tmp_path, [tmp_path / "a.py"], threading.Event())
    assert res.status == "not_analyzed"


def test_lizard_duplicacion_ilegible_conserva_complejidad(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    row = '2,16,5,0,2,"f@1-2@a.py","a.py","f","f( )",1,2\n'
    monkeypatch.setattr(complexity, "run_tool", _fake(row, "basura sin cabecera"))
    (res,) = complexity.scan_complexity(tmp_path, [tmp_path / "a.py"], threading.Event())
    assert res.status == "ok"
    assert "uplicación no disponible" in res.reason
    assert [(f.line_start, f.severity) for f in res.findings] == [(1, "high")]
