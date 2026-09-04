"""crypto_utils.py — cifrado de PII centralizado para el agente Taller Mecánico.

Todo módulo que lea o escriba clientes.{nombre,telefono,email,direccion}
pasa por aquí — ningún módulo futuro (agenda, inventario, crm, ni los
agentes de hitos 3+) debe implementar su propia lógica de cifrado. Ver
README_taller_mecanico.md, sección "Cifrado de PII".

Dos primitivas, con propósitos distintos y claves independientes:

- encrypt/decrypt: Fernet (AES-128-CBC + HMAC-SHA256, autenticado). NO es
  determinista — el mismo valor produce un token distinto cada vez. Sirve
  para poder recuperar el dato original, no para buscarlo por igualdad.
- hash_for_lookup: HMAC-SHA256 determinista, con una clave DIFERENTE de
  la de Fernet. El mismo valor produce siempre el mismo hash — esto es
  lo que permite un UNIQUE/búsqueda por igualdad (telefono_hash) sin
  guardar el teléfono en claro ni depender de un cifrado no determinista
  que rompería esa restricción.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken  # noqa: F401 (re-exportado para llamadores)
from dotenv import load_dotenv

load_dotenv(override=False)


class CryptoConfigError(RuntimeError):
    """Falta o es inválida una variable de entorno de cifrado requerida."""


_fernet_cache: dict[str, Fernet] = {}


def _fernet() -> Fernet:
    key = os.environ.get("TALLER_MECANICO_FERNET_KEY")
    if not key:
        raise CryptoConfigError(
            "TALLER_MECANICO_FERNET_KEY no está definida. Generarla con:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    # Cacheado por valor de clave (no @lru_cache sin argumentos): los
    # tests rotan TALLER_MECANICO_FERNET_KEY vía monkeypatch.setenv entre
    # casos, y un cache que ignorase la clave devolvería el Fernet de una
    # ejecución anterior tras la rotación.
    cached = _fernet_cache.get(key)
    if cached is not None:
        return cached
    try:
        fernet = Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise CryptoConfigError(f"TALLER_MECANICO_FERNET_KEY inválida: {exc}") from exc
    _fernet_cache.clear()  # una sola clave activa a la vez, no acumular
    _fernet_cache[key] = fernet
    return fernet


def _hmac_key() -> bytes:
    key = os.environ.get("TALLER_MECANICO_HMAC_KEY")
    if not key:
        raise CryptoConfigError(
            "TALLER_MECANICO_HMAC_KEY no está definida. Generarla con:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    return key.encode("utf-8")


def encrypt(value: str) -> str:
    """Cifra un valor de texto plano. Devuelve un token Fernet (str ASCII)."""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Descifra un token Fernet.

    Lanza `cryptography.fernet.InvalidToken` si la clave no coincide, el
    token fue manipulado, o ni siquiera es ASCII válido (un token Fernet
    real siempre lo es; un valor corrupto con bytes no-ASCII es tan
    inválido como uno con la firma HMAC rota, y debe fallar de la misma
    forma para que el llamador solo necesite capturar una excepción) —
    nunca devuelve un valor parcial o adivinado.
    """
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidToken(f"Token no es ASCII válido: {exc}") from exc
    return _fernet().decrypt(token_bytes).decode("utf-8")


def hash_for_lookup(value: str) -> str:
    """HMAC-SHA256 (hex) determinista de `value`, para UNIQUE/búsqueda por igualdad.

    No aplica ninguna normalización de formato de teléfono (espacios,
    prefijo +34, guiones...) más allá de un `strip()` — dos
    representaciones distintas del mismo número producirán hashes
    distintos. La normalización de formato, si hace falta, es
    responsabilidad del módulo llamante (crm.py) antes de invocar esto.
    """
    normalized = value.strip()
    return hmac.new(_hmac_key(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
