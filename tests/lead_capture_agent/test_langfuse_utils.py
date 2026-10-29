import logging

import pytest

from backend.agents.lead_capture_agent import langfuse_utils
from tests.lead_capture_agent.conftest import FakeLangfuseClient


class TestDesactivadoPorDefecto:
    """Sin LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY (el caso por defecto en
    toda la suite, ver `langfuse_desactivado` en conftest.py), todo debe
    volverse un no-op barato, nunca lanzar."""

    def test_get_client_devuelve_none(self):
        assert langfuse_utils._get_client() is None

    def test_registrar_evento_no_hace_nada(self):
        langfuse_utils.registrar_evento("x", input={}, output={})  # no debe lanzar

    def test_generacion_streaming_entrega_observacion_vacia(self):
        with langfuse_utils.generacion_streaming("x", "modelo", input_data="hola") as obs:
            assert obs.trace_id is None
            assert obs.observation_id is None

    def test_completar_no_hace_nada(self):
        with langfuse_utils.generacion_streaming("x", "modelo", input_data="hola") as obs:
            obs.completar(output="respuesta")  # no debe lanzar


class TestClienteInyectado:
    def test_registrar_evento_llama_a_create_event(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        langfuse_utils.registrar_evento(
            "lead-capture-chat", input={"user_text": "hola"}, output={"reply": "hey"}
        )

        assert fake.eventos == [
            {
                "name": "lead-capture-chat",
                "input": {"user_text": "hola"},
                "output": {"reply": "hey"},
                "metadata": {},
            }
        ]

    def test_generacion_streaming_completar_registra_output(self, monkeypatch):
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with langfuse_utils.generacion_streaming(
            "lead-capture-stream", "claude-haiku-4-5-20251001", input_data=[{"role": "user"}]
        ) as obs:
            assert obs.trace_id is not None
            assert obs.observation_id is not None
            obs.completar(output="respuesta final")

        assert fake.actualizaciones == [{"output": "respuesta final", "usage_details": None}]


class TestResiliencia:
    """Requisito no negociable: un fallo de Langfuse nunca debe romper la
    respuesta al visitante, pero tampoco debe desaparecer sin dejar
    rastro (a diferencia del `except Exception: pass` original)."""

    def test_fallo_al_abrir_no_impide_seguir_ejecutando(self, monkeypatch, caplog):
        fake = FakeLangfuseClient(fallar_al_abrir=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with caplog.at_level(logging.ERROR):
            ejecutado = False
            with langfuse_utils.generacion_streaming("x", "modelo", input_data="hola") as obs:
                assert obs.trace_id is None
                ejecutado = True
            assert ejecutado

        assert any("abrir" in r.message for r in caplog.records)

    def test_fallo_al_actualizar_no_lanza_pero_queda_en_el_log(self, monkeypatch, caplog):
        fake = FakeLangfuseClient(fallar_al_actualizar=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        with caplog.at_level(logging.ERROR):
            with langfuse_utils.generacion_streaming("x", "modelo", input_data="hola") as obs:
                obs.completar(output="respuesta")  # no debe lanzar

        assert any("actualizar" in r.message for r in caplog.records)

    def test_registrar_evento_fallo_no_lanza_pero_queda_en_el_log(self, monkeypatch, caplog):
        class ClienteQueFalla(FakeLangfuseClient):
            def create_event(self, **kwargs):
                raise RuntimeError("fallo simulado")

        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: ClienteQueFalla())

        with caplog.at_level(logging.ERROR):
            langfuse_utils.registrar_evento("x", input={}, output={})  # no debe lanzar

        assert any("registrar el evento" in r.message for r in caplog.records)

    def test_excepcion_de_negocio_dentro_del_with_se_propaga_intacta(self, monkeypatch):
        """Regresión directa del bug de contextlib ya encontrado en
        taller_mecanico: una excepción real del código llamante nunca
        debe convertirse en un segundo `yield` ni silenciarse."""
        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        class ErrorDeNegocioDePrueba(ValueError):
            pass

        with pytest.raises(ErrorDeNegocioDePrueba):
            with langfuse_utils.generacion_streaming("x", "modelo", input_data="hola"):
                raise ErrorDeNegocioDePrueba("algo salió mal en el streaming, no en Langfuse")

    def test_construccion_del_cliente_fallida_queda_en_el_log_y_no_lanza(self, monkeypatch, caplog):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

        def _fallar(**kwargs):
            raise RuntimeError("credenciales inválidas simuladas")

        import langfuse

        monkeypatch.setattr(langfuse, "Langfuse", _fallar)

        with caplog.at_level(logging.ERROR):
            assert langfuse_utils._get_client() is None

        assert any("construir el cliente Langfuse" in r.message for r in caplog.records)
