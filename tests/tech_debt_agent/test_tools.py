import sys
import threading
import time

import pytest

from backend.agents.tech_debt_agent.tools import Cancelled, ToolTimeout, ToolUnavailable, run_tool

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


def test_devuelve_stdout(tmp_path):
    assert (
        run_tool([sys.executable, "-c", "print('hi')"], tmp_path, 5, threading.Event()).strip()
        == "hi"
    )


def test_no_hereda_secretos_del_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secreto")
    code = "import os; print(os.environ.get('ANTHROPIC_API_KEY'), os.environ.get('X_EXTRA'))"
    out = run_tool(
        [sys.executable, "-c", code], tmp_path, 5, threading.Event(), env={"X_EXTRA": "1"}
    )
    assert out.split() == ["None", "1"]


def test_timeout_mata_el_proceso(tmp_path):
    t0 = time.monotonic()
    with pytest.raises(ToolTimeout):
        run_tool(SLEEP, tmp_path, 1, threading.Event())
    assert time.monotonic() - t0 < 5


def test_cancelacion_mata_el_proceso(tmp_path):
    ev = threading.Event()
    threading.Timer(0.5, ev.set).start()
    with pytest.raises(Cancelled):
        run_tool(SLEEP, tmp_path, 30, ev)


def test_binario_inexistente(tmp_path):
    with pytest.raises(ToolUnavailable):
        run_tool(["no-existe-xyz"], tmp_path, 5, threading.Event())


def test_codigo_de_salida_no_aceptado(tmp_path):
    with pytest.raises(RuntimeError):
        run_tool([sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path, 5, threading.Event())


def test_codigo_aceptado_por_ok_codes(tmp_path):
    out = run_tool(
        [sys.executable, "-c", "import sys; print('x'); sys.exit(1)"],
        tmp_path,
        5,
        threading.Event(),
        {0, 1},
    )
    assert out.strip() == "x"


def test_env_se_mezcla_con_el_entorno(tmp_path):
    code = "import os; print(os.environ['TD_X'])"
    out = run_tool([sys.executable, "-c", code], tmp_path, 5, threading.Event(), env={"TD_X": "v"})
    assert out.strip() == "v"


def test_cancel_previo_no_arranca_el_proceso(tmp_path):
    marca = tmp_path / "marca"
    ev = threading.Event()
    ev.set()
    code = f"open({str(marca)!r}, 'w').close()"
    with pytest.raises(Cancelled):
        run_tool([sys.executable, "-c", code], tmp_path, 5, ev)
    assert not marca.exists()


def test_salida_demasiado_grande(tmp_path, monkeypatch):
    from backend.agents.tech_debt_agent import tools

    monkeypatch.setattr(tools, "MAX_OUTPUT_BYTES", 10)
    with pytest.raises(RuntimeError, match="demasiado grande"):
        run_tool([sys.executable, "-c", "print('x' * 100)"], tmp_path, 5, threading.Event())
