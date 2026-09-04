"""Fixtures y helpers compartidos entre los tests de taller_mecanico.

El cliente Anthropic falso vivía duplicado en test_router.py; se extrae
aquí porque diagnostico.py necesita exactamente el mismo doble de prueba
(misma forma de client.messages.create -> objeto con .content[0].text).
"""

import json
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from cryptography.fernet import Fernet

from backend.agents.taller_mecanico import db as tm_db
from backend.agents.taller_mecanico import langfuse_utils


@pytest.fixture(autouse=True)
def crypto_env(monkeypatch):
    """Claves de cifrado válidas para cualquier test que llame a crm.py
    (que a su vez llama a crypto_utils.py). autouse=True porque cada vez
    más módulos (diagnostico.py, y los que vengan) dependen de crm.py
    indirectamente; los tests de test_crypto_utils.py que necesitan
    probar la AUSENCIA de una clave la borran ellos mismos con
    monkeypatch.delenv dentro del propio test, después de que esta
    fixture ya la puso."""
    monkeypatch.setenv("TALLER_MECANICO_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TALLER_MECANICO_HMAC_KEY", "test-hmac-key-not-for-production")


@pytest.fixture(autouse=True)
def langfuse_desactivado(monkeypatch):
    """Desactiva Langfuse por defecto en TODA la suite de taller_mecanico.

    Hallazgo real durante la integración de observabilidad: el `.env` de
    la raíz del monorepo tiene LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY
    reales (los usa lead_capture_agent) -- sin este fixture, la suite
    mockeada de taller_mecanico habría activado Langfuse de verdad en
    cada corrida de tests (mismo principio que ya se aplica a
    ANTHROPIC_API_KEY vía el `client=` inyectable: los tests no deben
    depender de ni disparar tráfico real hacia un servicio externo
    compartido). autouse=True por la misma razón que `crypto_env`: cada
    vez más módulos llaman a langfuse_utils indirectamente. Los tests
    dedicados de test_langfuse_utils.py que SÍ necesitan simular Langfuse
    "activado" lo hacen inyectando un cliente falso vía
    `monkeypatch.setattr(langfuse_utils, "_get_client", ...)`, no
    reactivando las claves de entorno reales.

    También resetea el singleton/caché de fallo de langfuse_utils entre
    tests -- sin esto, el primer test que lograra construir (o fallar al
    construir) un cliente real dejaría ese estado contaminando todos los
    tests siguientes del proceso."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("TALLER_MECANICO_LANGFUSE_ENABLED", raising=False)
    monkeypatch.setattr(langfuse_utils, "_client_singleton", None)
    monkeypatch.setattr(langfuse_utils, "_intento_de_construccion_fallido", False)


@dataclass
class FakeBlock:
    text: str


@dataclass
class FakeUsage:
    """Doble mínimo de `anthropic.types.Usage` -- los agentes leen
    `response.usage.input_tokens/output_tokens` para pasarlos como
    `usage_details` a Langfuse (ver langfuse_utils.py); sin este campo,
    cualquier test con el cliente falso rompería con AttributeError en
    cuanto un agente empezara a leer `.usage`."""

    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class FakeMessage:
    content: list = field(default_factory=list)
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeMessagesResource:
    """Sustituye a client.messages -- guarda la última llamada para poder
    aserttar sobre model/system/messages sin golpear la API real."""

    def __init__(self, respuesta_texto: str):
        self._respuesta_texto = respuesta_texto
        self.ultima_llamada: dict | None = None

    def create(self, **kwargs):
        self.ultima_llamada = kwargs
        return FakeMessage(content=[FakeBlock(text=self._respuesta_texto)])


class FakeAnthropicClient:
    def __init__(self, respuesta_texto: str):
        self.messages = FakeMessagesResource(respuesta_texto)


def client_con_json(payload: dict) -> FakeAnthropicClient:
    return FakeAnthropicClient(json.dumps(payload, ensure_ascii=False))


@dataclass
class FakeLangfuseSpan:
    trace_id: str
    id: str
    parent_observation_id: str | None = None


class FakeLangfuseClient:
    """Doble mínimo del cliente Langfuse real (API de spans de v4.x) para
    probar langfuse_utils.py y su integración con los agentes sin tocar
    la red ni credenciales reales.

    Una única instancia comparte `trace_id` entre todas las observaciones
    que abre (mismo comportamiento que el SDK real hace vía contextvars
    de OpenTelemetry cuando varias llamadas ocurren dentro del mismo
    `with` externo) -- así un test puede verificar que router/diagnostico/
    evaluador comparten una traza cuando se ejecutan encadenados bajo la
    misma instancia inyectada.

    `self.jerarquia` mapea observation_id -> parent_observation_id (o
    `None` para la raíz), reconstruido a partir de `_observation_id_actual`
    (el mismo mecanismo de "guardar el anterior, restaurar al salir" que
    ya usaba este doble para compartir `trace_id` -- aquí, además, ese
    "anterior" ES el padre real de la observación que se abre). Sin esto,
    este doble no podía distinguir "todas comparten trace_id porque están
    genuinamente anidadas" de "todas comparten trace_id por casualidad,
    pero como trazas independientes/sin padre" -- exactamente la clase de
    bug que un hallazgo real en el dashboard de Langfuse detectó y que
    los tests, con la versión anterior de este doble, no podían haber
    atrapado."""

    def __init__(
        self,
        fallar_al_abrir: bool = False,
        fallar_al_actualizar: bool = False,
        fallar_al_cerrar: bool = False,
    ):
        self.fallar_al_abrir = fallar_al_abrir
        self.fallar_al_actualizar = fallar_al_actualizar
        self.fallar_al_cerrar = fallar_al_cerrar
        self._contador = 0
        self._trace_id: str | None = None
        self._observation_id_actual: str | None = None
        self.actualizaciones: list[dict] = []
        self.scores: list[dict] = []
        self.jerarquia: dict[str, str | None] = {}
        self.nombres: dict[str, str] = {}

    @contextmanager
    def start_as_current_observation(self, *, as_type: str, name: str, **kwargs):
        if self.fallar_al_abrir:
            raise RuntimeError("fallo simulado al abrir la observación en Langfuse")
        self._contador += 1
        if self._trace_id is None:
            self._trace_id = f"trace-{id(self)}"
        anterior = self._observation_id_actual  # el padre real, si lo hay
        span = FakeLangfuseSpan(
            trace_id=self._trace_id, id=f"obs-{self._contador}", parent_observation_id=anterior
        )
        self.jerarquia[span.id] = anterior
        self.nombres[span.id] = name
        self._observation_id_actual = span.id
        try:
            yield span
        except BaseException:
            raise
        else:
            # Simula el SDK real fallando SOLO al cerrar el span (p.ej. un
            # error de red en el flush final) -- nunca cuando el cuerpo
            # del `with` del llamante ya lanzó su propia excepción.
            if self.fallar_al_cerrar:
                raise RuntimeError("fallo simulado al cerrar la observación en Langfuse")
        finally:
            self._observation_id_actual = anterior

    def update_current_generation(self, *, output=None, usage_details=None, **kwargs):
        if self.fallar_al_actualizar:
            raise RuntimeError("fallo simulado al actualizar la generación en Langfuse")
        self.actualizaciones.append(
            {
                "observation_id": self._observation_id_actual,
                "output": output,
                "usage_details": usage_details,
            }
        )

    def update_current_span(self, *, output=None, **kwargs):
        if self.fallar_al_actualizar:
            raise RuntimeError("fallo simulado al actualizar el span en Langfuse")
        self.actualizaciones.append(
            {"observation_id": self._observation_id_actual, "output": output}
        )

    def create_score(
        self, *, trace_id, observation_id, name, value, comment=None, data_type=None, **kwargs
    ):
        self.scores.append(
            {
                "trace_id": trace_id,
                "observation_id": observation_id,
                "name": name,
                "value": value,
                "comment": comment,
                "data_type": data_type,
            }
        )


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "taller_mecanico.db"
    monkeypatch.setattr(tm_db, "DB_PATH", db_path)
    connection = tm_db.get_conn()
    yield connection
    connection.close()
