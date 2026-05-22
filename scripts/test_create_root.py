"""Diagnostic: probe create_root against the now-factory-defaulted 192.168.1.220.

Tries the configured 'pass' password first; if rejected, reports the
exact response body. Useful for figuring out password-complexity rules
on modern Axis firmware.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx
from aamp.device import AxisDevice, VapixError

IP = "192.168.1.220"

def probe_pwdgrp(pw: str, *, user: str = "root") -> tuple[int, str]:
    """Call /axis-cgi/pwdgrp.cgi directly with the given password; return (status, body)."""
    url = f"http://{IP}/axis-cgi/pwdgrp.cgi"
    params = {
        "action": "add",
        "user": user,
        "pwd": pw,
        "grp": "root",
        "sgrp": "admin:operator:viewer:ptz",
    }
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(url, params=params)
        return r.status_code, (r.text or "").strip()
    except httpx.HTTPError as e:
        return 0, f"{type(e).__name__}: {e}"


# 1. Confirm device is in needs_setup state
print("--- baseline ---")
with AxisDevice(ip=IP) as dev:
    info = dev.inspect()
print(f"reachable={info.get('reachable')}  needs_initial_setup={info.get('needs_initial_setup')}")
print(f"system_ready={info.get('system_ready')}")

# 2. Try a few passwords, from weakest to strongest, to find the policy.
candidates = [
    ("pass", "4-char lowercase only (user-requested)"),
    ("Pass1234", "8-char mixed (typical minimum)"),
    ("Axis1234!", "9-char with special char"),
    ("AxisAdmin2026!", "stronger; meets typical 12+ rules"),
]

for pw, descr in candidates:
    print(f"\n--- pwdgrp.cgi with pw={pw!r} ({descr}) ---")
    status, body = probe_pwdgrp(pw)
    print(f"  status={status}  body[:300]={body[:300]!r}")
    if status == 200 and not body.lower().startswith(("error", "# error")):
        print(f"  -> SUCCESS with pw={pw!r}")
        print(f"  -> Verifying we can now authenticate with that password...")
        time.sleep(2)
        with AxisDevice(ip=IP, user="root", password=pw) as dev:
            try:
                from aamp.device import AuthState
                state, _ = dev.try_authenticate([pw], user="root")
                print(f"  -> try_authenticate returned: {state.value!r}")
                if state == AuthState.OK:
                    bi = dev.basic_info()
                    print(f"  -> basic_info: model={bi.get('model_nbr')!r} fw={bi.get('firmware_version')!r}")
            except Exception as e:
                print(f"  -> auth probe failed: {type(e).__name__}: {e}")
        sys.exit(0)

print("\nAll passwords were rejected. Device is still in needs_setup state.")
print("You'll need to provide a stronger password or manually set one via the web UI.")
sys.exit(1)
