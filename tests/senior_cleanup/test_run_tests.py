import json
import subprocess
import sys

import pytest

OK = "def test_ok():\n    assert True\n"
KNOWN = "def test_known():\n    assert 1 == 2\n"


@pytest.fixture
def rt(load_script):
    return load_script("run_tests")


@pytest.fixture
def project(rt, make_repo, write_report):
    """Mini proyecto pytest: test_ok pasa, test_known falla. Commiteado y con plan.json."""
    repo = make_repo()
    (repo / "pytest.ini").write_text("[pytest]\n")
    (repo / "test_ok.py").write_text(OK)
    (repo / "test_known.py").write_text(KNOWN)
    rt.plan.git(repo, "add", "-A")
    rt.plan.git(repo, "commit", "-q", "-m", "tests")
    rt.plan.build_plan(write_report(repo, []), repo)
    return repo


def test_base_registra_fallo_conocido(rt, project):
    base = rt.baseline(project)
    assert base["known_failures"] == ["test_known::test_known"]
    assert base["opaque_red"] is False
    assert (
        json.loads((rt.plan.state_dir(project) / "baseline.json").read_text(encoding="utf-8"))
        == base
    )


def test_verify_mismo_fallo_es_ok(rt, project):
    rt.baseline(project)
    out = rt.verify(project)
    assert out["ok"] is True and out["new_failures"] == [] and out["fixed"] == []


def test_verify_detecta_arreglado(rt, project):
    rt.baseline(project)
    (project / "test_known.py").write_text("def test_known():\n    assert True\n")
    out = rt.verify(project)
    assert out["ok"] is True and out["fixed"] == ["test_known::test_known"]


def test_verify_fallo_nuevo_no_ok(rt, project):
    rt.baseline(project)
    (project / "test_ok.py").write_text("def test_ok():\n    assert False\n")
    out = rt.verify(project)
    assert out["ok"] is False and out["new_failures"] == ["test_ok::test_ok"]


def test_error_de_coleccion_no_ok(rt, project):
    rt.baseline(project)
    (project / "test_bad.py").write_text("def test_bad(:\n")
    out = rt.verify(project)
    assert out["ok"] is False and any(r["collect_error"] for r in out["results"])


def test_timeout_no_ok(rt, project, monkeypatch):
    rt.baseline(project)
    (project / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(10)\n")
    monkeypatch.setenv("SENIOR_CLEANUP_TEST_TIMEOUT", "2")
    out = rt.verify(project)
    assert out["ok"] is False and out["results"][0]["timed_out"] is True


def test_accept_saca_el_fallo_de_new_failures(rt, project):
    rt.baseline(project)
    (project / "test_ok.py").write_text("def test_ok():\n    assert False\n")
    assert rt.verify(project)["ok"] is False
    rt.accept(project, "test_ok::test_ok")
    out = rt.verify(project)
    assert out["ok"] is True and out["new_failures"] == []


def test_cmd_manual_sobrescribe(rt, project):
    base = rt.baseline(project, cmd="python -m pytest test_ok.py")
    assert base["commands"] == [["python", "-m", "pytest", "test_ok.py"]]
    assert base["known_failures"] == []


def test_comando_no_pytest_rojo_es_opaque(rt, project):
    base = rt.baseline(project, cmd='python -c "import sys; sys.exit(1)"')
    assert base["opaque_red"] is True
    assert rt.verify(project)["ok"] is True  # rojo desde la base: no se puede atribuir al lote


def test_comando_no_pytest_que_se_rompe_no_ok(rt, project):
    (project / "check.py").write_text(
        "import pathlib, sys\nsys.exit(pathlib.Path('ROTO').exists())\n"
    )
    rt.plan.git(project, "add", "check.py")
    rt.plan.git(project, "commit", "-q", "-m", "check")
    rt.baseline(project, cmd="python check.py")
    (project / "ROTO").write_text("")
    assert rt.verify(project)["ok"] is False


def test_sin_comando_de_tests_es_error(rt, make_repo, write_report):
    repo = make_repo()
    rt.plan.build_plan(write_report(repo, []), repo)
    with pytest.raises(rt.plan.PlanError) as exc:
        rt.baseline(repo)
    assert exc.value.code == "no_tests"


def test_ejecutar_tests_no_ensucia_el_arbol(rt, project):
    assert not (project / ".gitignore").exists()
    rt.baseline(project)
    rt.verify(project)
    assert rt.plan.git(project, "status", "--porcelain", "--untracked-files=all") == ""


def test_cli_verify_sale_1_si_no_ok(rt, project):
    rt.baseline(project)
    (project / "test_ok.py").write_text("def test_ok():\n    assert False\n")
    res = subprocess.run(
        [sys.executable, rt.__file__, "verify"], cwd=project, capture_output=True, timeout=120
    )
    assert res.returncode == 1
    assert json.loads(res.stdout.decode("utf-8"))["new_failures"] == ["test_ok::test_ok"]
