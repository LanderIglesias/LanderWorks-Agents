import threading

import pytest

from backend.agents.tech_debt_agent.findings import Family, Severity
from backend.agents.tech_debt_agent.repo_fetcher import list_source_files
from backend.agents.tech_debt_agent.scanners.ghost_tests import scan_ghost_tests
from backend.agents.tech_debt_agent.tools import Cancelled
from tests.tech_debt_agent.conftest import PLANTED


def _scan(repo, cancel=None):
    files = list_source_files(repo)
    results = scan_ghost_tests(repo, files, cancel or threading.Event())
    assert len(results) == 1 and results[0].family == Family.GHOST_TESTS
    return results[0]


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_detecta_plantados(vibe_repo):
    r = _scan(vibe_repo)
    assert r.status == "ok"
    got = {(f.file, f.line_start) for f in r.findings}
    for planted in PLANTED[Family.GHOST_TESTS]:
        assert planted in got
    sev = {(f.file, f.line_start): f.severity for f in r.findings}
    assert sev[("tests/test_ghost.py", 6)] == Severity.HIGH
    assert sev[("tests/test_ghost.py", 10)] == Severity.HIGH
    assert sev[("tests/test_ghost.py", 14)] == Severity.MEDIUM
    assert sev[("web/src/App.test.tsx", 4)] == Severity.HIGH


def test_test_real_no_se_marca(tmp_path):
    _write(
        tmp_path,
        "tests/test_ok.py",
        "import pytest\n"
        "def test_a():\n    x = 1\n    assert x == 1\n"
        "def test_b():\n    with pytest.raises(ValueError):\n        int('x')\n"
        "def test_c(mocker):\n    m = mocker.Mock()\n    assert_valid(m)\n"
        "class TestK:\n    def test_d(self):\n        self.assertEqual(1, 1)\n"
        "    def test_e(self):\n        assert 1 == pytest.approx(1.0)\n",
    )
    _write(tmp_path, "tests/ok.test.ts", "it('a', () => {\n  expect(1).toBe(1);\n});\n")
    _write(tmp_path, "main.py", "x = 1\n")
    assert _scan(tmp_path).findings == []


def test_metodos_en_clase_se_detectan(tmp_path):
    _write(tmp_path, "test_k.py", "class TestK:\n    def test_x(self):\n        pass\n")
    f = _scan(tmp_path).findings
    assert [(x.line_start, x.severity) for x in f] == [(2, Severity.HIGH)]


def test_assert_sobre_mock(tmp_path):
    _write(
        tmp_path,
        "test_m.py",
        "from unittest.mock import MagicMock\n"
        "def test_a():\n    m = MagicMock()\n    m.run()\n    assert m.call_count == 1\n",
    )
    f = _scan(tmp_path).findings
    assert [(x.line_start, x.severity) for x in f] == [(2, Severity.MEDIUM)]


def test_sin_tests_es_critical(tmp_path):
    _write(tmp_path, "main.py", "x = 1\n")
    r = _scan(tmp_path)
    assert r.status == "ok" and len(r.findings) == 1
    f = r.findings[0]
    assert f.severity == Severity.CRITICAL and f.line_start is None and f.file == "."
    assert "no tiene tests" in f.title


def test_sin_codigo_fuente(tmp_path):
    _write(tmp_path, "README.md", "hola\n")
    r = _scan(tmp_path)
    assert r.status == "not_analyzed" and r.reason == "sin código fuente"


def test_sintaxis_invalida_no_lanza(tmp_path):
    _write(tmp_path, "test_bad.py", "def test_x(:\n  pass\n")
    _write(tmp_path, "test_nul.py", "def test_y():\n    pass\x00\n")
    _write(
        tmp_path,
        "test_deep.py",
        "def test_z():\n    assert " + "(" * 3000 + "1" + ")" * 3000 + "\n",
    )
    assert _scan(tmp_path).status == "ok"


def test_js_variantes(tmp_path):
    _write(
        tmp_path,
        "a.spec.js",
        "test.only('a', async () => {\n  const s = '}';\n});\n"
        "it.each([[1]])('b', (n) => {\n  expect(n).toBe(1);\n});\n"
        "it('c', () => expect(1).toBe(1));\n"
        "it.skip('d', () => {});\n",
    )
    lines = [f.line_start for f in _scan(tmp_path).findings]
    assert lines == [1]


def test_cancelado(tmp_path):
    _write(tmp_path, "test_a.py", "def test_a():\n    pass\n")
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        _scan(tmp_path, ev)


def test_raises_importado_y_alias(tmp_path):
    _write(
        tmp_path,
        "test_r.py",
        "import pytest as pt\nfrom pytest import raises, warns\n"
        "def test_a():\n    with raises(ValueError):\n        int('x')\n"
        "def test_b():\n    with pt.raises(ValueError):\n        int('x')\n"
        "def test_c():\n    with warns(UserWarning):\n        pass\n",
    )
    assert _scan(tmp_path).findings == []


def test_layouts_js_sin_critical(tmp_path):
    _write(tmp_path, "main.py", "x = 1\n")
    _write(tmp_path, "cypress/e2e/a.cy.ts", "it('a', () => {\n  cy.get('x');\n});\n")
    r = _scan(tmp_path)
    assert [(f.file, f.line_start) for f in r.findings] == [("cypress/e2e/a.cy.ts", 1)]
    other = tmp_path / "o"
    _write(other, "app.js", "x = 1\n")
    _write(other, "__tests__/b.mjs", "test('b', () => { expect(1).toBe(1) })\n")
    assert _scan(other).findings == []


def test_solo_config_no_es_codigo(tmp_path):
    _write(tmp_path, "vite.config.ts", "export default {}\n")
    _write(tmp_path, "setup.py", "x = 1\n")
    _write(tmp_path, "scripts/run.py", "x = 1\n")
    _write(tmp_path, "types.d.ts", "declare const a: number\n")
    r = _scan(tmp_path)
    assert r.status == "not_analyzed" and r.reason == "sin código fuente"


def test_fixtures_mocker_no_son_mock(tmp_path):
    _write(
        tmp_path,
        "test_f.py",
        "def test_a(mock_user):\n    assert mock_user.name == 'x'\n",
    )
    assert _scan(tmp_path).findings == []


def test_unittest_testfoo(tmp_path):
    _write(tmp_path, "test_u.py", "class T:\n    def testFoo(self):\n        pass\n")
    assert [f.line_start for f in _scan(tmp_path).findings] == [2]


def test_comentario_de_bloque_no_cuenta(tmp_path):
    _write(tmp_path, "a.test.js", "it('a', () => {\n  /* expect(1) */\n  run();\n});\n")
    assert [f.line_start for f in _scan(tmp_path).findings] == [1]
