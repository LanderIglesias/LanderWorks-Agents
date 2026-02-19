from __future__ import annotations

import json
import smtplib
import socket
import urllib.request
from email.message import EmailMessage

from .config import settings


def send_handoff_to_sheets(payload: dict) -> bool:
    url = (settings.SHEETS_WEBHOOK_URL or "").strip()
    secret = (settings.SHEETS_WEBHOOK_SECRET or "").strip()
    if not url or not secret:
        print("[SHEETS] disabled: missing webhook config")
        return False

    payload = dict(payload)
    payload["secret"] = secret

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "dental-agent/1.0"},
        method="POST",
    )

    # Apps Script a veces tarda (cold start). Dale margen + reintentos.
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read() or b""
                text = raw.decode("utf-8", errors="replace")
                ok = 200 <= resp.status < 300
                print(f"[SHEETS] attempt={attempt} status={resp.status} ok={ok} body={text[:500]}")
                return ok
        except TimeoutError as e:
            print(f"[SHEETS] attempt={attempt} TIMEOUT: {e}")
        except Exception as e:
            print(f"[SHEETS] attempt={attempt} ERROR: {type(e).__name__}: {e}")

    return False


def _smtp_connect_ipv4_first(host: str, port: int, timeout: int = 10) -> smtplib.SMTP:
    host = (host or "").strip()
    port_i = int(port)
    if not host:
        raise ValueError("SMTP_HOST vacío")

    infos = socket.getaddrinfo(
        host,
        port_i,
        type=socket.SOCK_STREAM,
    )

    # Ordena: IPv4 primero (AF_INET), luego IPv6 (AF_INET6)
    infos.sort(key=lambda x: 0 if x[0] == socket.AF_INET else 1)

    last_err: Exception | None = None
    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        try:
            s = smtplib.SMTP(timeout=timeout)
            # sockaddr: (ip, port) en IPv4; (ip, port, flow, scope) en IPv6
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
        s = _smtp_connect_ipv4_first(host, port, timeout=2)
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
