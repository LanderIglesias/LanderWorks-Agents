import os

import pytest


@pytest.fixture
def plan(load_script):
    return load_script("plan")


def _f(file, family=6, rule=None, line_start=None, line_end=None):
    return {
        "family": family,
        "file": file,
        "rule": rule,
        "line_start": line_start,
        "line_end": line_end,
    }


def _commit(plan, repo, msg="add"):
    plan.git(repo, "add", "-A")
    plan.git(repo, "commit", "-q", "-m", msg)


@pytest.mark.parametrize(
    "path", ["../x.py", "/etc/passwd", "C:/x.py", "src\\app.py", "no_existe.py"]
)
def test_rutas_rechazadas(plan, make_repo, path):
    repo = make_repo()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("a = 1\n")
    _commit(plan, repo)
    kind, reason = plan.classify_location(repo, _f(path, line_start=1), plan.head_files(repo))
    assert kind == "rejected" and reason


def test_symlink_rechazado(plan, make_repo):
    repo = make_repo()
    try:
        os.symlink("app.py", repo / "enlace.py")
    except OSError:
        pytest.skip("no se pueden crear symlinks en este sistema")
    plan.git(repo, "config", "core.symlinks", "true")
    _commit(plan, repo)
    files = plan.head_files(repo)
    assert "enlace.py" in files
    kind, reason = plan.classify_location(repo, _f("enlace.py", line_start=1), files)
    assert kind == "rejected" and reason


def test_repo_y_archivo(plan, make_repo):
    repo = make_repo()
    (repo / "requirements.txt").write_text("requests==2.19.0\n")
    _commit(plan, repo)
    files = plan.head_files(repo)
    assert plan.classify_location(repo, _f(".", family=7, rule="ghost-missing"), files) == (
        "repo",
        None,
    )
    assert plan.classify_location(repo, _f("requirements.txt", family=3, rule="GHSA-x"), files) == (
        "file",
        None,
    )
    assert plan.classify_location(repo, _f("app.py", line_start=3, line_end=3), files) == (
        "line",
        None,
    )


@pytest.mark.parametrize(
    "finding",
    [
        _f("app.py", family=1, rule="history:aws-access-token"),
        _f("borrado.env", family=1, rule="aws-access-token"),
    ],
)
def test_secreto_historial(plan, make_repo, finding):
    repo = make_repo()
    assert plan.classify_location(repo, finding, plan.head_files(repo)) == ("history_only", None)


def test_fragmento_lineas(plan, make_repo):
    repo = make_repo()
    assert (
        plan.capture_snippet(repo, _f("app.py", line_start=3, line_end=5))
        == "x3 = 3\nx4 = 4\nx5 = 5\n"
    )


def test_fragmento_maximo_20_lineas(plan, make_repo):
    repo = make_repo()
    snippet = plan.capture_snippet(repo, _f("app.py", line_start=1, line_end=30))
    assert snippet.count("\n") == 20


def test_fragmento_sin_linea_es_none(plan, make_repo):
    repo = make_repo()
    assert plan.capture_snippet(repo, _f("app.py")) is None


def test_fragmento_test_fantasma_python_es_la_funcion(plan, make_repo):
    repo = make_repo()
    body = "import os\n\n\ndef test_a():\n    x = 1\n    y = 2\n    assert True\n\n\ndef test_b():\n    pass\n"
    (repo / "test_x.py").write_text(body)
    _commit(plan, repo)
    f = _f("test_x.py", family=7, rule="ghost-trivial", line_start=4, line_end=4)
    assert plan.capture_snippet(repo, f) == "def test_a():\n    x = 1\n    y = 2\n    assert True\n"


@pytest.mark.parametrize(
    "family,rule,kind,mode",
    [
        (6, "debug-true", "line", "confirm"),
        (6, "T201", "line", "auto"),
        (6, None, "line", "confirm"),
        (4, "flask-debug-activo", "line", "confirm"),
        (4, None, "line", "confirm"),
        (4, "S110", "line", "auto"),
        (4, "S112", "line", "auto"),
        (4, "E722", "line", "auto"),
        (4, "except-pass-tragado", "line", "auto"),
        (4, "except-print-tragado", "line", "auto"),
        (4, "catch-vacio", "line", "auto"),
        (4, "promise-catch-vacio", "line", "auto"),
        (4, "error-expuesto-en-respuesta", "line", "auto"),
        (4, "traceback-en-respuesta", "line", "auto"),
        (4, "BLE001", "line", "auto"),
        (4, "express-error-expuesto", "line", "auto"),
        (7, "ghost-missing", "repo", "confirm"),
        (7, "ghost-missing", "file", "confirm"),
        (7, "ghost-none", "line", "auto"),
        (7, "ghost-mock", "line", "auto"),
        (7, None, "line", "confirm"),
        (1, "aws-access-token", "line", "confirm"),
        (2, "sql-injection", "line", "confirm"),
        (3, "GHSA-x", "file", "confirm"),
        (5, "complexity-ccn", "line", "confirm"),
        (8, None, "line", "confirm"),
    ],
)
def test_modo(plan, family, rule, kind, mode):
    assert plan.mode_for(_f("a.py", family=family, rule=rule), kind) == mode
