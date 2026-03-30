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

from backend.apps.scaffold_web_agent.domain import SessionState, Status, Step
from backend.apps.scaffold_web_agent.tenants import Tenant

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
        from backend.apps.scaffold_web_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        fake_response = make_fake_anthropic_response("Hola, soy el asistente de Synapse Labs.")

        with patch("backend.apps.scaffold_web_agent.llm_engine.anthropic.Anthropic") as mock_cls:
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
        from backend.apps.scaffold_web_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        fake_response = make_fake_anthropic_response("Encantado de ayudarte.")

        with patch("backend.apps.scaffold_web_agent.llm_engine.anthropic.Anthropic") as mock_cls:
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
        from backend.apps.scaffold_web_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        fake_response = make_fake_anthropic_response("Perfecto, te contactaremos.")

        with patch("backend.apps.scaffold_web_agent.llm_engine.anthropic.Anthropic") as mock_cls:
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
        from backend.apps.scaffold_web_agent.llm_engine import handle_user_message_llm

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

        with patch("backend.apps.scaffold_web_agent.llm_engine.anthropic.Anthropic") as mock_cls:
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
        from backend.apps.scaffold_web_agent.llm_engine import handle_user_message_llm

        state = SessionState()
        fake_response = make_fake_anthropic_response("¿En qué más puedo ayudarte?")

        with patch("backend.apps.scaffold_web_agent.llm_engine.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = fake_response
            new_state, reply = handle_user_message_llm(
                state, "Solo quería preguntar", knowledge_text="k"
            )

        assert new_state.step == Step.START
        assert new_state.step != Step.SEND


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
                "backend.apps.scaffold_web_agent.chat_service",
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
        from backend.apps.scaffold_web_agent import chat_service as cs

        llm_called = []

        def fake_llm(state, message, knowledge_text=""):
            llm_called.append({"message": message, "knowledge": knowledge_text})
            new_state = SessionState()
            new_state.step = Step.COLLECT_CONTACT
            return new_state, "Respuesta LLM"

        # Parcheamos el import dinámico dentro de chat_service
        monkeypatch.setattr(
            "backend.apps.scaffold_web_agent.llm_engine.handle_user_message_llm",
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
        from backend.apps.scaffold_web_agent import chat_service as cs

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
        import backend.apps.scaffold_web_agent.sqlite_store as ss

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

        import backend.apps.scaffold_web_agent.sqlite_store as ss

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
