"""Diagnostic v2: try multiple create-root endpoints + methods to find the
one AXIS OS 12.9 expects.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx

IP = "192.168.1.220"
PW_TRY = "AxisAdmin2026!"   # strong enough to bypass any complexity rule

# Helper: print a request + response in one line
def probe(method: str, path: str, *, params=None, json_body=None, headers=None, descr: str = "") -> None:
    url = f"http://{IP}{path}"
    print(f"\n=== {descr or method+' '+path} ===")
    print(f"  -> {method} {path}  params={params}  json={json_body}")
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.request(method, url, params=params, json=json_body, headers=headers)
        print(f"  <- status={r.status_code}  ctype={r.headers.get('content-type', '?')}")
        body = (r.text or "").strip()
        print(f"  <- body[:400]={body[:400]!r}")
    except httpx.HTTPError as e:
        print(f"  !! {type(e).__name__}: {e}")


# 1. Legacy pwdgrp.cgi via GET (what Axis docs traditionally show)
probe("GET", "/axis-cgi/pwdgrp.cgi", params={
    "action": "add", "user": "root", "pwd": PW_TRY,
    "grp": "root", "sgrp": "admin:operator:viewer:ptz",
}, descr="GET pwdgrp.cgi (legacy / Axis docs convention)")

# 2. Legacy pwdgrp.cgi via POST (what onboard.py / device.py currently uses)
probe("POST", "/axis-cgi/pwdgrp.cgi", params={
    "action": "add", "user": "root", "pwd": PW_TRY,
    "grp": "root", "sgrp": "admin:operator:viewer:ptz",
}, descr="POST pwdgrp.cgi (current code path)")

# 3. JSON-RPC user-management endpoint (newer Axis OS 11.6+ style)
probe("POST", "/axis-cgi/user-management/v1.cgi", json_body={
    "apiVersion": "1.0",
    "method": "createUser",
    "params": {
        "username": "root",
        "password": PW_TRY,
        "roles": ["admin", "operator", "viewer", "ptz"],
    },
}, descr="POST user-management JSON-RPC (createUser)")

# 4. Alternative path
probe("POST", "/axis-cgi/usergroup/v1.cgi", json_body={
    "apiVersion": "1.0",
    "method": "createUser",
    "params": {
        "username": "root",
        "password": PW_TRY,
    },
}, descr="POST usergroup/v1.cgi (createUser)")

# 5. AXIS OS 11.6+ "initial setup" endpoint
probe("POST", "/axis-cgi/initial-setup.cgi", json_body={
    "apiVersion": "1.0",
    "method": "setRootPassword",
    "params": {"password": PW_TRY},
}, descr="POST initial-setup.cgi (modern OS, setRootPassword)")

# 6. List of API discovery — many Axis devices expose /axis-cgi/apidiscovery.cgi
probe("POST", "/axis-cgi/apidiscovery.cgi", json_body={
    "apiVersion": "1.0",
    "method": "getApiList",
}, descr="POST apidiscovery.cgi getApiList")

# 7. List of API discovery via GET
probe("GET", "/axis-cgi/apidiscovery.cgi", params={"apiVersion": "1.0", "method": "getApiList"},
      descr="GET apidiscovery.cgi getApiList (legacy)")
