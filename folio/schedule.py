"""Nightly sync: macOS launchd (a per-user LaunchAgent) or Windows Task Scheduler (a per-user task).

macOS (launchd):
- StartCalendarInterval runs the job at the chosen local time. If the Mac is asleep then,
  launchd runs it once when the Mac wakes.
- RunAtLoad runs it at login (after a reboot); `--scheduled` makes that a no-op when a sync
  already succeeded in the last 18 hours.
- The project must not live in Desktop, Documents, Downloads or iCloud Drive: macOS privacy
  protection (TCC) blocks background jobs from reading those folders.

Windows (Task Scheduler), the same behaviour:
- A daily trigger at the chosen local time, and a logon trigger.
- StartWhenAvailable runs a missed run as soon as the computer is on again (the launchd catch-up).
- It runs on battery, never overlaps itself, and stops after an hour.
- pythonw.exe (no console window) writes its own log with --log-file, since Task Scheduler keeps no output.
"""
from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from pathlib import Path

from . import paths

LABEL = "com.folioscreen.sync"
PROTECTED = ("Desktop", "Documents", "Downloads", "Library/Mobile Documents")


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(python: str, project_dir: Path, hour: int, minute: int) -> dict:
    logs = paths.log_dir()
    return {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "folio", "sync", "--scheduled"],
        "WorkingDirectory": str(project_dir),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "sync.log"),
        "StandardErrorPath": str(logs / "sync.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def check_location(project_dir: Path) -> None:
    rel = str(project_dir.resolve()).replace(str(Path.home()) + "/", "")
    if any(rel == p or rel.startswith(p + "/") for p in PROTECTED):
        raise SystemExit(f"The project is in a protected folder ({rel}). Background jobs cannot read it there.\n"
                         f"Move it, for example: mv '{project_dir}' ~/Developer/folioscreen")


def install(project_dir: Path, at: str) -> None:
    if sys.platform == "win32":
        return _win_install(project_dir, at)
    if sys.platform != "darwin":
        raise SystemExit("Scheduling is available on macOS (launchd) and Windows (Task Scheduler).")
    check_location(project_dir)
    hour, minute = (int(x) for x in at.split(":"))
    data = build_plist(sys.executable, project_dir.resolve(), hour, minute)
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    with open(p, "wb") as fh:
        plistlib.dump(data, fh)
    r = subprocess.run(["launchctl", "load", str(p)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"launchctl load failed: {r.stderr.strip()}")
    from .sync import load_config, config_path
    cfg = load_config()
    cfg["schedule_time"] = f"{hour:02d}:{minute:02d}"
    paths.write_private(config_path(), json.dumps(cfg, indent=2) + "\n")
    print(f"Installed {p}\nRuns daily at {at} local time (and once after login if that run was missed).")
    print(f"Log: {paths.log_dir() / 'sync.log'}")


def uninstall() -> None:
    if sys.platform == "win32":
        return _win_uninstall()
    p = plist_path()
    from .sync import load_config, config_path
    cfg = load_config()
    cfg.pop("schedule_time", None)
    paths.write_private(config_path(), json.dumps(cfg, indent=2) + "\n")
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
        p.unlink()
        print(f"Removed {p}")
    else:
        print("No FolioScreen schedule installed.")


def status() -> dict:
    if sys.platform == "win32":
        return _win_status()
    p = plist_path()
    if not p.exists():
        return {"installed": False}
    with open(p, "rb") as fh:
        data = plistlib.load(fh)
    r = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True) if sys.platform == "darwin" else None
    return {"installed": True, "time": data.get("StartCalendarInterval"), "python": data["ProgramArguments"][0],
            "loaded": bool(r and r.returncode == 0)}


# ============================================================================ Windows Task Scheduler
TASK_NAME = r"\FolioScreen\Nightly sync"
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def windows_python(executable: str) -> str:
    """pythonw.exe beside python.exe (same virtual environment): runs without a console window."""
    p = Path(executable)
    w = p.with_name("pythonw.exe")
    return str(w) if p.name.lower() == "python.exe" and w.exists() else str(p)


def build_task_xml(python: str, project_dir: Path, hour: int, minute: int, user: str, log_file: Path,
                   today: str) -> str:
    from xml.sax.saxutils import escape
    args = f'-m folio sync --scheduled --log-file "{log_file}"'
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="{TASK_NS}">
  <RegistrationInfo>
    <Description>FolioScreen nightly sync: fetch, reconcile, publish to Power BI and verify.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{today}T{hour:02d}:{minute:02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python)}</Command>
      <Arguments>{escape(args)}</Arguments>
      <WorkingDirectory>{escape(str(project_dir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def parse_task_xml(text: str) -> dict:
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text.encode("utf-16") if text.lstrip().startswith("<?xml") and "UTF-16" in text[:60] else text)
    ns = {"t": TASK_NS}
    start = root.findtext(".//t:CalendarTrigger/t:StartBoundary", default="", namespaces=ns)
    hh, mm = (start.split("T")[1].split(":")[:2] if "T" in start else ("0", "0"))
    enabled = (root.findtext(".//t:Settings/t:Enabled", default="true", namespaces=ns) or "true").lower() == "true"
    return {"installed": True, "time": {"Hour": int(hh), "Minute": int(mm)},
            "python": root.findtext(".//t:Exec/t:Command", default="", namespaces=ns), "loaded": enabled}


def _win_user() -> str:
    import os
    user, domain = os.environ.get("USERNAME", ""), os.environ.get("USERDOMAIN", "")
    return f"{domain}\\{user}" if domain else user


def _win_install(project_dir: Path, at: str) -> None:
    import tempfile
    from datetime import date
    hour, minute = (int(x) for x in at.split(":"))
    xml = build_task_xml(windows_python(sys.executable), project_dir.resolve(), hour, minute, _win_user(),
                         paths.log_dir() / "sync.log", date.today().isoformat())
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "folioscreen-task.xml"
        f.write_text(xml, encoding="utf-16")
        r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(f), "/F"], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"Task Scheduler refused the task: {(r.stderr or r.stdout).strip()}")
    from .sync import load_config, config_path
    cfg = load_config()
    cfg["schedule_time"] = f"{hour:02d}:{minute:02d}"
    paths.write_private(config_path(), json.dumps(cfg, indent=2) + "\n")
    print(f"Created the Task Scheduler task '{TASK_NAME}'.\nRuns daily at {at} local time, at logon, and as soon as "
          "possible after a missed run.")
    print(f"Log: {paths.log_dir() / 'sync.log'}")


def _win_uninstall() -> None:
    from .sync import load_config, config_path
    cfg = load_config()
    cfg.pop("schedule_time", None)
    paths.write_private(config_path(), json.dumps(cfg, indent=2) + "\n")
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
    print(f"Removed the task '{TASK_NAME}'." if r.returncode == 0 else "No FolioScreen task installed.")


def _win_status() -> dict:
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        return {"installed": False}
    try:
        return parse_task_xml(r.stdout)
    except Exception:
        return {"installed": True, "loaded": True}
