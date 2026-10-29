"""api.py — wrapper HTTP mínimo de Taller Mecánico (hito 5 del Hub
Personal de Agentes).

taller_mecanico es una librería Python pura (8 hitos, cifrado,
Langfuse) sin ninguna capa HTTP hasta ahora -- este módulo es
DELIBERADAMENTE mínimo: solo adapta lo que ya existe a HTTP para que el
Hub Personal de Agentes pueda arrancarlo/pararlo como
`IsolatedProcessConnector` y hablar con él. No rediseña nada de
taller_mecanico ni añade funcionalidad de negocio nueva (calendario,
Bizum, etc. ya están completos en hitos anteriores).

Tres decisiones confirmadas antes de escribir esto (documentadas aquí,
no solo en la conversación que las decidió):

1. **Sin autenticación.** Este proceso solo lo invoca el propio Hub,
   local a local (`IsolatedProcessConnector`, mismo patrón que el resto
   de agentes locales del hub), en la máquina de un único usuario. No
   se expone a ninguna red que no sea `127.0.0.1`. Añadir un token aquí
   protegería contra una amenaza que no existe en este despliegue (a
   diferencia de Lead Capture Agent, que SÍ está en un EC2 público, o
   de los endpoints `/admin/*` de ese mismo agente, que sí necesitan
   `X-Admin-Token`). Si este wrapper alguna vez se expusiera más allá
   de `127.0.0.1`, esta decisión debe revisarse -- no es la conclusión
   correcta para un despliegue distinto de este.
2. **BD real de taller_mecanico** (`db.get_conn()`, el mismo `DB_PATH`
   de siempre), no una instancia separada para el hub. Verificado ANTES
   de asumirlo: no existía ninguna BD real ni claves Fernet/HMAC
   persistentes configuradas (solo placeholders vacíos en
   `.env.example`; los tests generan una clave y una BD efímera nueva
   en cada corrida) -- se generaron claves reales y se añadieron al
   `.env` de la raíz del monorepo como parte de este hito, y esta
   ejecución crea `data/taller_mecanico.db` la primera vez que
   `get_conn()` corre. Una herramienta personal de un único usuario no
   necesita duplicar datos en una segunda instancia.
3. **Sin Docker.** taller_mecanico nunca lo tuvo y no lo necesita para
   esto -- se ejecuta como proceso Python directo
   (`uvicorn backend.agents.taller_mecanico.api:app`), gestionado por
   `IsolatedProcessConnector` exactamente igual que otros procesos
   locales del hub.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import (
    agenda,
    crm,
    db,
    diagnostico,
    evaluador,
    flujo_completo,
    inventario,
    presupuestador,
    router,
)

# docs_url/redoc_url/openapi_url en None: nadie consume el schema OpenAPI
# de este wrapper (el hub solo llama a /health, /mensaje, /decisiones) --
# no hay razón para exponerlo, y sí un pequeño coste de disclosure
# combinado con H2 (rebinding) si algún día se accede desde fuera de
# 127.0.0.1.
app = FastAPI(
    title="Taller Mecánico — wrapper HTTP (hito 5 del hub)",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Sin esto, un rebinding DNS (una página hace que `evil.test` resuelva a
# 127.0.0.1) convierte este wrapper sin auth en same-origin para el
# navegador del propio desarrollador -- hallazgo de la revisión de
# seguridad de este hito. `--host 127.0.0.1` no protege contra esto: los
# paquetes sí llegan por loopback, lo único que falta validar es el
# header Host.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


def get_db() -> Any:
    """Una conexión SQLite real por petición -- abrir/cerrar es barato
    (SQLite local, WAL). `check_same_thread=False`: confirmado con una
    prueba de 100 peticiones concurrentes que FastAPI/anyio puede
    despachar la apertura (antes del `yield`) y el cierre (después) a
    hilos distintos del threadpool incluso dentro de una misma
    petición -- sin este flag, eso revienta con
    `sqlite3.ProgrammingError`. Sigue siendo seguro: cada conexión la
    usa un único dueño lógico (la petición) de forma secuencial, nunca
    dos hilos a la vez sobre la misma conexión."""
    conn = db.get_conn(check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


# Not-found: id de cliente/vehículo/pieza/cita que no existe -- error de
# quien llama, no un fallo del wrapper.
_NOT_FOUND_ERRORS = (
    crm.ClienteNoEncontradoError,
    crm.VehiculoNoEncontradoError,
    inventario.PiezaNoEncontradaError,
    agenda.CitaNoEncontradaError,
)

# Fallo de un paso del pipeline de IA (el modelo devolvió algo que no
# pasó la validación de su schema) -- no es culpa de quien llama al
# wrapper, es el proveedor upstream fallando -- 502, no 400.
_UPSTREAM_ERRORS = (
    router.RouterRespuestaInvalidaError,
    diagnostico.DiagnosticoRespuestaInvalidaError,
    evaluador.EvaluadorRespuestaInvalidaError,
    presupuestador.PresupuestadorRespuestaInvalidaError,
)


class MensajeIn(BaseModel):
    # Límites de la revisión de seguridad: /mensaje dispara hasta 5
    # llamadas reales a Anthropic (coste real) y filas reales en
    # citas/presupuestos -- validar barato en el borde ANTES de gastar
    # esas llamadas, no solo dejar que flujo_completo valide por dentro.
    mensaje: str = Field(min_length=1, max_length=4000)
    cliente_id: int = Field(gt=0)
    vehiculo_id: int = Field(gt=0)
    fecha_hora_cita: str | None = Field(default=None, max_length=32)
    duracion_cita_minutos: int = Field(default=60, gt=0, le=8 * 60)
    piezas_candidatas: list[int] | None = Field(default=None, max_length=50)
    horas_mano_obra: float | None = Field(default=None, ge=0, le=100)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/mensaje")
def procesar_mensaje(payload: MensajeIn, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Ejecuta `flujo_completo.procesar_flujo_completo()` REAL -- ninguna
    lógica de negocio vive aquí, este endpoint solo traduce HTTP <-> la
    función Python ya existente y probada (292+ tests en
    `tests/taller_mecanico/`).

    `cliente_id`/`vehiculo_id` deben referirse a un cliente/vehículo YA
    existente -- crear clientes de prueba es responsabilidad de
    `crm.alta_cliente()`/`crm.alta_vehiculo()`, fuera del alcance de
    este wrapper (este hito es solo el adaptador HTTP, no una nueva
    superficie de alta de datos)."""
    try:
        return flujo_completo.procesar_flujo_completo(
            conn,
            mensaje=payload.mensaje,
            cliente_id=payload.cliente_id,
            vehiculo_id=payload.vehiculo_id,
            fecha_hora_cita=payload.fecha_hora_cita,
            duracion_cita_minutos=payload.duracion_cita_minutos,
            piezas_candidatas=payload.piezas_candidatas,
            horas_mano_obra=payload.horas_mano_obra,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except _UPSTREAM_ERRORS as exc:
        # El modelo devolvió algo que no pasó la validación de su
        # schema -- fallo del proveedor upstream, no de quien llama.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        # Resto de ValueError propios de taller_mecanico: fecha_hora_cita
        # /piezas_candidatas/horas_mano_obra faltantes cuando el
        # diagnóstico se aprueba, vehículo que no pertenece al cliente,
        # solapamiento de citas, presupuesto rechazado, etc. -- petición
        # mal formada dado el estado real, no 500 genérico. Nótese que
        # esto NO captura KeyError/IndexError (subclases de LookupError
        # pero no de _NOT_FOUND_ERRORS) ni CryptoConfigError
        # (RuntimeError) -- esos son bugs/fallos de configuración
        # reales y deben seguir siendo 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/decisiones")
def listar_decisiones(limite: int = 20, conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    """Últimas `limite` filas de `decision_log`, más recientes primero --
    para poder ver qué ha pasado sin abrir la BD a mano. `limite` se
    acota a [1, 200] para que un valor absurdo no fuerce una consulta
    gigante contra una BD que puede crecer sin límite.

    Columnas explícitas (no `SELECT *`): así una columna añadida a
    `decision_log` en el futuro no se publica aquí automáticamente sin
    decisión explícita."""
    limite = max(1, min(limite, 200))
    filas = conn.execute(
        "SELECT id, timestamp, agent, input_text, reasoning, output, "
        "verdict, verdict_reason, langfuse_trace_id "
        "FROM decision_log ORDER BY id DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return [dict(fila) for fila in filas]


# UI guiada de 4 pasos (hito 9): un único POST a /mensaje, revelación
# progresiva del mismo resultado en el cliente -- ver
# frontend/index.html. Igual que pdf_translator_v2/router.py, el HTML
# vive en su propio fichero (no como string Python) para que se pueda
# editar/formatear como HTML real; esto NO añade una capa de build ni
# StaticFiles -- sigue siendo un único fichero autocontenido (CSS/JS
# inline), servido tal cual, mismo espíritu "wrapper deliberadamente
# mínimo" del resto de este módulo.
_FRONTEND_INDEX = Path(__file__).resolve().parent / "frontend" / "index.html"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _FRONTEND_INDEX.read_text(encoding="utf-8")
