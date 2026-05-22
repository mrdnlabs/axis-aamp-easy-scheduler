"""Smoke test the OAuth flow against the running AAM Pro.

Reads credentials from environment / .aamp_credentials file.
Runs the full login dance, then hits one authenticated endpoint to confirm
the bearer token is accepted.

NEVER prints the password or token. Prints only:
- whether each flow step succeeded
- the GET /webapi/v1/sites response (which has no secrets)
"""

from __future__ import annotations

import json
import sys

import httpx

from aamp.auth import AampAuth, AuthError
from aamp.config import load_config


def main() -> int:
    try:
        cfg = load_config()
    except RuntimeError as e:
        print(f"CONFIG: {e}")
        return 2
    print(f"Config loaded: {cfg!r}")  # password is masked in repr

    with AampAuth(cfg) as auth:
        try:
            token = auth.access_token()
        except AuthError as e:
            print(f"AUTH FAILED: {e}")
            return 1
        print(f"AUTH OK: got access token ({len(token)} chars, prefix '{token[:6]}...')")

        # Smoke endpoint: GET /webapi/v1/sites should be 200 and JSON.
        with httpx.Client(base_url=cfg.host, verify=cfg.verify_tls, timeout=10) as http:
            r = http.get("/webapi/v1/sites", headers=auth.http_headers())
        if r.status_code != 200:
            print(f"API FAILED: GET /webapi/v1/sites -> {r.status_code} {r.text[:200]}")
            return 1
        body = r.json()
        print("API OK: GET /webapi/v1/sites ->")
        print(json.dumps(body, indent=2))

        # Token refresh check — request again, should be cached.
        token2 = auth.access_token()
        print(f"Cached token identical: {token == token2}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
