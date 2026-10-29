"""
Tests para los cambios del motor LLM:

1. test_llm_engine_*         → prueba llm_engine.py con la API de Anthropic mockeada
2. test_chat_service_llm_*   → prueba que chat_service enruta al motor LLM
                               cuando el tenant tiene knowledge_text
3. test_messages_*           → prueba que el campo 'messages' se serializa
                               y deserializa correctamente en SQLite
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.agents.lead_capture_agent.domain import SessionState, Status, Step
from backend.agents.lead_capture_agent.tenants import Tenant

# ── Helpers compartidos ───────────────────────────────────────────────────────


def make_tenant_with_knowledge(knowledge: str = "Somos Synapse Labs.") -> Tenant:
    """Tenant con knowledge_text → activa el motor LLM."""
    return Tenant(
        tenant_id="synapse_demo",
        widget_token="tok_abc",
        inbox_email="hola@synapse-labs.ai",
        subject_prefix="[Synapse]",
        allowed_origins=["https://synapse-labs.ai"],
        agent_type="scaffold_web_agent",
        knowledge_text=knowledge,
    )


def make_tenant_no_knowledge() -> Tenant:
    """Tenant sin knowledge_text → usa el motor de reglas."""
    return Tenant(
        tenant_id="tenant-old",
        widget_token="tok_old",
        inbox_email="hello@example.com",
        subject_prefix="[Old]",
        allowed_origins=["http://localhost"],
        agent_type="scaffold_web_agent",
        knowledge_text="",  # vacío → motor de reglas
    )


def make_fake_anthropic_response(text: str):
    """
    Simula la respuesta de anthropic.Anthropic().messages.create()
    sin hacer ninguna llamada real a la API.
    """
    content_block = MagicMock()
    content_block.text = text

    response = MagicMock()
    response.content = [content_block]
    return response


# ── Tests del motor LLM (llm_engine.py) ──────────────────────────────────────


class TestLlmEngine:
    """Prueba handle_user_message_llm con la API de Anthropic mockeada."""

    def test_responde_con_texto_del_llm(self):
        """El motor devuelve la respuesta del LLM sin el marcador."""
        from backend.agents.lead_capture_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        fake_response = make_fake_anthropic_response("Hola, soy el asistente de Synapse Labs.")

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = fake_response
            new_state, reply = handle_user_message_llm(
                state, "Hola", knowledge_text="Synapse Labs es..."
            )

        assert reply == "Hola, soy el asistente de Synapse Labs."
        # El step no cambia si no hay marcador SEND_LEAD
        assert new_state.step == Step.START

    def test_guarda_historial_en_state_messages(self):
        """
        Cada turno añade el mensaje del usuario y la respuesta al historial.
        Así el LLM tiene contexto en la siguiente llamada.
        """
        from backend.agents.lead_capture_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        fake_response = make_fake_anthropic_response("Encantado de ayudarte.")

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = fake_response
            new_state, _ = handle_user_message_llm(state, "Hola", knowledge_text="k")

        # Debe haber 2 mensajes: el del usuario y el del asistente
        assert len(new_state.messages) == 2
        assert new_state.messages[0] == {"role": "user", "content": "Hola"}
        assert new_state.messages[1] == {
            "role": "assistant",
            "content": "Encantado de ayudarte.",
        }

    def test_extrae_email_del_mensaje_del_usuario(self):
        """
        Si el usuario escribe su email en el mensaje, se guarda en state.data.email
        aunque el LLM no lo mencione explícitamente.
        """
        from backend.agents.lead_capture_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        fake_response = make_fake_anthropic_response("Perfecto, te contactaremos.")

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = fake_response
            new_state, _ = handle_user_message_llm(
                state,
                "Mi email es juan@empresa.com, quiero información",
                knowledge_text="k",
            )

        assert new_state.data.email == "juan@empresa.com"

    def test_marcador_send_lead_activa_step_send(self):
        """
        Cuando el LLM incluye <<<SEND_LEAD>>> en su respuesta,
        el step pasa a SEND y el marcador no aparece en el reply visible.
        """
        from backend.agents.lead_capture_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        state.data.email = "lead@empresa.com"
        state.data.topic = "Consulta sobre precios"
        # Simular historial previo
        state.messages = [
            {"role": "user", "content": "Quiero saber los precios"},
            {"role": "assistant", "content": "Claro, ¿me das tu email?"},
            {"role": "user", "content": "lead@empresa.com"},
            {"role": "assistant", "content": "¿Te parece bien que lo envíe al equipo?"},
        ]

        llm_reply = "Perfecto, lo envío ahora.\n<<<SEND_LEAD>>>"
        fake_response = make_fake_anthropic_response(llm_reply)

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = fake_response
            new_state, reply = handle_user_message_llm(state, "Sí, adelante", knowledge_text="k")

        # El marcador no debe aparecer en la respuesta visible
        assert "<<<SEND_LEAD>>>" not in reply
        assert reply == "Perfecto, lo envío ahora."
        # El step debe ser SEND para que chat_service procese el lead
        assert new_state.step == Step.SEND
        # El summary debe estar construido
        assert new_state.data.summary is not None
        assert "lead@empresa.com" in new_state.data.summary
        assert new_state.data.status == Status.READY_TO_SEND

    def test_marcador_no_aparece_si_usuario_no_confirma(self):
        """
        Si el LLM no incluye el marcador, el step no cambia a SEND.
        """
        from backend.agents.lead_capture_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        fake_response = make_fake_anthropic_response("¿En qué más puedo ayudarte?")

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = fake_response
            new_state, reply = handle_user_message_llm(
                state, "Solo quería preguntar", knowledge_text="k"
            )

        assert new_state.step == Step.START
        assert new_state.step != Step.SEND


class TestRedaccionTranscripcionParaLangfuse:
    """Decisión de producto confirmada explícitamente por el usuario tras
    la auditoría de PII (ver README_lead_capture_agent.md): antes de
    mandar la transcripción completa a Langfuse en cualquiera de las dos
    rutas, se redacta cualquier email detectado (reutilizando
    `_EMAIL_RE`, no un mecanismo nuevo). No cubre teléfono/nombre en
    texto libre -- riesgo residual documentado, no un descuido."""

    def test_redacta_el_email_en_el_contenido(self):
        from backend.agents.lead_capture_agent.llm_engine import (
            _redactar_transcripcion_para_langfuse,
        )

        mensajes = [
            {"role": "user", "content": "Mi email es juan@empresa.com, llamadme"},
            {"role": "assistant", "content": "Perfecto, ¿en qué puedo ayudarte?"},
        ]
        redactados = _redactar_transcripcion_para_langfuse(mensajes)

        assert redactados[0]["content"] == "Mi email es [EMAIL_REDACTADO], llamadme"
        assert redactados[1]["content"] == "Perfecto, ¿en qué puedo ayudarte?"

    def test_no_muta_la_lista_original(self):
        from backend.agents.lead_capture_agent.llm_engine import (
            _redactar_transcripcion_para_langfuse,
        )

        original = [{"role": "user", "content": "contacto: ana@empresa.com"}]
        _redactar_transcripcion_para_langfuse(original)

        assert original[0]["content"] == "contacto: ana@empresa.com"

    def test_sin_email_deja_el_contenido_igual(self):
        from backend.agents.lead_capture_agent.llm_engine import (
            _redactar_transcripcion_para_langfuse,
        )

        mensajes = [{"role": "user", "content": "Quiero información sobre precios"}]
        redactados = _redactar_transcripcion_para_langfuse(mensajes)

        assert redactados == mensajes


class TestObservabilidadLangfuseUnificada:
    """Verifica el requisito explícito de esta corrección: ambas rutas
    (streaming y no-streaming) deben mandar el MISMO nivel de detalle a
    Langfuse -- la transcripción completa, redactada igual en las dos."""

    def test_ruta_no_streaming_manda_la_transcripcion_completa_redactada(self, monkeypatch):
        from backend.agents.lead_capture_agent import langfuse_utils
        from backend.agents.lead_capture_agent.llm_engine import handle_user_message_llm
        from tests.lead_capture_agent.conftest import FakeLangfuseClient

        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        state = SessionState()
        fake_response = make_fake_anthropic_response("Encantado de ayudarte.")

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = fake_response
            handle_user_message_llm(state, "Mi email es juan@empresa.com", knowledge_text="k")

        evento = fake.eventos[0]
        assert evento["name"] == "lead-capture-chat"
        # La transcripción completa (lista de mensajes), no solo {"user_text": ...}.
        assert isinstance(evento["input"], list)
        assert evento["input"][0]["role"] == "user"
        assert "[EMAIL_REDACTADO]" in evento["input"][0]["content"]
        assert "juan@empresa.com" not in evento["input"][0]["content"]

    def test_ambas_rutas_mandan_el_mismo_formato_de_input(self, monkeypatch):
        from backend.agents.lead_capture_agent import langfuse_utils
        from backend.agents.lead_capture_agent.llm_engine import (
            handle_user_message_llm,
            stream_user_message_llm,
        )
        from tests.lead_capture_agent.conftest import FakeLangfuseClient

        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        mensaje = "Mi email es lead@empresa.com, quiero información"

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = make_fake_anthropic_response("ok")
            handle_user_message_llm(SessionState(), mensaje, knowledge_text="k")

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.stream.return_value = FakeStreamManager(["ok"])
            list(stream_user_message_llm(SessionState(), mensaje, knowledge_text="k"))

        evento_no_streaming = fake.eventos[0]
        obs_streaming = fake.observaciones_abiertas[0]

        for input_data in (evento_no_streaming["input"], obs_streaming["input"]):
            assert isinstance(input_data, list)
            assert input_data[0]["role"] == "user"
            assert "[EMAIL_REDACTADO]" in input_data[0]["content"]
            assert "lead@empresa.com" not in input_data[0]["content"]

        # Mismo formato exacto en ambas rutas -- eso es "unificar el nivel
        # de detalle": no solo "las dos redactan", sino "las dos mandan
        # la misma estructura de transcripción".
        assert evento_no_streaming["input"] == obs_streaming["input"]

    def test_email_repetido_por_el_llm_en_su_propia_respuesta_tambien_se_redacta(self, monkeypatch):
        """Regresión directa de un hallazgo real al verificar contra el
        servidor real de Langfuse (no un test mockeado): Claude a veces
        repite el email del visitante en su respuesta para confirmarlo
        ("Veo que eres tú@ejemplo.com..."). Redactar solo `input` dejaba
        el email intacto en `output` -- ningún test mockeado lo detectó
        porque ninguna respuesta de prueba anterior incluía un email."""
        from backend.agents.lead_capture_agent import langfuse_utils
        from backend.agents.lead_capture_agent.llm_engine import handle_user_message_llm
        from tests.lead_capture_agent.conftest import FakeLangfuseClient

        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        state = SessionState()
        fake_response = make_fake_anthropic_response(
            "¡Genial! Veo que tu email es juan@empresa.com, te contactaremos ahí."
        )

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = fake_response
            handle_user_message_llm(state, "Mi email es juan@empresa.com", knowledge_text="k")

        evento = fake.eventos[0]
        assert "[EMAIL_REDACTADO]" in evento["output"]["reply"]
        assert "juan@empresa.com" not in evento["output"]["reply"]

    def test_email_repetido_por_el_llm_en_streaming_tambien_se_redacta(self, monkeypatch):
        from backend.agents.lead_capture_agent import langfuse_utils
        from backend.agents.lead_capture_agent.llm_engine import stream_user_message_llm
        from tests.lead_capture_agent.conftest import FakeLangfuseClient

        fake = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake)

        state = SessionState()
        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.stream.return_value = FakeStreamManager(
                ["Veo que tu email es juan@empresa.com, gracias."]
            )
            list(stream_user_message_llm(state, "Mi email es juan@empresa.com", knowledge_text="k"))

        actualizacion = fake.actualizaciones[0]
        assert "[EMAIL_REDACTADO]" in actualizacion["output"]
        assert "juan@empresa.com" not in actualizacion["output"]


class FakeStreamManager:
    """Doble de `anthropic.Anthropic().messages.stream(...)` -- un context
    manager cuyo `.text_stream` es un iterable de chunks de texto, igual
    que el SDK real. Sin esto no había ninguna forma de probar
    `stream_user_message_llm` con la API de Anthropic mockeada -- por
    eso esta función nunca tuvo tests hasta esta corrección."""

    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def text_stream(self):
        return iter(self._chunks)


class TestStreamUserMessageLlm:
    """`stream_user_message_llm` no tenía NINGÚN test antes de esta
    corrección -- ni siquiera uno que confirmara que produce chunks SSE
    válidos, mucho menos que ejercitara su integración con Langfuse (el
    bug real que motivó esta corrección: `langfuse.trace().generation()`,
    inexistente en la versión fijada, fallaba en silencio en CADA
    respuesta y ningún test lo detectaba)."""

    def _consumir(self, generator):
        return list(generator)

    def test_produce_chunks_sse_y_evento_final(self):
        from backend.agents.lead_capture_agent.llm_engine import stream_user_message_llm

        state = SessionState()
        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.stream.return_value = FakeStreamManager(
                ["Hola, ", "encantado ", "de ayudarte."]
            )
            eventos = self._consumir(stream_user_message_llm(state, "Hola", knowledge_text="k"))

        assert any('"chunk"' in e for e in eventos)
        assert '"done": true' in eventos[-1]

    def test_on_complete_recibe_el_estado_y_la_respuesta_limpia(self):
        from backend.agents.lead_capture_agent.llm_engine import stream_user_message_llm

        state = SessionState()
        recibido = {}

        def on_complete(new_state, clean_reply):
            recibido["state"] = new_state
            recibido["reply"] = clean_reply

        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.stream.return_value = FakeStreamManager(
                ["Perfecto, lo envío ahora.\n<<<SEND_LEAD>>>"]
            )
            self._consumir(
                stream_user_message_llm(
                    state, "Sí, adelante", knowledge_text="k", on_complete=on_complete
                )
            )

        assert recibido["reply"] == "Perfecto, lo envío ahora."
        assert recibido["state"].step == Step.SEND

    def test_langfuse_activo_registra_la_generacion_de_streaming(self, monkeypatch):
        """Verifica la corrección del bug real: con Langfuse "activo" (un
        FakeLangfuseClient inyectado), la observación de streaming se
        abre y se completa con el output real -- ya no con
        langfuse.trace().generation(), inexistente."""
        from backend.agents.lead_capture_agent import langfuse_utils
        from backend.agents.lead_capture_agent.llm_engine import stream_user_message_llm
        from tests.lead_capture_agent.conftest import FakeLangfuseClient

        fake_langfuse = FakeLangfuseClient()
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake_langfuse)

        state = SessionState()
        with patch("backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.stream.return_value = FakeStreamManager(["Hola."])
            self._consumir(stream_user_message_llm(state, "Hola", knowledge_text="k"))

        assert fake_langfuse.actualizaciones == [{"output": "Hola.", "usage_details": None}]

    def test_fallo_de_langfuse_no_rompe_la_respuesta_al_visitante(self, monkeypatch, caplog):
        """Requisito no negociable de la corrección: un fallo de Langfuse
        durante el streaming nunca debe impedir que el visitante reciba
        su respuesta completa."""
        import logging

        from backend.agents.lead_capture_agent import langfuse_utils
        from backend.agents.lead_capture_agent.llm_engine import stream_user_message_llm
        from tests.lead_capture_agent.conftest import FakeLangfuseClient

        fake_langfuse = FakeLangfuseClient(fallar_al_abrir=True)
        monkeypatch.setattr(langfuse_utils, "_get_client", lambda: fake_langfuse)

        state = SessionState()
        with caplog.at_level(logging.ERROR):
            with patch(
                "backend.agents.lead_capture_agent.llm_engine.anthropic.Anthropic"
            ) as mock_cls:
                mock_cls.return_value.messages.stream.return_value = FakeStreamManager(
                    ["Respuesta completa igualmente."]
                )
                eventos = self._consumir(stream_user_message_llm(state, "Hola", knowledge_text="k"))

        assert any("Respuesta completa igualmente." in e for e in eventos)
        # A diferencia del bug original (except Exception: pass mudo), el
        # fallo queda en el log del servidor.
        assert any("abrir" in r.message for r in caplog.records)


# ── Tests de enrutamiento en chat_service.py ─────────────────────────────────


class DummySessionService:
    def __init__(self, state=None):
        self.state = state or SessionState()
        self.saved = None

    def get_state(self, tenant_id, session_id):
        return self.state

    def save_state(self, tenant_id, session_id, state):
        self.saved = state


class DummyLeadService:
    def __init__(self):
        self.created = None

    def create_lead(
        self,
        *,
        tenant_id=None,
        session_id=None,
        email=None,
        topic=None,
        summary=None,
        **kw,
    ):
        self.created = {"email": email, "topic": topic, "summary": summary}


class DummyDeliveryService:
    def __init__(self):
        self.delivered = False

    def deliver_lead(self, *, tenant, category_value, summary, mailer):
        self.delivered = True


class DummyEventService:
    def __init__(self):
        self.events = []

    def record(self, *, tenant_id, session_id, event_type, event_payload=None):
        self.events.append(event_type)


class DummyMailer:
    def send(self, to_email, subject, body):
        pass


class TestChatServiceLlmRouting:
    """
    Prueba que chat_service enruta correctamente al motor LLM
    cuando el tenant tiene knowledge_text, y al motor de reglas cuando no.
    """

    def _make_service(self, state=None):
        return (
            __import__(
                "backend.agents.lead_capture_agent.chat_service",
                fromlist=["ChatApplicationService"],
            ).ChatApplicationService(
                session_service=DummySessionService(state),
                lead_service=DummyLeadService(),
                delivery_service=DummyDeliveryService(),
                event_service=DummyEventService(),
            ),
            DummySessionService(state),
        )

    def test_tenant_con_knowledge_usa_llm_engine(self, monkeypatch):
        """
        Si el tenant tiene knowledge_text, chat_service llama a
        handle_user_message_llm en vez de handle_user_message.
        """
        from backend.agents.lead_capture_agent import chat_service as cs

        llm_called = []

        def fake_llm(state, message, knowledge_text=""):
            llm_called.append({"message": message, "knowledge": knowledge_text})
            new_state = SessionState()
            new_state.step = Step.COLLECT_CONTACT
            return new_state, "Respuesta LLM"

        # Parcheamos el import dinámico dentro de chat_service
        monkeypatch.setattr(
            "backend.agents.lead_capture_agent.llm_engine.handle_user_message_llm",
            fake_llm,
        )

        session_svc = DummySessionService()
        service = cs.ChatApplicationService(
            session_service=session_svc,
            lead_service=DummyLeadService(),
            delivery_service=DummyDeliveryService(),
            event_service=DummyEventService(),
        )

        tenant = make_tenant_with_knowledge("Synapse Labs knowledge aquí")

        result = service.process_chat(
            tenant=tenant,
            client_ip="127.0.0.1",
            session_id="sess-llm",
            message="Hola",
            mailer=DummyMailer(),
        )

        assert result.reply == "Respuesta LLM"
        assert len(llm_called) == 1
        assert llm_called[0]["knowledge"] == "Synapse Labs knowledge aquí"

    def test_tenant_sin_knowledge_usa_motor_reglas(self, monkeypatch):
        """
        Si knowledge_text está vacío, chat_service usa el motor de reglas
        (handle_user_message) y NO llama al LLM.
        """
        from backend.agents.lead_capture_agent import chat_service as cs

        rules_called = []

        def fake_rules(state, message):
            rules_called.append(message)
            new_state = SessionState()
            new_state.step = Step.COLLECT_CONTACT
            return new_state, "Respuesta reglas"

        monkeypatch.setattr(cs, "handle_user_message", fake_rules)

        session_svc = DummySessionService()
        service = cs.ChatApplicationService(
            session_service=session_svc,
            lead_service=DummyLeadService(),
            delivery_service=DummyDeliveryService(),
            event_service=DummyEventService(),
        )

        tenant = make_tenant_no_knowledge()

        result = service.process_chat(
            tenant=tenant,
            client_ip="127.0.0.1",
            session_id="sess-rules",
            message="Hello",
            mailer=DummyMailer(),
        )

        assert result.reply == "Respuesta reglas"
        assert len(rules_called) == 1


# ── Tests de serialización del campo messages ─────────────────────────────────


class TestMessagesSerializacion:
    """
    Prueba que el campo 'messages' se guarda y recupera correctamente
    en SQLite, y que sesiones antiguas sin el campo son compatibles.
    """

    def test_messages_se_persisten_entre_requests(self, tmp_path, monkeypatch):
        """
        Guarda un state con messages y lo recupera: el historial debe mantenerse.
        """
        import backend.agents.lead_capture_agent.sqlite_store as ss

        monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "test.db")
        store = ss.SQLiteSessionStore()

        state = SessionState()
        state.messages = [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "Bienvenido"},
        ]

        store.set("tenant1", "sess1", state)
        recovered = store.get("tenant1", "sess1")

        assert recovered.messages == state.messages

    def test_sesion_antigua_sin_messages_devuelve_lista_vacia(self, tmp_path, monkeypatch):
        """
        Compatibilidad hacia atrás: si el JSON guardado no tiene el campo
        'messages' (sesión de antes del cambio), se devuelve [] sin error.
        """
        import json
        import sqlite3

        import backend.agents.lead_capture_agent.sqlite_store as ss

        db = tmp_path / "test.db"
        monkeypatch.setattr(ss, "_db_path", lambda: db)

        # Crear la tabla manualmente con un JSON sin 'messages'
        ss._connect()  # crea la tabla
        old_json = json.dumps({"step": "start", "data": {"status": "collecting"}})
        with sqlite3.connect(str(db)) as con:
            con.execute(
                "INSERT INTO scaffold_sessions(tenant_id, session_id, state_json, updated_at) VALUES (?,?,?,?)",
                ("t1", "s1", old_json, 999),
            )
            con.commit()

        store = ss.SQLiteSessionStore()
        recovered = store.get("t1", "s1")

        # No debe lanzar error y messages debe ser lista vacía
        assert recovered.messages == []
        assert recovered.step == Step.START

    def test_messages_vacio_en_estado_nuevo(self):
        """Un SessionState recién creado tiene messages vacío."""
        state = SessionState()
        assert state.messages == []
