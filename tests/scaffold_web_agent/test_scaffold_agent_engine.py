from backend.agents.scaffold_web_agent.domain import SessionState, Step
from backend.agents.scaffold_web_agent.engine import handle_user_message


def test_happy_path_reaches_confirm():
    s = SessionState()
    s, r = handle_user_message(s, "Hello")
    assert s.step == Step.COLLECT_CONTACT

    s, r = handle_user_message(s, "buyer@company.com")
    assert s.step == Step.COLLECT_CASE

    s, r = handle_user_message(s, "We need a quotation FOB Ningbo, MOQ?")
    assert s.step == Step.CONFIRM
    assert "I’m going to send this summary" in r
