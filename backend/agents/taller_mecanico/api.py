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


_INDEX_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Taller Mecánico — wrapper HTTP</title>
<style>
  body { font: 14px system-ui, sans-serif; max-width: 720px; margin: 32px auto; padding: 0 16px; color: #201d18; }
  h1 { font-size: 1.2rem; }
  label { display: block; margin-top: 12px; font-weight: 600; }
  input, textarea { width: 100%; padding: 6px 8px; margin-top: 4px; box-sizing: border-box; font: inherit; }
  button { margin-top: 16px; padding: 8px 16px; cursor: pointer; }
  pre { background: #f2f0ec; padding: 12px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }
  .aviso { color: #6c6659; font-size: 0.85rem; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.85rem; }
  th, td { text-align: left; border-bottom: 1px solid #eeece6; padding: 4px 6px; }
</style>
</head>
<body>
<h1>Taller Mecánico — interfaz mínima</h1>
<p class="aviso">taller_mecanico nunca tuvo UI hasta este hito -- esta página es
solo para escribir un mensaje de cliente y ver el resultado real de
<code>flujo_completo.procesar_flujo_completo()</code>. cliente_id/vehiculo_id deben
existir ya en la base de datos (se crean con <code>crm.py</code>, no desde aquí).</p>

<form id="f">
  <label>Mensaje del cliente
    <textarea name="mensaje" rows="2" required>Mi coche hace un ruido raro al frenar por las mañanas</textarea>
  </label>
  <label>cliente_id <input name="cliente_id" type="number" required></label>
  <label>vehiculo_id <input name="vehiculo_id" type="number" required></label>
  <label>fecha_hora_cita (opcional, "YYYY-MM-DD HH:MM") <input name="fecha_hora_cita" placeholder="2026-09-01 10:00"></label>
  <label>piezas_candidatas (opcional, ids separados por coma) <input name="piezas_candidatas" placeholder="1,2"></label>
  <label>horas_mano_obra (opcional) <input name="horas_mano_obra" type="number" step="0.25"></label>
  <button type="submit">Enviar</button>
</form>
<h2>Resultado</h2>
<pre id="resultado">(nada enviado todavía)</pre>

<h2>Últimas decisiones (decision_log)</h2>
<table id="decisiones"><thead><tr><th>id</th><th>agent</th><th>output</th></tr></thead><tbody></tbody></table>

<script>
async function cargarDecisiones() {
  const resp = await fetch('/decisiones?limite=10');
  const filas = await resp.json();
  const tbody = document.querySelector('#decisiones tbody');
  tbody.innerHTML = '';
  for (const fila of filas) {
    const tr = document.createElement('tr');
    // textContent, no innerHTML: fila.output es texto de decision_log,
    // que en el camino de "respuesta del modelo no parseable" guarda el
    // texto crudo del modelo verbatim (hallazgo de la revisión de
    // seguridad de este hito) -- innerHTML lo ejecutaria como HTML/JS.
    for (const valor of [fila.id, fila.agent, (fila.output || '').slice(0, 80)]) {
      const td = document.createElement('td');
      td.textContent = valor == null ? '' : String(valor);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

document.querySelector('#f').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const form = new FormData(ev.target);
  const piezas = form.get('piezas_candidatas');
  const payload = {
    mensaje: form.get('mensaje'),
    cliente_id: Number(form.get('cliente_id')),
    vehiculo_id: Number(form.get('vehiculo_id')),
    fecha_hora_cita: form.get('fecha_hora_cita') || null,
    piezas_candidatas: piezas ? piezas.split(',').map((s) => Number(s.trim())) : null,
    horas_mano_obra: form.get('horas_mano_obra') ? Number(form.get('horas_mano_obra')) : null,
  };
  const resp = await fetch('/mensaje', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  document.querySelector('#resultado').textContent = JSON.stringify(data, null, 2);
  cargarDecisiones();
});

cargarDecisiones();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML
