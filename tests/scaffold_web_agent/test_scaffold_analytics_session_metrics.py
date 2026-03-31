import uuid

from backend.agents.scaffold_web_agent.analytics_service import AnalyticsService
from backend.agents.scaffold_web_agent.sqlite_store import insert_event


def test_analytics_service_uses_unique_sessions_for_session_rates(test_db):
    tenant_id = f"tenant-session-metrics-{uuid.uuid4().hex}"

    insert_event(
        tenant_id=tenant_id,
        session_id="sess-1",
        event_type="chat_requested",
        event_payload={"message_length": 4},
    )
    insert_event(
        tenant_id=tenant_id,
        session_id="sess-1",
        event_type="chat_requested",
        event_payload={"message_length": 5},
    )
    insert_event(
        tenant_id=tenant_id,
        session_id="sess-1",
        event_type="chat_replied",
        event_payload={"step": "confirm"},
    )
    insert_event(
        tenant_id=tenant_id,
        session_id="sess-1",
        event_type="lead_created",
        event_payload={"has_email": True},
    )
    insert_event(
        tenant_id=tenant_id,
        session_id="sess-2",
        event_type="chat_requested",
        event_payload={"message_length": 8},
    )

    result = AnalyticsService().tenant_summary(tenant_id)

    assert result["chat_requested_count"] == 3
    assert result["unique_sessions_with_chat_requested"] == 2
    assert result["unique_sessions_with_chat_replied"] == 1
    assert result["unique_sessions_with_lead_created"] == 1
    assert result["session_reply_rate"] == 0.5
    assert result["session_lead_creation_rate"] == 0.5
