"""Fernet tokens for the stateless /api/check contract (ARCHITECTURE §8).

The server hands out ``GET /api/puzzle`` responses with a token that carries
the solution and the killer id; ``POST /api/check`` decrypts the token, so no
game state is stored server-side.

Key derivation: ``urlsafe_b64encode(sha256(MURDOKU_SECRET).digest())``.

Secret resolution (per call, no caching of the derived key):

- ``MURDOKU_SECRET`` set (non-empty) -> key derived from it;
- unset and ``MURDOKU_DEV=1`` -> random per-process key (cached in the module
  global ``_dev_key`` so tokens survive within the process) + a stderr warning;
  tokens become invalid on restart;
- unset otherwise -> :class:`MissingSecretError` (the ``python -m
  murdoku.server`` entry point resolves the key first thing, so the server
  refuses to start).
"""

import json
import os
import sys
from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken as _FernetInvalidToken

SECRET_ENV = "MURDOKU_SECRET"
DEV_ENV = "MURDOKU_DEV"

# Random key used when MURDOKU_SECRET is unset and MURDOKU_DEV=1.  Cached so
# all tokens made in one process share one key (spec: per-process key).
_dev_key: bytes | None = None


class InvalidToken(Exception):
    """Token is tampered, made with a different key, or malformed."""


class MissingSecretError(RuntimeError):
    """MURDOKU_SECRET is unset and MURDOKU_DEV is not 1."""


def get_fernet() -> Fernet:
    """Resolve the Fernet instance from the environment (see module docs)."""
    global _dev_key
    secret = os.environ.get(SECRET_ENV)
    if secret:
        key = urlsafe_b64encode(sha256(secret.encode()).digest())
        return Fernet(key)
    if os.environ.get(DEV_ENV) == "1":
        if _dev_key is None:
            _dev_key = Fernet.generate_key()
            print(
                "murdoku: MURDOKU_SECRET is not set; MURDOKU_DEV=1 -> using "
                "a random per-process key (tokens become invalid on restart)",
                file=sys.stderr,
            )
        return Fernet(_dev_key)
    raise MissingSecretError(
        f"{SECRET_ENV} is not set: set it to a non-empty secret string, "
        f"or set {DEV_ENV}=1 for a throwaway per-process key (dev only)"
    )


def make_token(payload: dict) -> str:
    """Serialize ``payload`` as compact JSON and encrypt it -> token str."""
    data = json.dumps(payload, separators=(",", ":")).encode()
    return get_fernet().encrypt(data).decode()


def read_token(token: str) -> dict:
    """Decrypt and deserialize a token made by :func:`make_token`.

    Raises :class:`InvalidToken` for anything that does not decrypt with the
    current key or does not decode to a JSON object.
    """
    try:
        data = get_fernet().decrypt(token.encode())
    except _FernetInvalidToken:
        raise InvalidToken("token is invalid or tampered with") from None
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise InvalidToken("token payload is not valid JSON") from None
    if not isinstance(payload, dict):
        raise InvalidToken("token payload must be a JSON object")
    return payload
