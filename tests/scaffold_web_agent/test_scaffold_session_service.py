from backend.agents.scaffold_web_agent.domain import SessionState, Step
from backend.agents.scaffold_web_agent.session_service import SessionService


class DummyStore:
    def __init__(self) -> None:
        self.get_calls = []
        self.set_calls = []
        self.result = SessionState()

    def get(self, tenant_id: str, session_id: str) -> SessionState:
        self.get_calls.append((tenant_id, session_id))
        return self.result

    def set(self, tenant_id: str, session_id: str, state: SessionState) -> None:
        self.set_calls.append((tenant_id, session_id, state))


def test_session_service_get_state_delegates_to_store():
    store = DummyStore()
    service = SessionService(store=store)
    store.result.step = Step.CONFIRM

    result = service.get_state("tenant-a", "session-1")

    assert store.get_calls == [("tenant-a", "session-1")]
    assert result.step == Step.CONFIRM


def test_session_service_save_state_delegates_to_store():
    store = DummyStore()
    service = SessionService(store=store)
    state = SessionState()
    state.step = Step.DONE

    service.save_state("tenant-a", "session-1", state)

    assert len(store.set_calls) == 1
    tenant_id, session_id, saved_state = store.set_calls[0]
    assert tenant_id == "tenant-a"
    assert session_id == "session-1"
    assert saved_state is state


def test_session_service_list_for_tenant_delegates(monkeypatch):
    service = SessionService(store=DummyStore())
    expected = [
        {
            "session_id": "session-1",
            "state_json": '{"step":"confirm"}',
            "updated_at": 123456,
        }
    ]

    def fake_list_sessions_for_tenant(tenant_id: str, limit: int = 20):
        assert tenant_id == "tenant-a"
        assert limit == 7
        return expected

    monkeypatch.setattr(
        "backend.agents.scaffold_web_agent.session_service.list_sessions_for_tenant",
        fake_list_sessions_for_tenant,
    )

    result = service.list_for_tenant("tenant-a", 7)

    assert result == expected
