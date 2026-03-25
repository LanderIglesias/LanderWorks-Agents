from backend.apps.scaffold_web_agent.analytics_service import AnalyticsService


def test_analytics_service_tenant_summary_combines_base_and_event_metrics(monkeypatch):
    service = AnalyticsService()

    base_summary = {
        "tenant_id": "tenant-a",
        "total_sessions": 10,
        "done_sessions": 3,
        "confirm_sessions": 4,
        "sessions_with_email": 7,
    }

    events = [
        {
            "id": 1,
            "tenant_id": "tenant-a",
            "session_id": "sess-1",
            "event_type": "chat_requested",
            "event_payload_json": "{}",
            "created_at": 123,
        },
        {
            "id": 2,
            "tenant_id": "tenant-a",
            "session_id": "sess-1",
            "event_type": "chat_replied",
            "event_payload_json": "{}",
            "created_at": 124,
        },
        {
            "id": 3,
            "tenant_id": "tenant-a",
            "session_id": "sess-1",
            "event_type": "lead_delivery_requested",
            "event_payload_json": "{}",
            "created_at": 125,
        },
        {
            "id": 4,
            "tenant_id": "tenant-a",
            "session_id": "sess-1",
            "event_type": "lead_created",
            "event_payload_json": "{}",
            "created_at": 126,
        },
        {
            "id": 5,
            "tenant_id": "tenant-a",
            "session_id": "sess-1",
            "event_type": "lead_delivery_completed",
            "event_payload_json": "{}",
            "created_at": 127,
        },
        {
            "id": 6,
            "tenant_id": "tenant-a",
            "session_id": "sess-2",
            "event_type": "chat_requested",
            "event_payload_json": "{}",
            "created_at": 128,
        },
        {
            "id": 7,
            "tenant_id": "tenant-a",
            "session_id": "sess-2",
            "event_type": "chat_requested",
            "event_payload_json": "{}",
            "created_at": 129,
        },
    ]

    def fake_tenant_analytics(tenant_id: str) -> dict:
        assert tenant_id == "tenant-a"
        return base_summary

    def fake_list_events_for_tenant(tenant_id: str, limit: int = 10000):
        assert tenant_id == "tenant-a"
        assert limit == 10000
        return events

    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.analytics_service.tenant_analytics",
        fake_tenant_analytics,
    )
    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.analytics_service.list_events_for_tenant",
        fake_list_events_for_tenant,
    )

    result = service.tenant_summary("tenant-a")

    assert result == {
        "tenant_id": "tenant-a",
        "total_sessions": 10,
        "done_sessions": 3,
        "confirm_sessions": 4,
        "sessions_with_email": 7,
        "total_events": 7,
        "chat_requested_count": 3,
        "chat_replied_count": 1,
        "lead_delivery_requested_count": 1,
        "lead_created_count": 1,
        "lead_delivery_completed_count": 1,
        "lead_creation_rate": 1 / 3,
        "delivery_completion_rate": 1.0,
        "unique_sessions_with_chat_requested": 2,
        "unique_sessions_with_chat_replied": 1,
        "unique_sessions_with_lead_delivery_requested": 1,
        "unique_sessions_with_lead_created": 1,
        "unique_sessions_with_lead_delivery_completed": 1,
        "session_reply_rate": 0.5,
        "session_lead_creation_rate": 0.5,
        "session_delivery_completion_rate": 1.0,
    }


def test_analytics_service_tenant_summary_handles_zero_denominators(monkeypatch):
    service = AnalyticsService()

    def fake_tenant_analytics(tenant_id: str) -> dict:
        return {
            "tenant_id": tenant_id,
            "total_sessions": 0,
            "done_sessions": 0,
            "confirm_sessions": 0,
            "sessions_with_email": 0,
        }

    def fake_list_events_for_tenant(tenant_id: str, limit: int = 10000):
        return []

    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.analytics_service.tenant_analytics",
        fake_tenant_analytics,
    )
    monkeypatch.setattr(
        "backend.apps.scaffold_web_agent.analytics_service.list_events_for_tenant",
        fake_list_events_for_tenant,
    )

    result = service.tenant_summary("tenant-a")

    assert result == {
        "tenant_id": "tenant-a",
        "total_sessions": 0,
        "done_sessions": 0,
        "confirm_sessions": 0,
        "sessions_with_email": 0,
        "total_events": 0,
        "chat_requested_count": 0,
        "chat_replied_count": 0,
        "lead_delivery_requested_count": 0,
        "lead_created_count": 0,
        "lead_delivery_completed_count": 0,
        "lead_creation_rate": 0.0,
        "delivery_completion_rate": 0.0,
        "unique_sessions_with_chat_requested": 0,
        "unique_sessions_with_chat_replied": 0,
        "unique_sessions_with_lead_delivery_requested": 0,
        "unique_sessions_with_lead_created": 0,
        "unique_sessions_with_lead_delivery_completed": 0,
        "session_reply_rate": 0.0,
        "session_lead_creation_rate": 0.0,
        "session_delivery_completion_rate": 0.0,
    }
