from backend.apps.scaffold_web_agent.sqlite_store import insert_event, list_events_for_tenant


def test_insert_event_and_list_events_for_tenant(test_db):
    session_id = "sess-event-persistence-001"

    insert_event(
        tenant_id="tenant-a",
        session_id=session_id,
        event_type="chat_requested",
        event_payload={"message_length": 4},
    )

    events = list_events_for_tenant("tenant-a", limit=100)

    matching = [event for event in events if event["session_id"] == session_id]

    assert matching, "Expected at least one event for the inserted session_id"

    event = matching[0]
    assert event["tenant_id"] == "tenant-a"
    assert event["session_id"] == session_id
    assert event["event_type"] == "chat_requested"
    assert '"message_length": 4' in event["event_payload_json"]
