from pydantic import BaseModel


class ChatIn(BaseModel):
    sender: str | None = None
    user: str


class ChatOut(BaseModel):
    reply: str
    sources: list[str] = []


class Lead(BaseModel):
    nombre: str | None = None
    telefono: str | None = None
    motivo: str | None = None
    urgencia: str | None = None
    tratamiento: str | None = None
