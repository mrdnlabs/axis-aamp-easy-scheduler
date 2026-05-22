"""Step 1: change root password from AxisAdmin2026! (set by diagnostic probe)
back to 'pass' (the user's original state).
Step 2: re-run the full E2E test now that create_root + param_set use GET.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx
from aamp.device import AuthState, AxisDevice

IP = "192.168.1.220"
CURRENT_PW = "AxisAdmin2026!"
TARGET_PW = "pass"

print("=== Step 1: change password from current to 'pass' ===")
# Use GET /axis-cgi/pwdgrp.cgi?action=update with auth.
auth = httpx.DigestAuth("root", CURRENT_PW)
params = {
    "action": "update",
    "user": "root",
    "pwd": TARGET_PW,
}
try:
    with httpx.Client(timeout=10.0) as c:
        r = c.get(f"http://{IP}/axis-cgi/pwdgrp.cgi", params=params, auth=auth)
    print(f"  status={r.status_code}  body[:200]={(r.text or '').strip()[:200]!r}")
    if r.status_code != 200 or "error" in (r.text or "").lower():
        print(f"  FAILED — bailing out")
        sys.exit(1)
except httpx.HTTPError as e:
    print(f"  network error: {e}")
    sys.exit(1)

print()
print("=== Step 2: verify auth works with the new password ===")
time.sleep(1)
with AxisDevice(ip=IP, user="root", password=TARGET_PW) as dev:
    state, _ = dev.try_authenticate([TARGET_PW], user="root")
    print(f"  try_authenticate -> {state.value!r}")
    if state != AuthState.OK:
        print(f"  FAILED — pass was rejected; device may have a complexity policy now")
        sys.exit(2)
    bi = dev.basic_info()
    print(f"  model={bi.get('model_nbr')!r}  fw={bi.get('firmware_version')!r}  serial={bi.get('serial')!r}")

print()
print("=== Step 3: run the full E2E test (test_device_220.py) ===")
result = subprocess.run(
    [sys.executable, str(Path(__file__).resolve().parent / "test_device_220.py")],
    capture_output=False,
)
sys.exit(result.returncode)
