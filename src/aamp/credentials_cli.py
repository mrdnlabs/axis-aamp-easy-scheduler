"""CLI entry points for credential management.

Four console scripts (wired in ``pyproject.toml`` [project.scripts]):

- ``aamp-set-credential <account_id>/<field>`` — prompt for a value (never
  echoed), store it in the configured credential store.
- ``aamp-list-credentials`` — list all known credentials with masked values.
- ``aamp-delete-credential <account_id>/<field>`` — remove a credential.
- ``aamp-migrate-credentials`` — copy secrets from ``.aamp_credentials``
  into the OS keyring, then rename the plaintext file.

**Design principle:** these run in the user's terminal, NEVER in the LLM
context. The password is typed into a TTY via ``getpass`` and goes
straight to the OS keyring — it never appears in stdout, env, or
process arguments.
"""

from __future__ import annotations

import getpass
import sys
from datetime import datetime
from typing import Optional

from .credentials import (
    CREDS_FILE_NAMES,
    KNOWN_SECRETS,
    PROJECT_ROOT,
    KeyringCredentialStore,
    SecretField,
    _read_creds_file,
    find_credentials_file,
    get_credential_store,
    secret_for,
)


MASK = "********"   # fixed length — no character-count leak


def _parse_id(arg: str) -> tuple[str, str]:
    """Parse ``account_id/field`` into ``(account_id, field)``. Exits on error."""
    if "/" not in arg:
        _die(f"Expected '<account_id>/<field>', got: {arg!r}\n"
             f"Known fields:\n{_format_known_secrets()}")
    account_id, field = arg.split("/", 1)
    account_id, field = account_id.strip(), field.strip()
    if not account_id or not field:
        _die(f"Empty account_id or field in {arg!r}")
    if secret_for(account_id, field) is None:
        print(
            f"warning: '{account_id}/{field}' is not in the canonical secret table.\n"
            f"It will be stored, but no code currently fetches it.\n"
            f"Known fields:\n{_format_known_secrets()}",
            file=sys.stderr,
        )
    return account_id, field


def _format_known_secrets() -> str:
    return "\n".join(f"  {s.account_id}/{s.field:<24}  {s.description}"
                      for s in KNOWN_SECRETS)


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# aamp-set-credential
# ---------------------------------------------------------------------------

def set_main(argv: Optional[list[str]] = None) -> int:
    """``aamp-set-credential <account_id>/<field>``"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "Usage: aamp-set-credential <account_id>/<field>\n"
            "\n"
            "Stores a secret in the OS-native credential store (Windows\n"
            "Credential Manager / macOS Keychain / libsecret). The value is\n"
            "typed into a TTY prompt and never appears on screen.\n"
            "\n"
            f"Known fields:\n{_format_known_secrets()}"
        )
        return 0
    account_id, field = _parse_id(argv[0])
    # Ensure we use a writable backend
    try:
        store = KeyringCredentialStore()
    except RuntimeError as e:
        _die(f"{e}", code=3)
    # Prompt twice for confirmation — typo protection
    value = getpass.getpass(f"Value for {account_id}/{field} (input hidden): ")
    if not value:
        _die("Empty value rejected.")
    confirm = getpass.getpass(f"Confirm {account_id}/{field}: ")
    if value != confirm:
        _die("Values do not match.")
    # Soft validation: warn on suspiciously short password fields
    if "password" in field and len(value) < 8:
        print(f"warning: '{field}' is {len(value)} chars — most Axis firmware "
              f"rejects passwords under 8.", file=sys.stderr)
    store.set(account_id, field, value)
    print(f"Stored {account_id}/{field} = {MASK} in OS keyring.")
    return 0


# ---------------------------------------------------------------------------
# aamp-list-credentials
# ---------------------------------------------------------------------------

def list_main(argv: Optional[list[str]] = None) -> int:
    """``aamp-list-credentials``"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"-h", "--help"}:
        print(
            "Usage: aamp-list-credentials\n"
            "\n"
            "Lists every credential currently stored, with values masked.\n"
            "Reads from the configured backend (keyring + .aamp_credentials\n"
            "fallback by default)."
        )
        return 0
    store = get_credential_store()
    rows = store.list_accounts()
    if not rows:
        print("(no credentials stored)")
        return 1
    print(f"Stored credentials ({type(store).__name__}):\n")
    width_a = max(len(a) for a, _ in rows)
    for account_id, fields in rows:
        for f in fields:
            print(f"  {account_id:<{width_a}}/{f:<24}  {MASK}")
    return 0


# ---------------------------------------------------------------------------
# aamp-delete-credential
# ---------------------------------------------------------------------------

def delete_main(argv: Optional[list[str]] = None) -> int:
    """``aamp-delete-credential <account_id>/<field>``"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "Usage: aamp-delete-credential <account_id>/<field>\n"
            "\n"
            "Removes the credential from the OS keyring. Confirms before\n"
            "deleting — type DELETE to proceed."
        )
        return 0
    account_id, field = _parse_id(argv[0])
    try:
        store = KeyringCredentialStore()
    except RuntimeError as e:
        _die(f"{e}", code=3)
    existing = store.get(account_id, field)
    if existing is None:
        print(f"(no credential at {account_id}/{field}; nothing to delete)")
        return 0
    confirm = input(f"Delete {account_id}/{field}? Type DELETE to confirm: ").strip()
    if confirm != "DELETE":
        print("Cancelled.")
        return 1
    store.delete(account_id, field)
    print(f"Deleted {account_id}/{field} from OS keyring.")
    return 0


# ---------------------------------------------------------------------------
# aamp-migrate-credentials
# ---------------------------------------------------------------------------

def migrate_main(argv: Optional[list[str]] = None) -> int:
    """``aamp-migrate-credentials``"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"-h", "--help"}:
        print(
            "Usage: aamp-migrate-credentials\n"
            "\n"
            "Reads .aamp_credentials, writes each secret to the OS keyring,\n"
            "and offers to rename the plaintext file as a backup.\n"
            "\n"
            "Idempotent — re-running with already-migrated keys says\n"
            "'already present; skipping' per key. Non-secret keys (host,\n"
            "username, voice_id, etc.) are left in .aamp_credentials."
        )
        return 0

    creds_path = find_credentials_file()
    if creds_path is None:
        print("No .aamp_credentials file found in project root or home. Nothing to migrate.")
        return 0
    print(f"Migrating from: {creds_path}")
    file_creds = _read_creds_file(creds_path)

    try:
        store = KeyringCredentialStore()
    except RuntimeError as e:
        _die(f"{e}", code=3)

    migrated: list[SecretField] = []
    skipped_existing: list[SecretField] = []
    not_in_file: list[SecretField] = []
    for s in KNOWN_SECRETS:
        existing = store.get(s.account_id, s.field)
        file_val = file_creds.get(s.env_var)
        if existing is not None:
            skipped_existing.append(s)
            continue
        if not file_val:
            not_in_file.append(s)
            continue
        store.set(s.account_id, s.field, file_val)
        migrated.append(s)

    # Summary table (values always masked)
    print()
    print(f"Migration summary:")
    for s in migrated:
        print(f"  [moved]   {s.account_id}/{s.field:<24} = {MASK}")
    for s in skipped_existing:
        print(f"  [present] {s.account_id}/{s.field:<24} = {MASK}  (already in keyring)")
    for s in not_in_file:
        print(f"  [absent]  {s.account_id}/{s.field:<24}        (not in {creds_path.name})")

    if not migrated:
        print("\nNothing to do. The keyring already has every secret found in the file.")
        return 0

    # Offer to rename the plaintext file. Renaming, not deleting — safer.
    print()
    answer = input(
        f"Rename {creds_path.name} to {creds_path.name}.bak.<timestamp>? "
        "(secrets are now in keyring; the plaintext file is no longer needed) [y/N]: "
    ).strip().lower()
    if answer == "y":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = creds_path.with_name(f"{creds_path.name}.bak.{ts}")
        creds_path.rename(backup)
        print(f"Renamed: {creds_path} -> {backup}")
        print(f"\nNon-secret fields (host, username, etc.) were in {creds_path.name}.")
        print(f"If you need them, copy from the backup before deleting it.")
    else:
        print(f"Left {creds_path} in place. Delete it manually once you're confident "
              f"the migration worked.")
    return 0
