"""Pre-publication privacy scan for the repository.

Flags: real credential values found in the Keychain, account labels from the local config,
UUIDs (SnapTrade account/connection IDs look like UUIDs), long hex/base64 tokens, files that must
never be committed, and FolioScreen state files copied into the repo.
"""
from __future__ import annotations

import re
from pathlib import Path

THIRD_PARTY = ("tools/schemas/", "tools/node/node_modules/")  # Microsoft's published schemas and parser
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}
# Every state and report file FolioScreen writes (folio/sync.py, probe.py, report_check.py, powerbi.py), plus secrets files.
FORBIDDEN_NAMES = re.compile(r"^(known_good_|demo_inputs_|deployment_|check_report_|verify_|probe_\d|last_run|last_success|"
                             r"last_sync_summary|safety_test|sandbox_snapshot|visual_probe\.json|config\.json|history\.jsonl|"
                             r"microsoft_auth_record)|\.env$|transactions.*\.csv$")
IMAGES = (".png", ".jpg", ".jpeg", ".heic", ".gif", ".webp", ".pdf")
IMAGE_DIR = "docs/images/"   # demo screenshots only (see docs/images/README.md)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
LONG_TOKEN = re.compile(r"\b[A-Za-z0-9]{40,}\b")
ALLOWED_UUID_FILES = (".platform", ".tmdl", "visual.json", "CY26SU05.json", "model_writer.py")  # lineage tags and logical IDs are generated, not personal


def scan(root: Path, secret_values=(), labels=()) -> list:
    findings = []
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts) or not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(THIRD_PARTY):
            continue
        if FORBIDDEN_NAMES.search(p.name):
            findings.append((rel, "FolioScreen state or report file: must not be committed"))
        if p.suffix.lower() in IMAGES and not rel.startswith(IMAGE_DIR):
            findings.append((rel, f"image outside {IMAGE_DIR}: screenshots belong there, and only of the demo"))
        if p.stat().st_size > 5_000_000 or p.suffix.lower() in IMAGES + (".zip",):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for v in secret_values:
            if v and v in text:
                findings.append((rel, "contains a credential value from your credential store"))
        for lab in labels:
            if lab and len(lab) > 3 and lab in text:
                findings.append((rel, f"contains your account label '{lab[:3]}…'"))
        if not rel.endswith(ALLOWED_UUID_FILES) and "tests/" not in rel and UUID.search(text):
            findings.append((rel, "contains a UUID (check it is not a SnapTrade account or connection ID)"))
        for m in LONG_TOKEN.finditer(text):
            if not rel.endswith(ALLOWED_UUID_FILES) and not re.fullmatch(r"[0-9]+", m.group()):
                findings.append((rel, "contains a long token-like string"))
                break
    return findings
