"""Sync orchestration: fetch -> normalize -> reconcile -> validate -> publish -> refresh -> verify.

Safety rules (requirement 3):
- Nothing is sent to Power BI unless the fetch AND validation fully succeed (no partial portfolios).
- Only the semantic model is updated by a sync; the report definition is only touched by `folio deploy`.
- After an update the model is refreshed and verified (the refreshed data hash must equal what was
  published). If the refresh fails or verification fails, the last known-good definition is restored
  and refreshed again.
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from . import __version__, paths
from .normalize import normalize
from .reconcile import OPEN_END, reconcile, summary

DEFAULT_CONFIG = {
    "model_name": "FolioScreen-PoC",
    "demo_model_name": "FolioScreen-Demo",
    "benchmark": "SPY",
    "allow_trade_connections": False,
    "stale_after_hours": 36,
    "account_labels": {},
    "type_map": {},
}

EXIT = {"OK": 0, "SKIPPED": 0, "DRY_RUN": 0, "FETCH_FAILED": 2, "AUTH_REQUIRED": 3, "VALIDATION_FAILED": 4,
        "ROLLED_BACK": 5, "ROLLBACK_FAILED": 6, "LOCKED": 7, "POLICY_BLOCKED": 8, "NOT_DEPLOYED": 9,
        "PUBLISH_FAILED_UNCHANGED": 10, "ERROR": 11, "CREDENTIALS_REQUIRED": 12, "FAILED_NO_VERIFIED_VERSION": 13}

CREDENTIAL_MARKERS = ("credential", "DataSourceAccessError", "DM_GWPipeline_Gateway", "Unauthorized",
                      "access to the data source", "AccessUnauthorized")


class SyncError(RuntimeError):
    def __init__(self, outcome: str, message: str):
        super().__init__(message)
        self.outcome = outcome


# ============================================================================ config & state
def config_path() -> Path:
    return paths.state_dir() / "config.json"


def load_config() -> dict:
    p = config_path()
    cfg = dict(DEFAULT_CONFIG)
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    else:
        paths.write_private(p, json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    return cfg


def _state_file(name: str) -> Path:
    return paths.state_dir() / name


def save_state(name: str, obj) -> None:
    paths.write_private(_state_file(name), json.dumps(obj, indent=2, default=str) + "\n")


def load_state(name: str):
    p = _state_file(name)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def record_run(outcome: str, details: dict) -> None:
    """Sanitized run record: statuses and counts only, never amounts or identifiers."""
    entry = {"finished_utc": utcnow(), "outcome": outcome, **details}
    save_state("last_run.json", entry)
    with open(_state_file("history.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    if outcome == "OK":
        save_state("last_success.json", entry)


def utcnow(offset_s: int = 0) -> str:
    t = datetime.now(timezone.utc).timestamp() + offset_s
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


@contextmanager
def single_instance():
    lock = open(_state_file("sync.lock"), "a+", encoding="utf-8")
    try:
        if sys.platform == "win32":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise SyncError("LOCKED", "Another FolioScreen sync is already running.")
    try:
        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            lock.close()


# ============================================================================ dataset
def build_dataset(*, demo: bool, scenario: str = "clean", config: Optional[dict] = None,
                  today: Optional[date] = None, reader=None) -> tuple:
    """Returns (dataset, demo_prices_or_None, fetch_stats)."""
    config = config or load_config()
    today = today or date.today()
    if demo:
        from . import demo as demo_mod
        gen = demo_mod.generate(as_of=today, scenario=scenario)
        snapshot, prices, salt = gen["snapshot"], gen["prices"], "demo-salt-not-secret"
        source, benchmark = f"Demo ({scenario})", demo_mod.BENCHMARK
    else:
        from . import secrets
        from .snaptrade_source import SnapTradeReader, SnapTradeError
        reader = reader or SnapTradeReader(secrets.get("snaptrade_client_id"), secrets.get("snaptrade_consumer_key"))
        try:
            snapshot = reader.fetch_snapshot()
        except SnapTradeError as exc:
            raise SyncError("FETCH_FAILED", str(exc))
        prices, salt, source, benchmark = None, secrets.account_salt(), "SnapTrade", config["benchmark"]
    raw_ids = _raw_ids(snapshot)
    norm = normalize(snapshot, salt, config, today=today.isoformat())
    dataset = reconcile(norm, synced_utc=utcnow(), today=today.isoformat(), benchmark=benchmark,
                        source=source, tool_version=__version__)
    validate(dataset, raw_ids)
    return dataset, prices, snapshot.get("fetch_stats", {})


def _raw_ids(snapshot: dict) -> list:
    ids = [c.get("id") for c in snapshot.get("connections", [])]
    for r in snapshot.get("accounts", []):
        a = r["account"]
        ids += [a.get("id"), a.get("number"), a.get("institution_account_id"), a.get("name"),
                a.get("display_name"), a.get("masked_account_number"), a.get("connection_id")]
    return [str(i) for i in ids if i and len(str(i)) >= 6]


def validate(dataset: dict, raw_ids: list) -> None:
    problems = []
    # 1. reconstruction ends exactly at the reported holdings and cash
    end_units = {}
    for u in dataset["units_history"]:
        if u["to_date"] == OPEN_END:
            end_units[(u["account_key"], u["instrument_key"])] = u["units"]
    for p in dataset["positions"]:
        if p["cash_equivalent"]:
            continue
        got = end_units.get((p["account_key"], p["instrument_key"]))
        if got is None or abs(got - (p["units"] or 0)) > 1e-6:
            problems.append(f"reconstructed units do not end at reported units for {p['instrument_key']}")
    end_cash = {c["account_key"]: c["cash"] for c in dataset["cash_history"] if c["to_date"] == OPEN_END}
    for a in dataset["accounts"]:
        reported = sum(c["amount"] or 0 for c in dataset["cash"] if c["account_key"] == a["account_key"] and c["currency"] == "USD")
        if abs(end_cash.get(a["account_key"], 0.0) - reported) > 0.005:
            problems.append("reconstructed cash does not end at reported cash")
    # 2. tickers safe for the Tickers parameter
    for t in dataset["tickers"]:
        if not t or "," in t or len(t) > 20:
            problems.append(f"invalid ticker '{t}'")
    # 3. no raw brokerage identifiers anywhere in what will be published
    blob = json.dumps(dataset, default=str)
    if any(rid in blob for rid in raw_ids):
        problems.append("a raw brokerage identifier would be published")
    # 4. size guard for embedded tables
    if len(blob) > 25_000_000:
        problems.append("dataset too large to embed")
    if problems:
        raise SyncError("VALIDATION_FAILED", "; ".join(sorted(set(problems))))


def check_policy(dataset: dict, config: dict) -> None:
    trade = [a for a in dataset["accounts"] if a["connection_access"] == "trade"]
    if trade and not config.get("allow_trade_connections"):
        raise SyncError("POLICY_BLOCKED",
                        "A brokerage connection has trading access. Reconnect it as read-only "
                        "(folio connect), or set allow_trade_connections in config.json.")


# ============================================================================ rendering
def render_model(dataset: dict, demo_prices: Optional[dict], name: str) -> dict:
    from .model_writer import render_semantic_model
    token = None
    if demo_prices is None:
        from . import secrets
        token = secrets.get("tiingo_token")
    return render_semantic_model(dataset, demo_prices=demo_prices, tiingo_token=token, name=name)


def render_report_parts(name: str, model_id: str, base_theme: Path) -> list:
    from .model_writer import BASE_THEME_REL
    from .powerbi import parts_from_files
    from .report import render_full_report
    files = render_full_report(name)
    files["definition.pbir"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byConnection": {"connectionString": f"semanticmodelid={model_id}"}}}, indent=2)
    files[BASE_THEME_REL] = base_theme.read_bytes()
    return parts_from_files(files)


VERIFY_DAX = """EVALUATE
ROW (
    "DataHash", [Data Hash],
    "Positions", COUNTROWS ( Positions ),
    "Accounts", COUNTROWS ( Accounts ),
    "PortfolioValue", [Portfolio Value],
    "MissingPriceDays", [Missing Price Days]
)"""


# ============================================================================ publishing
class _Unchanged(Exception):
    pass


class Publisher:
    def __init__(self, pbi, name: str, log=print):
        self.pbi, self.name, self.log = pbi, name, log

    def model_id(self) -> str:
        mid = self.pbi.find_item("semanticModels", self.name)
        if not mid:
            raise SyncError("NOT_DEPLOYED", f"No semantic model named '{self.name}' in My workspace. Run folio deploy first.")
        return mid

    def _apply(self, model_id: str, files: dict) -> dict:
        """Update the definition, then refresh. Returns the refresh result.
        Raises _Unchanged if the definition update itself was rejected (model left as it was)."""
        from .powerbi import PowerBIError, parts_from_files
        started = utcnow(-60)  # tolerate small clock differences with the Service
        try:
            self.pbi.update_definition("semanticModels", model_id, parts_from_files(files), "TMDL")
        except PowerBIError as exc:
            raise _Unchanged(str(exc))
        from .powerbi import RefreshLimitError
        for attempt in range(4):
            try:
                self.pbi.trigger_refresh(model_id)
                break
            except RefreshLimitError as exc:
                self.log(str(exc))
                return {"status": "NotStarted", "error": str(exc)[:300], "refresh_limit": True}
            except PowerBIError as exc:  # e.g. a scheduled refresh is already running
                if attempt == 3:
                    return {"status": "NotStarted", "error": str(exc)[:300]}
                self.log("Refresh request rejected; retrying in 90 s…")
                time.sleep(90)
        return self.pbi.wait_for_refresh(model_id, started, progress=self.log)

    def settings(self, model_id: str) -> dict:
        """Refresh schedule and data-source credentials binding, captured around every update."""
        from .powerbi import PowerBIError
        out = {}
        for key, fn in (("schedule", self.pbi.refresh_schedule), ("datasources", self.pbi.datasources)):
            try:
                out[key] = fn(model_id)
            except (PowerBIError, AttributeError) as exc:
                out[key] = {"unavailable": str(exc)[:150]}
        return out

    @staticmethod
    def compare_settings(before: dict, after: dict) -> dict:
        changed = [k for k in ("schedule", "datasources") if before.get(k) != after.get(k)]
        return {"preserved": not changed, "changed": changed, "schedule_enabled": (after.get("schedule") or {}).get("enabled")}

    def verify(self, model_id: str, expected_hash: str) -> dict:
        from .powerbi import PowerBIError
        try:
            rows = self.pbi.execute_dax(model_id, VERIFY_DAX)
        except PowerBIError as exc:
            return {"verified": None, "note": f"executeQueries unavailable: {str(exc)[:200]}"}
        row = {k.strip("[]"): v for k, v in (rows[0] if rows else {}).items()}
        got = row.get("DataHash")
        return {"verified": got == expected_hash, "data_hash_seen": got, "positions": row.get("Positions"),
                "missing_price_days": row.get("MissingPriceDays")}

    def publish(self, files: dict, expected_hash: str, rollback_files: Optional[dict], rollback_hash: Optional[str]) -> dict:
        mid = self.model_id()
        before = self.settings(mid)
        self.log("Updating semantic model definition and refreshing…")
        try:
            res = self._apply(mid, files)
        except _Unchanged as exc:
            return {"outcome": "PUBLISH_FAILED_UNCHANGED", "error": str(exc)[:300]}
        result = {"refresh": res}
        if res["status"] == "Completed":
            v = self.verify(mid, expected_hash)
            result["verification"] = v
            if v["verified"] is not False:
                result["outcome"] = "OK"
                result["settings"] = self.compare_settings(before, self.settings(mid))
                return result
            self.log("Verification failed: refreshed data hash differs from what was published.")
        else:
            self.log(f"Refresh did not complete ({res['status']}).")
        credentials = any(m.lower() in (res.get("error") or "").lower() for m in CREDENTIAL_MARKERS)
        if not rollback_files:
            result["outcome"] = "CREDENTIALS_REQUIRED" if credentials else "FAILED_NO_VERIFIED_VERSION"
            result["rollback"] = "no verified version exists yet, so there is nothing to restore"
            return result
        result.update(self.restore(mid, rollback_files, rollback_hash))
        if credentials and result["outcome"] == "ROLLED_BACK":
            result["outcome"] = "CREDENTIALS_REQUIRED"
        return result

    def restore(self, mid: str, files: dict, good_hash: Optional[str]) -> dict:
        """Put back the last verified definition. A failed refresh leaves the previous data in place
        (measured by folio safety-test), so the definition is restored without a refresh whenever the
        model still serves the verified data. Only otherwise is it refreshed (one more Tiingo round)."""
        from .powerbi import PowerBIError, parts_from_files
        self.log("Restoring the last verified model definition…")
        try:
            self.pbi.update_definition("semanticModels", mid, parts_from_files(files), "TMDL")
        except PowerBIError as exc:
            return {"outcome": "ROLLBACK_FAILED", "rollback": str(exc)[:300]}
        v = self.verify(mid, good_hash) if good_hash else {"verified": None}
        if v["verified"] is True:
            return {"outcome": "ROLLED_BACK", "rollback_verification": v, "rollback_refreshed": False}
        self.log("The model is not serving the verified data; refreshing the restored definition…")
        from .powerbi import RefreshLimitError
        for attempt in range(4):
            try:
                self.pbi.trigger_refresh(mid)
                break
            except RefreshLimitError as exc:
                return {"outcome": "ROLLBACK_FAILED", "rollback": str(exc)[:300]}
            except PowerBIError:
                if attempt == 3:
                    return {"outcome": "ROLLBACK_FAILED", "rollback": "refresh could not be started"}
                time.sleep(90)
        rb = self.pbi.wait_for_refresh(mid, utcnow(-60), progress=self.log)
        if rb["status"] != "Completed":
            return {"outcome": "ROLLBACK_FAILED", "rollback_refresh": rb}
        v = self.verify(mid, good_hash) if good_hash else {"verified": None}
        return {"outcome": "ROLLED_BACK" if v["verified"] is not False else "ROLLBACK_FAILED",
                "rollback_refresh": rb, "rollback_verification": v, "rollback_refreshed": True}


def known_good(name: str) -> tuple:
    """(dataset, demo_prices) of the last definition that refreshed and verified successfully."""
    obj = load_state(f"known_good_{name}.json")
    return (obj["dataset"], obj.get("demo_prices")) if obj else (None, None)


def remember_good(name: str, dataset: dict, demo_prices: Optional[dict]) -> None:
    save_state(f"known_good_{name}.json", {"dataset": dataset, "demo_prices": demo_prices})


# ============================================================================ commands
def run_sync(*, demo: bool = False, dry_run: bool = False, scheduled: bool = False, force: bool = False,
             log=print, pbi=None) -> int:
    config = load_config()
    name = config["demo_model_name"] if demo else config["model_name"]
    t0 = time.time()
    if scheduled:
        base_log = log
        log = lambda msg: base_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
        log(f"Scheduled run started (FolioScreen {__version__}).")
    if scheduled and not force:
        last = load_state("last_success.json")
        slot = last_scheduled_slot(config.get("schedule_time"))
        if last and _already_synced_since(last["finished_utc"], slot):
            log(f"Already synced successfully since the scheduled time {slot}; nothing to do.")
            return EXIT["SKIPPED"]
    try:
        with single_instance():
            log("Fetching portfolio data…" if not demo else "Generating demo data…")
            dataset, demo_prices, fetch_stats = build_dataset(demo=demo, config=config)
            check_policy(dataset, config)
            s = summary(dataset)
            paths.write_private(paths.reports_dir() / "last_sync_summary.json", json.dumps(s, indent=2) + "\n")
            log(f"Accounts {len(s['accounts'])}, positions {s['positions']}, activities {s['activities']}, "
                f"issues {s['issues_by_severity']}, performance {s['portfolio_performance']}")
            if dry_run:
                record_run("DRY_RUN", {"summary": s, "fetch": fetch_stats})
                log(f"Dry run: nothing sent to Power BI. Summary: {paths.reports_dir() / 'last_sync_summary.json'}")
                return EXIT["OK"]
            if pbi is None:
                from .powerbi import MicrosoftAuth, PowerBI
                pbi = PowerBI(MicrosoftAuth(interactive=False))
            files = render_model(dataset, demo_prices, name)
            good_ds, good_prices = known_good(name)
            rb_files = render_model(good_ds, good_prices, name) if good_ds else None
            result = Publisher(pbi, name, log).publish(files, dataset["meta"]["data_hash"], rb_files,
                                                       good_ds["meta"]["data_hash"] if good_ds else None)
            outcome = result["outcome"]
            if outcome == "OK":
                remember_good(name, dataset, demo_prices)
                st = result.get("settings") or {}
                if st and not st.get("preserved"):
                    log(f"WARNING: Power BI settings changed during the update: {st.get('changed')}")
                    _notify(f"Sync OK, but these model settings changed: {', '.join(st.get('changed', []))}. Check the refresh schedule and credentials.")
                elif not demo and st.get("schedule_enabled") is False:
                    log("Note: no refresh schedule is set on this model (prices only update when you sync).")
            record_run(outcome, {"model": name, "seconds": round(time.time() - t0), "result": result,
                                 "fetch": fetch_stats, "data_hash": dataset["meta"]["data_hash"]})
            log(f"Sync outcome: {outcome}")
            if outcome == "CREDENTIALS_REQUIRED":
                log("Power BI could not use the api.tiingo.com credential. In the model settings set it to Anonymous, "
                    "privacy Organizational, tick 'Skip test connection', then run folio sync again.")
                _notify("Set the api.tiingo.com credential (Anonymous) in the model settings, then run folio sync.")
            elif outcome != "OK":
                _notify(f"Sync {outcome.replace('_', ' ').lower()}. Report keeps the previous data; run folio status.")
            return EXIT[outcome]
    except SyncError as exc:
        record_run(exc.outcome, {"model": name, "message": str(exc)})
        log(f"{exc.outcome}: {exc}")
        _notify(f"Sync stopped: {str(exc)[:120]}")
        return EXIT[exc.outcome]
    except Exception as exc:  # AuthRequired and anything unexpected
        from .powerbi import AuthRequired
        outcome = "AUTH_REQUIRED" if isinstance(exc, AuthRequired) else "ERROR"
        record_run(outcome, {"model": name, "message": f"{type(exc).__name__}: {str(exc)[:300]}"})
        log(f"{outcome}: {exc}")
        _notify("Microsoft sign-in needed: run folio auth login" if outcome == "AUTH_REQUIRED" else "Sync failed; run folio status")
        return EXIT[outcome]


def last_scheduled_slot(hhmm: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """Most recent local scheduled time at or before now, e.g. '2026-11-10 21:30'."""
    if not hhmm:
        return None
    from datetime import timedelta
    now = now or datetime.now()
    h, m = (int(x) for x in hhmm.split(":"))
    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    return slot.strftime("%Y-%m-%d %H:%M")


def _already_synced_since(last_success_utc: str, slot_local: Optional[str]) -> bool:
    if slot_local is None:  # schedule time unknown: fall back to "within the last 18 hours"
        return _hours_since(last_success_utc) < 18
    success_local = datetime.strptime(last_success_utc[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).astimezone()
    return success_local.strftime("%Y-%m-%d %H:%M") >= slot_local


def _hours_since(iso: str) -> float:
    t = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def _notify(text: str) -> None:
    from .notify import notify
    notify("FolioScreen", text)


def deploy(*, demo: bool, scenario: str, base_theme: Path, log=print, refresh: bool = True) -> int:
    from .powerbi import MicrosoftAuth, PowerBI, RefreshLimitError, parts_from_files
    config = load_config()
    name = config["demo_model_name"] if demo else config["model_name"]
    pbi = PowerBI(MicrosoftAuth(interactive=False))
    dataset, demo_prices, _ = build_dataset(demo=demo, scenario=scenario, config=config)
    check_policy(dataset, config)
    files = render_model(dataset, demo_prices, name)
    parts = parts_from_files(files)
    mid = pbi.find_item("semanticModels", name)
    created = not mid
    if mid:
        log(f"Updating semantic model {name}")
        pbi.update_definition("semanticModels", mid, parts, "TMDL")
    else:
        log(f"Creating semantic model {name}")
        mid = pbi.create_item("semanticModels", name, parts, "TMDL")
    rparts = render_report_parts(name, mid, base_theme)
    rid = pbi.find_item("reports", name)
    if rid:
        log(f"Updating report {name}")
        pbi.update_definition("reports", rid, rparts, "PBIR")
    else:
        log(f"Creating report {name}")
        rid = pbi.create_item("reports", name, rparts, "PBIR")
    ws = pbi.my_workspace_id()
    save_state(f"deployment_{name}.json", {"model_id": mid, "report_id": rid, "workspace_id": ws, "deployed_utc": utcnow()})
    log(f"Report:         https://app.powerbi.com/groups/me/reports/{rid}")
    log(f"Model settings: https://app.powerbi.com/groups/me/settings/datasets/{mid}")
    if demo:
        save_state(f"demo_inputs_{name}.json", {"dataset": dataset, "prices": demo_prices})
        if not refresh:
            log("Refresh skipped (--no-refresh). The model keeps serving the data from its last refresh;")
            log("report and measure changes are live now. Check with: folio check-report --demo")
            return 0
        started = utcnow(-60)
        try:
            pbi.trigger_refresh(mid)
        except RefreshLimitError as exc:
            log(str(exc))
            log("The model and report definitions above were published, and the model keeps serving the data")
            log("from its last refresh, so report and measure changes are live. Check with: folio check-report --demo")
            return 0
        res = pbi.wait_for_refresh(mid, started, progress=log)
        log(f"Initial refresh: {res['status']} {res.get('error') or ''}")
        if res["status"] == "Completed":
            v = Publisher(pbi, name, log).verify(mid, dataset["meta"]["data_hash"])
            log(f"Verification: {v}")
            remember_good(name, dataset, demo_prices)
        return 0 if res["status"] == "Completed" else 5
    if created:
        log("Next: in the model settings set the api.tiingo.com credential to Anonymous, tick 'Skip test connection',")
        log("      then run: folio sync")
    else:
        log("Definitions published. The model keeps its data until the next sync (folio sync, or tonight's schedule).")
    return 0


def _demo_prices_from_state(name: str) -> tuple:
    obj = load_state(f"demo_inputs_{name}.json")
    if not obj:
        raise SyncError("NOT_DEPLOYED", "No demo deployment recorded. Run: folio deploy --demo")
    return obj["dataset"], obj["prices"]


def verify_calculations(*, demo: bool, log=print, tolerance: float = 0.01) -> dict:
    """Compares Power BI's Portfolio Daily table with the Python reference engine, row by row."""
    from .engine import portfolio_daily
    from .powerbi import MicrosoftAuth, PowerBI
    config = load_config()
    name = config["demo_model_name"] if demo else config["model_name"]
    pbi = PowerBI(MicrosoftAuth(interactive=False))
    mid = Publisher(pbi, name, log).model_id()
    if demo:
        dataset, prices = _demo_prices_from_state(name)
        closes = {t: [(r[0], r[1]) for r in rows] for t, rows in prices.items()}
    else:
        dataset, _ = known_good(name)
        if not dataset:
            raise SyncError("NOT_DEPLOYED", "No successful live sync recorded yet.")
        closes = fetch_tiingo_closes(dataset["tickers"], dataset["meta"]["price_start"])
    expected = {r["Date"]: r for r in portfolio_daily(dataset, closes)["rows"]}
    rows = pbi.execute_dax(mid, "EVALUATE SELECTCOLUMNS ( 'Portfolio Daily', \"Date\", 'Portfolio Daily'[Date], "
                                "\"Value\", 'Portfolio Daily'[Value], \"Flow\", 'Portfolio Daily'[Flow], "
                                "\"TWRIndex\", 'Portfolio Daily'[TWRIndex] )")
    if not rows:
        out = {"model": name, "passed": False, "rows_python": len(expected), "rows_powerbi": 0,
               "problem": "The model has no data yet: it has never refreshed successfully. Check the api.tiingo.com "
                          "credential (Anonymous, Skip test connection) and run folio sync."}
        paths.write_private(paths.reports_dir() / f"verify_{name}.json", json.dumps(out, indent=2) + "\n")
        return out
    got = {}
    for r in rows:
        r = {k.split("[")[-1].strip("]"): v for k, v in r.items()}
        got[str(r["Date"])[:10]] = r
    mism = []
    for d, e in expected.items():
        g = got.get(d)
        if g is None:
            mism.append({"date": d, "problem": "missing in Power BI"})
            continue
        for col, tol in (("Value", tolerance), ("Flow", tolerance)):
            if abs((g.get(col) or 0) - e[col]) > tol:
                mism.append({"date": d, "column": col, "powerbi": g.get(col), "python": e[col]})
        ei, gi = e["TWRIndex"], g.get("TWRIndex")
        if (ei is None) != (gi is None) or (ei is not None and abs(gi - ei) > 1e-9 * max(1, abs(ei))):
            mism.append({"date": d, "column": "TWRIndex", "powerbi": gi, "python": ei})
    extra = sorted(set(got) - set(expected))
    out = {"model": name, "rows_python": len(expected), "rows_powerbi": len(got), "extra_dates_in_powerbi": extra[:5],
           "mismatches": len(mism), "first_mismatches": mism[:10], "passed": not mism and not extra}
    if not demo:  # live amounts never leave the Mac: keep only the counts in the saved report
        out["first_mismatches"] = [{k: v for k, v in m.items() if k in ("date", "column", "problem")} for m in mism[:10]]
    paths.write_private(paths.reports_dir() / f"verify_{name}.json", json.dumps(out, indent=2) + "\n")
    return out


def fetch_tiingo_prices(tickers: list, start: str) -> dict:
    """{ticker: [(date, close, adjClose, divCash, splitFactor)]}: the same shape as the demo prices. One request per ticker."""
    import requests
    from . import secrets
    token = secrets.get("tiingo_token")
    out = {}
    for t in tickers:
        r = requests.get(f"https://api.tiingo.com/tiingo/daily/{t}/prices", params={"startDate": start, "token": token}, timeout=60)
        if r.status_code != 200:
            raise SyncError("FETCH_FAILED", f"Tiingo returned HTTP {r.status_code} for {t}")
        out[t] = [(row["date"][:10], row["close"], row.get("adjClose"), row.get("divCash", 0.0), row.get("splitFactor", 1.0))
                  for row in r.json()]
    return out


def fetch_tiingo_closes(tickers: list, start: str) -> dict:
    import requests
    from . import secrets
    token = secrets.get("tiingo_token")
    out = {}
    for t in tickers:
        r = requests.get(f"https://api.tiingo.com/tiingo/daily/{t}/prices", params={"startDate": start, "token": token}, timeout=60)
        if r.status_code != 200:
            raise SyncError("FETCH_FAILED", f"Tiingo returned HTTP {r.status_code} for {t}")
        out[t] = [(row["date"][:10], row["close"]) for row in r.json()]
    return out


def inject_refresh_error(prices_tmdl: str) -> str:
    """Make the Prices partition fail at refresh time, keeping TMDL indentation intact."""
    lines = prices_tmdl.split("\n")
    for i, line in enumerate(lines):
        if "Source = #table(" in line:
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = (indent + 'Source = error Error.Record("FolioScreen.SafetyTest", "Intentional refresh failure"),\n'
                        + line.replace("Source = #table(", "Unused = #table(", 1))
            return "\n".join(lines)
    raise ValueError("Prices partition has no #table to replace")


def safety_test(*, log=print) -> dict:
    """Requirement 3 test on the demo model: what survives a definition update, and does rollback work?"""
    from .powerbi import MicrosoftAuth, PowerBI, PowerBIError
    config = load_config()
    name = config["demo_model_name"]
    pbi = PowerBI(MicrosoftAuth(interactive=False))
    dep = load_state(f"deployment_{name}.json")
    if not dep:
        raise SyncError("NOT_DEPLOYED", "Run folio deploy --demo first.")
    mid, rid = dep["model_id"], dep["report_id"]
    pub = Publisher(pbi, name, log)

    def snap(label):
        s = {"label": label}
        for key, fn in (("schedule", lambda: pbi.refresh_schedule(mid)), ("datasources", lambda: pbi.datasources(mid)),
                        ("report_binding", lambda: pbi.report_binding(rid)), ("data", lambda: pub.verify(mid, "?"))):
            try:
                s[key] = fn()
            except PowerBIError as exc:
                s[key] = {"error": str(exc)[:200]}
        return s

    report = {"model": name, "steps": []}
    base_ds, base_prices = known_good(name)
    if not base_ds:
        raise SyncError("NOT_DEPLOYED", "No verified demo deployment yet. Run folio deploy --demo.")
    log("Step 1/4: recording current settings and data…")
    before = snap("before")
    report["steps"].append(before)

    # A: definition update only (no refresh): does the old data stay queryable, and do settings survive?
    ds_a = dict(base_ds)
    ds_a["meta"] = {**base_ds["meta"], "synced_utc": utcnow(), "source": base_ds["meta"]["source"] + " safety-A"}
    from .reconcile import data_hash
    ds_a["meta"]["data_hash"] = data_hash(ds_a)
    from .powerbi import parts_from_files
    log("Step 2/4: updating the definition without refreshing, then checking what the report serves…")
    pbi.update_definition("semanticModels", mid, parts_from_files(render_model(ds_a, base_prices, name)), "TMDL")
    after_a = snap("after definition update, before refresh")
    report["steps"].append(after_a)

    # B: refresh the updated definition
    log("Step 3/4: refreshing the updated definition…")
    started = utcnow(-60)
    pbi.trigger_refresh(mid)
    res_b = pbi.wait_for_refresh(mid, started, progress=log)
    after_b = snap("after refresh")
    after_b["refresh"] = res_b
    report["steps"].append(after_b)
    if res_b["status"] == "Completed":
        remember_good(name, ds_a, base_prices)

    # C: intentional failure, then automatic rollback through the real publish path
    bad_files = render_model(ds_a, base_prices, name)
    bad_files["definition/tables/Prices.tmdl"] = inject_refresh_error(bad_files["definition/tables/Prices.tmdl"])
    log("Step 4/4: publishing a deliberately broken definition; Power BI retries a failing refresh for several minutes before the automatic rollback…")
    good_ds, good_prices = known_good(name)
    result_c = pub.publish(bad_files, "intentional-failure", render_model(good_ds, good_prices, name), good_ds["meta"]["data_hash"])
    after_c = snap("after intentional failure + rollback")
    after_c["publish_result"] = result_c
    report["steps"].append(after_c)

    def same(key):
        return before.get(key) == after_a.get(key) == after_b.get(key) == after_c.get(key)

    report["checks"] = {
        "schedule_preserved": "n/a on the demo model (no data connection, so Power BI cannot schedule it); checked on every live sync" if before.get("schedule", {}).get("enabled") in (None, False) else same("schedule"),
        "datasources_preserved": same("datasources"),
        "report_binding_preserved": same("report_binding"),
        "data_queryable_between_update_and_refresh": bool((after_a.get("data") or {}).get("data_hash_seen")),
        "old_data_still_served_before_refresh": (after_a.get("data") or {}).get("data_hash_seen") == base_ds["meta"]["data_hash"],
        "refresh_after_update_completed": res_b["status"] == "Completed",
        "failure_detected": result_c.get("refresh", {}).get("status") != "Completed",
        "rollback_outcome": result_c.get("outcome"),
        "data_after_rollback_is_known_good": (after_c.get("data") or {}).get("data_hash_seen") == good_ds["meta"]["data_hash"],
    }
    paths.write_private(paths.reports_dir() / "safety_test.json", json.dumps(report, indent=2, default=str) + "\n")
    return report
