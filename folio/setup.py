"""`folio setup`: guided first run, demo first, then your own data. `folio setup --check`: the same checks, read-only.

Each step checks the current state, explains what is missing and why, and asks before acting. Every external call
goes through `Env`, so the flow is tested offline with fakes (tests/test_setup.py).

Order (each later step needs the earlier ones):
  1 Python environment          4 SnapTrade keys (optional from here)   7 Live model in Power BI
  2 Microsoft sign-in           5 Brokerage connection (Sandbox first)  8 First sync
  3 Demo report                 6 Tiingo key                            9 Nightly schedule
                                                                       10 Power BI's own price refresh
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

OK, TODO, FAIL, SKIP = "ok", "todo", "fail", "skip"
DEVICE = "Mac" if sys.platform == "darwin" else "computer"


def _store() -> str:
    from .secrets import store_name
    return store_name()
MARK = {OK: "✓", TODO: "○", FAIL: "✗", SKIP: "–"}
REQUIRED_PY = (3, 11)
PACKAGES = ("azure.identity", "keyring", "requests", "snaptrade_client")


@dataclass
class Result:
    step: str
    state: str
    detail: str
    fix: str = ""


@dataclass
class Env:
    """Every side effect setup can have. Defaults are the real implementations; tests pass fakes."""
    ask: Callable[[str], str] = input
    log: Callable[[str], None] = print
    root: Optional[object] = None
    base_theme: Optional[object] = None
    _pbi: Optional[object] = field(default=None, repr=False)

    # ---------------------------------------------------------------- environment
    def python_ok(self) -> tuple:
        missing = []
        for mod in PACKAGES:
            try:
                __import__(mod)
            except Exception:
                missing.append(mod)
        return sys.version_info[:2] >= REQUIRED_PY, missing

    # ---------------------------------------------------------------- Microsoft / Power BI
    def ms_signed_in(self) -> str:
        """'' when silent sign-in works, else the reason."""
        from .powerbi import AuthRequired, MicrosoftAuth
        try:
            MicrosoftAuth(interactive=False).describe()
            return ""
        except AuthRequired as exc:
            return str(exc)

    def ms_login(self) -> str:
        from .powerbi import MicrosoftAuth
        return MicrosoftAuth(interactive=True).login()

    def pbi(self):
        if self._pbi is None:
            from .powerbi import MicrosoftAuth, PowerBI
            self._pbi = PowerBI(MicrosoftAuth(interactive=False))
        return self._pbi

    def find(self, kind: str, name: str) -> Optional[str]:
        return self.pbi().find_item(kind, name)

    def deploy(self, demo: bool) -> int:
        from .sync import deploy
        return deploy(demo=demo, scenario="clean", base_theme=self.base_theme, log=self.log)

    def sync(self) -> int:
        from .sync import run_sync
        return run_sync(log=self.log)

    def last_live_success(self, name: str) -> Optional[str]:
        from .sync import known_good, load_state
        ds, _ = known_good(name)
        if not ds:
            return None
        return (load_state("last_success.json") or {}).get("finished_utc") or ds["meta"].get("synced_utc")

    def last_outcome(self) -> str:
        from .sync import load_state
        return (load_state("last_run.json") or {}).get("outcome") or ""

    # ---------------------------------------------------------------- credentials
    def secret_set(self, name: str) -> bool:
        from . import secrets
        return secrets.is_set(name)

    def store_secrets(self, group: str) -> None:
        from . import secrets
        secrets.prompt_and_store(group)

    def snaptrade_connections(self) -> list:
        """Raises on rejected keys or no network."""
        from . import secrets
        from .snaptrade_source import SnapTradeReader
        reader = SnapTradeReader(secrets.get("snaptrade_client_id"), secrets.get("snaptrade_consumer_key"))
        return reader.connections()

    def connect_link(self, sandbox: bool) -> str:
        from . import secrets
        from .snaptrade_source import SnapTradeReader
        reader = SnapTradeReader(secrets.get("snaptrade_client_id"), secrets.get("snaptrade_consumer_key"))
        return reader.connection_portal_link(sandbox=sandbox)

    def tiingo_ok(self) -> str:
        """'' when Tiingo accepts the token (one request), else the reason."""
        import requests
        from . import secrets
        r = requests.get("https://api.tiingo.com/api/test", params={"token": secrets.get("tiingo_token")}, timeout=30)
        return "" if r.status_code == 200 else f"Tiingo answered HTTP {r.status_code}"

    def price_schedule(self, model_id: str) -> dict:
        return self.pbi().refresh_schedule(model_id)

    def set_price_schedule(self, model_id: str, time_hhmm: str, time_zone: str) -> None:
        self.pbi().set_refresh_schedule(model_id, time_hhmm, time_zone)

    def local_timezone(self) -> str:
        """This computer's IANA time zone: /etc/localtime on macOS, `tzutil /g` (a Windows ID) on Windows; else UTC."""
        import os
        import subprocess
        try:
            if sys.platform == "win32":
                win = subprocess.run(["tzutil", "/g"], capture_output=True, text=True, timeout=10).stdout.strip()
                return WINDOWS_TZ.get(win.replace("_dstoff", ""), "UTC")
            target = os.path.realpath("/etc/localtime")
            return target.split("zoneinfo/", 1)[1]
        except Exception:
            return "UTC"

    # ---------------------------------------------------------------- schedule
    def schedule_status(self) -> dict:
        from .schedule import status
        return status()

    def schedule_install(self, time_hhmm: str) -> None:
        from .schedule import install
        install(self.root, time_hhmm)

    def config(self) -> dict:
        from .sync import load_config
        return load_config()


PRICE_REFRESH_LOCAL = "07:00"   # Power BI's own refresh: prices stay current even when the computer is off
MIN_GAP_MINUTES = 120

# Power BI stores a refresh schedule in a Windows time zone ID. Common ones, mapped to IANA zones.
WINDOWS_TZ = {
    "UTC": "UTC", "Coordinated Universal Time": "UTC",
    "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver", "US Mountain Standard Time": "America/Phoenix",
    "Pacific Standard Time": "America/Los_Angeles", "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu", "Atlantic Standard Time": "America/Halifax",
    "Newfoundland Standard Time": "America/St_Johns", "Canada Central Standard Time": "America/Regina",
    "Central America Standard Time": "America/Guatemala", "Mexico Standard Time": "America/Mexico_City",
    "SA Eastern Standard Time": "America/Cayenne", "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "GMT Standard Time": "Europe/London", "Greenwich Standard Time": "Atlantic/Reykjavik",
    "W. Europe Standard Time": "Europe/Berlin", "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw", "Romance Standard Time": "Europe/Paris",
    "E. Europe Standard Time": "Europe/Chisinau", "GTB Standard Time": "Europe/Athens",
    "FLE Standard Time": "Europe/Kyiv", "Russian Standard Time": "Europe/Moscow",
    "Israel Standard Time": "Asia/Jerusalem", "South Africa Standard Time": "Africa/Johannesburg",
    "Arabian Standard Time": "Asia/Dubai", "India Standard Time": "Asia/Kolkata",
    "China Standard Time": "Asia/Shanghai", "Singapore Standard Time": "Asia/Singapore",
    "Tokyo Standard Time": "Asia/Tokyo", "Korea Standard Time": "Asia/Seoul",
    "AUS Eastern Standard Time": "Australia/Sydney", "E. Australia Standard Time": "Australia/Brisbane",
    "W. Australia Standard Time": "Australia/Perth", "New Zealand Standard Time": "Pacific/Auckland",
}
IANA_TO_WINDOWS = {v: k for k, v in reversed(list(WINDOWS_TZ.items()))}
IANA_TO_WINDOWS.update({"America/Detroit": "Eastern Standard Time", "America/Toronto": "Eastern Standard Time",
                        "America/Vancouver": "Pacific Standard Time", "Europe/Amsterdam": "W. Europe Standard Time",
                        "Europe/Rome": "W. Europe Standard Time", "Europe/Madrid": "Romance Standard Time",
                        "Europe/Brussels": "Romance Standard Time", "Europe/Dublin": "GMT Standard Time",
                        "Europe/Lisbon": "GMT Standard Time", "Europe/Bucharest": "GTB Standard Time",
                        "Etc/UTC": "UTC"})


def _minutes(hhmm: str) -> int:
    h, m = (int(x) for x in str(hhmm).split(":")[:2])
    return (h * 60 + m) % 1440


def _hhmm(minutes: int) -> str:
    minutes %= 1440
    return f"{minutes // 60:02}:{minutes % 60:02}"


def price_refresh_state(sched: dict, sync_hhmm: str, local_tz: str, on=None) -> tuple:
    """(state, detail) for Power BI's own scheduled refresh against this computer's nightly sync. Both are converted
    to the local time zone (IANA) on the given date before comparing; an unknown time zone is reported, not guessed."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    if not sched or not sched.get("enabled") or not sched.get("times"):
        return TODO, f"off: prices update only when the {DEVICE} syncs"
    win = str(sched.get("localTimeZoneId") or "UTC")
    iana = WINDOWS_TZ.get(win)
    if not iana:
        return TODO, (f"daily at {', '.join(sched['times'])} ({win}): time zone not recognised; make sure it is at least "
                      f"{MIN_GAP_MINUTES // 60} hours from the {DEVICE}'s sync at {sync_hhmm}")
    on = on or date.today()
    local = []
    for t in sched["times"]:
        h, m = (int(x) for x in t.split(":")[:2])
        moment = datetime(on.year, on.month, on.day, h, m, tzinfo=ZoneInfo(iana)).astimezone(ZoneInfo(local_tz))
        local.append(moment.hour * 60 + moment.minute)
    mine = _minutes(sync_hhmm)
    gap = min(min(abs(t - mine), 1440 - abs(t - mine)) for t in local)
    shown = ", ".join(_hhmm(t) for t in local)
    where = "" if iana == local_tz else f" ({', '.join(sched['times'])} {win})"
    if gap < MIN_GAP_MINUTES:
        return TODO, (f"daily at {shown} your time{where}, within {gap} min of the {DEVICE}'s sync at {sync_hhmm}: "
                      "they compete for refreshes")
    return OK, f"daily at {shown} your time{where}; the {DEVICE} syncs at {sync_hhmm}"


def _is_sandbox(conn: dict) -> bool:
    b = conn.get("brokerage") or {}
    names = [str(b.get(k) or "").lower() for k in ("name", "slug", "display_name")] if isinstance(b, dict) else [str(b).lower()]
    return any(n.startswith("sandbox") for n in names)


def run(*, check_only: bool = False, env: Optional[Env] = None) -> int:
    env = env or Env()
    log = env.log
    results: list = []

    def ask_yes(question: str, default: bool = True) -> bool:
        if check_only:
            return False
        hint = "[Y/n]" if default else "[y/N]"
        ans = env.ask(f"{question} {hint} ").strip().lower()
        return default if not ans else ans.startswith("y")

    def record(step, state, detail, fix=""):
        results.append(Result(step, state, detail, fix))
        log(f"  {MARK[state]} {step}: {detail}" + (f"\n      → {fix}" if fix and state != OK else ""))

    cfg = env.config()
    demo_name, live_name = cfg["demo_model_name"], cfg["model_name"]
    log("FolioScreen setup" + (" — check only, nothing will be changed" if check_only else ""))
    log("")

    # 1 ---------------------------------------------------------------- Python environment
    py_ok, missing = env.python_ok()
    if not py_ok or missing:
        record("Python environment", FAIL,
               (f"Python {sys.version_info.major}.{sys.version_info.minor}; needs {REQUIRED_PY[0]}.{REQUIRED_PY[1]}+" if not py_ok else "")
               + (f" missing packages: {', '.join(missing)}" if missing else ""),
               "python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt")
        return _summary(results, log)
    record("Python environment", OK, f"Python {sys.version_info.major}.{sys.version_info.minor}, packages installed")

    # 2 ---------------------------------------------------------------- Microsoft sign-in
    why = env.ms_signed_in()
    if why:
        log("\n  FolioScreen publishes to your own Power BI 'My workspace' (free). Sign-in opens a browser once;")
        log(f"  the sign-in is cached securely ({_store()}) so nightly runs need no browser.")
        if ask_yes("Sign in to Microsoft now?"):
            user = env.ms_login()
            record("Microsoft sign-in", OK, f"signed in as {user}")
        else:
            record("Microsoft sign-in", TODO, "not signed in", "python -m folio auth login")
            return _summary(results, log)
    else:
        record("Microsoft sign-in", OK, "silent sign-in works")

    # 3 ---------------------------------------------------------------- demo report
    if env.find("reports", demo_name):
        record("Demo report", OK, f"{demo_name} is in My workspace")
    else:
        log("\n  The demo report uses a fictional portfolio: every page complete, no other accounts needed.")
        log("  Publishing it uses one of the model's 8 daily refreshes.")
        if ask_yes(f"Publish the demo report ({demo_name}) now?"):
            code = env.deploy(demo=True)
            if code == 0 and env.find("reports", demo_name):
                record("Demo report", OK, f"{demo_name} published")
            else:
                record("Demo report", FAIL, f"deploy ended with code {code}", "python -m folio deploy --demo")
                return _summary(results, log)
        else:
            record("Demo report", TODO, "not published", "python -m folio deploy --demo")

    # ---------------------------------------------------------------- own data (optional)
    keys_present = env.secret_set("snaptrade_client_id") and env.secret_set("snaptrade_consumer_key")
    if not check_only and not keys_present:
        log("\n  Next, optionally: your own portfolio. This needs free SnapTrade Personal API keys (read-only brokerage")
        log("  access) and a free Tiingo API key (daily closing prices). The SnapTrade Sandbox lets you rehearse")
        log("  with simulated data first. Check both services' current terms and limits on their own websites.")
        if not ask_yes("Connect your own data now?", default=False):
            record("Own data", SKIP, "not set up (optional)", "python -m folio setup   (any time)")
            return _summary(results, log)
    elif check_only and not keys_present:
        record("SnapTrade keys", SKIP, "not set up (optional: only needed for your own data)", "python -m folio setup")
        return _summary(results, log)

    # 4 ---------------------------------------------------------------- SnapTrade keys
    if not keys_present:
        log("\n  Create a SnapTrade account, generate Personal API keys (client ID and consumer key) in its dashboard,")
        log(f"  then paste them at the hidden prompts. They are stored only in your {_store()}.")
        env.store_secrets("snaptrade")
    try:
        conns = env.snaptrade_connections()
        record("SnapTrade keys", OK, "SnapTrade accepts the keys")
    except Exception as exc:
        record("SnapTrade keys", FAIL, f"SnapTrade rejected the request ({str(exc)[:120]})",
               "check the keys in your SnapTrade dashboard, then: python -m folio secrets set snaptrade")
        return _summary(results, log)

    # 5 ---------------------------------------------------------------- brokerage connection
    def describe(cs: list) -> tuple:
        sb = sum(_is_sandbox(c) for c in cs)
        trade = [c for c in cs if str(c.get("type")).lower() == "trade"]
        disabled = [c for c in cs if c.get("disabled")]
        return sb, len(cs) - sb, trade, disabled

    if not conns and not check_only:
        log("\n  No brokerage is connected yet. The Sandbox (simulated data) is the safest first connection:")
        log("  it proves the whole pipeline before any real account is involved. Connections are read-only.")
        sandbox = ask_yes("Connect the SnapTrade Sandbox (simulated) first?")
        log(f"\n  Open this link in your browser:\n  {env.connect_link(sandbox=sandbox)}")
        env.ask("  Press Enter when the connection is complete… ")
        conns = env.snaptrade_connections()
    sb, real, trade, disabled = describe(conns)
    if not conns:
        record("Brokerage connection", TODO, "none connected", "python -m folio connect --sandbox   (or connect for a real broker)")
        return _summary(results, log)
    if trade and not cfg.get("allow_trade_connections"):
        record("Brokerage connection", FAIL, f"{len(trade)} connection(s) have trading access; FolioScreen needs read-only",
               "remove it in SnapTrade, then: python -m folio connect")
        return _summary(results, log)
    if disabled:
        record("Brokerage connection", FAIL, f"{len(disabled)} connection(s) are disabled at the brokerage",
               "reconnect: python -m folio connect")
        return _summary(results, log)
    record("Brokerage connection", OK, f"{sb} Sandbox, {real} real, all read-only")

    # 6 ---------------------------------------------------------------- Tiingo key
    if not env.secret_set("tiingo_token"):
        if check_only:
            record("Tiingo key", TODO, "not stored", "python -m folio secrets set tiingo")
            return _summary(results, log)
        log("\n  Tiingo supplies daily closing prices. Create a free account, copy your API token, and paste it at the")
        log("  hidden prompt. FolioScreen uses one request per ticker per refresh.")
        env.store_secrets("tiingo")
    why = env.tiingo_ok()
    if why:
        record("Tiingo key", FAIL, why, "check the token at tiingo.com, then: python -m folio secrets set tiingo")
        return _summary(results, log)
    record("Tiingo key", OK, "Tiingo accepts the token")

    # 7 ---------------------------------------------------------------- live model
    mid = env.find("semanticModels", live_name)
    if not mid:
        if not ask_yes(f"Publish your live model and report ({live_name}) now?"):
            record("Live model", TODO, "not published", "python -m folio deploy")
            return _summary(results, log)
        env.deploy(demo=False)
        mid = env.find("semanticModels", live_name)
        if not mid:
            record("Live model", FAIL, "deploy did not create the model", "python -m folio deploy")
            return _summary(results, log)
        _credential_steps(env, mid, check_only)
    record("Live model", OK, f"{live_name} is in My workspace")

    # 8 ---------------------------------------------------------------- first sync
    when = env.last_live_success(live_name)
    if not when:
        if env.last_outcome() == "CREDENTIALS_REQUIRED":
            _credential_steps(env, mid, check_only)
        if ask_yes("Run the first sync now (fetch, reconcile, publish, verify)?"):
            code = env.sync()
            when = env.last_live_success(live_name)
            if code != 0 or not when:
                record("First sync", FAIL, f"sync ended with code {code} ({env.last_outcome() or 'see the log'})",
                       "python -m folio status")
                return _summary(results, log)
        else:
            record("First sync", TODO, "no verified sync yet", "python -m folio sync")
            return _summary(results, log)
    record("First sync", OK, f"last verified sync {when}")

    # 9 ---------------------------------------------------------------- nightly schedule
    st = env.schedule_status()
    if st.get("installed") and st.get("loaded", True):
        t = st.get("time") or {}
        record("Nightly schedule", OK, f"daily at {t.get('Hour', '?'):02}:{t.get('Minute', 0):02}" if isinstance(t, dict) and "Hour" in t
               else "installed")
    elif ask_yes("Install the nightly sync (default 21:30, after the US close)?"):
        hhmm = (env.ask("  Time (HH:MM, Enter for 21:30): ").strip() or "21:30")
        env.schedule_install(hhmm)
        record("Nightly schedule", OK, f"daily at {hhmm}")
    else:
        record("Nightly schedule", TODO, "not installed", "python -m folio schedule install --time 21:30")

    # 10 --------------------------------------------------------------- Power BI's own price refresh
    st = env.schedule_status()
    t = st.get("time") if st.get("installed") else None
    sync_hhmm = f"{t['Hour']:02}:{t.get('Minute', 0):02}" if isinstance(t, dict) and "Hour" in t else cfg.get("schedule_time", "21:30")
    local_tz = env.local_timezone()
    state, detail = price_refresh_state(env.price_schedule(mid), sync_hhmm, local_tz)
    if state != OK and not check_only:
        log(f"  {MARK[state]} Price refresh in Power BI: {detail}")
        log(f"\n  Power BI can refresh prices on its own, so the report stays current even when the {DEVICE} is off.")
        log(f"  It should run well apart from the {DEVICE}'s sync: each refresh counts towards 8 per day, and two at once compete.")
        if ask_yes(f"Set Power BI's price refresh to {PRICE_REFRESH_LOCAL} daily, your time (email on failure)?"):
            win = IANA_TO_WINDOWS.get(local_tz)
            if win:   # in your own time zone: follows daylight saving time
                env.set_price_schedule(mid, PRICE_REFRESH_LOCAL, win)
            else:     # time zone without a known Windows ID: the equivalent UTC time today
                from datetime import datetime
                from zoneinfo import ZoneInfo
                d = datetime.now(ZoneInfo(local_tz)).replace(hour=7, minute=0).astimezone(ZoneInfo("UTC"))
                env.set_price_schedule(mid, f"{d.hour:02}:{d.minute:02}", "UTC")
            state, detail = price_refresh_state(env.price_schedule(mid), sync_hhmm, local_tz)
    record("Price refresh in Power BI", state, detail, f"python -m folio setup   (sets {PRICE_REFRESH_LOCAL} daily)")
    return _summary(results, log)


def _credential_steps(env: Env, model_id: str, check_only: bool) -> None:
    env.log("\n  One step in Power BI, once: the Tiingo price query needs its credential set.")
    env.log(f"  1. Open: https://app.powerbi.com/groups/me/settings/datasets/{model_id}")
    env.log("  2. Data source credentials → api.tiingo.com → Edit credentials")
    env.log("  3. Authentication method: Anonymous; tick 'Skip test connection'; Sign in")
    env.log(f"  (The token itself stays in the model's parameters, written by folio sync from your {_store()}.)")
    if not check_only:
        env.ask("  Press Enter when done… ")


def _summary(results: list, log) -> int:
    log("")
    todo = [r for r in results if r.state in (TODO, FAIL)]
    if not todo:
        log("Setup complete." if any(r.step == "Nightly schedule" for r in results) else "Ready.")
    else:
        log("Next:")
        for r in todo:
            log(f"  {MARK[r.state]} {r.step}: {r.fix}")
    return 1 if any(r.state == FAIL for r in results) else 0
