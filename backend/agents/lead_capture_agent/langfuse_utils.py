"""langfuse_utils.py — observabilidad Langfuse para lead_capture_agent.

Corrige un bug real, no introduce una decisión de diseño nueva:
`llm_engine.stream_user_message_llm()` usaba `langfuse.trace(name=...).generation(...)`,
un método que NO existe en la versión realmente fijada en el
`requirements.txt` raíz del monorepo (`langfuse==4.5.1`) —
confirmado instanciando el cliente real: `Langfuse().trace(...)` lanza
`AttributeError: 'Langfuse' object has no attribute 'trace'`. La llamada
estaba envuelta en `except Exception: pass`, así que fallaba en silencio
en cada respuesta en streaming, sin dejar rastro y sin que ningún test
lo detectara (la suite de este agente no tenía ninguna aserción sobre
Langfuse).

API usada: la de spans/observaciones de Langfuse >=3
(`start_as_current_observation` / `update_current_generation` /
`create_event`), la misma ya verificada y en producción en
`backend/agents/taller_mecanico/langfuse_utils.py`.

Por qué se replica el patrón aquí en vez de importarlo desde
taller_mecanico: cada agente de este monorepo vive aislado en su propia
carpeta `backend/agents/<nombre>/` (convención ya establecida y
verificada contra `dental_agent`/`expense_tracker`) — no existe ningún
`backend/shared/` ni módulo común entre agentes hoy, así que importar
`taller_mecanico.langfuse_utils` desde aquí introduciría un acoplamiento
entre dos agentes de portfolio independientes que no existía antes, solo
para una corrección de bug. El propio contenido reutilizable es además
más simple aquí: `lead_capture_agent` no tiene una jerarquía de
orquestación (no hay Router/Evaluador/Presupuestador anidados, cada
turno de chat es una única llamada LLM independiente), así que no hace
falta `traza_interaccion`/`registrar_score`, solo una observación
'generation' por turno.

Dos garantías, igual que en taller_mecanico:
1. Si LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY no están configuradas,
   todo aquí es un no-op barato. La observabilidad nunca es una
   dependencia dura del flujo de negocio (nunca debe impedir que un
   visitante reciba su respuesta).
2. Un fallo real de Langfuse (red, API incompatible, lo que sea) nunca
   se propaga como excepción de negocio -- pero, a diferencia del bug
   original, tampoco desaparece en silencio: se registra con
   `logger.exception(...)` en el log del servidor.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_client_singleton: Any = None
_intento_de_construccion_fallido = False
# A diferencia de taller_mecanico (llamadas de test/un solo flujo),
# lead_capture_agent sirve tráfico real concurrente: endpoints síncronos
# de FastAPI (`chat_stream`/`handle_user_message_llm`) corren en el pool
# de hilos de Starlette, así que varias peticiones pueden ejecutar
# `_get_client()` a la vez. Sin este lock, un burst de peticiones al
# arrancar el proceso podría pasar el `is not None` a la vez y construir
# varios `Langfuse()` (cada uno con su propio exportador en segundo
# plano) antes de que la asignación se estabilice -- ninguna corrupción
# de datos, pero sí hilos/colas huérfanos innecesarios.
_client_lock = threading.Lock()


def _habilitado() -> bool:
    import os

    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY")) and bool(
        os.environ.get("LANGFUSE_SECRET_KEY")
    )


def _get_client() -> Any | None:
    """Devuelve el cliente Langfuse singleton, o None si no está
    configurado o si construirlo falló. Nunca lanza.

    Doble comprobación con lock: la primera lectura de
    `_client_singleton` (sin lock) es el camino rápido común en un
    servidor con tráfico real -- una vez construido, no hay contención.
    Solo la construcción en sí (rara: una vez por proceso, o nunca si ya
    falló) entra al lock, para que un burst de peticiones concurrentes
    en el arranque no construya varios clientes Langfuse a la vez."""
    global _client_singleton, _intento_de_construccion_fallido
    if not _habilitado():
        return None
    if _client_singleton is not None:
        return _client_singleton
    with _client_lock:
        if _client_singleton is not None:
            return _client_singleton
        if _intento_de_construccion_fallido:
            return None
        try:
            from langfuse import Langfuse

            _client_singleton = Langfuse()
        except Exception:
            logger.exception(
                "No se pudo construir el cliente Langfuse; observabilidad desactivada "
                "para el resto del proceso."
            )
            _intento_de_construccion_fallido = True
            return None
        return _client_singleton


def registrar_evento(name: str, input: Any, output: Any, metadata: dict | None = None) -> None:
    """Wrapper de `client.create_event(...)` -- ya funcionaba antes de
    esta corrección (existe en langfuse==4.5.1), se mantiene igual en
    comportamiento. Se centraliza aquí solo para que la ruta
    no-streaming pase por el mismo `_get_client()` lazy que la de
    streaming, en vez de un `Langfuse()` construido a nivel de módulo al
    importar `llm_engine.py` -- eso es lo que hacía que la suite de
    tests de este agente mandara eventos reales a Langfuse en cada
    corrida (ver `tests/lead_capture_agent/conftest.py`,
    `langfuse_desactivado`), sin que nadie lo hubiera pedido."""
    client = _get_client()
    if client is None:
        return
    try:
        client.create_event(name=name, input=input, output=output, metadata=metadata or {})
    except Exception:
        logger.exception("Fallo al registrar el evento '%s' en Langfuse.", name)


@dataclass
class ObservacionLangfuse:
    trace_id: str | None = None
    observation_id: str | None = None
    _client: Any = field(default=None, repr=False)

    def completar(self, output: Any, usage_details: dict | None = None) -> None:
        """Registra la salida real de la generación activa. No hace nada
        si Langfuse no está configurado; nunca lanza si la llamada real
        falla -- el fallo queda en el log, no en la respuesta al
        visitante."""
        if self._client is None:
            return
        try:
            self._client.update_current_generation(output=output, usage_details=usage_details)
        except Exception:
            logger.exception("Fallo al actualizar la generación de streaming en Langfuse.")


_SIN_OBSERVACION = ObservacionLangfuse()


@contextlib.contextmanager
def generacion_streaming(
    name: str, model: str, input_data: Any, metadata: dict | None = None
) -> Iterator[ObservacionLangfuse]:
    """Abre una observación tipo 'generation' para un turno de chat en
    streaming. Cualquier excepción que el código del llamante lance
    dentro del `with` se propaga tal cual -- nunca se silencia aquí;
    solo un fallo de Langfuse al abrir o cerrar la observación se
    neutraliza (y se deja constancia con `logger.exception`, no con un
    `except Exception: pass` mudo como el bug original).

    Gestiona apertura y cierre a mano (`cm.__enter__()`/`cm.__exit__()`)
    en vez de con un `with` anidado, para poder proteger open/close por
    separado sin volver a mezclar los fallos de Langfuse con las
    excepciones de negocio del llamante -- mismo diseño ya verificado en
    `taller_mecanico/langfuse_utils.py::_observacion`."""
    client = _get_client()
    if client is None:
        yield _SIN_OBSERVACION
        return

    try:
        cm = client.start_as_current_observation(
            as_type="generation", name=name, model=model, input=input_data, metadata=metadata or {}
        )
        obs_raw = cm.__enter__()
    except Exception:
        logger.exception("Fallo al abrir la observación de streaming en Langfuse.")
        yield _SIN_OBSERVACION
        return

    obs = ObservacionLangfuse(trace_id=obs_raw.trace_id, observation_id=obs_raw.id, _client=client)
    try:
        yield obs
    except BaseException:
        try:
            cm.__exit__(*sys.exc_info())
        except Exception:
            logger.exception("Fallo al cerrar la observación de streaming tras una excepción real.")
        raise
    else:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            logger.exception("Fallo al cerrar la observación de streaming en Langfuse.")
