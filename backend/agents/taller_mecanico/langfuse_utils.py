"""langfuse_utils.py — observabilidad opcional vía Langfuse.

Capa fina y aislada: ningún agente ni orquestación importa `langfuse`
directamente, todos pasan por aquí -- igual que `crypto_utils.py` es el
único módulo autorizado a cifrar. Tres garantías no negociables:

1. Requiere OPT-IN EXPLÍCITO por variable de entorno propia
   (`TALLER_MECANICO_LANGFUSE_ENABLED=1`), además de
   LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY. Hallazgo real de la revisión
   de seguridad de esta integración: LANGFUSE_PUBLIC_KEY/SECRET_KEY son
   variables COMPARTIDAS con `lead_capture_agent` en el `.env` de la raíz
   del monorepo -- sin este segundo interruptor, cualquier ejecución de
   taller_mecanico en un entorno donde ya existen esas credenciales
   (puestas ahí para OTRO agente) empezaría a mandar texto libre de
   clientes a un proyecto de Langfuse ajeno, sin que nadie lo pidiera
   para ESTE agente. Con las credenciales compartidas presentes pero sin
   este flag, `_habilitado()` devuelve False -- mismo resultado que si
   Langfuse no estuviera configurado en absoluto.
2. Si no está habilitado (por el punto 1), todo aquí se vuelve un no-op
   barato (sin intentar importar `langfuse` siquiera). La observabilidad
   es una capa adicional, nunca una dependencia dura del flujo de
   negocio.
3. Cualquier excepción real de la librería Langfuse (fallo de red, API
   incompatible, lo que sea) se traga en silencio -- un agente nunca debe
   fallar porque Langfuse falló. Esto cubre explícitamente tanto ABRIR
   como CERRAR una observación (ver `_abrir_observacion`/`_ObservacionAbierta`
   más abajo) -- un primer intento solo protegía la apertura, dejando
   una `RuntimeError` real potencial si el propio `__exit__` del SDK
   fallara al cerrar el span.

API usada: la de spans/observaciones de Langfuse >=3
(`start_as_current_observation` / `update_current_generation` /
`update_current_span` / `create_score`), confirmada por introspección
directa contra la versión EXACTA fijada en el requirements.txt raíz del
monorepo (langfuse==4.5.1) -- NO `langfuse.trace().generation()`: ese
método no existe en 4.5.1 (`AttributeError: 'Langfuse' object has no
attribute 'trace'`, comprobado instanciando el cliente real). Es
exactamente el mismo bug ya documentado en
`backend/agents/lead_capture_agent/llm_engine.py` (su ruta de streaming
usa ese patrón inexistente, silenciado por un `except Exception: pass`
que nunca se detectó porque ningún test lo ejercita) -- ver
README_taller_mecanico.md, sección "Observabilidad con Langfuse", para
el detalle completo de por qué no se replica ese patrón aquí.

Estructura de trazas: una traza por interacción completa de cliente
(abierta por flujo_completo.py, o por flujo_diagnostico.py/
flujo_presupuesto.py cuando se llaman de forma independiente), con un
span/generación anidado por cada agente que participa -- la propagación
de anidamiento la hace el propio SDK de Langfuse vía el contexto activo
de OpenTelemetry (contextvars), no código propio de este módulo.
"""

from __future__ import annotations

import contextlib
import os
import sys as _sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=False)

_client_singleton: Any = None
_intento_de_construccion_fallido = False


def _habilitado() -> bool:
    return (
        os.environ.get("TALLER_MECANICO_LANGFUSE_ENABLED") == "1"
        and bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))
        and bool(os.environ.get("LANGFUSE_SECRET_KEY"))
    )


def _entorno() -> str | None:
    """'test' cuando el proceso corre bajo pytest -- `PYTEST_CURRENT_TEST`
    es una variable que pytest fija automáticamente durante cada test
    (documentado, estable, no un detalle de implementación frágil), así
    que esto no requiere que quien ejecute un test de humo real
    (`test_*_live.py` con `TALLER_MECANICO_LANGFUSE_ENABLED=1`) recuerde
    configurar nada aparte: cualquier traza que SÍ llegue a Langfuse
    durante los tests queda etiquetada como 'test' en el campo nativo
    `environment` de Langfuse, separable de las interacciones reales en
    el dashboard sin depender de convenciones de nombres. Fuera de
    pytest, devuelve `None` -- el SDK usa entonces su propio default
    (`LANGFUSE_TRACING_ENVIRONMENT`, o "default" si tampoco está fijada)."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return "test"
    return None


def _get_client() -> Any | None:
    """Devuelve el cliente Langfuse singleton, o None si no está
    configurado o si construirlo falló. Nunca lanza -- un fallo aquí
    (credenciales inválidas, LANGFUSE_HOST inalcanzable en el momento de
    construir el cliente, etc.) deja la observabilidad desactivada para
    el resto del proceso, no interrumpe el arranque."""
    global _client_singleton, _intento_de_construccion_fallido
    if not _habilitado():
        return None
    if _client_singleton is not None:
        return _client_singleton
    if _intento_de_construccion_fallido:
        return None
    try:
        from langfuse import Langfuse

        _client_singleton = Langfuse(environment=_entorno())
    except Exception:
        _intento_de_construccion_fallido = True
        return None
    return _client_singleton


@dataclass
class ObservacionLangfuse:
    """Handle devuelto por `traza_interaccion`/`generacion_agente`.
    `trace_id`/`observation_id` son `None` si Langfuse no está
    configurado o si abrir la observación falló -- el código llamante
    (p.ej. `_registrar_decision` de cada agente) los guarda tal cual en
    `decision_log.langfuse_trace_id`/`langfuse_observation_id`, que
    aceptan NULL exactamente para este caso."""

    trace_id: str | None = None
    observation_id: str | None = None
    _client: Any = field(default=None, repr=False)

    def completar_generacion(self, output: Any, usage_details: dict | None = None) -> None:
        """Registra la salida real (y opcionalmente el uso de tokens) de
        la generación actualmente activa. Debe llamarse dentro del mismo
        bloque `with` que la abrió. No hace nada si Langfuse no está
        configurado; nunca lanza si la llamada real falla."""
        if self._client is None:
            return
        try:
            self._client.update_current_generation(output=output, usage_details=usage_details)
        except Exception:
            pass

    def completar_span(self, output: Any) -> None:
        """Equivalente a `completar_generacion` para observaciones
        abiertas como span (no generation) -- p.ej. la traza raíz de una
        interacción completa."""
        if self._client is None:
            return
        try:
            self._client.update_current_span(output=output)
        except Exception:
            pass

    def registrar_score(
        self, name: str, value: str, comment: str, data_type: str = "CATEGORICAL"
    ) -> None:
        """Adjunta un score a ESTA observación (no a la que esté activa
        en el contexto en ese momento) -- por eso usa `create_score` con
        `trace_id`/`observation_id` explícitos, no `score_current_*`.
        Pensado para el veredicto del Evaluador: se llama sobre el handle
        devuelto por Diagnóstico/Presupuestador (la observación evaluada),
        no sobre la propia generación del Evaluador."""
        if self._client is None or self.trace_id is None:
            return
        try:
            self._client.create_score(
                trace_id=self.trace_id,
                observation_id=self.observation_id,
                name=name,
                value=value,
                data_type=data_type,
                comment=comment,
            )
        except Exception:
            pass


_SIN_OBSERVACION = ObservacionLangfuse()


@contextlib.contextmanager
def _observacion(*, as_type: str, name: str, **kwargs: Any) -> Iterator[ObservacionLangfuse]:
    """Implementación común de `traza_interaccion`/`generacion_agente`.

    Gestiona ABRIR y CERRAR el `with client.start_as_current_observation(...)`
    real a mano (`cm.__enter__()`/`cm.__exit__()`), en vez de delegar el
    cierre a `contextlib.ExitStack`, para poder proteger de verdad las
    TRES fases por separado sin volver a mezclar los fallos de Langfuse
    con las excepciones de negocio del llamante:

    - Abrir (`cm.__enter__()`): si falla, se neutraliza y se entrega
      `_SIN_OBSERVACION` -- ninguna llamada a Langfuse llega a ejecutarse
      después.
    - El cuerpo del `with` del llamante (el `yield` de abajo): cualquier
      excepción que lance -- de negocio o no -- se relanza TAL CUAL tras
      un intento best-effort de cerrar el `cm` real; nunca se convierte
      en un segundo `yield` (eso es lo que rompía `contextlib` con
      "generator didn't stop after throw()" en un primer intento de este
      módulo, cuando el `except Exception` envolvía también el `yield`).
    - Cerrar en el camino feliz (`cm.__exit__(None, None, None)`): si el
      propio SDK de Langfuse falla AL CERRAR el span (p.ej. un error de
      red al hacer flush), eso NO debe propagarse como si fuera un
      fallo del agente -- hallazgo real de la revisión de seguridad de
      esta integración: `contextlib.ExitStack` no distingue este caso
      del anterior, así que un fallo únicamente en el cierre sí se
      habría colado hacia el código de negocio."""
    client = _get_client()
    if client is None:
        yield _SIN_OBSERVACION
        return

    try:
        cm = client.start_as_current_observation(as_type=as_type, name=name, **kwargs)
        obs_raw = cm.__enter__()
    except Exception:
        yield _SIN_OBSERVACION
        return

    obs = ObservacionLangfuse(trace_id=obs_raw.trace_id, observation_id=obs_raw.id, _client=client)
    try:
        yield obs
    except BaseException:
        try:
            cm.__exit__(*_sys.exc_info())
        except Exception:
            pass
        raise
    else:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass


def traza_interaccion(
    nombre: str, metadata: dict | None = None
) -> contextlib.AbstractContextManager:
    """Abre la observación raíz (`as_type='span'`) de una interacción
    completa de cliente. Si ya hay una traza activa en el contexto (p.ej.
    flujo_completo.py ya abrió una y esto se llama desde
    flujo_diagnostico.py dentro de esa misma llamada), el propio SDK de
    Langfuse anida esta como hija en vez de crear una traza nueva --
    comportamiento estándar de propagación de contexto de OpenTelemetry,
    no algo que este módulo gestione manualmente. Si Langfuse no está
    habilitado o abrir/cerrar la observación falla, entrega
    `ObservacionLangfuse()` (todo `None`) y el código dentro del `with`
    sigue ejecutándose normalmente. Cualquier excepción que el código del
    llamante lance dentro del `with` se propaga tal cual -- nunca se
    silencia aquí."""
    return _observacion(as_type="span", name=nombre, metadata=metadata or {})


def generacion_agente(
    nombre_agente: str,
    model: str,
    input_data: Any,
    metadata: dict | None = None,
) -> contextlib.AbstractContextManager:
    """Abre una observación tipo 'generation' para la llamada LLM de un
    agente concreto, anidada en la traza activa (o creando una nueva si
    no hay ninguna -- mismo comportamiento de `traza_interaccion`).
    Devuelve un `ObservacionLangfuse` para registrar la salida real con
    `.completar_generacion(...)` una vez el agente termina de procesar la
    respuesta del modelo, y para encadenar un score posterior (Evaluador)
    con `.registrar_score(...)`. Cualquier excepción que el código del
    llamante lance dentro del `with` (p.ej. una respuesta del modelo mal
    formada) se propaga tal cual -- nunca se silencia aquí; solo un fallo
    de Langfuse al abrir o cerrar la observación se neutraliza."""
    return _observacion(
        as_type="generation",
        name=nombre_agente,
        model=model,
        input=input_data,
        metadata=metadata or {},
    )


def usage_details(response: Any) -> dict[str, int | None] | None:
    """Extrae `{"input", "output"}` de tokens de una respuesta de
    Anthropic de forma defensiva (`getattr`, nunca acceso directo a
    `.usage.input_tokens`). Hallazgo real de la revisión de seguridad de
    esta integración: los cuatro agentes construían este dict accediendo
    directamente a `response.usage.input_tokens`/`.output_tokens` como
    argumentos posicionales de `completar_generacion(...)` -- se evalúan
    ANTES de entrar a ese método, así que un `response` sin `.usage`
    (cualquier doble de test que no lo modele, o una forma de respuesta
    no estándar) lanzaba `AttributeError` incluso con Langfuse
    completamente DESACTIVADO, violando la garantía de "la observabilidad
    nunca puede romper el flujo de negocio". Devuelve `None` si `response`
    no tiene `.usage` -- `completar_generacion` acepta `usage_details=None`
    sin problema."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        "input": getattr(usage, "input_tokens", None),
        "output": getattr(usage, "output_tokens", None),
    }


def registrar_score(
    trace_id: str | None,
    observation_id: str | None,
    name: str,
    value: str,
    comment: str,
    data_type: str = "CATEGORICAL",
) -> None:
    """Igual que `ObservacionLangfuse.registrar_score`, pero sin necesitar
    el objeto original -- útil cuando el handle cruzó una frontera de
    función/orquestación y solo quedan los IDs (p.ej. los que ya viajan
    dentro de `diagnostico_output`/`presupuesto_output`). No hace nada si
    Langfuse no está configurado o si `trace_id` es `None`."""
    client = _get_client()
    if client is None or trace_id is None:
        return
    try:
        client.create_score(
            trace_id=trace_id,
            observation_id=observation_id,
            name=name,
            value=value,
            data_type=data_type,
            comment=comment,
        )
    except Exception:
        pass
