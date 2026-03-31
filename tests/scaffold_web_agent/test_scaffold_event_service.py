from backend.agents.scaffold_web_agent.event_service import EventService


def test_event_service_record_delegates(monkeypatch):
    service = EventService()
    called = {}

    def fake_insert_event(
        tenant_id: str, session_id: str, event_type: str, event_payload: dict | None
    ):
        called["tenant_id"] = tenant_id
        called["session_id"] = session_id
        called["event_type"] = event_type
        called["event_payload"] = event_payload

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.event_service.insert_event",
        fake_insert_event,
    )

    service.record(
        tenant_id="tenant-a",
        session_id="sess-1",
        event_type="chat_requested",
        event_payload={"message_length": 4},
    )

    assert called == {
        "tenant_id": "tenant-a",
        "session_id": "sess-1",
        "event_type": "chat_requested",
        "event_payload": {"message_length": 4},
    }


def test_event_service_list_for_tenant_delegates(monkeypatch):
    service = EventService()
    expected = [
        {
            "id": 1,
            "tenant_id": "tenant-a",
            "session_id": "sess-1",
            "event_type": "chat_requested",
            "event_payload_json": '{"message_length": 4}',
            "created_at": 123456,
        }
    ]

    def fake_list_events_for_tenant(tenant_id: str, limit: int = 100):
        assert tenant_id == "tenant-a"
        assert limit == 7
        return expected

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.event_service.list_events_for_tenant",
        fake_list_events_for_tenant,
    )

    result = service.list_for_tenant("tenant-a", 7)

    assert result == expected
