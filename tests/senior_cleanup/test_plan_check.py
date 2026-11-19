import json
import subprocess
import sys

import pytest


@pytest.fixture
def plan(load_script):
    return load_script("plan")


def _err(plan, report, cwd):
    with pytest.raises(plan.PlanError) as exc:
        plan.check(report, cwd)
    return exc.value


def _cli(plan, report, cwd):
    return subprocess.run(
        [sys.executable, plan.__file__, "check", str(report)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_check_ok_en_repo_limpio(plan, make_repo, write_report):
    repo = make_repo()
    sha = plan.git(repo, "rev-parse", "HEAD")
    out = plan.check(write_report(repo, []), repo)
    assert out["ok"] is True
    assert out["head_sha"] == sha
    assert out["branch"] == f"senior-cleanup/{sha[:7]}"
    assert out["resume_available"] is False


def test_sha_distinto_aborta(plan, make_repo, write_report):
    repo = make_repo()
    report = write_report(repo, [])
    old = plan.git(repo, "rev-parse", "HEAD")
    (repo / "b.py").write_text("y = 1\n")
    plan.git(repo, "add", "-A")
    plan.git(repo, "commit", "-q", "-m", "second")
    e = _err(plan, report, repo)
    assert e.code == "sha_mismatch"
    assert e.details["report_sha"] == old
    assert e.details["head_sha"] == plan.git(repo, "rev-parse", "HEAD")
    assert e.details["report_date"] and e.details["head_date"]


def test_sha_que_no_esta_en_local_da_fecha_null(plan, make_repo, write_report):
    repo = make_repo()
    e = _err(plan, write_report(repo, [], head_sha="f" * 40), repo)
    assert e.code == "sha_mismatch" and e.details["report_date"] is None


def test_arbol_sucio_modificado(plan, make_repo, write_report):
    repo = make_repo()
    (repo / "app.py").write_text("cambiado\n")
    e = _err(plan, write_report(repo, []), repo)
    assert e.code == "dirty_tree" and "app.py" in e.details["files"]


def test_arbol_sucio_sin_seguimiento(plan, make_repo, write_report):
    repo = make_repo()
    (repo / "nuevo.py").write_text("z = 1\n")
    e = _err(plan, write_report(repo, []), repo)
    assert e.code == "dirty_tree" and "nuevo.py" in e.details["files"]


@pytest.mark.parametrize("version", [None, 2])
def test_schema_ausente_o_distinto(plan, make_repo, write_report, version):
    repo = make_repo()
    report = write_report(repo, [], schema_version=version)
    assert _err(plan, report, repo).code == "bad_schema"


@pytest.mark.parametrize("drop", ["repo", "families"])
def test_faltan_claves_obligatorias(plan, make_repo, write_report, drop):
    repo = make_repo()
    report = write_report(repo, [])
    data = json.loads(report.read_text())
    del data[drop]
    report.write_text(json.dumps(data))
    assert _err(plan, report, repo).code == "bad_schema"


def test_json_roto(plan, make_repo, tmp_path):
    repo = make_repo()
    report = tmp_path / "roto.json"
    report.write_text("{no es json")
    assert _err(plan, report, repo).code == "bad_json"


def test_json_con_bom_y_crlf_se_acepta(plan, make_repo, write_report):
    repo = make_repo()
    report = write_report(repo, [])
    text = json.dumps(json.loads(report.read_text()), indent=2).replace("\n", "\r\n")
    report.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    assert plan.check(report, repo)["ok"] is True


@pytest.mark.parametrize("transform", [lambda s: s[:7], str.upper])
def test_sha_corto_o_mayusculas_es_bad_schema(plan, make_repo, write_report, transform):
    repo = make_repo()
    sha = plan.git(repo, "rev-parse", "HEAD")
    report = write_report(repo, [], head_sha=transform(sha))
    assert _err(plan, report, repo).code == "bad_schema"


def test_no_es_repo_git(plan, make_repo, write_report, tmp_path):
    repo = make_repo()
    report = write_report(repo, [])
    outside = tmp_path / "no_git"
    outside.mkdir()
    assert _err(plan, report, outside).code == "not_git"


def test_rama_existente_sin_progreso(plan, make_repo, write_report):
    repo = make_repo()
    sha = plan.git(repo, "rev-parse", "HEAD")
    plan.git(repo, "branch", f"senior-cleanup/{sha[:7]}")
    assert _err(plan, write_report(repo, []), repo).code == "branch_exists"


def _empezar_limpieza(plan, repo, sha):
    branch = f"senior-cleanup/{sha[:7]}"
    plan.git(repo, "checkout", "-q", "-b", branch)
    state = plan.state_dir(repo)
    state.mkdir(parents=True)
    (state / "plan.json").write_text(json.dumps({"report_sha": sha, "branch": branch}))
    (state / "progress.json").write_text(json.dumps({"batches": {"1": {"status": "applied"}}}))


def test_rama_existente_con_progreso_ofrece_retomar(plan, make_repo, write_report):
    repo = make_repo()
    sha = plan.git(repo, "rev-parse", "HEAD")
    report = write_report(repo, [])
    _empezar_limpieza(plan, repo, sha)
    assert plan.check(report, repo)["resume_available"] is True

    (repo / "app.py").write_text("arreglado\n")
    plan.git(repo, "commit", "-q", "-am", "fix(senior-cleanup): lote 1")
    out = plan.check(report, repo)
    assert out["ok"] is True and out["resume_available"] is True
    assert out["head_sha"] == sha


def test_retomar_con_plan_de_otro_sha_aborta(plan, make_repo, write_report):
    repo = make_repo()
    sha = plan.git(repo, "rev-parse", "HEAD")
    report = write_report(repo, [])
    _empezar_limpieza(plan, repo, sha)
    plan_json = plan.state_dir(repo) / "plan.json"
    plan_json.write_text(json.dumps({"report_sha": "f" * 40}))
    (repo / "app.py").write_text("arreglado\n")
    plan.git(repo, "commit", "-q", "-am", "fix(senior-cleanup): lote 1")
    assert _err(plan, report, repo).code == "sha_mismatch"


def test_cli_devuelve_json_y_codigo_2(plan, make_repo, write_report):
    repo = make_repo()
    res = _cli(plan, write_report(repo, [], head_sha="0" * 40), repo)
    assert res.returncode == 2
    out = json.loads(res.stdout)
    assert out["ok"] is False and out["code"] == "sha_mismatch"


def test_cli_emite_utf8_con_caracteres_fuera_de_cp1252(plan, make_repo, write_report):
    repo = make_repo()
    finding = {
        "family": 6,
        "file": "../x.py",
        "line_start": 1,
        "line_end": 1,
        "title": "✋ 日本",
        "rule": "T201",
    }
    report = write_report(repo, [finding])
    res = subprocess.run(
        [sys.executable, plan.__file__, "plan", str(report)],
        cwd=repo,
        capture_output=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout.decode("utf-8"))["rejected"][0]["title"] == "✋ 日本"


def test_cli_ok_devuelve_0(plan, make_repo, write_report):
    repo = make_repo()
    res = _cli(plan, write_report(repo, []), repo)
    assert res.returncode == 0 and json.loads(res.stdout)["ok"] is True
