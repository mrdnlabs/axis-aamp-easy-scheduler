"""PostgreSQL connection helper for the AXIS Audio Manager Pro database.

Reads credentials from AAM Pro's plaintext INI file. The DB listens on
localhost only, so we are not exposing the password to the network — but we
still treat it as a secret in our own logs and tool outputs.
"""

from __future__ import annotations

import configparser
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg

DEFAULT_INI_PATH = Path(
    r"C:\ProgramData\AXIS Communications\AXIS Audio Manager Pro\Manager\AamPro.ini"
)


class CredentialsError(RuntimeError):
    """Raised when we can't read the AAM Pro PostgreSQL credentials."""


def read_credentials(ini_path: Path | str | None = None) -> dict[str, str]:
    """Load DB connection params from AamPro.ini.

    Returns a dict with keys: host, port, dbname, user, password.
    Override the path with the ``AAMP_INI_PATH`` environment variable or by
    passing ``ini_path`` explicitly (useful for tests / fixtures).
    """
    path = Path(ini_path or os.environ.get("AAMP_INI_PATH") or DEFAULT_INI_PATH)
    if not path.exists():
        raise CredentialsError(f"AamPro.ini not found at {path}")
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if "PostgreSQL" not in parser:
        raise CredentialsError(f"No [PostgreSQL] section in {path}")
    pg = parser["PostgreSQL"]
    try:
        return {
            "host": pg["Addr"],
            "port": pg["Port"],
            "dbname": pg["DbName"],
            "user": pg["User"],
            "password": pg["Password"],
        }
    except KeyError as e:
        raise CredentialsError(f"Missing key {e!s} in [PostgreSQL] section") from e


def connection_string(creds: dict[str, str] | None = None) -> str:
    """Build a libpq-style connection string."""
    c = creds or read_credentials()
    # Use keyword/value form so the password can contain special chars without URL-encoding.
    return (
        f"host={c['host']} port={c['port']} dbname={c['dbname']} "
        f"user={c['user']} password={c['password']}"
    )


@contextmanager
def connect(*, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection. Safe in a ``with`` block."""
    conn = psycopg.connect(connection_string(), autocommit=autocommit)
    try:
        yield conn
    finally:
        conn.close()


def dict_rows(cursor: psycopg.Cursor) -> list[dict]:
    """Convert a cursor's results into a list of column-name dicts."""
    cols = [d.name for d in cursor.description] if cursor.description else []
    return [dict(zip(cols, row)) for row in cursor.fetchall()]
