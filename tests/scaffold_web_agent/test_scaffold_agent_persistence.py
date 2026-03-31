from backend.agents.scaffold_web_agent.engine import handle_user_message
from backend.agents.scaffold_web_agent.sqlite_store import SQLiteSessionStore


def test_session_persists_between_requests(tmp_path, monkeypatch):
    # Redirect DB to tmp folder for test isolation
    import backend.agents.scaffold_web_agent.sqlite_store as ss

    monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "scaffold.db")

    store = SQLiteSessionStore()
    tenant_id = "t1"
    sid = "s1"

    st = store.get(tenant_id, sid)
    st, _ = handle_user_message(st, "Hello")
    store.set(tenant_id, sid, st)

    st2 = store.get(tenant_id, sid)
    assert st2.step == st.step

    st2, _ = handle_user_message(st2, "buyer@company.com")
    store.set(tenant_id, sid, st2)

    st3 = store.get(tenant_id, sid)
    assert st3.data.email == "buyer@company.com"
