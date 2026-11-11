"""Local file locations. Everything private lives outside the repository.

macOS: ~/Library/Application Support/FolioScreen (state, reports) and ~/Library/Logs/FolioScreen.
Windows: %LOCALAPPDATA%\\FolioScreen (state, reports, logs).
FOLIO_HOME overrides the base folder (used by tests).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    override = os.environ.get("FOLIO_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "FolioScreen"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "FolioScreen"
    else:
        base = Path.home() / ".local" / "share" / "folioscreen"
    return _private_dir(base)


def log_dir() -> Path:
    override = os.environ.get("FOLIO_HOME")
    if override:
        return _private_dir(Path(override) / "logs")
    if sys.platform == "darwin":
        return _private_dir(Path.home() / "Library" / "Logs" / "FolioScreen")
    return _private_dir(app_dir() / "logs")


def state_dir() -> Path:
    return _private_dir(app_dir() / "state")


def reports_dir() -> Path:
    """Sanitized reports (counts and statuses only) that are safe to paste into a chat."""
    return _private_dir(app_dir() / "reports")


def _private_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def write_private(path: Path, text: str) -> None:
    """Write a file readable only by the current user (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)
