from pathlib import Path

import pytest

from backend.agents.tech_debt_agent.code_analyzer import _mi_rating, _short_path
from backend.agents.tech_debt_agent.dependency_scanner import (
    _extract_imports,
    _find_unused,
    _parse_requirements,
)
from backend.agents.tech_debt_agent.repo_fetcher import fetch_repo
from backend.agents.tech_debt_agent.report_generator import _score_label, calculate_health_score
from backend.agents.tech_debt_agent.test_analyzer import analyze_tests

# ── Health score ─────────────────────────────────────────────────────────────

TESTS_PERFECTOS = {
    "has_tests": True,
    "test_ratio": 80,
    "has_pytest_config": True,
    "has_ci_cd": True,
}


def test_repo_impecable_saca_100():
    assert calculate_health_score({}, TESTS_PERFECTOS, {}) == 100


def test_repo_sin_nada_saca_0():
    codigo = {"summary": {"by_severity": {"critical": 10}}}
    assert calculate_health_score(codigo, {}, {"has_requirements": False}) == 0


def test_issues_criticos_pesan_mas_que_altos():
    def score(severidad: dict) -> int:
        return calculate_health_score({"summary": {"by_severity": severidad}}, TESTS_PERFECTOS, {})

    assert score({"critical": 1}) == 90
    assert score({"high": 1}) == 97
    assert score({"medium": 1}) == 99


def test_dependencias_sin_fijar_restan():
    assert calculate_health_score({}, TESTS_PERFECTOS, {"unpinned": ["a", "b"]}) == 96


@pytest.mark.parametrize(
    ("score", "etiqueta"),
    [(80, "Healthy"), (79, "Moderate"), (40, "Needs Attention"), (20, "Critical"), (0, "Severely")],
)
def test_score_label(score, etiqueta):
    assert etiqueta in _score_label(score)


# ── Analisis de tests ────────────────────────────────────────────────────────


def _repo(root: Path, *archivos: str) -> list[str]:
    rutas = []
    for nombre in archivos:
        ruta = root / nombre
        ruta.write_text("def funcion():\n    pass\n", encoding="utf-8")
        rutas.append(str(ruta))
    return rutas


def test_sin_tests_es_issue_critico(tmp_path):
    resultado = analyze_tests(str(tmp_path), _repo(tmp_path, "engine.py"))
    assert resultado["has_tests"] is False
    assert {"type": "no_tests", "severity": "critical"}.items() <= resultado["issues"][0].items()


def test_ratio_cuenta_archivos_con_su_test_correspondiente(tmp_path):
    archivos = _repo(tmp_path, "engine.py", "api.py", "test_engine.py")
    resultado = analyze_tests(str(tmp_path), archivos)
    assert resultado["has_tests"] is True
    assert resultado["test_ratio"] == 50


def test_detecta_configuracion_de_pytest(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    archivos = _repo(tmp_path, "engine.py", "test_engine.py")
    assert analyze_tests(str(tmp_path), archivos)["has_pytest_config"] is True


# ── Dependencias ─────────────────────────────────────────────────────────────


def test_parse_requirements_ignora_comentarios_y_opciones(tmp_path):
    ruta = tmp_path / "requirements.txt"
    ruta.write_text("# comentario\n\n-r base.txt\nfastapi==0.1\nhttpx\n", encoding="utf-8")
    assert _parse_requirements(ruta) == ["fastapi==0.1", "httpx"]


def test_extract_imports_toma_el_modulo_raiz_y_sobrevive_a_sintaxis_invalida(tmp_path):
    bueno = tmp_path / "bueno.py"
    bueno.write_text("import langchain.chat_models\nfrom os import path\n", encoding="utf-8")
    malo = tmp_path / "malo.py"
    malo.write_text("def (:\n", encoding="utf-8")
    assert _extract_imports([str(bueno), str(malo)]) == {"langchain", "os"}


def test_find_unused_resuelve_alias_de_pypi():
    usados = {"sklearn", "fastapi"}
    unused = _find_unused(["scikit-learn==1.0", "fastapi==0.1", "requests==2.0"], usados)
    assert len(unused) == 1
    assert "requests" in unused[0]


# ── Utilidades y frontera de entrada ─────────────────────────────────────────


def test_short_path_quita_la_carpeta_temporal():
    ruta = str(Path("tmp") / "tech_debt_abc" / "src" / "app.py")
    assert _short_path(ruta) == str(Path("src") / "app.py")
    assert _short_path("otra/ruta.py") == "otra/ruta.py"


@pytest.mark.parametrize(("mi", "letra"), [(20, "A"), (19.9, "B"), (10, "B"), (9.9, "C")])
def test_mi_rating(mi, letra):
    assert _mi_rating(mi).startswith(letra)


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/a/b",
        "http://github.com/a/b",
        "https://github.com.evil.com/a/b",
        "file:///etc/passwd",
        "https://github.com",
        "",
    ],
)
def test_fetch_repo_solo_acepta_github(url):
    with pytest.raises(ValueError, match="URL no válida"):
        fetch_repo(url)
