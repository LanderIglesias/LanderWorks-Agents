from .agent import respond
from .tools import clasifica_intencion, clasifica_urgencia


def route(message: str, sender: str | None = None) -> tuple[str, list[str], dict]:
    """
    Wrapper estable: unifica el comportamiento.
    Devuelve (reply, sources, trace) para el webhook de Twilio,
    pero la lógica real vive en agent.respond().
    """
    intent = clasifica_intencion(message)
    urg = clasifica_urgencia(message)
    trace = {"intent": intent, "urgency": urg}

    reply, sources = respond(message, sender=sender)
    return reply, sources, trace
