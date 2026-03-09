from backend.apps.scaffold_web_agent.domain import SessionState, Status, Step
from backend.apps.scaffold_web_agent.engine import handle_user_message


def test_happy_path_reaches_confirm():
    s = SessionState()
    s, r = handle_user_message(s, "Hello")
    assert s.step == Step.COLLECT_CONTACT

    s, r = handle_user_message(s, "buyer@company.com")
    assert s.step == Step.COLLECT_CASE

    s, r = handle_user_message(s, "We need a quotation FOB Ningbo, MOQ?")
    assert s.step == Step.COLLECT_CASE
    assert s.data.category is not None

    s, r = handle_user_message(s, "Ringlock, 1000 sqm, delivery Spain, need in 2 weeks.")
    assert s.step == Step.CONFIRM
    assert s.data.status == Status.READY_TO_SEND
    assert s.data.summary is not None
