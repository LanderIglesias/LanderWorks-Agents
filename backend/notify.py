from __future__ import annotations

import smtplib
import socket
from email.message import EmailMessage

from .config import settings


def _smtp_connect_ipv4_first(host: str, port: int, timeout: int = 10) -> smtplib.SMTP:
    # Intenta IPv4 primero (Render suele no tener ruta IPv6)
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    # ordena: AF_INET primero
    infos.sort(key=lambda x: 0 if x[0] == socket.AF_INET else 1)

    last_err: Exception | None = None
    for sockaddr in infos:
        try:
            s = smtplib.SMTP(timeout=timeout)
            s.connect(sockaddr[0], sockaddr[1])
            return s
        except Exception as e:
            last_err = e

    raise last_err or OSError("SMTP connect failed")


def send_handoff_email(subject: str, body: str) -> bool:
    """
    Envía email por SMTP. Devuelve True si envía, False si está deshabilitado
    o falla (NO debe tumbar el bot).
    """
    host = (settings.SMTP_HOST or "").strip()
    user = (settings.SMTP_USER or "").strip()
    pwd = (settings.SMTP_PASS or "").strip()
    to = (settings.NOTIFY_EMAIL_TO or "").strip()

    if not (host and user and pwd and to):
        print("[EMAIL] disabled: missing SMTP config")
        return False

    from_addr = (settings.SMTP_FROM or "").strip() or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)

    try:
        port = int(settings.SMTP_PORT)
        s = _smtp_connect_ipv4_first(host, port, timeout=10)
        try:
            s.ehlo()
            if port == 587:
                s.starttls()
                s.ehlo()
            s.login(user, pwd)
            s.send_message(msg)
        finally:
            try:
                s.quit()
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"[EMAIL] ERROR sending email via SMTP: {type(e).__name__}: {e}")
        return False
