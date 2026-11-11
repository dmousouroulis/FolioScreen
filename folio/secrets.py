"""API credentials live only in the system's credential store (via the `keyring` package):
the macOS Keychain, or Windows Credential Manager.

Values are entered through a hidden prompt, never as command-line arguments,
so they never reach shell history, logs or project files.
"""
from __future__ import annotations

import getpass
import secrets as _secrets

SERVICE = "FolioScreen"

NAMES = {
    "snaptrade_client_id": "SnapTrade Personal client ID",
    "snaptrade_consumer_key": "SnapTrade Personal consumer key",
    "tiingo_token": "Tiingo API token",
}


def store_name() -> str:
    import sys
    return {"darwin": "macOS Keychain", "win32": "Windows Credential Manager"}.get(sys.platform, "system keyring")


class MissingSecret(RuntimeError):
    pass


def _keyring():
    import keyring  # imported lazily so tests and demo mode need no Keychain
    return keyring


def get(name: str) -> str:
    value = _keyring().get_password(SERVICE, name)
    if not value:
        group = "snaptrade" if name.startswith("snaptrade") else "tiingo"
        raise MissingSecret(f"{NAMES.get(name, name)} is not in the {store_name()}. Run: folio secrets set {group}")
    return value


def is_set(name: str) -> bool:
    try:
        return bool(_keyring().get_password(SERVICE, name))
    except Exception:
        return False


def prompt_and_store(group: str) -> None:
    names = [n for n in NAMES if n.startswith(group)]
    if not names:
        raise SystemExit(f"Unknown secret group '{group}'. Use: snaptrade or tiingo")
    for n in names:
        value = getpass.getpass(f"{NAMES[n]} (input hidden): ").strip()
        if not value:
            raise SystemExit(f"Nothing entered; {store_name()} left unchanged.")
        _keyring().set_password(SERVICE, n, value)
    print(f"Stored {', '.join(NAMES[n] for n in names)} in the {store_name()} (service '{SERVICE}').")


def account_salt() -> str:
    """Random per-installation salt used to pseudonymise account identifiers."""
    kr = _keyring()
    salt = kr.get_password(SERVICE, "account_salt")
    if not salt:
        salt = _secrets.token_hex(16)
        kr.set_password(SERVICE, "account_salt", salt)
    return salt


def known_secret_values() -> list:
    """Used by the privacy scan to search project files for real credential values."""
    out = []
    for n in list(NAMES) + ["account_salt"]:
        try:
            v = _keyring().get_password(SERVICE, n)
        except Exception:
            v = None
        if v and len(v) >= 8:
            out.append(v)
    return out
