from backend.apps.scaffold_web_agent.analytics_service import AnalyticsService
from backend.apps.scaffold_web_agent.sqlite_store import insert_event


def test_analytics_service_counts_persisted_events(test_db):
    import uuid

    tenant_id = f"tenant-analytics-events-{uuid.uuid4().hex}"

    insert_event(
        tenant_id=tenant_id,
        session_id="sess-1",
        event_type="chat_requested",
        event_payload={"message_length": 4},
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
        event_type="lead_delivery_requested",
        event_payload={"has_email": True},
    )
    insert_event(
        tenant_id=tenant_id,
        session_id="sess-1",
        event_type="lead_created",
        event_payload={"has_email": True},
    )
    insert_event(
        tenant_id=tenant_id,
        session_id="sess-1",
        event_type="lead_delivery_completed",
        event_payload={"status": "sent"},
    )
    insert_event(
        tenant_id=tenant_id,
        session_id="sess-2",
        event_type="chat_requested",
        event_payload={"message_length": 8},
    )

    result = AnalyticsService().tenant_summary(tenant_id)

    assert result["tenant_id"] == tenant_id
    assert result["total_events"] >= 6
    assert result["chat_requested_count"] == 2
    assert result["chat_replied_count"] == 1
    assert result["lead_delivery_requested_count"] == 1
    assert result["lead_created_count"] == 1
    assert result["lead_delivery_completed_count"] == 1
    assert result["lead_creation_rate"] == 0.5
    assert result["delivery_completion_rate"] == 1.0
