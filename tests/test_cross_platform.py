"""Platform-specific pieces, testable everywhere: CI runs these on macOS, Windows and Linux."""
from pathlib import Path

import pytest


def test_windows_task_mirrors_the_launchd_job():
    from folio.schedule import build_task_xml, parse_task_xml
    xml = build_task_xml(r"C:\Users\me\folioscreen\.venv\Scripts\pythonw.exe", Path(r"C:\Users\me\folioscreen"),
                         21, 30, r"PC\me", Path(r"C:\Users\me\AppData\Local\FolioScreen\logs\sync.log"), "2026-11-12")
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml          # catch up a missed run (launchd: wake)
    assert "<LogonTrigger>" in xml                                          # launchd: RunAtLoad
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "--scheduled --log-file" in xml and "pythonw.exe" in xml
    st = parse_task_xml(xml)
    assert st["time"] == {"Hour": 21, "Minute": 30} and st["installed"] and st["loaded"]


def test_windows_task_xml_escapes_paths():
    from folio.schedule import build_task_xml, parse_task_xml
    xml = build_task_xml(r"C:\A & B\pythonw.exe", Path(r"C:\A & B"), 7, 5, "me", Path(r"C:\logs\sync.log"), "2026-01-01")
    assert "A &amp; B" in xml and parse_task_xml(xml)["python"] == r"C:\A & B\pythonw.exe"


def test_only_one_sync_at_a_time():
    from folio.sync import SyncError, single_instance
    with single_instance():
        with pytest.raises(SyncError, match="already running"):
            with single_instance():
                pass
    with single_instance():   # released afterwards
        pass


def test_scheduled_output_goes_to_the_log_file(tmp_path):
    from folio.cli import main
    import sys
    log = tmp_path / "logs" / "sync.log"
    out, err = sys.stdout, sys.stderr
    try:
        assert main(["sync", "--demo", "--dry-run", "--log-file", str(log)]) == 0
    finally:
        sys.stdout.close()
        sys.stdout, sys.stderr = out, err
    text = log.read_text(encoding="utf-8")
    assert "Dry run: nothing sent to Power BI" in text


def test_windows_time_zone_ids_cover_the_mapping_both_ways():
    from folio.setup import IANA_TO_WINDOWS, WINDOWS_TZ
    from zoneinfo import ZoneInfo
    for win, iana in WINDOWS_TZ.items():
        ZoneInfo(iana)                      # every target exists (tzdata on Windows)
    for iana, win in IANA_TO_WINDOWS.items():
        assert win in WINDOWS_TZ
