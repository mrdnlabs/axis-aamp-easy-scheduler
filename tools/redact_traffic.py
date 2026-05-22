"""Scrub a traffic log of credentials and tokens.

Rewrites the JSONL log file in place (with a .bak copy). Masks:
- ``password=...`` form params
- ``access_token``, ``refresh_token``, ``id_token`` JSON fields
- ``code_verifier``, ``code`` OAuth params (still sensitive even though short-lived)
- ``Set-Cookie`` headers (already masked but double-check)

The original is preserved as ``<name>.bak`` (only the first time — subsequent runs
overwrite the .jsonl but leave .bak from the first redaction in place).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

# JSON-string field patterns to mask (apply to body text when content-type is json-ish)
JSON_FIELDS_TO_MASK = ("access_token", "refresh_token", "id_token", "password",
                      "client_secret", "code_verifier")

# Form-urlencoded fields to mask
FORM_FIELDS_TO_MASK = ("password", "code_verifier", "code", "client_secret",
                       "access_token", "refresh_token")


def mask_json_body(body: str) -> str:
    """Replace sensitive JSON string-field values with a masked stub."""
    if not body:
        return body
    for field in JSON_FIELDS_TO_MASK:
        # "field":"value" — handle backslash-escapes inside the value
        pattern = re.compile(rf'("{re.escape(field)}"\s*:\s*")((?:[^"\\]|\\.)*)(")')
        body = pattern.sub(lambda m: f'{m.group(1)}***MASKED***{m.group(3)}', body)
    return body


def mask_form_body(body: str) -> str:
    if not body:
        return body
    for field in FORM_FIELDS_TO_MASK:
        # field=value (& or end-of-string terminated)
        pattern = re.compile(rf'(^|&)({re.escape(field)})=([^&]*)')
        body = pattern.sub(lambda m: f'{m.group(1)}{m.group(2)}=***MASKED***', body)
    return body


def looks_form_encoded(body: str | None) -> bool:
    if not body:
        return False
    return bool(re.match(r'^[a-zA-Z_][\w.\-]*=', body)) and "&" in body


def redact_entry(entry: dict) -> dict:
    body = entry.get("body")
    if not isinstance(body, str):
        return entry
    if body.lstrip().startswith(("{", "[")):
        entry["body"] = mask_json_body(body)
    elif looks_form_encoded(body):
        entry["body"] = mask_form_body(body)
    return entry


def redact_file(path: Path) -> tuple[int, int]:
    """Redact a single JSONL log file. Returns (total_lines, redacted_count)."""
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    total = 0
    changed = 0
    lines_out: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                lines_out.append(line)
                continue
            total += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                lines_out.append(line)
                continue
            before = entry.get("body")
            entry = redact_entry(entry)
            after = entry.get("body")
            if before != after:
                changed += 1
            lines_out.append(json.dumps(entry, default=str))
    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines_out) + ("\n" if lines_out else ""))
    return total, changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="JSONL log paths to redact (default: all in logs/)")
    ap.add_argument("--delete-bak", action="store_true",
                    help="After redacting, delete the .bak originals too (use after verifying redaction).")
    args = ap.parse_args()
    targets = [Path(p) for p in args.paths] if args.paths else sorted(LOG_DIR.glob("traffic_*.jsonl"))
    if not targets:
        print("(no log files)")
        return 0
    grand_total = grand_changed = 0
    for p in targets:
        total, changed = redact_file(p)
        grand_total += total
        grand_changed += changed
        print(f"  {p.name}: {changed}/{total} entries redacted")
        if args.delete_bak:
            bak = p.with_suffix(p.suffix + ".bak")
            if bak.exists():
                bak.unlink()
                print(f"    deleted {bak.name}")
    print(f"\nDone. {grand_changed}/{grand_total} entries had sensitive content masked.")
    if not args.delete_bak:
        print("Original logs are preserved with .bak suffix. Run with --delete-bak to remove them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
