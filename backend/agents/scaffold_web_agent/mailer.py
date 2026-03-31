from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.email.resend_mailer import ResendMailer, load_resend_mailer


class Mailer(Protocol):
    def send(self, to_email: str, subject: str, body: str) -> None: ...


@dataclass
class ResendAdapterMailer:
    resend: ResendMailer

    def send(self, to_email: str, subject: str, body: str) -> None:
        # We send as plain text for now (stable + readable)
        self.resend.send(to_email=to_email, subject=subject, text=body)


class FakeMailer:
    def __init__(self) -> None:
        self.sent = []  # list of tuples (to, subject, body)

    def send(self, to_email: str, subject: str, body: str) -> None:
        self.sent.append((to_email, subject, body))


def load_prod_mailer() -> Mailer:
    return ResendAdapterMailer(load_resend_mailer())
