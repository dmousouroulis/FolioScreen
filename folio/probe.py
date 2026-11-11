"""SnapTrade Personal capability probe (requirement 5).

Calls only read-only endpoints, then writes a sanitized report: connection access types and
freshness modes, sync status dates, transaction-type counts, history depth, how BUY amounts
relate to units x price and fees, rate-limit headers actually returned, and reconciliation issue
counts. It contains no account identifiers, no amounts and no holdings.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date

from . import paths
from .normalize import holdings_sync, normalize, num
from .reconcile import reconcile, summary
from .snaptrade_source import READ_ONLY_CALLS


def run(reader) -> dict:
    api = reader.status()
    snap = reader.fetch_snapshot()
    report = {
        "generated": date.today().isoformat(),
        "auth_mode": "Personal API key (no userId/userSecret sent)",
        "api_status": {k: api.get(k) for k in ("online", "version") if isinstance(api, dict)},
        "endpoints_called": sorted(READ_ONLY_CALLS - {"authentication.login_snap_trade_user"}),
        "refresh_endpoint_called": False, "trading_endpoints_called": False,
        "connections": [{"broker": (c.get("brokerage") or {}).get("name"), "access_type": c.get("type"),
                         "disabled": c.get("disabled"), "data_freshness_mode": c.get("data_freshness_mode")}
                        for c in snap["connections"]],
        "accounts": [],
        "fetch_stats": snap.get("fetch_stats"),
    }
    for i, r in enumerate(snap["accounts"], start=1):
        a, acts = r["account"], r["activities"]
        dates = sorted(x.get("trade_date", "")[:10] for x in acts if x.get("trade_date"))
        sync = a.get("sync_status") or {}
        pos = (r["positions"] or {}).get("results", []) if isinstance(r["positions"], dict) else []
        report["accounts"].append({
            "account": f"account {i}", "institution": a.get("institution_name") or "(see connections)", "kind": a.get("kind"),
            "transactions_sync": {k: (sync.get("transactions") or {}).get(k) for k in ("initial_sync_completed", "first_transaction_date", "last_successful_sync")},
            "holdings_sync": {k: holdings_sync(sync).get(k) for k in ("initial_sync_completed", "last_successful_sync")},
            "sync_status_shape": {k: type(v).__name__ for k, v in sync.items()},
            "positions": len(pos), "position_kinds": dict(Counter((p.get("instrument") or {}).get("kind") for p in pos)),
            "positions_with_cost_basis": sum(1 for p in pos if p.get("cost_basis") is not None),
            "positions_data_freshness_as_of": (r["positions"] or {}).get("data_freshness") if isinstance(r["positions"], dict) else None,
            "balance_currencies": sorted({(b.get("currency") or {}).get("code") if isinstance(b.get("currency"), dict) else b.get("currency") for b in r["balances"]}),
            "activities": len(acts), "earliest_trade_date": dates[0] if dates else None, "latest_trade_date": dates[-1] if dates else None,
            "activity_types": dict(Counter(str(x.get("type")) for x in acts).most_common()),
            "buy_amount_convention": _buy_convention(acts),
        })
    norm = normalize(snap, "probe-throwaway-salt", {}, today=date.today().isoformat())
    ds = reconcile(norm, synced_utc="probe", today=date.today().isoformat(), benchmark="SPY", source="probe", tool_version="probe")
    s = summary(ds)
    report["reconciliation"] = {"issues_by_code": s["issues_by_code"], "issues_by_severity": s["issues_by_severity"],
                                "accounts": [{k: v for k, v in acc.items() if k != "account_key"} for acc in s["accounts"]],
                                "portfolio_performance": s["portfolio_performance"]}
    out = paths.reports_dir() / f"probe_{date.today().isoformat()}.json"
    paths.write_private(out, json.dumps(report, indent=2, default=str) + "\n")
    report["_saved_to"] = str(out)
    return report


def _buy_convention(acts: list) -> dict:
    """How does a BUY's amount relate to units x price and the fee? (decides cash reconstruction)"""
    c = Counter()
    for a in acts:
        if str(a.get("type")).upper() != "BUY":
            continue
        u, p, amt, fee = num(a.get("units")), num(a.get("price")), num(a.get("amount")), num(a.get("fee")) or 0.0
        if None in (u, p, amt):
            c["missing_fields"] += 1
            continue
        gross = u * p
        tol = 0.01 + 1e-4 * abs(gross)
        if abs(amt + gross) <= tol and fee == 0:
            c["amount = -units*price (no fee)"] += 1
        elif abs(amt + gross + fee) <= tol:
            c["amount includes fee"] += 1
        elif abs(amt + gross) <= tol:
            c["amount excludes fee"] += 1
        else:
            c["other"] += 1
    return dict(c)


ID_KEYS = {"id", "connection_id", "brokerage_authorization", "institution_account_id", "institution_id",
           "masked_account_number", "number", "display_name", "name", "external_reference_id", "local_id"}


import re as _re
_UUID = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I)


class NotSandbox(RuntimeError):
    pass


def _is_sandbox(conn: dict) -> bool:
    b = conn.get("brokerage") or {}
    names = [str(b.get(k) or "").lower() for k in ("name", "slug", "display_name")] if isinstance(b, dict) else [str(b).lower()]
    return any(n == "sandbox" or n.startswith("sandbox") for n in names)


def _scrub(node, salt: str = "sandbox", parent_key: str = ""):
    """Replace identifier values with stable placeholders. Account/connection names are identifiers;
    a brokerage's or security's descriptive name is kept."""
    import hashlib
    keep_name = parent_key in ("brokerage", "symbol", "instrument", "currency", "exchange", "type")
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in ID_KEYS and isinstance(v, (str, int)) and not (k == "name" and keep_name):
                out[k] = "X" + hashlib.sha256(f"{salt}{v}".encode()).hexdigest()[:8]
            else:
                out[k] = _scrub(v, salt, k)
        return out
    if isinstance(node, list):
        return [_scrub(v, salt, parent_key) for v in node]
    if isinstance(node, str) and _UUID.match(node):
        return "X" + hashlib.sha256(f"{salt}{node}".encode()).hexdigest()[:8]
    return node


def sandbox_dump(reader) -> dict:
    """Full detail of SnapTrade's *simulated* brokerage data, to pin down transaction conventions.
    Refuses to run if any connection is not the Sandbox, so real data can never be dumped."""
    conns = reader.connections()
    if not conns or not all(_is_sandbox(c) for c in conns):
        raise NotSandbox("sandbox-dump only runs when every SnapTrade connection is the Sandbox brokerage. "
                         "Remove real connections first (or use folio probe, which is always sanitized).")
    snap = reader.fetch_snapshot()
    snap = _scrub(snap)
    norm = normalize(snap, "sandbox", {}, today=date.today().isoformat())
    ds = reconcile(norm, synced_utc="sandbox", today=date.today().isoformat(), benchmark="SPY", source="sandbox", tool_version="sandbox")
    out = {"snapshot": snap, "issues": ds["issues"], "units_history": ds["units_history"]}
    path = paths.reports_dir() / "sandbox_snapshot.json"
    paths.write_private(path, json.dumps(out, indent=2, default=str) + "\n")
    lines = []
    for i, r in enumerate(snap["accounts"], start=1):
        lines.append(f"\n=== Sandbox account {i}")
        lines.append("Positions:  symbol | kind | units | price | cost_basis | cash_equivalent")
        res = (r["positions"] or {}).get("results", []) if isinstance(r["positions"], dict) else []
        for p in res:
            ins = p.get("instrument") or {}
            lines.append(f"   {ins.get('symbol')} | {ins.get('kind')} | {p.get('units')} | {p.get('price')} | {p.get('cost_basis')} | {p.get('cash_equivalent')}")
        lines.append(f"Cash: {[(b.get('currency'), b.get('cash')) for b in r['balances']]}")
        lines.append("Activities (oldest first):  date | type | symbol | units | price | amount | fee | description")
        for a in sorted(r["activities"], key=lambda x: str(x.get("trade_date"))):
            sym = (a.get("symbol") or {}).get("symbol") if isinstance(a.get("symbol"), dict) else None
            lines.append(f"   {str(a.get('trade_date'))[:10]} | {a.get('type')} | {sym} | {a.get('units')} | {a.get('price')} | "
                         f"{a.get('amount')} | {a.get('fee')} | {str(a.get('description') or '')[:60]}")
    lines.append("\nReconciliation issues:")
    for i in ds["issues"]:
        lines.append(f"   {i['severity']} {i['code']}: {i['message'][:160]}")
    txt = paths.reports_dir() / "sandbox_snapshot.txt"
    paths.write_private(txt, "\n".join(lines) + "\n")
    return {"json": str(path), "text": str(txt), "printable": "\n".join(lines)}
