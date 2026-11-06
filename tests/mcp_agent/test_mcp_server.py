import asyncio
import json
import os
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

# El modulo crea engine y cliente al importarse; estos valores solo evitan que
# falle sin .env. Ningun test llega a conectar: get_connection va parcheado.
os.environ.setdefault("MEETING_DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("OPENAI_API_KEY", "test")

from backend.agents.mcp_agent import server  # noqa: E402


def _llamar(nombre: str, **argumentos) -> str:
    resultado = asyncio.run(server.call_tool(nombre, argumentos))
    return resultado[0].text


@pytest.fixture
def fila(monkeypatch):
    """Devuelve un setter: la consulta simulada devuelve la fila indicada."""

    def _set(valor):
        @contextmanager
        def conexion_falsa():
            conn = MagicMock()
            conn.execute.return_value.fetchone.return_value = valor
            yield conn

        monkeypatch.setattr(server, "get_connection", conexion_falsa)

    return _set


def test_herramientas_expuestas():
    nombres = {t.name for t in asyncio.run(server.list_tools())}
    assert {"list_meetings", "search_meeting", "ask_meeting", "get_current_date"} <= nombres


def test_herramienta_desconocida():
    assert _llamar("no_existe") == "Herramienta desconocida: no_existe"


@pytest.mark.parametrize(
    "herramienta",
    ["get_meeting_extractions", "get_meeting_summary", "list_action_items_by_owner"],
)
def test_reunion_inexistente(fila, herramienta):
    fila(None)
    assert _llamar(herramienta, meeting_id="x", owner="ana") == "Reunión no encontrada"


def test_action_items_filtra_por_responsable_sin_distinguir_mayusculas(fila):
    fila(([{"task": "Acta", "owner": "Ana Ruiz"}, {"task": "Demo", "owner": "Luis"}],))
    items = json.loads(_llamar("list_action_items_by_owner", meeting_id="x", owner="ana"))
    assert items == [{"task": "Acta", "owner": "Ana Ruiz"}]


def test_action_items_tolera_owner_null_del_llm(fila):
    fila(([{"task": "Sin dueno", "owner": None}, {"task": "Acta", "owner": "Ana"}],))
    items = json.loads(_llamar("list_action_items_by_owner", meeting_id="x", owner="ana"))
    assert [i["task"] for i in items] == ["Acta"]


def test_action_items_null_en_base_de_datos(fila):
    fila((None,))
    assert json.loads(_llamar("list_action_items_by_owner", meeting_id="x", owner="ana")) == []


def test_ask_meeting_sin_contexto_no_llama_al_llm(monkeypatch):
    monkeypatch.setattr(server, "search_meeting", lambda **_: [])
    respuesta = _llamar("ask_meeting", meeting_id="x", question="¿Qué se decidió?")
    assert respuesta == "No se encontró contenido relevante en la reunión"


def test_get_current_datetime_respeta_la_zona_horaria():
    datos = json.loads(_llamar("get_current_datetime", timezone="UTC"))
    assert datos["timezone"] == "UTC"
    assert datos["iso8601"].endswith("+00:00")
