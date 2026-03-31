import re

EURO = re.compile(r"(?:\d{1,3}(?:[.\s]\d{3})*|\d+)\s*(?:€|eur|euros)", re.I)


def _asked_price(msg: str) -> bool:
    m = msg.lower()
    return any(k in m for k in ["precio", "vale", "cuánto", "coste", "costaría", "presupuesto"])


def validate_prices_and_sources(user_msg: str, reply: str, sources: list[str]) -> bool:
    # si preguntan por precio, exige cifra o "desde" y al menos una fuente
    if not _asked_price(user_msg):
        return True
    has_number = bool(re.search(r"\d", reply)) or ("desde" in reply.lower())
    has_source = bool(sources)
    return has_number and has_source
