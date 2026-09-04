"""Tests del wrapper HTTP mínimo de Taller Mecánico (hito 5 del Hub
Personal de Agentes). taller_mecanico es una librería Python pura --
este wrapper es SOLO el adaptador HTTP (health, procesar un mensaje vía
flujo_completo.procesar_flujo_completo real, y consultar decision_log);
no se rediseña ni se añade ninguna funcionalidad de negocio nueva.

Todos los pasos de Claude se mockean aquí (mismo patrón `client_con_json`
que el resto de la suite) -- la verificación de que el wrapper funciona
de principio a fin CONTRA LA API REAL es un test de humo separado, con
el mismo gate `TALLER_MECANICO_RUN_LIVE_TESTS=1` que ya usa el resto de
la suite `_live`, no aquí."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.agents.taller_mecanico import (
    api,
    crm,
    db,
    diagnostico,
    evaluador,
    inventario,
    presupuestador,
    router,
)
from tests.taller_mecanico.conftest import FakeBlock, FakeMessage, FakeUsage, client_con_json


class _ClienteSecuencial:
    """Doble de `anthropic.Anthropic` que devuelve una respuesta JSON
    DISTINTA por cada llamada, en orden -- necesario para `evaluador.py`,
    cuyo `_get_client()` se usa para DOS evaluaciones con esquemas
    distintos dentro del mismo flujo (diagnóstico y presupuesto); un
    único cliente `client_con_json()` fijo no puede servir a ambas."""

    def __init__(self, payloads: list[dict]):
        self._payloads = list(payloads)
        self.messages = self

    def create(self, **kwargs):
        payload = self._payloads.pop(0)
        return FakeMessage(
            content=[FakeBlock(text=json.dumps(payload, ensure_ascii=False))],
            usage=FakeUsage(),
        )


@pytest.fixture
def escenario(conn):
    cliente_id = crm.alta_cliente(conn, nombre="Cliente de prueba", telefono="600222333")
    vehiculo_id = crm.alta_vehiculo(
        conn, cliente_id, matricula="9999TST", marca="Seat", modelo="Ibiza", kilometraje=80000
    )
    pieza_id = inventario.alta_pieza(
        conn, "Pastillas de prueba", precio_unitario=40.0, stock_inicial=10
    )
    return {"cliente_id": cliente_id, "vehiculo_id": vehiculo_id, "pieza_id": pieza_id}


@pytest.fixture
def client(conn):
    """`conn` (de conftest.py) ya redirige `db.DB_PATH` a una BD temporal
    por test -- pero NO se reutiliza ese mismo objeto `Connection` para
    las peticiones HTTP: hace falta que el override de `get_db` abra una
    conexión NUEVA por petición, exactamente como hace `get_db()` en
    `api.py` (mismo `check_same_thread=False`, mismo motivo: confirmado
    con una prueba de 100 peticiones concurrentes -- ver
    `test_concurrencia_no_revienta_con_sqlite_programming_error` -- que
    FastAPI/anyio puede despachar la apertura y el cierre de una MISMA
    conexión de una MISMA petición a hilos distintos del threadpool).
    Como `db.DB_PATH` sigue apuntando al mismo fichero temporal (gracias
    al monkeypatch de la fixture `conn`), estas conexiones nuevas
    leen/escriben la misma BD que `conn` en el propio test (WAL permite
    varias conexiones concurrentes al mismo fichero)."""

    def _get_db_de_test():
        conexion = db.get_conn(check_same_thread=False)
        try:
            yield conexion
        finally:
            conexion.close()

    api.app.dependency_overrides[api.get_db] = _get_db_de_test
    # base_url="http://127.0.0.1": el `TrustedHostMiddleware` añadido en
    # este hito (mitigación de DNS-rebinding, hallazgo de la revisión de
    # seguridad) rechaza el host "testserver" que usa TestClient por
    # defecto con 400 -- los tests deben usar un host permitido, igual
    # que el hub real.
    with TestClient(api.app, base_url="http://127.0.0.1") as test_client:
        yield test_client
    api.app.dependency_overrides.pop(api.get_db, None)


def test_health_responde_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_index_sirve_html_standalone(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<form" in resp.text or "<script" in resp.text  # UI mínima real, no una página vacía


class TestProcesarMensaje:
    def test_via_de_urgencia_no_necesita_datos_de_presupuesto(self, client, escenario, monkeypatch):
        """El camino más simple del wrapper -- un único paso real
        (Router) hasta escalado_humano_inmediato, sin necesitar
        `fecha_hora_cita`/`piezas_candidatas`/`horas_mano_obra`."""
        monkeypatch.setattr(
            router,
            "_get_client",
            lambda: client_con_json(
                {
                    "intencion": "urgencia",
                    "agente_destino": "diagnostico",
                    "razonamiento": "Riesgo de seguridad inmediato.",
                }
            ),
        )
        resp = client.post(
            "/mensaje",
            json={
                "mensaje": "Se me han roto los frenos, no puedo parar el coche",
                "cliente_id": escenario["cliente_id"],
                "vehiculo_id": escenario["vehiculo_id"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resultado_final"] == "escalado_humano_inmediato"
        assert data["router"]["intencion"] == "urgencia"
        assert data["cita_id"] is None

    def test_caso_de_aceptacion_completo_hasta_presupuesto_aprobado(
        self, client, escenario, monkeypatch
    ):
        """Reproduce el caso de aceptación del documento de arranque
        ('ruido raro al frenar por las mañanas') CON LOS 5 PASOS
        MOCKEADOS -- la versión sin mocks, contra la API real, es la
        verificación de humo del checkpoint (ver README de este hito)."""
        monkeypatch.setattr(
            router,
            "_get_client",
            lambda: client_con_json(
                {
                    "intencion": "consulta_tecnica",
                    "agente_destino": "diagnostico",
                    "razonamiento": "Síntoma de frenos, requiere diagnóstico.",
                }
            ),
        )
        monkeypatch.setattr(
            diagnostico,
            "_get_client",
            lambda: client_con_json(
                {
                    "causas_probables": ["Pastillas de freno desgastadas"],
                    "revisar_primero": "Espesor de las pastillas",
                    "confianza": "media",
                    "razonamiento": "Ruido matutino compatible con pastillas desgastadas por humedad nocturna.",
                }
            ),
        )
        # UNA sola instancia, reutilizada en las DOS llamadas a
        # `evaluador._get_client()` dentro del mismo flujo (evaluación
        # del diagnóstico y del presupuesto) -- hallazgo real durante la
        # propia escritura de este test: un `lambda` que construye un
        # `_ClienteSecuencial` nuevo en cada llamada reinicia la cola
        # cada vez, así que la segunda evaluación recibía otra vez el
        # primer payload (el del diagnóstico) en vez del segundo.
        cliente_evaluador = _ClienteSecuencial(
            [
                {
                    "veredicto": "aprobado",
                    "confianza_evaluador": "media",
                    "coherente_con_historial": True,
                    "advertencia": None,
                    "feedback_para_reintento": None,
                    "razonamiento": "Diagnóstico razonable dado el kilometraje.",
                },
                {
                    "veredicto": "aprobado",
                    "coherente_con_diagnostico": True,
                    "descuento_verificado": True,
                    "advertencia": None,
                    "feedback_para_reintento": None,
                    "razonamiento": "Presupuesto coherente con el diagnóstico aprobado.",
                },
            ]
        )
        monkeypatch.setattr(evaluador, "_get_client", lambda: cliente_evaluador)
        monkeypatch.setattr(
            presupuestador,
            "_get_client",
            lambda: client_con_json(
                {
                    "piezas_seleccionadas": [
                        {
                            "pieza_id": escenario["pieza_id"],
                            "cantidad": 2,
                            "eleccion": "original",
                            "justificacion": "Pieza original disponible en stock.",
                        }
                    ],
                    "descuento_tipo": "ninguno",
                    "criterio_excepcional": None,
                    "porcentaje_descuento_excepcional": None,
                    "razonamiento": "Sin motivo de descuento excepcional.",
                }
            ),
        )

        resp = client.post(
            "/mensaje",
            json={
                "mensaje": "Mi coche hace un ruido raro al frenar por las mañanas",
                "cliente_id": escenario["cliente_id"],
                "vehiculo_id": escenario["vehiculo_id"],
                "fecha_hora_cita": "2026-09-01 10:00",
                "piezas_candidatas": [escenario["pieza_id"]],
                "horas_mano_obra": 1.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resultado_final"] == "aprobado", data
        assert data["cita_id"] is not None
        assert data["presupuestador"]["decision_id"] is not None

    def test_cliente_inexistente_devuelve_404_no_500(self, client):
        """`crm.ClienteNoEncontradoError`/`VehiculoNoEncontradoError` (ambas
        `LookupError`) deben traducirse a un 404 claro, no a un 500
        genérico -- error de quien llama (id equivocado), no del wrapper."""
        resp = client.post(
            "/mensaje",
            json={"mensaje": "hola", "cliente_id": 999999, "vehiculo_id": 999999},
        )
        assert resp.status_code == 404

    def test_falta_fecha_cita_devuelve_400_no_500(self, client, escenario, monkeypatch):
        """`ValueError` de `flujo_completo` (fecha_hora_cita obligatoria si
        el diagnóstico se aprueba) debe traducirse a 400 -- error de la
        petición del cliente, no un fallo del wrapper."""
        monkeypatch.setattr(
            router,
            "_get_client",
            lambda: client_con_json(
                {
                    "intencion": "consulta_tecnica",
                    "agente_destino": "diagnostico",
                    "razonamiento": "x",
                }
            ),
        )
        monkeypatch.setattr(
            diagnostico,
            "_get_client",
            lambda: client_con_json(
                {
                    "causas_probables": ["x"],
                    "revisar_primero": "x",
                    "confianza": "alta",
                    "razonamiento": "x",
                }
            ),
        )
        monkeypatch.setattr(
            evaluador,
            "_get_client",
            lambda: client_con_json(
                {
                    "veredicto": "aprobado",
                    "confianza_evaluador": "alta",
                    "coherente_con_historial": True,
                    "advertencia": None,
                    "feedback_para_reintento": None,
                    "razonamiento": "x",
                }
            ),
        )
        resp = client.post(
            "/mensaje",
            json={
                "mensaje": "ruido al frenar",
                "cliente_id": escenario["cliente_id"],
                "vehiculo_id": escenario["vehiculo_id"],
                # fecha_hora_cita omitida a propósito
            },
        )
        assert resp.status_code == 400

    def test_vehiculo_de_otro_cliente_devuelve_400(self, client, escenario, conn):
        """El propio `flujo_completo` valida que `vehiculo_id` pertenezca a
        `cliente_id` (hallazgo de seguridad del hito 8 de taller_mecanico) --
        el wrapper debe traducir ese `ValueError` a 400, no a 500."""
        otro_cliente_id = crm.alta_cliente(conn, nombre="Otro Cliente", telefono="600333444")
        resp = client.post(
            "/mensaje",
            json={
                "mensaje": "hola",
                "cliente_id": otro_cliente_id,
                "vehiculo_id": escenario["vehiculo_id"],
            },
        )
        assert resp.status_code == 400


def test_decisiones_devuelve_las_ultimas_entradas_mas_recientes_primero(client, conn):
    conn.execute(
        "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output) "
        "VALUES ('2026-01-01 00:00:00', 'primero', 'router', 'r1', '{}')"
    )
    conn.execute(
        "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output) "
        "VALUES ('2026-01-01 00:01:00', 'segundo', 'router', 'r2', '{}')"
    )
    conn.commit()

    resp = client.get("/decisiones")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["input_text"] == "segundo"  # más reciente primero
    assert data[1]["input_text"] == "primero"


def test_decisiones_respeta_el_limite(client, conn):
    for i in range(5):
        conn.execute(
            "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output) "
            "VALUES ('2026-01-01 00:00:00', ?, 'router', 'r', '{}')",
            (f"mensaje-{i}",),
        )
    conn.commit()

    resp = client.get("/decisiones", params={"limite": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_decisiones_sin_filas_devuelve_lista_vacia_no_error(client):
    resp = client.get("/decisiones")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.parametrize("limite_pedido", [0, -5, 99999999999999999999999])
def test_decisiones_limite_fuera_de_rango_se_acota_no_falla(client, conn, limite_pedido):
    """0/negativo se acota a 1 (no a "sin filas"); un valor absurdamente
    grande se acota a 200, no fuerza una consulta sin límite real."""
    conn.execute(
        "INSERT INTO decision_log (timestamp, input_text, agent, reasoning, output) "
        "VALUES ('2026-01-01 00:00:00', 'x', 'router', 'r', '{}')"
    )
    conn.commit()
    resp = client.get("/decisiones", params={"limite": limite_pedido})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


class TestPropagaFalloUpstream:
    """`*RespuestaInvalidaError` (router/diagnostico/evaluador/
    presupuestador, todas `ValueError`) son un fallo del MODELO, no de
    quien llama al wrapper -- deben mapear a 502, no a 400 ni a un 500
    genérico indistinguible de un bug propio (hallazgo de la revisión de
    código: el `except ValueError` original era demasiado amplio y las
    confundía con errores de la petición)."""

    def test_respuesta_del_router_no_parseable_devuelve_502(self, client, escenario, monkeypatch):
        class _ClienteRotoJSON:
            messages = None

            def __init__(self):
                self.messages = self

            def create(self, **kwargs):
                return FakeMessage(content=[FakeBlock(text="esto no es JSON")], usage=FakeUsage())

        monkeypatch.setattr(router, "_get_client", lambda: _ClienteRotoJSON())
        resp = client.post(
            "/mensaje",
            json={
                "mensaje": "hola",
                "cliente_id": escenario["cliente_id"],
                "vehiculo_id": escenario["vehiculo_id"],
            },
        )
        assert resp.status_code == 502


def test_concurrencia_no_revienta_con_sqlite_programming_error(client):
    """Hallazgo CRÍTICO de la revisión de código: `check_same_thread=True`
    (el valor original) podía hacer que peticiones concurrentes a
    /decisiones fallaran con `sqlite3.ProgrammingError`, porque
    FastAPI/anyio puede despachar la apertura y el cierre de una MISMA
    conexión de una MISMA petición a hilos distintos del threadpool.

    IMPORTANTE, descubierto al intentar verificar esto con rigor: este
    test es de humo, NO la prueba de regresión real -- si el bug
    reapareciera, esta prueba podría seguir en verde. Se confirmó
    reproduciéndolo 100/100 veces con un script standalone contra el
    servidor real ya arrancado con una BD poblada, pero, DENTRO de
    pytest, con una BD de test pequeña y sin carga previa, el mismo
    cruce de hilos NO se reprodujo en 5 intentos seguidos incluso con el
    bug reintroducido a propósito -- el reparto de hilos de anyio es lo
    bastante no determinista (reutiliza el hilo recién liberado si
    queda libre a tiempo) que una petición barata puede evitar el cruce
    por pura suerte de scheduling. La prueba de regresión real, que SÍ
    fuerza el cruce de hilos a mano y por tanto no depende de esa suerte,
    es `test_check_same_thread_false_permite_usar_la_conexion_desde_otro_hilo`
    en `test_db.py`. Esta prueba de aquí se conserva como humo de
    extremo a extremo vía HTTP, no como garantía de regresión."""
    import asyncio

    import httpx

    async def _disparar_muchas():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as ac:
            respuestas = await asyncio.gather(
                *[ac.get("/decisiones", params={"limite": 5}) for _ in range(60)]
            )
            return [r.status_code for r in respuestas]

    codigos = asyncio.run(_disparar_muchas())
    assert codigos == [200] * len(codigos)


def test_concurrencia_en_escritura_no_pierde_ni_mezcla_filas_de_decision_log(
    client, conn, escenario, monkeypatch
):
    """No basta con "todas responden sin excepción" -- ausencia de
    excepción no descarta un lost-update SILENCIOSO (exactamente la
    categoría de bug que ya sufrieron `descontar_stock`/`crear_cita` en
    el hito 2 original de taller_mecanico: sin excepción visible, solo
    una fila perdida o con datos de otra petición). Este test dispara
    peticiones concurrentes REALES vía `/mensaje` con mensajes
    DISTINGUIBLES y verifica el contenido final de `decision_log`, no
    solo los códigos de estado.

    Camino de "urgencia" elegido porque escribe exactamente 1 fila en
    `decision_log` (agent='router', `input_text` = el mensaje recibido)
    y el flujo se detiene ahí -- sin necesitar mockear
    diagnóstico/evaluador/presupuestador, y sin ambigüedad sobre cuántas
    filas debería haber al final.

    LÍMITE HONESTO de esta prueba (mismo motivo que en
    `test_concurrencia_no_revienta_con_sqlite_programming_error`): el
    cruce real de hilos vía FastAPI/anyio es no determinista y no se
    reprodujo de forma fiable dentro de pytest con una BD de test
    pequeña -- así que esta prueba, aunque verifica integridad de datos
    de verdad (no solo códigos de estado) si el cruce de hilos ocurre,
    NO garantiza que vaya a ocurrir en cada ejecución. La garantía de
    que `check_same_thread=False` funciona -- y por tanto de que ningún
    lost-update de este tipo puede colarse por esa vía -- la da la
    prueba determinista en `test_db.py`
    (`test_check_same_thread_false_permite_usar_la_conexion_desde_otro_hilo`),
    que fuerza el cruce a mano en vez de depender del scheduler. Esta
    prueba se conserva como verificación adicional de extremo a extremo
    bajo carga concurrente real, no como la prueba de regresión
    principal."""
    import asyncio
    import json as json_lib

    import httpx

    class _ClienteUrgenciaSiempre:
        """Doble sin estado mutable compartido entre llamadas (a
        diferencia de `_ClienteSecuencial`) -- cada llamada concurrente
        construye su propia respuesta, nada que una carrera pueda
        corromper del lado del doble mismo; lo único bajo prueba es la
        capa de persistencia (SQLite) del wrapper."""

        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            payload = {
                "intencion": "urgencia",
                "agente_destino": "diagnostico",
                "razonamiento": "Riesgo de seguridad inmediato.",
            }
            return FakeMessage(content=[FakeBlock(text=json_lib.dumps(payload))], usage=FakeUsage())

    monkeypatch.setattr(router, "_get_client", lambda: _ClienteUrgenciaSiempre())

    n = 40
    mensajes_esperados = [f"urgencia-concurrente-{i}" for i in range(n)]

    async def _disparar_todas():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as ac:
            return await asyncio.gather(
                *[
                    ac.post(
                        "/mensaje",
                        json={
                            "mensaje": mensaje,
                            "cliente_id": escenario["cliente_id"],
                            "vehiculo_id": escenario["vehiculo_id"],
                        },
                    )
                    for mensaje in mensajes_esperados
                ]
            )

    respuestas = asyncio.run(_disparar_todas())

    # 1. Todas responden 200 con el resultado esperado -- sin esto, lo
    # de abajo no significaría nada (podría haber 500s silenciados).
    assert [r.status_code for r in respuestas] == [200] * n
    for resp in respuestas:
        assert resp.json()["resultado_final"] == "escalado_humano_inmediato"

    # 2. Integridad real de decision_log bajo concurrencia -- ni una
    # fila perdida, ni duplicada, ni con el input_text de otra petición.
    filas = conn.execute(
        "SELECT input_text FROM decision_log WHERE agent = 'router' "
        "AND input_text LIKE 'urgencia-concurrente-%'"
    ).fetchall()
    input_texts = [fila["input_text"] for fila in filas]

    assert len(input_texts) == n, (
        f"se esperaban {n} filas, hay {len(input_texts)} -- "
        "lost-update o escritura duplicada bajo concurrencia"
    )
    assert sorted(input_texts) == sorted(mensajes_esperados), (
        "el contenido de las filas no coincide exactamente con los mensajes "
        "enviados -- datos de una petición mezclados con otra"
    )
    assert len(set(input_texts)) == n  # sin duplicados exactos
