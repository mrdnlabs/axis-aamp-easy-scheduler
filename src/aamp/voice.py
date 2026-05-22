"""ElevenLabs text-to-speech integration.

Generates voice audio from text, saves to ``assets/voice/``, and (optionally)
uploads to AAM Pro as a library item ready for scheduling.

Configuration:
  - ``ELEVENLABS_API_KEY`` env var or ``.aamp_credentials`` entry.
  - ``ELEVENLABS_VOICE_ID`` optional default voice (otherwise we use the
    well-known "Rachel" stock voice id).
  - ``ELEVENLABS_MODEL`` optional model id (default ``eleven_multilingual_v2``).

Tool surface (wrapped as MCP):
  generate_voice_announcement(text, slug?, voice?, model?, upload=True)
    → returns the local filename + the AAM Pro library item id (if uploaded).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from .api import AampApi
from .config import AampConfig


ELEVENLABS_BASE = "https://api.elevenlabs.io"

# Stable, well-known stock voices on ElevenLabs (these IDs have been
# consistent for years). Most users override via ELEVENLABS_VOICE_ID.
DEFAULT_VOICE_IDS = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",         # default — clear, mid-pitch female
    "Adam":   "pNInz6obpgDQGcFmaJgB",         # mid-pitch male
    "Antoni": "ErXwobaYiN019PkySvjV",         # warm male
    "Bella":  "EXAVITQu4vr4xnSDxMaL",         # soft female
}
DEFAULT_MODEL = "eleven_multilingual_v2"


def _safe_slug(text: str, max_len: int = 50) -> str:
    """Make a filesystem-safe slug from a string."""
    s = re.sub(r"[^a-zA-Z0-9\-_ ]", "", text).strip().replace(" ", "_").lower()
    return s[:max_len] or "voice"


def _api_key() -> Optional[str]:
    return os.environ.get("ELEVENLABS_API_KEY") or _api_key_from_credentials()


def _api_key_from_credentials() -> Optional[str]:
    """Fall back to .aamp_credentials in the project root."""
    project_root = Path(__file__).resolve().parent.parent.parent
    creds_file = project_root / ".aamp_credentials"
    if not creds_file.exists():
        return None
    for line in creds_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "ELEVENLABS_API_KEY":
            return v.strip().strip('"').strip("'") or None
    return None


def _resolve_voice_id(voice: Optional[str]) -> str:
    """Accept either a stock voice name (Rachel/Adam/...) or a raw voice id."""
    if not voice:
        # Default: env override → Rachel
        return os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_IDS["Rachel"]
    # Direct id?
    if len(voice) >= 16 and not voice.isalpha():
        return voice
    if voice in DEFAULT_VOICE_IDS:
        return DEFAULT_VOICE_IDS[voice]
    # Title-case lookup ("rachel" → "Rachel")
    if voice.title() in DEFAULT_VOICE_IDS:
        return DEFAULT_VOICE_IDS[voice.title()]
    raise ValueError(
        f"Unknown voice {voice!r}. Use one of {sorted(DEFAULT_VOICE_IDS)} "
        f"or pass a raw ElevenLabs voice id."
    )


def voice_output_dir(project_root: Optional[Path] = None) -> Path:
    """Return the directory where generated voice MP3s live."""
    root = project_root or Path(__file__).resolve().parent.parent.parent
    d = root / "assets" / "voice"
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_audio(
    text: str,
    *,
    voice: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    output_path: Optional[Path] = None,
    slug: Optional[str] = None,
) -> Path:
    """Call ElevenLabs TTS and write an MP3. Returns the path to the saved file.

    Raises ``RuntimeError`` if the API key is missing or the call fails.
    """
    api_key = _api_key()
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not set. Add it to .aamp_credentials or env."
        )
    voice_id = _resolve_voice_id(voice)
    if output_path is None:
        name = (slug or _safe_slug(text)) + ".mp3"
        output_path = voice_output_dir() / name

    url = f"/v1/text-to-speech/{voice_id}"
    body = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    headers = {
        "xi-api-key": api_key,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    with httpx.Client(base_url=ELEVENLABS_BASE, timeout=httpx.Timeout(60.0, connect=10.0)) as c:
        r = c.post(url, headers=headers, json=body)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs returned {r.status_code}: {r.text[:300]}")
    output_path.write_bytes(r.content)
    return output_path


# ---------------------------------------------------------------------------
# Higher-level helper: generate + (optional) upload + (optional) find item-id
# ---------------------------------------------------------------------------

def generate_and_upload(
    text: str,
    *,
    api: AampApi,
    voice: Optional[str] = None,
    slug: Optional[str] = None,
    category: str = "announcement",
    library_subdir: str = "voice",
) -> dict[str, Any]:
    """Generate voice audio, upload it to the matching AAM Pro library, and
    discover the resulting libraryItemId.

    Returns a dict with: local_path, library_id, target_path, library_item_id (or None).
    """
    from . import write as _write   # local import to avoid circular at module-load
    if slug is None:
        slug = _safe_slug(text)
    local_path = generate_audio(text, voice=voice, slug=slug)

    upload_info = _write.upload_audio_file(
        api,
        file_path=str(local_path),
        category=category,
        target_directory=library_subdir,
    )

    # Try to find the new library item by name to surface its id.
    library_id = upload_info["library_id"]
    new_item_id: Optional[int] = None
    try:
        matches = api.search_library(library_id, pattern=slug)
        for m in matches:
            if m.path and slug in m.path:
                new_item_id = m.id
                break
    except Exception:
        pass

    return {
        "local_path": str(local_path),
        "library_id": library_id,
        "target_path": upload_info["uploaded_name"],
        "library_item_id": new_item_id,
        "slug": slug,
        "voice": voice or "Rachel",
    }
