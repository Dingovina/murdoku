"""Entry point: ``python -m murdoku.server`` (ARCHITECTURE §8).

Resolves the token key first so a missing ``MURDOKU_SECRET`` aborts startup
with a clear error instead of failing on the first request.
"""

import os

import uvicorn

from . import tokens
from .app import app


def main() -> None:
    tokens.get_fernet()  # fail fast: MissingSecretError before serving
    host = os.environ.get("MURDOKU_HOST", "127.0.0.1")
    port = int(os.environ.get("MURDOKU_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
