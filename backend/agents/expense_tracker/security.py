"""security.py — Autenticación del Expense Tracker.

Dos esquemas distintos a propósito, para dos audiencias distintas:

- `verify_webhook_signature`: protege POST /webhook/expense, que llaman las
  automatizaciones de Atajos SIN usuario presente (se disparan solas al
  pagar o al recibir un email). No cabe un login interactivo ahí. En un
  mundo ideal esto sería HMAC-SHA256 sobre el body, pero Atajos (la app de
  automatizaciones de iOS) no tiene ninguna acción nativa para calcular un
  HMAC — solo hash plano (MD5/SHA1/SHA256/SHA512), que no es lo mismo:
  construir un HMAC real requeriría una extensión nativa en Swift, fuera de
  alcance de este proyecto. El esquema real es Bearer token + timestamp:
  un secreto estático distinto del de la PWA, más la misma ventana de 60s
  para que una petición capturada no se pueda reenviar más tarde.
- `verify_app_token`: protege los endpoints que solo usa el propio usuario
  desde la PWA en el navegador (siempre hay un humano tecleando en ese
  momento), así que basta un token estático simple en Authorization, sin
  ventana de timestamp.

Ambas devuelven 401 genérico sin detallar qué falló exactamente (token
ausente vs. incorrecto, o timestamp caducado) para no darle a un atacante
información sobre qué parte de la comprobación está fallando.
"""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime

from fastapi import Header, HTTPException

TIMESTAMP_TOLERANCE_SECONDS = 60

_UNAUTHORIZED = HTTPException(status_code=401, detail="Unauthorized")


def verify_webhook_signature(
    authorization: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
) -> None:
    secret = os.getenv("EXPENSE_TRACKER_WEBHOOK_SECRET")
    if not secret or not authorization or not authorization.startswith("Bearer "):
        raise _UNAUTHORIZED

    token = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(token, secret):
        raise _UNAUTHORIZED

    if not x_timestamp or not _timestamp_within_tolerance(x_timestamp):
        raise _UNAUTHORIZED


def _timestamp_within_tolerance(raw_timestamp: str) -> bool:
    """`raw_timestamp` es ISO 8601 (ej. "2026-08-11T10:45:00Z"), no unix
    time — Atajos en iOS no tiene forma sencilla de generar un entero unix
    directamente (el patrón de formato personalizado no lo soporta como
    cabría esperar), pero sí ofrece "ISO 8601" nativo en el desplegable de
    formato de fecha. `datetime.fromisoformat` entiende el sufijo "Z" desde
    Python 3.11 (este proyecto corre en 3.12).
    """
    try:
        parsed = datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - parsed
    return abs(delta.total_seconds()) <= TIMESTAMP_TOLERANCE_SECONDS


def verify_app_token(authorization: str | None = Header(default=None)) -> None:
    """Dependencia de los endpoints que solo usa la PWA desde el navegador."""
    expected = os.getenv("EXPENSE_TRACKER_APP_TOKEN")
    if not expected or not authorization or not authorization.startswith("Bearer "):
        raise _UNAUTHORIZED

    token = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(token, expected):
        raise _UNAUTHORIZED
