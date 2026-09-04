import pytest

from backend.agents.taller_mecanico import langfuse_utils
from tests.taller_mecanico.conftest import FakeLangfuseClient


class TestDesactivadoPorDefecto:
    """Sin LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY (el caso por defecto en
    toda la suite, ver fixture `langfuse_desactivado` en conftest.py),
    todo debe volverse un no-op barato, nunca lanzar."""

    def test_get_client_devuelve_none(self):
        assert langfuse_utils._get_client() is None

    def test_traza_interaccion_entrega_observacion_vacia(self):
        with langfuse_utils.traza_interaccion("x") as obs:
            assert obs.trace_id is None
            assert obs.observation_id is None

    def test_generacion_agente_entrega_observacion_vacia(self):
        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola") as obs:
            assert obs.trace_id is None
            assert obs.observation_id is None

    def test_completar_generacion_no_hace_nada(self):
        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola") as obs:
            obs.completar_generacion(output={"ok": True})  # no debe lanzar

    def test_credenciales_compartidas_presentes_sin_el_flag_propio_siguen_desactivadas(
        self, monkeypatch
    ):
        """Hallazgo real de la revisión de seguridad: LANGFUSE_PUBLIC_KEY/
        LANGFUSE_SECRET_KEY son compartidas con lead_capture_agent vía el
        .env del monorepo. Sin TALLER_MECANICO_LANGFUSE_ENABLED=1, tener
        esas credenciales presentes NO debe activar Langfuse para
        taller_mecanico -- de lo contrario, cualquier entorno donde ya
        existan (puestas ahí para OTRO agente) empezaría a mandar texto
        de clientes a un proyecto de Langfuse ajeno sin que nadie lo
        pidiera para este agente."""
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-compartida-de-lead-capture-agent")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-compartida-de-lead-capture-agent")
        assert langfuse_utils._habilitado() is False
        assert langfuse_utils._get_client() is None

    def test_registrar_score_no_hace_nada(self):
        langfuse_utils.registrar_score(
            None, None, "veredicto", "aprobado", "razon"
        )  # no debe lanzar


class TestClienteInyectado:
    """Con un FakeLangfuseClient inyectado (monkeypatching `_get_client`,
    nunca reactivando las variables de entorno reales -- ver
    `langfuse_desactivado` en conftest.py), verifica el comportamiento
    real de apertura/anidado/actualización/score."""

    def test_generacion_agente_devuelve_trace_id_y_observation_id(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola") as obs:
            assert obs.trace_id is not None
            assert obs.observation_id is not None

    def test_spans_anidados_comparten_el_mismo_trace_id(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with langfuse_utils.traza_interaccion("interaccion_cliente") as raiz:
            with langfuse_utils.generacion_agente(
                "router", "modelo-x", input_data="hola"
            ) as obs_router:
                pass
            with langfuse_utils.generacion_agente(
                "diagnostico", "modelo-x", input_data="sintomas"
            ) as obs_diag:
                pass

        assert raiz.trace_id == obs_router.trace_id == obs_diag.trace_id
        # Pero cada observación tiene su propio observation_id.
        assert len({raiz.observation_id, obs_router.observation_id, obs_diag.observation_id}) == 3

    def test_completar_generacion_registra_output_y_usage(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola") as obs:
            obs.completar_generacion(
                output={"intencion": "cita"}, usage_details={"input": 5, "output": 7}
            )

        assert fake.actualizaciones == [
            {
                "observation_id": obs.observation_id,
                "output": {"intencion": "cita"},
                "usage_details": {"input": 5, "output": 7},
            }
        ]

    def test_registrar_score_via_metodo_de_instancia(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with langfuse_utils.generacion_agente("diagnostico", "modelo-x", input_data="x") as obs:
            pass
        obs.registrar_score("veredicto_evaluador", "aprobado", "razonamiento de prueba")

        assert fake.scores == [
            {
                "trace_id": obs.trace_id,
                "observation_id": obs.observation_id,
                "name": "veredicto_evaluador",
                "value": "aprobado",
                "comment": "razonamiento de prueba",
                "data_type": "CATEGORICAL",
            }
        ]

    def test_registrar_score_funcion_standalone_con_ids_sueltos(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        langfuse_utils.registrar_score("trace-1", "obs-1", "veredicto", "rechazado", "motivo")

        assert fake.scores == [
            {
                "trace_id": "trace-1",
                "observation_id": "obs-1",
                "name": "veredicto",
                "value": "rechazado",
                "comment": "motivo",
                "data_type": "CATEGORICAL",
            }
        ]

    def test_registrar_score_standalone_sin_trace_id_no_hace_nada(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        langfuse_utils.registrar_score(None, None, "veredicto", "aprobado", "x")

        assert fake.scores == []

    def test_completar_span_registra_output_de_la_traza_raiz(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with langfuse_utils.traza_interaccion("interaccion_cliente") as raiz:
            raiz.completar_span(output={"resultado_final": "aprobado"})

        assert fake.actualizaciones == [
            {"observation_id": raiz.observation_id, "output": {"resultado_final": "aprobado"}}
        ]


class TestResiliencia:
    """Núcleo del requisito 'si Langfuse falla, el flujo de negocio no se
    entera' -- y, sobre todo, regresión del bug real encontrado durante
    esta integración: una excepción de negocio lanzada DENTRO de un
    `with langfuse_utils.generacion_agente(...):` nunca debe silenciarse
    ni convertirse en un RuntimeError de contextlib."""

    def test_fallo_al_abrir_la_observacion_no_impide_seguir_ejecutando(self, monkeypatch):
        fake = FakeLangfuseClient(fallar_al_abrir=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        ejecutado = False
        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola") as obs:
            assert obs.trace_id is None
            ejecutado = True
        assert ejecutado

    def test_fallo_al_actualizar_la_generacion_no_lanza(self, monkeypatch):
        fake = FakeLangfuseClient(fallar_al_actualizar=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola") as obs:
            obs.completar_generacion(output={"ok": True})  # no debe lanzar pese al fallo simulado

    def test_fallo_al_cerrar_la_observacion_en_el_camino_feliz_no_lanza(self, monkeypatch):
        """Hallazgo real de la revisión de seguridad: la primera versión
        de este módulo delegaba el cierre en `contextlib.ExitStack`, que
        NO protegía un fallo del propio SDK al cerrar el span (p.ej. un
        error de red durante el flush) -- ese fallo se habría propagado
        como si fuera un error del agente, pese a que el cuerpo del
        `with` del llamante terminó sin ningún problema."""
        fake = FakeLangfuseClient(fallar_al_cerrar=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        ejecutado = False
        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola"):
            ejecutado = True
        assert ejecutado  # el `with` completo termina sin propagar el fallo de cierre

    def test_fallo_al_cerrar_no_enmascara_una_excepcion_de_negocio_real(self, monkeypatch):
        """Si el llamante YA lanzó su propia excepción, un fallo adicional
        al cerrar Langfuse nunca debe sustituirla -- la excepción de
        negocio original es la que debe llegar al llamante."""
        fake = FakeLangfuseClient(fallar_al_cerrar=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        class ErrorDeNegocioDePrueba(ValueError):
            pass

        with pytest.raises(ErrorDeNegocioDePrueba):
            with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola"):
                raise ErrorDeNegocioDePrueba("x")

    def test_excepcion_de_negocio_dentro_del_with_se_propaga_intacta(self, monkeypatch):
        """Regresión directa del bug encontrado: la primera implementación
        envolvía el `yield` en un `except Exception: yield ...` amplio,
        que capturaba TAMBIÉN las excepciones de negocio del llamante y
        las convertía en un segundo yield -- contextlib lo rechazaba con
        'RuntimeError: generator didn't stop after throw()', y de haberse
        tragado en vez de fallar así, habría escondido el error real
        (p.ej. RouterRespuestaInvalidaError) detrás de un "éxito" falso."""
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        class ErrorDeNegocioDePrueba(ValueError):
            pass

        with pytest.raises(ErrorDeNegocioDePrueba):
            with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola"):
                raise ErrorDeNegocioDePrueba("algo salió mal en el agente, no en Langfuse")

    def test_excepcion_de_negocio_se_propaga_incluso_si_langfuse_tambien_falla_al_abrir(
        self, monkeypatch
    ):
        fake = FakeLangfuseClient(fallar_al_abrir=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        class ErrorDeNegocioDePrueba(ValueError):
            pass

        with pytest.raises(ErrorDeNegocioDePrueba):
            with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola"):
                raise ErrorDeNegocioDePrueba("x")

    def test_registrar_score_metodo_swallow_si_create_score_falla(self, monkeypatch):
        class ClienteQueFallaAlPuntuar(FakeLangfuseClient):
            def create_score(self, **kwargs):
                raise RuntimeError("fallo simulado al crear el score")

        fake = ClienteQueFallaAlPuntuar()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with langfuse_utils.generacion_agente("diagnostico", "modelo-x", input_data="x") as obs:
            pass
        obs.registrar_score("veredicto", "aprobado", "x")  # no debe lanzar

    def test_registrar_score_standalone_swallow_si_create_score_falla(self, monkeypatch):
        class ClienteQueFallaAlPuntuar(FakeLangfuseClient):
            def create_score(self, **kwargs):
                raise RuntimeError("fallo simulado al crear el score")

        fake = ClienteQueFallaAlPuntuar()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        langfuse_utils.registrar_score(
            "trace-1", "obs-1", "veredicto", "aprobado", "x"
        )  # no debe lanzar

    def test_singleton_se_reutiliza_entre_llamadas(self, monkeypatch):
        construcciones = []

        class LangfuseFalso:
            def __init__(self, **kwargs):
                construcciones.append(kwargs)

        monkeypatch.setenv("TALLER_MECANICO_LANGFUSE_ENABLED", "1")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        import langfuse

        monkeypatch.setattr(langfuse, "Langfuse", LangfuseFalso)

        primero = langfuse_utils._get_client()
        segundo = langfuse_utils._get_client()

        assert primero is segundo
        assert len(construcciones) == 1  # no se reconstruye en la segunda llamada

    def test_cliente_real_se_construye_con_environment_test_bajo_pytest(self, monkeypatch):
        """Hallazgo del hito de anidado de trazas: cualquier traza real que
        llegue a Langfuse durante los tests (p.ej. un test de humo
        ejecutado con TALLER_MECANICO_LANGFUSE_ENABLED=1) debe quedar
        etiquetada como entorno 'test' -- separable en el dashboard de las
        interacciones reales. `PYTEST_CURRENT_TEST` lo fija pytest
        automáticamente durante cada test, así que esto se cumple sin que
        quien ejecute un test de humo tenga que configurar nada aparte."""
        construcciones = []

        class LangfuseFalso:
            def __init__(self, **kwargs):
                construcciones.append(kwargs)

        monkeypatch.setenv("TALLER_MECANICO_LANGFUSE_ENABLED", "1")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        import langfuse

        monkeypatch.setattr(langfuse, "Langfuse", LangfuseFalso)

        assert "PYTEST_CURRENT_TEST" in __import__("os").environ  # confirma la premisa
        langfuse_utils._get_client()

        assert construcciones == [{"environment": "test"}]

    def test_entorno_fuera_de_pytest_devuelve_none(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        assert langfuse_utils._entorno() is None

    def test_construccion_del_cliente_fallida_deja_todo_desactivado_sin_lanzar(self, monkeypatch):
        monkeypatch.setenv("TALLER_MECANICO_LANGFUSE_ENABLED", "1")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

        def _fallar(**kwargs):
            raise RuntimeError("credenciales inválidas simuladas")

        import langfuse

        monkeypatch.setattr(langfuse, "Langfuse", _fallar)

        assert langfuse_utils._get_client() is None
        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola") as obs:
            assert obs.trace_id is None


class TestUsageDetails:
    """Hallazgo real de la revisión de seguridad: los cuatro agentes
    construían el dict de uso de tokens accediendo directamente a
    `response.usage.input_tokens`/`.output_tokens` como argumento de
    `completar_generacion(...)` -- se evalúa ANTES de entrar a ese
    método, así que un `response` sin `.usage` rompía incluso con
    Langfuse completamente desactivado, violando la garantía de que la
    observabilidad nunca puede afectar al flujo de negocio."""

    def test_extrae_input_y_output_tokens(self):
        class UsageFalso:
            input_tokens = 10
            output_tokens = 20

        class RespuestaFalsa:
            usage = UsageFalso()

        assert langfuse_utils.usage_details(RespuestaFalsa()) == {"input": 10, "output": 20}

    def test_response_sin_usage_devuelve_none_sin_lanzar(self):
        class RespuestaSinUsage:
            pass

        assert langfuse_utils.usage_details(RespuestaSinUsage()) is None

    def test_usage_sin_los_campos_esperados_no_lanza(self):
        class UsageIncompleto:
            pass

        class RespuestaFalsa:
            usage = UsageIncompleto()

        assert langfuse_utils.usage_details(RespuestaFalsa()) == {"input": None, "output": None}

    def test_completar_generacion_acepta_el_resultado_directamente_cuando_falta_usage(
        self, monkeypatch
    ):
        """Regresión end-to-end del hallazgo: con Langfuse activo pero un
        `response` sin `.usage`, el flujo debe completar igual."""
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        class RespuestaSinUsage:
            pass

        with langfuse_utils.generacion_agente("router", "modelo-x", input_data="hola") as obs:
            obs.completar_generacion(
                output={"ok": True}, usage_details=langfuse_utils.usage_details(RespuestaSinUsage())
            )

        assert fake.actualizaciones == [
            {"observation_id": obs.observation_id, "output": {"ok": True}, "usage_details": None}
        ]
