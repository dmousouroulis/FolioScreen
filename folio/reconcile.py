"""Reconciliation and history reconstruction.

Policy (docs/reconciliation-policy.md):
- Today's holdings and cash are exactly what the brokerage reports.
- History is reconstructed *backwards* from those values using the reported transactions:
  units(d) = reported units today - sum(units of transactions dated after d).
- No deposit, withdrawal, opening balance or any other transaction is ever generated.
  When the transactions cannot explain the reported values, an Issue is raised and the
  affected calculations are marked Partial, Incomplete or Unavailable.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from .normalize import EPS, NON_CASH_AMOUNT_CLASSES, Issue, Normalized

UNITS_CLASSES = {"TRADE", "CORPORATE", "EXTERNAL_ASSET", "ADJUSTMENT", "UNCLASSIFIED"}  # not CASH_EQUIVALENT_TRADE
OPEN_END = "9999-12-31"
STATUS_RANK = {"Complete": 0, "Partial": 1, "Incomplete": 2, "Unavailable": 3}


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _minus_day(s: str) -> str:
    return (_d(s) - timedelta(days=1)).isoformat()


def _plus_day(s: str) -> str:
    return (_d(s) + timedelta(days=1)).isoformat()


def _step_series(start: str, opening: float, changes: dict) -> list:
    """[(from, to_exclusive, value)] beginning at `start` with `opening`, applying dated changes."""
    rows, cur, frm = [], opening, start
    for d in sorted(changes):
        if d <= frm:  # changes on the start date apply from the start date itself
            cur += changes[d]
            continue
        rows.append((frm, d, cur))
        cur += changes[d]
        frm = d
    rows.append((frm, OPEN_END, cur))
    # merge consecutive equal values
    merged = []
    for r in rows:
        if merged and abs(merged[-1][2] - r[2]) < EPS:
            merged[-1] = (merged[-1][0], r[1], merged[-1][2])
        else:
            merged.append(r)
    return merged


def reconcile(norm: Normalized, *, synced_utc: str, today: str, benchmark: str, source: str,
              tool_version: str) -> dict:
    issues: list = list(norm.issues)
    units_history, cash_history, flows = [], [], []
    acct_out = []

    acts_by_acct = defaultdict(list)
    for a in norm.activities:
        if a["trade_date"]:
            acts_by_acct[a["account_key"]].append(a)

    for acct in norm.accounts:
        akey = acct["account_key"]
        acts = sorted(acts_by_acct.get(akey, []), key=lambda a: a["trade_date"])
        first_act = acts[0]["trade_date"] if acts else None
        candidates = [x for x in (acct.get("tx_first_date"), first_act) if x]
        history_start = min(candidates) if candidates else None

        # ------------------------------------------------ units per instrument
        positions = [p for p in norm.positions if p["account_key"] == akey and not p["cash_equivalent"]]
        current = defaultdict(float)
        ticker_of = {}
        for p in positions:
            current[p["instrument_key"]] += p["units"] or 0.0
            if p["ticker"]:
                ticker_of[p["instrument_key"]] = p["ticker"]
        changes = defaultdict(lambda: defaultdict(float))
        for a in acts:
            if a["class"] in UNITS_CLASSES and a["instrument_key"] and abs(a["units"]) > EPS:
                changes[a["instrument_key"]][a["trade_date"]] += a["units"]
                if a["ticker"] and a["instrument_key"] not in ticker_of:
                    ticker_of[a["instrument_key"]] = a["ticker"]

        opening_empty = True
        for inst in sorted(set(current) | set(changes)):
            ch = changes.get(inst, {})
            opening = current.get(inst, 0.0) - sum(ch.values())
            if abs(opening) > EPS:
                opening_empty = False
            start = history_start or today
            series = _step_series(start, opening, ch) if history_start else [(today, OPEN_END, current.get(inst, 0.0))]
            negative = []
            for frm, to, u in series:
                units_history.append({"account_key": akey, "instrument_key": inst, "ticker": ticker_of.get(inst),
                                      "from_date": frm, "to_date": to, "units": round(u, 10)})
                if u < -EPS and to != OPEN_END:
                    negative.append((frm, to, u))
            if negative:
                first, last, low = negative[0][0], _minus_day(negative[-1][1]), min(n[2] for n in negative)
                issues.append(Issue("Error", "NEGATIVE_UNITS_IN_HISTORY",
                                    f"The brokerage reports {current.get(inst, 0.0):g} units of {inst} today, but its transactions add up to "
                                    f"{sum(ch.values()):+g}, which implies as low as {low:g} units between {first} and {last}. "
                                    f"A sale, transfer-out or corporate action is missing or misreported in the brokerage history.",
                                    account_key=akey, instrument_key=inst, affects_from=first, affects_to=last,
                                    perf_effect="unavailable_until"))
            if history_start and opening > EPS:
                issues.append(Issue("Warning", "HELD_BEFORE_HISTORY_START",
                                    f"{opening:g} units of {inst} were already held when the available history begins ({history_start}). "
                                    f"Values from {history_start} are reconstructed; cost basis uses the brokerage's reported figure and "
                                    f"realized gains on these units are unavailable.",
                                    account_key=akey, instrument_key=inst, affects="Cost basis & realized P&L",
                                    affects_to=history_start))

        # ------------------------------------------------ USD cash
        usd_now = [c["amount"] for c in norm.cash if c["account_key"] == akey and c["currency"] == "USD" and c["amount"] is not None]
        cash_now = sum(usd_now)
        cash_changes = defaultdict(float)
        for a in acts:
            if a["class"] in NON_CASH_AMOUNT_CLASSES:
                continue
            if (a["currency"] in (None, "USD")) and abs(a["amount"]) > EPS:
                cash_changes[a["trade_date"]] += a["amount"]
        if history_start:
            opening_cash = cash_now - sum(cash_changes.values())
            cseries = _step_series(history_start, opening_cash, cash_changes)
        else:
            opening_cash = cash_now
            cseries = [(today, OPEN_END, cash_now)]
        if abs(opening_cash) > 0.005:
            opening_empty = False
        for frm, to, c in cseries:
            cash_history.append({"account_key": akey, "from_date": frm, "to_date": to, "cash": round(c, 6)})
        if history_start and min(c for _, _, c in cseries) < -0.01:
            issues.append(Issue("Warning", "CASH_HISTORY_NEGATIVE",
                                "Reported transactions imply a negative cash balance at some point in the history "
                                "(margin borrowing, or deposits/fees missing from the brokerage history). Performance is marked Incomplete.",
                                account_key=akey, affects_from=history_start, perf_effect="incomplete"))

        # ------------------------------------------------ external flows
        for a in acts:
            if a["class"] == "EXTERNAL_CASH" and abs(a["amount"]) > EPS:
                flows.append({"account_key": akey, "date": a["trade_date"], "kind": "CASH",
                              "amount": a["amount"], "ticker": None, "units": 0.0})
            elif a["class"] == "EXTERNAL_ASSET" and abs(a["units"]) > EPS:
                t = ticker_of.get(a["instrument_key"]) if a["instrument_key"] else None
                flows.append({"account_key": akey, "date": a["trade_date"], "kind": "ASSET",
                              "amount": 0.0, "ticker": t, "units": a["units"]})
                if not t:
                    issues.append(Issue("Error", "UNPRICED_TRANSFER",
                                        f"Asset transfer of {a['instrument_key']} on {a['trade_date']} cannot be valued in USD.",
                                        account_key=akey, affects_from=a["trade_date"], affects_to=a["trade_date"],
                                        perf_effect="unavailable_until"))


        acct_out.append({**acct, "history_start": history_start, "opening_empty": bool(history_start) and opening_empty})

    # ------------------------------------------------ performance availability
    for acct in acct_out:
        akey = acct["account_key"]
        mine = [i for i in issues if i.account_key == akey]
        start = acct["history_start"]
        status = "Complete" if start else "Unavailable"
        for i in mine:
            if i.perf_effect == "unavailable":
                status = "Unavailable"
            elif i.perf_effect == "unavailable_until" and start and i.affects_to:
                start = max(start, _plus_day(i.affects_to))
        if status != "Unavailable" and start and start > today:
            status = "Unavailable"
        if status != "Unavailable":
            if any(i.perf_effect == "incomplete" for i in mine):
                status = "Incomplete"
            elif start != acct["history_start"]:
                status = "Partial"
        acct["performance_start"] = start if status != "Unavailable" else None
        acct["performance_status"] = status

    active = [a for a in acct_out if _account_has_data(a["account_key"], norm)]
    if not active or any(a["performance_status"] == "Unavailable" for a in active):
        p_status, p_start = "Unavailable", None
    else:
        # An account whose reconstructed opening state is empty (no units, no cash) and whose start
        # was not moved by an issue was worth zero before its first transaction: it does not limit
        # the portfolio's performance start.
        earliest = min(a["history_start"] for a in active)
        limiting = [a["performance_start"] for a in active
                    if not (a["opening_empty"] and a["performance_start"] == a["history_start"])]
        p_start = max(limiting) if limiting else earliest
        p_status = max((a["performance_status"] for a in active), key=lambda s: STATUS_RANK[s])
        if p_status == "Complete" and p_start != earliest:
            p_status = "Partial"

    priced_held = sorted({u["ticker"] for u in units_history if u["ticker"] and abs(u["units"]) > EPS})
    tickers = sorted(set(priced_held) | {benchmark})
    starts = [u["from_date"] for u in units_history if u["ticker"] and abs(u["units"]) > EPS]
    price_start = (_d(min(starts)) - timedelta(days=10)).isoformat() if starts else (_d(today) - timedelta(days=30)).isoformat()

    label_of = {a["account_key"]: a["label"] for a in acct_out}
    issue_rows = []
    for i in issues:
        d = i.to_dict()
        d["account_label"] = label_of.get(i.account_key)
        d["issue_key"] = hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]
        issue_rows.append(d)

    dataset = {
        "meta": {"source": source, "synced_utc": synced_utc, "today": today, "tool_version": tool_version,
                 "benchmark": benchmark, "price_start": price_start,
                 "performance_start": p_start, "performance_status": p_status,
                 "account_count": len(acct_out), "activity_count": len(norm.activities)},
        "accounts": acct_out,
        "positions": norm.positions,
        "cash": norm.cash,
        "activities": norm.activities,
        "units_history": units_history,
        "cash_history": cash_history,
        "flows": flows,
        "issues": issue_rows,
        "tickers": tickers,
    }
    dataset["meta"]["data_hash"] = data_hash(dataset)
    return dataset


def _account_has_data(akey: str, norm: Normalized) -> bool:
    return any(p["account_key"] == akey for p in norm.positions) or \
        any(c["account_key"] == akey and c["amount"] for c in norm.cash) or \
        any(a["account_key"] == akey for a in norm.activities)


def data_hash(dataset: dict) -> str:
    body = {k: v for k, v in dataset.items() if k != "meta"}
    body["meta"] = {k: v for k, v in dataset["meta"].items() if k != "data_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def summary(dataset: dict) -> dict:
    """Sanitized summary: counts and statuses only (safe to paste into a chat)."""
    sev = defaultdict(int)
    codes = defaultdict(int)
    for i in dataset["issues"]:
        sev[i["severity"]] += 1
        codes[i["code"]] += 1
    m = dataset["meta"]
    return {
        "source": m["source"], "synced_utc": m["synced_utc"], "data_hash": m["data_hash"],
        "accounts": [{"account_key": a["account_key"], "history_start": a["history_start"],
                      "performance_start": a["performance_start"], "performance_status": a["performance_status"],
                      "connection_access": a["connection_access"], "connection_status": a["connection_status"]}
                     for a in dataset["accounts"]],
        "positions": len(dataset["positions"]), "priced_tickers": len(dataset["tickers"]) - 1,
        "activities": len(dataset["activities"]),
        "activity_types": dict(sorted(_type_counts(dataset).items())),
        "issues_by_severity": dict(sev), "issues_by_code": dict(sorted(codes.items())),
        "portfolio_performance": {"status": m["performance_status"], "start": m["performance_start"]},
    }


def _type_counts(dataset: dict) -> dict:
    c = defaultdict(int)
    for a in dataset["activities"]:
        c[a["type"] or "(blank)"] += 1
    return c
