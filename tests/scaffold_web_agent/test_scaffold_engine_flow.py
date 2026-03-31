from backend.agents.scaffold_web_agent.domain import SessionState, Step
from backend.agents.scaffold_web_agent.engine import handle_user_message


def test_engine_preserves_initial_topic_and_does_not_repeat_question():
    state = SessionState()

    state, reply = handle_user_message(state, "I need a quotation for scaffolding")
    assert state.step == Step.COLLECT_CONTACT
    assert state.data.topic == "I need a quotation for scaffolding"
    assert "what’s your email" in reply.lower()

    state, reply = handle_user_message(state, "demo@company.com")
    assert state.step == Step.COLLECT_CASE
    assert "key details" in reply.lower()
    assert "what do you need help with?" not in reply.lower()

    state, reply = handle_user_message(
        state,
        "Ringlock scaffolding, 200m2, delivery to France, needed in 3 weeks",
    )
    assert state.step == Step.CONFIRM
    assert "i’m going to send this summary" in reply.lower()
    assert "Ringlock scaffolding, 200m2, delivery to France, needed in 3 weeks" in reply
