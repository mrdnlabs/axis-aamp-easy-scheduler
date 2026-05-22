"""End-to-end hardware test against the speaker at 192.168.1.220.

Phases:
  A: Inspect (read-only baseline)
  B: Authenticate with existing creds (root/pass)
  C: ACAP install (manual: resolve_eap -> upload -> start)
  D: Param config (manual: param_list -> param_set -> verify)
  E: Factory default (destructive — wipes ACAP, creds, settings)
  F: Wait for reboot; confirm needs_initial_setup
  G: Full re-provision via onboard_axis_device()

Phase G uses .aamp_credentials, so we mutate that file with our test
default password ('pass') temporarily and restore afterward.

Output is tagged with phase letters for easy log scanning.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aamp import acap as _acap
from aamp.config import AampConfig, load_config
from aamp.device import AuthState, AxisDevice, VapixError
from aamp.onboard import onboard_device

IP = "192.168.1.220"
USER = "root"
PW = "pass"

def my_lan_ip() -> str:
    """Get this machine's LAN IP from the device's perspective."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 1))
        return s.getsockname()[0]


def log(phase: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{phase}] {msg}", flush=True)


def wait_until_reachable(ip: str, *, timeout: float = 180.0, interval: float = 3.0) -> bool:
    """Poll ``is_reachable()`` until the device answers or timeout."""
    deadline = time.monotonic() + timeout
    last_status = ""
    while time.monotonic() < deadline:
        try:
            with AxisDevice(ip=ip) as d:
                if d.is_reachable():
                    return True
            status = "no response yet"
        except Exception as e:
            status = f"{type(e).__name__}"
        if status != last_status:
            log("WAIT", f"  ...{status}; remaining {int(deadline - time.monotonic())}s")
            last_status = status
        time.sleep(interval)
    return False


def wait_until_unreachable(ip: str, *, timeout: float = 30.0, interval: float = 1.0) -> None:
    """Poll until the device stops responding (post-reboot trigger)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with AxisDevice(ip=ip) as d:
                reach = d.is_reachable()
        except Exception:
            reach = False
        if not reach:
            log("WAIT", f"  device offline (confirmed)")
            return
        time.sleep(interval)
    log("WAIT", f"  device still reachable after {timeout}s — proceeding anyway")


# ===========================================================================
# Phase A: unauthenticated inspect
# ===========================================================================
log("A", "===== Phase A: pre-test inspection (unauthenticated) =====")
with AxisDevice(ip=IP) as dev:
    info = dev.inspect()
log("A", f"reachable={info.get('reachable')}")
log("A", f"  needs_initial_setup={info.get('needs_initial_setup')}")
bi = info.get("basic_info") or {}
log("A", f"  model={bi.get('model_nbr')!r}  fw={bi.get('firmware_version')!r}  "
      f"arch={bi.get('architecture')!r}")
if not bi or not bi.get("model_nbr"):
    log("A", "  (basic_info empty unauthenticated — expected on AXIS OS 12+; "
              "Phase B will re-fetch with auth)")

# ===========================================================================
# Phase B: auth with root/pass + re-fetch model/arch using authenticated path
# ===========================================================================
log("B", "===== Phase B: authenticate with existing creds =====")
with AxisDevice(ip=IP, user=USER, password=PW) as dev:
    state, pw_used = dev.try_authenticate([PW], user=USER)
    log("B", f"auth state={state.value!r}  pw_used={'***' if pw_used else None}")
    if state != AuthState.OK:
        log("B", f"FAILED — cannot proceed.")
        sys.exit(1)
    log("B", "auth OK, re-fetching basic_info via authenticated path")
    bi = dev.basic_info()
log("B", f"  model={bi.get('model_nbr')!r} ({bi.get('model_full')!r})")
log("B", f"  serial={bi.get('serial')!r}  fw={bi.get('firmware_version')!r}")
log("B", f"  architecture={bi.get('architecture')!r}")

# Save model + arch for later phases
model = bi.get("model_nbr") or bi.get("model") or "(unknown)"
arch = bi.get("architecture")
if not arch:
    log("B", f"FAILED: still no architecture info after auth; cannot pick .eap")
    sys.exit(1)
log("B", f"will use model={model!r}, arch={arch!r} for the rest of the test")

# ===========================================================================
# Phase C: ACAP install
# ===========================================================================
log("C", "===== Phase C: ACAP install =====")
with AxisDevice(ip=IP, user=USER, password=PW) as dev:
    apps_before = dev.list_applications()
    log("C", f"installed apps BEFORE: {[a.get('Name') for a in apps_before]}")
    for a in apps_before:
        log("C", f"  {a.get('Name')!r:25s} v{a.get('Version')!r:10s} status={a.get('Status')!r}")

    # Resolve the right eap. ALWAYS prefer the device-reported architecture
    # (from basic_info) over the MODEL_ARCH_TABLE heuristic — the table has
    # been wrong (C1110-E was tagged armv7hf when it's actually aarch64).
    eap = _acap.resolve_eap(model, arch_override=arch)
    log("C", f"resolved eap (arch={arch!r} from device): {eap.name}")

    existing = next((a for a in apps_before if a.get("Name") == "AudioManagerPro"), None)
    if existing:
        log("C", f"AudioManagerPro already installed (v{existing.get('Version')}); "
              f"skipping upload — testing start path only")
    else:
        log("C", f"uploading {eap.name} ({eap.stat().st_size // 1024} KiB)...")
        upload_t0 = time.monotonic()
        try:
            body = dev.upload_acap(eap)
            log("C", f"upload OK in {time.monotonic()-upload_t0:.1f}s; response: {body[:200]!r}")
        except VapixError as e:
            log("C", f"upload FAILED: {e}")
            raise

    # Wait a moment for the ACAP to register, then check and start
    time.sleep(2.0)
    apps_after_upload = dev.list_applications()
    log("C", f"installed apps AFTER upload: {[a.get('Name') for a in apps_after_upload]}")
    aampro = next((a for a in apps_after_upload if a.get("Name") == "AudioManagerPro"), None)
    if aampro is None:
        log("C", f"WARNING: AudioManagerPro not in list after upload; trying start anyway")
    else:
        log("C", f"AudioManagerPro present: v{aampro.get('Version')} status={aampro.get('Status')}")

    if not aampro or aampro.get("Status", "").lower() != "running":
        log("C", f"starting AudioManagerPro...")
        try:
            res = dev.start_application("AudioManagerPro")
            log("C", f"start OK: {res!r}")
        except VapixError as e:
            msg = str(e).lower()
            if "already" in msg or "running" in msg:
                log("C", f"already running (OK): {e}")
            else:
                log("C", f"start FAILED: {e}")
                raise

    # Final state
    time.sleep(1.0)
    apps_final = dev.list_applications()
    aampro_final = next((a for a in apps_final if a.get("Name") == "AudioManagerPro"), None)
    log("C", f"FINAL: AudioManagerPro v{aampro_final.get('Version') if aampro_final else '?'} "
          f"status={aampro_final.get('Status') if aampro_final else '?'}")

# ===========================================================================
# Phase D: param config
# ===========================================================================
log("D", "===== Phase D: configure AAM Pro server param =====")
target_host = my_lan_ip()
log("D", f"AAM Pro server IP (this machine): {target_host}")

with AxisDevice(ip=IP, user=USER, password=PW) as dev:
    # Wait for ACAP to register its parameter group
    log("D", "waiting 3s for ACAP to register paramgroup...")
    time.sleep(3.0)

    params_before = dev.param_list("AudioManagerPro")
    log("D", f"AudioManagerPro params BEFORE ({len(params_before)} keys):")
    for k, v in sorted(params_before.items()):
        log("D", f"  {k} = {v!r}")

    # Verified 2026-05-21 against C1110-E firmware 12.9.57: keys are
    # returned with a "root." prefix, e.g. root.AudioManagerPro.PrimaryServerIpAddress.
    # The .eap manifest documents the leaf name (PrimaryServerIpAddress); the
    # actual param.cgi list output includes the root. group prefix.
    key_candidates = [
        "root.AudioManagerPro.PrimaryServerIpAddress",
        "AudioManagerPro.PrimaryServerIpAddress",
        "root.AudioManagerPro.PrimaryServer.Address",
        "AudioManagerPro.PrimaryServer.Address",
    ]
    chosen_key = next((k for k in key_candidates if k in params_before), None)
    if chosen_key is None:
        # Probe-style fallback
        chosen_key = next(
            (k for k in params_before
             if "PrimaryServer" in k and ("IpAddress" in k or k.endswith(".Address"))),
            None,
        )
    log("D", f"chosen server-pointer key: {chosen_key!r}")
    if chosen_key is None:
        log("D", "FAILED: no plausible server-pointer key found")
        raise SystemExit(2)

    current_val = params_before.get(chosen_key, "")
    log("D", f"current value: {current_val!r}; setting to {target_host!r}")
    try:
        res = dev.param_set({chosen_key: target_host})
        log("D", f"param_set returned: {res!r}")
    except VapixError as e:
        log("D", f"param_set FAILED: {e}")
        raise

    # Verify
    params_after = dev.param_list("AudioManagerPro")
    actual = params_after.get(chosen_key, "")
    log("D", f"verified value: {actual!r}  {'OK' if actual == target_host else 'MISMATCH'}")

# ===========================================================================
# Phase E: factory default
# ===========================================================================
log("E", "===== Phase E: factory default =====")
log("E", "WARNING: this wipes ACAP + credentials. Proceeding (user authorized).")
with AxisDevice(ip=IP, user=USER, password=PW) as dev:
    try:
        res = dev.factory_default(hard=True)
        log("E", f"factory_default returned: {res!r}")
    except VapixError as e:
        log("E", f"factory_default returned with exception (often normal): {e}")

log("E", "device should now be rebooting; waiting for it to go offline...")
wait_until_unreachable(IP, timeout=30.0)

# ===========================================================================
# Phase F: wait for reboot, confirm needs_initial_setup
# ===========================================================================
log("F", "===== Phase F: wait for device to come back =====")
log("F", "polling for reachability (typical: 60-90s)...")
t0 = time.monotonic()
if not wait_until_reachable(IP, timeout=240.0):
    log("F", "FAILED: device did not come back online within 240s")
    raise SystemExit(3)
log("F", f"device back online after {time.monotonic()-t0:.0f}s")

# Give the device an extra moment to fully initialize systemready
time.sleep(5.0)

with AxisDevice(ip=IP) as dev:
    info = dev.inspect()
log("F", f"reachable={info.get('reachable')}")
log("F", f"  needs_initial_setup={info.get('needs_initial_setup')}")
log("F", f"  basic_info: model={(info.get('basic_info') or {}).get('model_nbr')!r} "
      f"fw={(info.get('basic_info') or {}).get('firmware_version')!r}")

if not info.get("needs_initial_setup"):
    log("F", "WARNING: device says needs_initial_setup=False after factory reset")
    log("F", "  This may mean: (a) factory reset didn't actually wipe creds, or")
    log("F", "                  (b) this firmware doesn't expose needs_initial_setup")
    log("F", "  Will still attempt create_root in Phase G as a sanity check.")
else:
    log("F", "  confirmed: device is in needs_initial_setup state")

# ===========================================================================
# Phase G: full re-provision via onboard_axis_device()
# ===========================================================================
log("G", "===== Phase G: re-provision via onboard_axis_device() =====")

# Temporarily set the credentials file so onboard_axis_device can find them.
# We restore at the end.
creds_path = Path(__file__).resolve().parent.parent / ".aamp_credentials"
original_creds = creds_path.read_text(encoding="utf-8") if creds_path.exists() else None
try:
    # Read the existing file and patch in the device password fields.
    lines = (original_creds or "").splitlines()
    out_lines = []
    saw_pw = saw_user = saw_cands = False
    for line in lines:
        if line.startswith("AAMP_DEVICE_DEFAULT_PASSWORD="):
            out_lines.append(f"AAMP_DEVICE_DEFAULT_PASSWORD={PW}")
            saw_pw = True
        elif line.startswith("AAMP_DEVICE_DEFAULT_USER="):
            out_lines.append(f"AAMP_DEVICE_DEFAULT_USER={USER}")
            saw_user = True
        elif line.startswith("AAMP_DEVICE_PASSWORD_CANDIDATES="):
            out_lines.append(f"AAMP_DEVICE_PASSWORD_CANDIDATES={PW}")
            saw_cands = True
        else:
            out_lines.append(line)
    if not saw_pw:
        out_lines.append(f"AAMP_DEVICE_DEFAULT_PASSWORD={PW}")
    if not saw_user:
        out_lines.append(f"AAMP_DEVICE_DEFAULT_USER={USER}")
    if not saw_cands:
        out_lines.append(f"AAMP_DEVICE_PASSWORD_CANDIDATES={PW}")
    creds_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    log("G", f"patched .aamp_credentials with test creds (user={USER}, pw=***)")

    cfg = load_config(require_password=True)
    log("G", f"cfg.device_default_user={cfg.device_default_user!r}")
    log("G", f"cfg.device_password_candidates={['***']*len(cfg.device_password_candidates)}")
    log("G", f"running onboard_device({IP}, dry_run=False)...")
    result = onboard_device(IP, dry_run=False, cfg=cfg)
    log("G", f"OVERALL: {result.overall}")
    for s in result.steps:
        log("G", f"  [{s.status}] {s.name}: {s.detail}")
        if s.error:
            log("G", f"    error: {s.error}")
finally:
    # Restore the credentials file. The user can choose later whether to
    # keep the test creds or not.
    if original_creds is not None:
        creds_path.write_text(original_creds, encoding="utf-8")
        log("G", "restored .aamp_credentials to its prior contents")

log("DONE", "===== All phases complete =====")
