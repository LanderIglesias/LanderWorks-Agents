import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("pytest_changed", ROOT / "scripts/pytest_changed.py")
pytest_changed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pytest_changed)
select = pytest_changed.select_targets
FULL = pytest_changed.FULL_SUITE


def test_codigo_de_agente_ejecuta_solo_sus_tests():
    assert select(["backend/agents/tech_debt_agent/tools.py"], ROOT) == ["tests/tech_debt_agent"]


def test_tests_y_fixtures_se_agrupan_por_carpeta():
    changed = [
        "tests/tech_debt_agent/test_tools.py",
        "tests/tech_debt_agent/fixtures/vibe_repo/app/main.py",
    ]
    assert select(changed, ROOT) == ["tests/tech_debt_agent"]


def test_codigo_compartido_ejecuta_la_suite_completa():
    assert select(["backend/main.py"], ROOT) == FULL
    assert select(["requirements.txt"], ROOT) == FULL
    assert select(["tests/conftest.py"], ROOT) == FULL


def test_solo_docs_no_ejecuta_nada():
    assert select(["docs/superpowers/plans/x.md", "README.md"], ROOT) == []


def test_test_suelto_en_raiz_de_tests():
    assert select(["tests/test_main_admin_routes.py"], ROOT) == ["tests/test_main_admin_routes.py"]
