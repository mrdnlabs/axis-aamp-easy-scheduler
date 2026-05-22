"""Locate and resolve AAM Pro ACAP (``.eap``) files for a given Axis device.

The AAM Pro server installer drops the per-architecture ACAPs into a
well-known folder on disk; we read them from there at upload time rather
than embedding binaries in this project. Each Axis network audio device
runs one of three CPU architectures, so we have to pick the right ``.eap``
for the model we just discovered.

Folder layout (after a stock AAM Pro install)::

    C:\\Program Files\\AXIS Communications\\AXIS Audio Manager Pro\\
        Manager\\Firmware\\
            AXIS_Audio_Manager_Pro_5_1_34_aarch64.eap        # "A" variant — standard speakers/amps
            AXIS_Audio_Manager_Pro_5_1_34_armv7hf.eap
            AXIS_Audio_Manager_Pro_5_1_34_mipsisa32r2el.eap
            AXIS_Audio_Manager_Pro_B_5_1_34_aarch64.eap      # "B" variant — paging consoles / mics
            AXIS_Audio_Manager_Pro_B_5_1_34_armv7hf.eap
            AXIS_Audio_Manager_Pro_B_5_1_34_mipsisa32r2el.eap

The version segment (``5_1_34`` here) changes with each AAM Pro release,
so we glob rather than hard-code it.

Why a model->arch table at all? Because the device's basic_info returns
``ProdNbr`` (e.g. ``C1310-E``) but not the CPU architecture. We could
parse the SoC out of ``param.cgi?Properties.System.Architecture`` after
authenticating, but for the *first* contact we usually just have the
basic-info propertyList and need to pick the right ACAP from that.
``MODEL_ARCH_TABLE`` covers the audio fleet we've validated against;
unknown models RAISE rather than guess (per the onboarding plan's
"wrong-arch .eap is rejected" risk note).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Where the AAM Pro server installer drops the per-arch ACAPs.
# Overridable via :func:`set_firmware_dir` if the user installed AAM Pro
# in a non-default location.
FIRMWARE_DIR: Path = Path(
    r"C:\Program Files\AXIS Communications\AXIS Audio Manager Pro\Manager\Firmware"
)

# Per the onboarding plan, the three architectures we handle:
ARCHITECTURES: tuple[str, ...] = ("aarch64", "armv7hf", "mipsisa32r2el")


# Model -> architecture mapping. Built from the Axis audio product page +
# the firmware/SoC tables in Axis support docs. Add to this as new models
# are validated against real hardware.
#
# Convention: keys are the canonical ``ProdNbr`` returned by basicdeviceinfo
# (e.g. ``C1310-E``, ``C8033``). Case-insensitive lookup in resolve_eap.
# IMPORTANT: this table is a FALLBACK heuristic for situations where we
# don't have an authoritative architecture from the device itself. The
# device's basicdeviceinfo.cgi reports the real architecture in the
# ``Architecture`` propertyList field — prefer that whenever you have it.
# Pass it via ``arch_override`` to :func:`resolve_eap`.
#
# Entries marked "verified" below were confirmed against real hardware.
# Others are best-guess from Axis product-line generation / SoC family and
# may be wrong — Axis sometimes ships a model in multiple silicon revisions.
MODEL_ARCH_TABLE: dict[str, str] = {
    # --- aarch64 (Artpec-8 or modern) — verified hardware: C1110-E (2026-05) ---
    "C1110-E": "aarch64",        # VERIFIED 2026-05 (was previously mis-tagged armv7hf)
    "C1111-E": "aarch64",        # same generation as C1110-E, likely aarch64 (UNVERIFIED)
    "C1310-E": "aarch64",
    "C1410": "aarch64",
    "C1510": "aarch64",
    "C1610-VE": "aarch64",
    "C1611-E": "aarch64",
    "C8210": "aarch64",
    "C8310": "aarch64",
    "C8410": "aarch64",
    "D3110": "aarch64",
    # --- armv7hf (Artpec-7) — all UNVERIFIED ---
    "C1004-E": "armv7hf",
    "C1210-E": "armv7hf",
    "C1211-E": "armv7hf",
    "C1310-E mk II": "armv7hf",
    "C1404-E": "armv7hf",
    "C8033": "armv7hf",          # paging console (uses "B" variant)
    "C8110": "armv7hf",
    # --- mipsisa32r2el (Artpec-5/6, legacy) — all UNVERIFIED ---
    "C2005": "mipsisa32r2el",
    "C3003-E": "mipsisa32r2el",
    "C3211-E": "mipsisa32r2el",
}

# Models that need the "B" variant of the ACAP installed *instead of* the
# main one. EMPTY BY DEFAULT — see comment block below for why.
#
# Reading the packages themselves (package.conf + manifest.json):
#   - non-B variant: appName=AudioManagerPro,  appId=414689
#   - B variant:     appName=AudioManagerProB, appId=414773
# Everything else is identical: same architecture, same paramConfig (both
# expect PrimaryServerIpAddress + PrimaryServerTlsPort=6998), same dbus
# methods, same fw_install path. The differing appId is exactly what
# Axis OS uses to let two ACAPs coexist on one device — strongly
# suggesting B is meant to be installed *alongside* the main ACAP, not
# instead of it, on devices that need to play two roles.
#
# Axis does NOT publicly document which device models (if any) require
# only B, or which need both, or what the second role actually is.
# Until we know, this table stays empty: every model gets the main
# variant, which is the safe default (matches what the AAM Pro SPA does
# when you click "Install ACAP" on a fresh speaker).
#
# When you've confirmed against real hardware which models need B —
# either solo or alongside the main variant — add them here AND adjust
# ``EapBundle.variant_for`` and ``onboard._derive_packages`` accordingly.
PAGING_MODELS: set[str] = set()


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EapBundle:
    """The set of ``.eap`` files found on disk for a given AAM Pro release."""
    version: str               # e.g. "5_1_34"
    by_arch_main: dict[str, Path]   # standard variant, keyed by arch
    by_arch_paging: dict[str, Path] # "B" variant, keyed by arch

    def variant_for(self, model: str) -> dict[str, Path]:
        """Return the correct per-arch dict for the given model."""
        return self.by_arch_paging if model in PAGING_MODELS else self.by_arch_main


# ---------------------------------------------------------------------------
# Disk scanning
# ---------------------------------------------------------------------------

# Matches e.g. AXIS_Audio_Manager_Pro_5_1_34_aarch64.eap
# Capture groups: 1=optional "B_" marker, 2=version (digits_underscores), 3=arch
_EAP_FILENAME_RE = re.compile(
    r"^AXIS_Audio_Manager_Pro_(B_)?(\d+(?:_\d+)+)_([a-z0-9]+)\.eap$",
    re.IGNORECASE,
)


def set_firmware_dir(path: Path | str) -> None:
    """Override the default firmware directory (useful for tests / portable installs)."""
    global FIRMWARE_DIR
    FIRMWARE_DIR = Path(path)


def list_available_eaps(firmware_dir: Optional[Path] = None) -> EapBundle:
    """Scan the firmware directory and return everything we found.

    Raises ``FileNotFoundError`` if the directory doesn't exist, and
    ``RuntimeError`` if it exists but contains no recognizable ``.eap``
    files (e.g. AAM Pro server isn't installed, or the layout changed).
    """
    root = Path(firmware_dir) if firmware_dir else FIRMWARE_DIR
    if not root.exists():
        raise FileNotFoundError(
            f"AAM Pro firmware directory not found: {root}. "
            "Install AXIS Audio Manager Pro on this machine, or pass an explicit path."
        )

    main: dict[str, Path] = {}
    paging: dict[str, Path] = {}
    version: Optional[str] = None
    for entry in sorted(root.iterdir()):
        if not entry.is_file() or entry.suffix.lower() != ".eap":
            continue
        m = _EAP_FILENAME_RE.match(entry.name)
        if not m:
            continue
        is_paging = m.group(1) is not None
        ver = m.group(2)
        arch = m.group(3).lower()
        # If multiple versions are present (e.g. user kept an old install),
        # keep the highest one. Underscored version compares correctly as a
        # tuple of ints, so split + map.
        if version is None or _ver_tuple(ver) > _ver_tuple(version):
            # New "winning" version — reset everything we collected.
            if version is not None and ver != version:
                main.clear()
                paging.clear()
            version = ver
        if ver != version:
            continue
        target = paging if is_paging else main
        target[arch] = entry

    if not main and not paging:
        raise RuntimeError(
            f"No AAM Pro .eap files found in {root}. "
            "Expected files like AXIS_Audio_Manager_Pro_<version>_<arch>.eap."
        )

    return EapBundle(version=version or "", by_arch_main=main, by_arch_paging=paging)


def _ver_tuple(v: str) -> tuple[int, ...]:
    """``"5_1_34"`` -> ``(5, 1, 34)`` for ordering."""
    try:
        return tuple(int(p) for p in v.split("_"))
    except ValueError:
        return (0,)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_eap(
    model: str,
    *,
    firmware_dir: Optional[Path] = None,
    arch_override: Optional[str] = None,
) -> Path:
    """Pick the correct ``.eap`` for the given Axis model.

    Lookup order:
      1. If ``arch_override`` is supplied, use it directly (skip the table).
      2. Otherwise, look up ``model`` in ``MODEL_ARCH_TABLE``.
      3. If the model isn't in the table, RAISE — never guess, because an
         upload to the wrong architecture will be rejected by the device
         (and we don't want to thrash through three attempts per device).

    Once the arch is known, picks the standard or "B" variant based on
    whether ``model`` is in ``PAGING_MODELS``.
    """
    if arch_override:
        arch = arch_override.lower()
    else:
        arch = MODEL_ARCH_TABLE.get(model) or MODEL_ARCH_TABLE.get(model.upper())
        if not arch:
            # Try a forgiving normalization — strip suffixes like " mk II"
            # or "-E" if absent in the table.
            key_norm = re.sub(r"\s+mk\s+\w+$", "", model, flags=re.IGNORECASE).strip()
            arch = MODEL_ARCH_TABLE.get(key_norm)
        if not arch:
            raise ValueError(
                f"Unknown Axis model {model!r}: no architecture mapping. "
                f"Add it to MODEL_ARCH_TABLE in src/aamp/acap.py "
                f"(known archs: {', '.join(ARCHITECTURES)}), "
                f"or pass arch_override='aarch64'|'armv7hf'|'mipsisa32r2el'."
            )

    if arch not in ARCHITECTURES:
        raise ValueError(
            f"Unsupported architecture {arch!r} for model {model!r}. "
            f"Expected one of: {', '.join(ARCHITECTURES)}."
        )

    bundle = list_available_eaps(firmware_dir=firmware_dir)
    variant = bundle.variant_for(model)
    eap = variant.get(arch)
    if eap is None:
        kind = "paging (B)" if model in PAGING_MODELS else "standard"
        raise FileNotFoundError(
            f"No {kind} .eap found for arch {arch!r} in {bundle.version!r}. "
            f"Reinstall AAM Pro or copy the missing file."
        )
    return eap
