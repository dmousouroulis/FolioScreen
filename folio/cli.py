"""folio — FolioScreen proof-of-concept command line (run as: python -m folio <command>)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_THEME = ROOT / "assets" / "CY26SU05.json"


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="folio", description="FolioScreen proof of concept")
    sub = ap.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("setup", help="guided first run: demo first, then your own data (asks before each step)")
    st.add_argument("--check", action="store_true", help="report what is set up and what is missing; change nothing")

    s = sub.add_parser("secrets", help="store or check credentials (macOS Keychain / Windows Credential Manager)")
    s.add_argument("action", choices=["set", "status"])
    s.add_argument("group", nargs="?", choices=["snaptrade", "tiingo"])

    c = sub.add_parser("connect", help="print a read-only SnapTrade Connection Portal link")
    c.add_argument("--sandbox", action="store_true", help="go straight to SnapTrade's simulated brokerage")

    pr = sub.add_parser("probe", help="SnapTrade Personal capability probe (read-only, sanitized report)")
    pr.add_argument("--sandbox-dump", action="store_true",
                    help="full detail of the simulated Sandbox brokerage only (refuses if any real connection exists)")

    a = sub.add_parser("auth", help="Microsoft sign-in")
    a.add_argument("action", choices=["login", "test", "logout"])

    b = sub.add_parser("build", help="write the PBIP files to a folder (demo data only)")
    b.add_argument("--out", default="pbip")
    b.add_argument("--scenario", choices=["clean", "issues"], default="clean")

    d = sub.add_parser("deploy", help="create or update the semantic model and report in My workspace")
    d.add_argument("--demo", action="store_true")
    d.add_argument("--scenario", choices=["clean", "issues"], default="clean")
    d.add_argument("--no-refresh", action="store_true",
                   help="publish definitions only (report or measure changes); keeps the model's current data")

    y = sub.add_parser("sync", help="fetch, reconcile and publish (same as the scheduled run)")
    y.add_argument("--demo", action="store_true")
    y.add_argument("--dry-run", action="store_true", help="fetch and reconcile only; nothing sent to Power BI")
    y.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    y.add_argument("--force", action="store_true")
    y.add_argument("--log-file", help=argparse.SUPPRESS)

    v = sub.add_parser("verify", help="compare Power BI's daily values and TWR with the Python reference engine")
    v.add_argument("--demo", action="store_true")

    cr = sub.add_parser("check-report", help="evaluate every report measure and compare key figures with Python (demo data)")
    cr.add_argument("--demo", action="store_true")
    sub.add_parser("safety-test", help="definition-update and rollback test on the demo model")

    vp = sub.add_parser("visual-probe", help="visual capability probe report (fictional demo data)")
    vp.add_argument("action", choices=["build", "deploy"])
    vp.add_argument("--out", default="build/visual-probe")
    sub.add_parser("status", help="last sync outcome, sign-in, schedule and credential status")

    sc = sub.add_parser("schedule", help="nightly launchd job")
    sc.add_argument("action", choices=["install", "uninstall", "status"])
    sc.add_argument("--time", default="21:30", help="local time HH:MM (default 21:30)")

    p = sub.add_parser("privacy-scan", help="scan the repository before committing")
    p.add_argument("path", nargs="?", default=str(ROOT))

    args = ap.parse_args(argv)
    if getattr(args, "log_file", None):  # scheduled runs on Windows: Task Scheduler keeps no output
        Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(args.log_file, "a", encoding="utf-8", buffering=1)
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # concise, sanitized error for anything unexpected
        from .sync import SyncError, EXIT
        if isinstance(exc, SyncError):
            print(f"{exc.outcome}: {exc}", file=sys.stderr)
            return EXIT.get(exc.outcome, 1)
        import traceback
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if "/folio/" in f.filename.replace("\\", "/")]
        where = f" at {frames[-1].filename.split('/folio/')[-1]}:{frames[-1].lineno} in {frames[-1].name}()" if frames else ""
        print(f"ERROR ({type(exc).__name__}{where}): {str(exc)[:500]}", file=sys.stderr)
        return 1


def _dispatch(args) -> int:
    from . import paths, secrets, sync

    if args.cmd == "setup":
        from .setup import Env, run
        return run(check_only=args.check, env=Env(root=ROOT, base_theme=BASE_THEME))

    if args.cmd == "secrets":
        if args.action == "set":
            if not args.group:
                raise SystemExit("Usage: folio secrets set snaptrade|tiingo")
            secrets.prompt_and_store(args.group)
        else:
            _print({n: ("set" if secrets.is_set(n) else "missing") for n in secrets.NAMES})
        return 0

    if args.cmd in ("connect", "probe"):
        from .snaptrade_source import SnapTradeReader
        reader = SnapTradeReader(secrets.get("snaptrade_client_id"), secrets.get("snaptrade_consumer_key"))
        if args.cmd == "connect":
            print("Open this link in your browser (it requests read-only access):")
            print(reader.connection_portal_link(sandbox=args.sandbox))
            return 0
        if args.sandbox_dump:
            from .probe import sandbox_dump
            res = sandbox_dump(reader)
            print(res["printable"])
            print(f"\nSaved: {res['text']}\n       {res['json']}\n(Sandbox data is fictional; identifiers replaced.)")
            return 0
        from .probe import run
        report = run(reader)
        _print(report)
        print(f"\nSaved to {report['_saved_to']} (no identifiers, amounts or holdings).")
        return 0

    if args.cmd == "auth":
        from .powerbi import MicrosoftAuth
        if args.action == "login":
            user = MicrosoftAuth(interactive=True).login()
            print(f"Signed in as {user}. Sign-in cached securely for scheduled runs ({secrets.store_name()} / encrypted token cache).")
        elif args.action == "test":
            _print(MicrosoftAuth(interactive=False).describe())
            print("Silent sign-in works (no browser was opened).")
        else:
            MicrosoftAuth.logout()
            print("Saved sign-in record removed. Scheduled runs will now stop with AUTH_REQUIRED until you run: folio auth login")
        return 0

    if args.cmd == "build":
        from .model_writer import write_pbip
        from .report import render_full_report
        cfg = sync.load_config()
        ds, prices, _ = sync.build_dataset(demo=True, scenario=args.scenario, config=cfg)
        name = "FolioScreen"
        write_pbip(Path(args.out), sync.render_model(ds, prices, name), render_full_report(name), BASE_THEME, name)
        print(f"Wrote demo PBIP ({args.scenario}) to {args.out}/")
        return 0

    if args.cmd == "deploy":
        return sync.deploy(demo=args.demo, scenario=args.scenario, base_theme=BASE_THEME, refresh=not args.no_refresh)

    if args.cmd == "sync":
        return sync.run_sync(demo=args.demo, dry_run=args.dry_run, scheduled=args.scheduled, force=args.force)

    if args.cmd == "verify":
        out = sync.verify_calculations(demo=args.demo)
        _print(out)
        return 0 if out["passed"] else 1

    if args.cmd == "check-report":
        from .report_check import run
        return run(demo=args.demo)
    if args.cmd == "visual-probe":
        from . import visual_probe
        if args.action == "build":
            visual_probe.write_probe_pbip(Path(args.out), BASE_THEME)
            print(f"Wrote the probe PBIP to {args.out}/")
            return 0
        res = visual_probe.deploy(BASE_THEME)
        _print(res)
        print(f"\nOpen the report: {res['report_url']}\nSaved: {paths.reports_dir() / 'visual_probe.json'}")
        return 0

    if args.cmd == "safety-test":
        rep = sync.safety_test()
        _print(rep["checks"])
        print(f"\nFull report: {paths.reports_dir() / 'safety_test.json'}")
        return 0

    if args.cmd == "status":
        from .schedule import status as sched_status
        from .powerbi import RECORD_FILE
        last = sync.load_state("last_run.json") or {}
        ok = sync.load_state("last_success.json") or {}
        res = last.get("result") or {}
        _print({
            "last_run": {k: last.get(k) for k in ("finished_utc", "outcome", "model", "message")},
            "last_run_checks": {"verification": (res.get("verification") or {}).get("verified"),
                                "settings": res.get("settings"), "rollback_refreshed": res.get("rollback_refreshed")},
            "next_scheduled_run_after": sync.load_config().get("schedule_time"),
            "last_success_utc": ok.get("finished_utc"),
            "microsoft_sign_in_saved": (paths.state_dir() / RECORD_FILE).exists(),
            "credentials": {n: ("set" if secrets.is_set(n) else "missing") for n in secrets.NAMES},
            "schedule": sched_status(),
            "log": str(paths.log_dir() / "sync.log"),
        })
        return 0

    if args.cmd == "schedule":
        from . import schedule
        if args.action == "install":
            schedule.install(ROOT, args.time)
        elif args.action == "uninstall":
            schedule.uninstall()
        else:
            _print(schedule.status())
        return 0

    if args.cmd == "privacy-scan":
        from .privacy_scan import scan
        cfg = sync.load_config()
        findings = scan(Path(args.path), secrets.known_secret_values(), list(cfg.get("account_labels", {}).values()))
        for rel, why in findings:
            print(f"  {rel}: {why}")
        print("Privacy scan: clean." if not findings else f"Privacy scan: {len(findings)} finding(s). Fix before committing.")
        return 0 if not findings else 1
    return 2
