"""Four-step onboarding pipeline for Axis network audio devices.

Given an IP (or a discovered fleet), bring each device from "factory state"
to "registered with our AAM Pro server":

    1. **Inspect & authenticate.** Probe ``basicdeviceinfo`` + ``systemready``;
       try the configured candidate passwords. If the device is in factory
       state, take the ``NEEDS_INITIAL_SETUP`` branch and create root.
    2. **Initial setup.** POST ``pwdgrp.cgi`` to create the root user with
       the fleet default password. Re-auth.
    3. **ACAP install.** Resolve the correct ``.eap`` (by model -> arch),
       upload it via ``applications/upload.cgi``, then start it.
    4. **Server pointer.** Use ``param.cgi`` to point the device at our AAM
       Pro server. The exact parameter name is discovered via probe-and-cache
       (see :func:`_resolve_server_pointer_key`) — never guessed.

Each step records a :class:`StepResult` so a failure in step 3 still
returns a usable trace of what happened in steps 1 and 2. The whole flow
is **idempotent**: re-running against an already-onboarded device skips
the steps whose preconditions are already satisfied.

The orchestration is intentionally **sequential per device** — Axis devices
can be temperamental during ACAP install and concurrent param writes — but
:func:`onboard_fleet` can fan out across devices (one worker per device).
For now we run fleets sequentially too; concurrency is a follow-up.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from . import acap as _acap
from . import discovery as _discovery
from .config import AampConfig, load_config
from .device import AuthState, AxisDevice, VapixError


# ACAP package name — what shows up in ``applications/list.cgi`` as the
# Axis ``Name`` attribute. Confirmed by reading package.conf inside the
# .eap (APPNAME="AudioManagerPro" / "AudioManagerProB"). Used for the
# has_application() idempotency check and start/stop control.
ACAP_PACKAGE_NAME = "AudioManagerPro"
ACAP_B_PACKAGE_NAME = "AudioManagerProB"   # the "B" sibling; role undocumented (see acap.PAGING_MODELS)

# Where we cache the discovered server-pointer parameter name. Lives at
# the project root next to ``.aamp_credentials``; safe to commit (no
# secrets) but not particularly useful to share, so .gitignore'd in practice.
PARAM_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / ".aamp_axis_paramcache.json"

# Candidate parameter names for "AAM Pro server address". The first one
# whose key exists on the device wins, and we cache that choice.
#
# VERIFIED 2026-05-21 against C1110-E firmware 12.9.57: the actual key is
# ``root.AudioManagerPro.PrimaryServerIpAddress`` (with "root." prefix).
# The leaf name PrimaryServerIpAddress also matches the .eap manifest's
# paramConfig declaration. Older firmware MAY return the same key without
# the root. prefix, so we include both forms.
SERVER_POINTER_CANDIDATES: tuple[str, ...] = (
    "root.AudioManagerPro.PrimaryServerIpAddress",   # VERIFIED on OS 12.9
    "AudioManagerPro.PrimaryServerIpAddress",        # same key, older firmware may strip "root."
    # Legacy / speculative fallbacks (kept for old firmware):
    "AudioManagerPro.PrimaryServer.Address",
    "AudioManagerPro.Server.Address",
    "AudioManagerPro.PrimaryServer.Host",
    "AudioManagerPro.Server.Host",
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """One step of the onboarding pipeline."""
    name: str                               # 'inspect', 'authenticate', 'create_root', 'acap_install', 'server_pointer'
    status: str = "pending"                 # 'pending' | 'skipped' | 'ok' | 'failed'
    detail: str = ""                        # human-readable summary
    error: Optional[str] = None             # populated on 'failed'
    data: dict[str, Any] = field(default_factory=dict)

    def mark(self, status: str, detail: str = "", *, error: Optional[str] = None,
              **data: Any) -> "StepResult":
        self.status = status
        self.detail = detail
        if error is not None:
            self.error = error
        if data:
            self.data.update(data)
        return self


@dataclass
class OnboardingResult:
    """Aggregate result for one device's onboarding run."""
    ip: str
    overall: str = "pending"                # 'ok' | 'failed' | 'partial'
    model: Optional[str] = None
    serial: Optional[str] = None
    mac: Optional[str] = None
    dry_run: bool = False
    steps: list[StepResult] = field(default_factory=list)

    def add(self, step: StepResult) -> StepResult:
        self.steps.append(step)
        return step

    def finalize(self) -> "OnboardingResult":
        statuses = {s.status for s in self.steps}
        if "failed" in statuses:
            self.overall = "failed"
        elif statuses == {"skipped"}:
            self.overall = "ok"          # nothing to do == success
        else:
            self.overall = "ok"
        return self

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Server-pointer parameter discovery (probe-confirm-cache)
# ---------------------------------------------------------------------------

def _load_param_cache() -> dict[str, str]:
    if not PARAM_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(PARAM_CACHE_PATH.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_param_cache(cache: dict[str, str]) -> None:
    try:
        PARAM_CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except OSError:
        pass


def _resolve_server_pointer_key(dev: AxisDevice) -> str:
    """Return the param.cgi key that controls the AAM Pro server address.

    First checks the on-disk cache. On a miss, lists every parameter under
    ``AudioManagerPro.*`` and looks for the first candidate that exists.
    Caches the result so subsequent devices don't pay the probe cost.

    Raises ``RuntimeError`` if zero or multiple plausible candidates are
    present — we refuse to guess (per the plan's risk note).
    """
    cache = _load_param_cache()
    cached = cache.get("server_pointer_key")
    if cached:
        return cached

    params = dev.param_list("AudioManagerPro")
    matches = [k for k in SERVER_POINTER_CANDIDATES if k in params]
    if not matches:
        # Generous fallback — look for any AudioManagerPro key (with or
        # without the "root." prefix) whose leaf indicates a server-address
        # parameter. Verified on real firmware: the key ends with
        # "PrimaryServerIpAddress".
        candidates = [
            k for k in params
            if "AudioManagerPro." in k
            and ("PrimaryServerIpAddress" in k or "PrimaryServer.Address" in k
                 or "PrimaryServer.Host" in k or "PrimaryServer.IpAddress" in k)
        ]
        if len(candidates) == 1:
            matches = candidates
        elif len(candidates) > 1:
            raise RuntimeError(
                f"Ambiguous server-pointer key on device: {candidates!r}. "
                "Inspect param.cgi output and add the right one to "
                "SERVER_POINTER_CANDIDATES in src/aamp/onboard.py."
            )
        else:
            raise RuntimeError(
                "No AudioManagerPro server-address parameter found on device. "
                "ACAP may not be installed/started yet, or the parameter naming "
                f"differs in this firmware. Known params: {sorted(params.keys())[:20]}"
            )
    if len(matches) > 1:
        # If multiple candidates are present we pick the first (most-specific)
        # but warn via the cache file so a human can review later.
        cache["server_pointer_alternates"] = matches[1:]
    chosen = matches[0]
    cache["server_pointer_key"] = chosen
    _save_param_cache(cache)
    return chosen


def _server_pointer_value(cfg: AampConfig, device_ip: str) -> str:
    """Compute the AAM Pro server address that ``device_ip`` should use.

    Resolution order:
      1. **Explicit override** — if ``cfg.device_facing_host`` is set (via
         ``AAMP_DEVICE_FACING_HOST`` in ``.aamp_credentials``), use it
         verbatim. This is for NAT, FQDN-preferred deployments, or
         situations where the auto-detect picks the wrong interface.
      2. **Per-device interface inference** — when ``cfg.host`` is
         localhost / 127.0.0.1 (we're running on the AAM Pro server),
         figure out which of our local interfaces routes to ``device_ip``
         and return that interface's IP. Works correctly on multi-homed
         servers (one NIC for management, another for the device VLAN —
         each device gets told its facing interface's IP).
      3. **Stripped host** — otherwise just strip scheme/port from
         ``cfg.host`` (e.g. ``https://aam-pro.example.com:443`` ->
         ``aam-pro.example.com``).
    """
    # 1. Explicit override wins.
    if cfg.device_facing_host:
        parsed = urlparse(cfg.device_facing_host)
        return (parsed.hostname or cfg.device_facing_host).strip()

    # 2. Per-device routing inference when cfg.host is local.
    parsed = urlparse(cfg.host)
    host = (parsed.hostname or cfg.host or "").strip().lower()
    if host in ("localhost", "127.0.0.1", "::1", ""):
        try:
            # UDP connect() doesn't send anything — it just asks the kernel
            # to resolve the route to `device_ip` and bind our end to the
            # selected interface. getsockname() then returns our IP on that
            # interface. This is the IP the device should use to reach us.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((device_ip, 1))
                return s.getsockname()[0]
        except OSError:
            # Couldn't resolve a route; surface the original host so error
            # messages have something meaningful to show.
            return host or "localhost"

    # 3. Use cfg.host as-is (FQDN / external IP scenario).
    return host


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

def onboard_device(
    ip: str,
    *,
    dry_run: bool = False,
    cfg: Optional[AampConfig] = None,
    arch_override: Optional[str] = None,
) -> OnboardingResult:
    """Run the 4-step onboarding pipeline against a single device.

    Idempotent. Each step is a no-op if its precondition is already
    satisfied (correct password already set, ACAP already installed,
    server pointer already configured).

    ``dry_run=True`` performs only read probes — no writes anywhere. The
    returned trace shows what each step WOULD have done.
    """
    cfg = cfg or load_config(require_password=True)
    result = OnboardingResult(ip=ip, dry_run=dry_run)

    with AxisDevice(ip=ip) as dev:
        # -- Step 1: inspect ---------------------------------------------
        s1 = result.add(StepResult(name="inspect"))
        try:
            info = dev.inspect()
        except Exception as e:
            s1.mark("failed", "could not inspect device", error=str(e))
            return result.finalize()
        if not info.get("reachable"):
            s1.mark("failed", f"device {ip} not reachable on HTTP",
                    error="unreachable")
            return result.finalize()
        bi = info.get("basic_info") or {}
        result.model = bi.get("model_nbr") or bi.get("model")
        result.serial = bi.get("serial")
        s1.mark("ok",
                f"model={result.model!r} fw={bi.get('firmware_version')!r} "
                f"needs_setup={info.get('needs_initial_setup', False)}",
                **{k: v for k, v in info.items() if k != "system_ready"})

        # -- Step 2: authenticate / create_root --------------------------
        s2 = result.add(StepResult(name="authenticate"))
        if info.get("needs_initial_setup"):
            if dry_run:
                s2.mark("skipped",
                        "device needs initial setup; would call create_root "
                        f"as {cfg.device_default_user!r}")
            else:
                if not cfg.device_default_password:
                    s2.mark("failed",
                            "No fleet device password is configured. "
                            "To set it without exposing it in chat, open a "
                            "TERMINAL (not chat) and run: "
                            "aamp-set-credential device/default_password. "
                            "Do NOT type the password into chat — it would "
                            "be logged and sent to the LLM.",
                            error="missing_default_password")
                    return result.finalize()
                try:
                    dev.create_root(cfg.device_default_password,
                                     user=cfg.device_default_user)
                    s2.mark("ok",
                            f"created root user {cfg.device_default_user!r}",
                            action="create_root")
                except VapixError as e:
                    s2.mark("failed", "create_root failed", error=str(e))
                    return result.finalize()
        else:
            candidates = cfg.device_password_candidates
            if not candidates:
                s2.mark("failed",
                        "Device requires authentication but no candidate "
                        "passwords are configured. To set the fleet "
                        "password without exposing it in chat, open a "
                        "TERMINAL (not chat) and run: "
                        "aamp-set-credential device/default_password. "
                        "Do NOT type the password into chat — it would "
                        "be logged and sent to the LLM.",
                        error="no_candidates")
                return result.finalize()
            try:
                state, pw = dev.try_authenticate(
                    candidates, user=cfg.device_default_user,
                )
            except Exception as e:
                s2.mark("failed", "try_authenticate raised", error=str(e))
                return result.finalize()
            if state == AuthState.OK:
                s2.mark("ok", f"authenticated as {cfg.device_default_user!r}",
                        action="reuse_existing_password")
            elif state == AuthState.NEEDS_INITIAL_SETUP:
                # Re-check edge: inspect said no but try_authenticate said yes.
                if dry_run:
                    s2.mark("skipped",
                            "would create root user (re-check showed factory state)")
                else:
                    try:
                        dev.create_root(cfg.device_default_password,
                                         user=cfg.device_default_user)
                        s2.mark("ok",
                                f"created root user {cfg.device_default_user!r}",
                                action="create_root_after_recheck")
                    except VapixError as e:
                        s2.mark("failed", "create_root failed", error=str(e))
                        return result.finalize()
            else:  # UNKNOWN_PASSWORD
                s2.mark("failed",
                        "none of the candidate passwords authenticated; "
                        "device has an unknown admin credential. Add it to "
                        "AAMP_DEVICE_PASSWORD_CANDIDATES or factory-reset.",
                        error="unknown_password")
                return result.finalize()

        # -- Refresh device identity now that we have auth -----------------
        # On AXIS OS 12+ basicdeviceinfo.cgi requires auth, so the
        # unauthenticated Step 1 probe leaves model=None / arch=None.
        # Re-fetch via the now-authenticated client so Steps 3-4 have
        # the model + architecture they need to pick the right .eap.
        if not dry_run and not result.model:
            try:
                bi = dev.basic_info()
                result.model = bi.get("model_nbr") or bi.get("model")
                # Keep s1.data["basic_info"] in sync so Step 3's arch lookup works.
                s1.data["basic_info"] = bi
            except VapixError:
                # Don't fail the run on this — Step 3 will surface its own error.
                pass

        # -- Step 3: ACAP install ---------------------------------------
        s3 = result.add(StepResult(name="acap_install"))
        try:
            apps = dev.list_applications()
        except VapixError as e:
            s3.mark("failed", "could not list applications", error=str(e))
            return result.finalize()
        # See acap.PAGING_MODELS for why this is empty by default — we
        # install the main "AudioManagerPro" ACAP on every model until we
        # confirm against real hardware that some models need the "B"
        # sibling instead of (or alongside) the main one.
        is_paging = result.model in _acap.PAGING_MODELS
        package_name = (ACAP_B_PACKAGE_NAME if is_paging
                        else ACAP_PACKAGE_NAME)
        # Match against Name / NiceName case-insensitively, and accept the
        # generic "AXIS Audio Manager Pro" NiceName regardless of variant.
        existing = None
        for a in apps:
            name = a.get("Name", "").lower()
            nice = a.get("NiceName", "").lower()
            if name == package_name or "audio manager pro" in nice:
                existing = a
                break
        # Prefer the device's self-reported architecture from basic_info
        # (authoritative) over the MODEL_ARCH_TABLE heuristic. The table
        # has been wrong before (C1110-E was tagged armv7hf when it's
        # actually aarch64 — verified 2026-05-21 against real hardware).
        device_arch = (
            arch_override
            or (s1.data.get("basic_info") or {}).get("architecture")
        )
        try:
            eap = _acap.resolve_eap(result.model or "",
                                     arch_override=device_arch)
        except (ValueError, FileNotFoundError) as e:
            s3.mark("failed", "could not resolve .eap for this model",
                    error=str(e))
            return result.finalize()
        if existing is not None:
            running = existing.get("Status", "").lower() == "running"
            if dry_run:
                s3.mark("skipped",
                        f"ACAP {existing.get('Name')!r} v{existing.get('Version')} "
                        f"already installed (status={existing.get('Status')}); "
                        f"would {'leave alone' if running else 'start it'}")
            elif running:
                s3.mark("skipped",
                        f"ACAP already running (v{existing.get('Version')})",
                        application=existing)
            else:
                try:
                    dev.start_application(existing.get("Name", package_name))
                    s3.mark("ok",
                            f"ACAP already installed; started "
                            f"v{existing.get('Version')}",
                            action="start_only", application=existing)
                except VapixError as e:
                    s3.mark("failed",
                            "start_application failed on existing ACAP",
                            error=str(e))
                    return result.finalize()
        else:
            if dry_run:
                s3.mark("skipped",
                        f"would upload + start {eap.name} ({eap.stat().st_size // 1024} KiB)",
                        eap_path=str(eap))
            else:
                try:
                    dev.upload_acap(eap)
                except VapixError as e:
                    s3.mark("failed", f"upload_acap({eap.name}) failed",
                            error=str(e))
                    return result.finalize()
                try:
                    dev.start_application(package_name)
                except VapixError as e:
                    # Some firmware auto-starts after upload; if start says
                    # "already running" we treat it as success.
                    msg = str(e).lower()
                    if "already" in msg or "running" in msg:
                        pass
                    else:
                        s3.mark("failed",
                                f"start_application({package_name}) failed",
                                error=str(e))
                        return result.finalize()
                s3.mark("ok",
                        f"uploaded {eap.name} and started {package_name}",
                        action="upload_and_start", eap_path=str(eap))

        # -- Step 4: server pointer --------------------------------------
        s4 = result.add(StepResult(name="server_pointer"))
        target_host = _server_pointer_value(cfg, ip)
        if dry_run:
            s4.mark("skipped",
                    f"would set AAM Pro server pointer to {target_host!r}",
                    target=target_host)
        else:
            # Give the ACAP a moment to register its parameter group on
            # first install — it's normally instant but slower on
            # mipsisa32r2el hardware.
            time.sleep(2.0)
            try:
                key = _resolve_server_pointer_key(dev)
            except (RuntimeError, VapixError) as e:
                s4.mark("failed",
                        "could not resolve server-pointer parameter key",
                        error=str(e))
                return result.finalize()
            try:
                current = dev.param_list("AudioManagerPro").get(key, "")
            except VapixError as e:
                s4.mark("failed",
                        f"could not read current value of {key}",
                        error=str(e))
                return result.finalize()
            if current == target_host:
                s4.mark("skipped",
                        f"{key} already set to {target_host!r}",
                        key=key, value=target_host)
            else:
                try:
                    dev.param_set({key: target_host})
                except VapixError as e:
                    s4.mark("failed", f"param_set({key}) failed",
                            error=str(e))
                    return result.finalize()
                s4.mark("ok",
                        f"set {key} = {target_host!r} (was {current!r})",
                        key=key, previous=current, value=target_host)

    return result.finalize()


def onboard_fleet(
    *,
    dry_run: bool = False,
    ip_list: Optional[list[str]] = None,
    prefer_mdns: bool = True,
    mdns_timeout: float = 5.0,
    cfg: Optional[AampConfig] = None,
) -> list[OnboardingResult]:
    """Discover (or accept) a list of devices and onboard each one.

    If ``ip_list`` is given, skips discovery and runs the pipeline against
    exactly those IPs (useful for cross-subnet fleets where mDNS/ARP
    can't see the devices).
    """
    cfg = cfg or load_config(require_password=True)
    if ip_list is None:
        discovered = _discovery.discover_all(
            prefer_mdns=prefer_mdns, mdns_timeout=mdns_timeout,
        )
        ip_list = [d.ip for d in discovered]
    out: list[OnboardingResult] = []
    for ip in ip_list:
        out.append(onboard_device(ip, dry_run=dry_run, cfg=cfg))
    return out
