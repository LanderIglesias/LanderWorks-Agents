import json

import pytest


@pytest.fixture
def plan(load_script):
    return load_script("plan")


def _item(family, file="a.py", line=1, mode="auto", severity="low", kind="line", rule="r"):
    return {
        "family": family,
        "file": file,
        "line_start": line,
        "line_end": line,
        "severity": severity,
        "rule": rule,
        "kind": kind,
        "mode": mode,
        "snippet": None,
    }


def _shape(batches):
    return [(b["mode"], b["family"], len(b["findings"])) for b in batches]


def test_orden_auto_6_4_7_y_confirm_por_severidad(plan):
    items = [
        _item(7, "t.py"),
        _item(4, "b.py"),
        _item(6, "c.py"),
        _item(8, "x.py", mode="confirm", severity="low"),
        _item(2, "y.py", mode="confirm", severity="high"),
        _item(1, "z.py", mode="confirm", severity="high"),
        _item(3, "r.txt", mode="confirm", severity="critical", kind="file", line=None),
    ]
    batches = plan.make_batches(items)
    assert [b["id"] for b in batches] == list(range(1, 8))
    assert [(b["mode"], b["family"]) for b in batches] == [
        ("auto", 6),
        ("auto", 4),
        ("auto", 7),
        ("confirm", 3),
        ("confirm", 1),
        ("confirm", 2),
        ("confirm", 8),
    ]


def test_lote_auto_max_15_sin_partir_archivo(plan):
    items = [_item(6, "a.py", i) for i in range(1, 11)] + [
        _item(6, "b.py", i) for i in range(1, 11)
    ]
    assert _shape(plan.make_batches(items)) == [("auto", 6, 10), ("auto", 6, 10)]


def test_archivos_pequenos_comparten_lote(plan):
    items = [_item(6, "a.py", i) for i in range(1, 6)] + [_item(6, "b.py", i) for i in range(1, 6)]
    assert _shape(plan.make_batches(items)) == [("auto", 6, 10)]


def test_archivo_con_mas_de_15_se_parte(plan):
    items = [_item(6, "a.py", i) for i in range(1, 21)]
    assert _shape(plan.make_batches(items)) == [("auto", 6, 15), ("auto", 6, 5)]


def test_monolito_mismo_archivo_un_lote(plan):
    items = [_item(5, "big.py", i, mode="confirm", severity="medium") for i in (10, 50, 90)]
    items.append(_item(5, "otro.py", 3, mode="confirm", severity="medium"))
    assert _shape(plan.make_batches(items)) == [("confirm", 5, 3), ("confirm", 5, 1)]


def test_lineas_descendentes_dentro_del_lote(plan):
    items = [_item(6, "a.py", line) for line in (3, None, 20, 7)]
    findings = plan.make_batches(items)[0]["findings"]
    assert [f["line_start"] for f in findings] == [20, 7, 3, None]


def test_history_only_fuera_de_lotes(plan):
    items = [_item(1, "old.env", kind="history_only", mode="confirm"), _item(6, "a.py")]
    assert _shape(plan.make_batches(items)) == [("auto", 6, 1)]


def test_detecta_pytest(plan, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    assert plan.detect_test_commands(tmp_path) == [["python", "-m", "pytest"]]


def test_detecta_pytest_por_carpeta_tests(plan, tmp_path):
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_a.py").write_text("")
    assert plan.detect_test_commands(tmp_path) == [["python", "-m", "pytest"]]


def test_detecta_npm(plan, tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    assert plan.detect_test_commands(tmp_path) == [["npm", "test"]]


def test_npm_placeholder_no_cuenta(plan, tmp_path):
    placeholder = 'echo "Error: no test specified" && exit 1'
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": placeholder}}))
    assert plan.detect_test_commands(tmp_path) == []


def test_ambos(plan, tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    assert plan.detect_test_commands(tmp_path) == [["python", "-m", "pytest"], ["npm", "test"]]


def test_ninguno(plan, tmp_path):
    (tmp_path / "package.json").write_text("{no es json")
    assert plan.detect_test_commands(tmp_path) == []


def _hallazgo(family, file, rule, severity="low", title="t"):
    return {
        "family": family,
        "severity": severity,
        "file": file,
        "line_start": 3,
        "line_end": 3,
        "title": title,
        "why": "w",
        "fix": "f",
        "source": "s",
        "rule": rule,
    }


def _findings_report(repo, plan):
    (repo / "conftest.py").write_text("")
    plan.git(repo, "add", "-A")
    plan.git(repo, "commit", "-q", "-m", "tests")
    return [
        _hallazgo(6, "app.py", "T201"),
        _hallazgo(1, "old.env", "history:aws", severity="high"),
        _hallazgo(6, "../fuera.py", "T201", title="fuera"),
    ]


def test_build_plan_escribe_estado_en_git_dir(plan, make_repo, write_report):
    repo = make_repo()
    findings = _findings_report(repo, plan)
    report = write_report(
        repo, findings, not_analyzed=[{"id": 8, "name": "x", "reason": "sin LLM"}]
    )
    out = plan.build_plan(report, repo)

    state = repo / ".git" / "senior-cleanup"
    assert json.loads((state / "plan.json").read_text(encoding="utf-8")) == out
    progress = json.loads((state / "progress.json").read_text(encoding="utf-8"))
    assert progress == {"batches": {"1": {"status": "pending", "note": ""}}}
    assert plan.git(repo, "status", "--porcelain") == ""

    assert out["branch"] == f"senior-cleanup/{out['report_sha'][:7]}"
    assert _shape(out["batches"]) == [("auto", 6, 1)]
    assert out["batches"][0]["findings"][0]["snippet"] == "x3 = 3\n"
    assert [h["file"] for h in out["history_only"]] == ["old.env"]
    assert out["rejected"] == [{"file": "../fuera.py", "title": "fuera", "reason": "ruta con '..'"}]
    assert out["not_analyzed"] == [{"id": 8, "name": "x", "reason": "sin LLM"}]
    assert out["test_commands"] == [["python", "-m", "pytest"]]


def test_build_plan_al_retomar_no_pisa_progreso(plan, make_repo, write_report):
    repo = make_repo()
    report = write_report(repo, _findings_report(repo, plan))
    first = plan.build_plan(report, repo)
    plan.git(repo, "checkout", "-q", "-b", first["branch"])
    plan.mark(repo, 1, "applied")
    (repo / "app.py").write_text("arreglado\n")
    plan.git(repo, "commit", "-q", "-am", "fix(senior-cleanup): lote 1")
    assert plan.build_plan(report, repo) == first
    progress = json.loads((plan.state_dir(repo) / "progress.json").read_text(encoding="utf-8"))
    assert progress["batches"]["1"]["status"] == "applied"


def test_mark_actualiza_y_estado_invalido(plan, make_repo, write_report):
    repo = make_repo()
    plan.build_plan(write_report(repo, _findings_report(repo, plan)), repo)
    out = plan.mark(repo, 1, "applied", "ok")
    assert out["batches"]["1"] == {"status": "applied", "note": "ok"}
    with pytest.raises(plan.PlanError) as exc:
        plan.mark(repo, 1, "hecho")
    assert exc.value.code == "bad_status"
    with pytest.raises(plan.PlanError) as exc:
        plan.mark(repo, 99, "applied")
    assert exc.value.code == "bad_batch"


def test_revert_restaura_y_borra_nuevos_incluso_en_carpetas_nuevas(plan, make_repo):
    repo = make_repo()
    (repo / "app.py").write_text("roto\n")
    (repo / "tests" / "new").mkdir(parents=True)
    (repo / "tests" / "new" / "test_x.py").write_text("def test_x(): pass\n")
    (repo / "staged.py").write_text("nuevo y en el índice\n")
    plan.git(repo, "add", "app.py", "staged.py")
    removed = plan.revert(repo)
    assert removed == ["staged.py", "tests/new/test_x.py"]
    assert plan.git(repo, "status", "--porcelain") == ""
    assert not (repo / "tests").exists()
    assert (repo / "app.py").read_text().startswith("x1 = 1")


def test_revert_no_borra_ignorados(plan, make_repo):
    repo = make_repo()
    (repo / ".gitignore").write_text("*.log\n")
    plan.git(repo, "add", ".gitignore")
    plan.git(repo, "commit", "-q", "-m", "ignore")
    (repo / "debug.log").write_text("x\n")
    (repo / "nuevo.py").write_text("x\n")
    assert plan.revert(repo) == ["nuevo.py"]
    assert (repo / "debug.log").exists()
