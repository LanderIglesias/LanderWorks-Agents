from backend.agents.scaffold_web_agent.domain import SessionState, Step
from backend.agents.scaffold_web_agent.engine import handle_user_message


def test_confirm_yes_moves_to_send_step():
    s = SessionState()
    s, _ = handle_user_message(s, "Hi")
    s, _ = handle_user_message(s, "buyer@company.com")
    s, _ = handle_user_message(s, "Need shipping lead time to Bilbao port")
    s, _ = handle_user_message(s, "Cuplock, 2 containers, deadline this week, Spain.")

    assert s.step == Step.CONFIRM
    s, _ = handle_user_message(s, "YES")
    assert s.step == Step.SEND
