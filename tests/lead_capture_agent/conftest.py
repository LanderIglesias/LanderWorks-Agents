"""Fixtures compartidas de tests/lead_capture_agent/.

`langfuse_desactivado` (autouse) evita que la suite mande tráfico real a
Langfuse: antes de esta corrección, `llm_engine.py` construía un cliente
Langfuse REAL a nivel de módulo (`langfuse = Langfuse()`, ejecutado al
importar el archivo) usando las credenciales reales del `.env` del
monorepo -- cualquier test que llamara a `handle_user_message_llm()` (la
mayoría de `test_llm_engine.py` lo hace, mockeando solo
`anthropic.Anthropic`) enviaba un evento real a Langfuse en cada corrida,
sin que nadie lo hubiera pedido. Mismo hallazgo y mismo fix que ya se
aplicó en `tests/taller_mecanico/conftest.py`.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass

import pytest

from backend.agents.lead_capture_agent import langfuse_utils


@pytest.fixture(autouse=True)
def langfuse_desactivado(monkeypatch, caplog):
    """Desactiva Langfuse por defecto en toda la suite de
    lead_capture_agent y resetea el singleton/caché de fallo del módulo
    entre tests. Los tests que SÍ necesitan simular Langfuse "activado"
    inyectan un `FakeLangfuseClient` vía
    `monkeypatch.setattr(langfuse_utils, "_get_client", ...)`, nunca
    reactivando las credenciales de entorno reales."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(langfuse_utils, "_client_singleton", None)
    monkeypatch.setattr(langfuse_utils, "_intento_de_construccion_fallido", False)
    caplog.set_level(logging.ERROR, logger="backend.agents.lead_capture_agent.langfuse_utils")


@dataclass
class FakeLangfuseSpan:
    trace_id: str
    id: str


class FakeLangfuseClient:
    """Doble mínimo del cliente Langfuse real (API de spans de v4.x),
    igual en espíritu al de `tests/taller_mecanico/conftest.py` pero
    reducido a lo que `lead_capture_agent` necesita: sin jerarquía de
    observaciones (no hay orquestación aquí), solo abrir/cerrar/actualizar
    una generación y registrar eventos sueltos."""

    def __init__(self, fallar_al_abrir: bool = False, fallar_al_actualizar: bool = False):
        self.fallar_al_abrir = fallar_al_abrir
        self.fallar_al_actualizar = fallar_al_actualizar
        self._contador = 0
        self.actualizaciones: list[dict] = []
        self.eventos: list[dict] = []
        self.observaciones_abiertas: list[dict] = []

    @contextlib.contextmanager
    def start_as_current_observation(self, *, as_type: str, name: str, **kwargs):
        if self.fallar_al_abrir:
            raise RuntimeError("fallo simulado al abrir la observación en Langfuse")
        self._contador += 1
        self.observaciones_abiertas.append({"as_type": as_type, "name": name, **kwargs})
        yield FakeLangfuseSpan(trace_id=f"trace-{id(self)}", id=f"obs-{self._contador}")

    def update_current_generation(self, *, output=None, usage_details=None, **kwargs):
        if self.fallar_al_actualizar:
            raise RuntimeError("fallo simulado al actualizar la generación en Langfuse")
        self.actualizaciones.append({"output": output, "usage_details": usage_details})

    def create_event(self, *, name, input=None, output=None, metadata=None, **kwargs):
        self.eventos.append({"name": name, "input": input, "output": output, "metadata": metadata})
