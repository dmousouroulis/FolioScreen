"""macOS notification (no-op elsewhere). Messages never contain amounts or identifiers."""
from __future__ import annotations

import subprocess
import sys


def notify(title: str, text: str) -> None:
    if sys.platform != "darwin":
        return
    safe = text.replace("\\", "").replace('"', "'")[:200]
    try:
        subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "{title}"'],
                       check=False, timeout=10, capture_output=True)
    except Exception:
        pass
