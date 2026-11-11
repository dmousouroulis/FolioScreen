"""`folio check-report`: verifies the deployed report model against an independent Python calculation.

1. Every measure is evaluated once (in batches; a failing batch is retried one measure at a time), so a DAX error is
   reported by name instead of showing up as a broken visual.
2. Every calculated table behind the report has rows.
3. Key figures are compared with Python: portfolio value, deposits, gain and its breakdown, today's change, the
   time-weighted and benchmark return, drawdown, volatility and best/worst day for every period, the money-weighted
   return, and value, day change and unrealized gain per holding.
"""
from __future__ import annotations

import json
import math
import statistics
from calendar import monthrange
from datetime import date, datetime

from . import paths

EXCLUDED_CLASSES = {"EXTERNAL_ASSET", "EXTERNAL_CASH", "CASH_EQUIVALENT_TRADE"}
PERIODS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "ALL": 0}


# ============================================================================ Python reference
def _edate(d: date, months: int) -> date:
    y, mth = d.year, d.month - months
    while mth <= 0:
        mth += 12
        y -= 1
    return date(y, mth, min(d.day, monthrange(y, mth)[1]))


def _xirr(cfs: list) -> float:
    t0 = cfs[0][0]

    def npv(r):
        return sum(a / (1 + r) ** ((d - t0).days / 365.0) for d, a in cfs)
    lo, hi = -0.99, 10.0
    for _ in range(300):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if npv(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def expected_figures(dataset: dict, prices: dict) -> dict:
    from .engine import PriceBook, portfolio_daily
    closes = {t: [(r[0], r[1]) for r in rows] for t, rows in prices.items()}
    rows = portfolio_daily(dataset, closes)["rows"]
    book = PriceBook(closes)
    bench = dataset["meta"]["benchmark"]
    perf = [r for r in rows if r.get("TWRIndex") is not None]
    last, prev = rows[-1], rows[-2]
    out = {"Day Change": last["Value"] - last["Flow"] - prev["Value"]}
    out["Day Change %"] = out["Day Change"] / prev["Value"]
    out["Portfolio Value"] = last["Value"]
    if not perf:
        # Performance unavailable (history does not reconcile): every 'since start' and period figure must be BLANK
        for k in ("Net Deposits", "Total Gain", "Money Weighted Return", "Account Fees", "Dividends and Interest"):
            out[k] = None
        for p in PERIODS:
            for n in ("Window TWR", "Window Benchmark", "Window Max Drawdown", "Window Volatility", "Window Best Day", "Window Worst Day"):
                out[f"{n}|{p}"] = None
        out.update(_holding_figures(dataset, prices, last))
        return out
    first = perf[0]
    v0 = first["Value"]
    nd = v0 + sum(r["Flow"] for r in rows if r["Date"] > first["Date"])
    out["Portfolio Value"] = last["Value"]
    out["Net Deposits"] = nd
    out["Total Gain"] = last["Value"] - nd
    out["Day Change"] = last["Value"] - last["Flow"] - prev["Value"]
    out["Day Change %"] = out["Day Change"] / prev["Value"]
    # money-weighted return since start
    cfs = [(datetime.fromisoformat(first["Date"]), -v0)]
    cfs += [(datetime.fromisoformat(r["Date"]), -r["Flow"]) for r in rows if r["Date"] > first["Date"] and abs(r["Flow"]) > 1e-9]
    cfs += [(datetime.fromisoformat(last["Date"]), last["Value"])]
    out["Money Weighted Return"] = _xirr(cfs)
    # period windows
    end = date.fromisoformat(last["Date"])
    for p, months in PERIODS.items():
        if months:
            target = _edate(end, months).isoformat()
            cand = [r for r in perf if r["Date"] <= target]
            s = cand[-1] if cand else first
        else:
            s = first
        seg = [r for r in perf if s["Date"] <= r["Date"] <= last["Date"]]
        idx = [r["TWRIndex"] / s["TWRIndex"] for r in seg]
        peak, mdd = 1.0, 0.0
        for v in idx:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        dr = [idx[i] / idx[i - 1] - 1 for i in range(1, len(idx))]
        b0, b1 = book.close_on_or_before(bench, s["Date"]), book.close_on_or_before(bench, last["Date"])
        out[f"Window TWR|{p}"] = idx[-1] - 1
        out[f"Window Benchmark|{p}"] = b1 / b0 - 1
        out[f"Window Max Drawdown|{p}"] = mdd
        out[f"Window Volatility|{p}"] = statistics.pstdev(dr) * math.sqrt(252) if len(dr) > 1 else None
        out[f"Window Best Day|{p}"] = max(dr) if dr else None
        out[f"Window Worst Day|{p}"] = min(dr) if dr else None
    out.update(_holding_figures(dataset, prices, last))
    _gain_figures(dataset, book, rows, first, last, out)
    return out


def _holding_figures(dataset: dict, prices: dict, last: dict) -> dict:
    out = {}
    split_after = {}
    for t, series in prices.items():
        splits = [(r[0], r[4]) for r in series if len(r) > 4 and r[4] and r[4] != 1]
        split_after[t] = splits

    def adj(t, d, cl):
        f = 1.0
        for sd, fac in split_after.get(t, []):
            if sd > d:
                f *= fac
        return cl / f
    hold = {}
    for pos in dataset["positions"]:
        if not pos.get("priced", True):
            continue
        h = hold.setdefault(pos["instrument_key"], {"t": pos["ticker"], "units": 0.0, "cost": 0.0, "cost_ok": True})
        h["units"] += pos["units"]
        if pos.get("broker_cost_basis") is None:
            h["cost_ok"] = False
        else:
            h["cost"] += pos["units"] * pos["broker_cost_basis"]
    total = sum(c["amount"] for c in dataset["cash"])
    for k, h in hold.items():
        series = [r for r in prices[h["t"]] if r[0] <= last["Date"]]
        (d1, c1), (d0, c0) = (series[-1][0], series[-1][1]), (series[-2][0], series[-2][1])
        h["value"] = h["units"] * c1
        total += h["value"]
        out[f"H Value|{k}"] = h["value"]
        out[f"H Day %|{k}"] = adj(h["t"], d1, c1) / adj(h["t"], d0, c0) - 1
        if h["cost_ok"]:
            out[f"H Unrealized|{k}"] = h["value"] - h["cost"]
    for k, h in hold.items():
        out[f"H Weight|{k}"] = h["value"] / total
    for k, h in hold.items():
        out[f"H Units|{k}"] = h["units"]
    for c in dataset["cash"]:
        out[f"Acct Cash|{c['account_key']}"] = out.get(f"Acct Cash|{c['account_key']}", 0.0) + c["amount"]
    sec_total = sum(h["value"] for h in hold.values())
    out["Largest Holding Weight"] = max(h["value"] for h in hold.values()) / total
    out["Effective Holdings"] = 1 / sum((h["value"] / sec_total) ** 2 for h in hold.values())
    if all(h["cost_ok"] for h in hold.values()):
        out["Unrealized Gain"] = sum(h["value"] - h["cost"] for h in hold.values())
    return out


def _gain_figures(dataset: dict, book, rows: list, first: dict, last: dict, out: dict) -> None:
    """Gain breakdown (cash-flow based, per security, since the performance start)."""
    s_date, e_date = first["Date"], last["Date"]
    units_on = {}
    for u in dataset["units_history"]:
        if u.get("ticker"):
            units_on.setdefault((u["instrument_key"], u["ticker"]), []).append(u)

    def value_on(key, t, d):
        segs = units_on.get((key, t), [])
        units = sum(u["units"] for u in segs if u["from_date"] <= d < u["to_date"])
        cl = book.close_on_or_before(t, d)
        return units * cl if cl is not None else 0.0
    sec_keys = {k for k, _ in units_on}
    acts = [a for a in dataset["activities"] if s_date < a["trade_date"] <= e_date and a["class"] not in EXCLUDED_CLASSES]
    breakdown = {}
    for (k, t) in units_on:
        cash = sum(a["amount"] for a in acts if a.get("instrument_key") == k)
        asset_in = sum(f["units"] * (book.close_on_or_before(t, f["date"]) or 0) for f in dataset["flows"]
                       if f["kind"] != "CASH" and f.get("ticker") == t and s_date < f["date"] <= e_date)
        breakdown[k] = value_on(k, t, e_date) - value_on(k, t, s_date) + cash - asset_in
    other = [a for a in acts if a.get("instrument_key") not in sec_keys]
    breakdown["Interest"] = sum(a["amount"] for a in other if a["class"] == "INCOME")
    breakdown["Fees"] = sum(a["amount"] for a in other if a["class"] == "COST")
    misc = sum(a["amount"] for a in other if a["class"] not in ("INCOME", "COST"))
    if abs(misc) > 1e-9:
        breakdown["Adjustments"] = misc
    for k, v in breakdown.items():
        out[f"Gain|{k}"] = v
    out["Gain Breakdown Gap"] = out["Total Gain"] - sum(breakdown.values())
    out["Account Fees"] = breakdown["Fees"]
    sec_income = sum(a["amount"] for a in acts if a.get("instrument_key") in sec_keys and a["class"] == "INCOME")
    out["Dividends and Interest"] = sec_income + breakdown["Interest"]


# ============================================================================ Power BI side
def _key(row: dict, name: str):
    for k in (f"[{name}]", name):
        if k in row:
            return row[k]
    for k, v in row.items():
        if k.endswith(f"[{name}]"):
            return v
    return None


def check(pbi, model_id: str, dataset: dict, prices: dict, log=print) -> dict:
    from .model_writer import MEASURES
    from .powerbi import PowerBIError
    from .report_model import REPORT_TABLES, report_measures
    result = {"measure_errors": {}, "empty_tables": [], "comparisons": [], "passed": False}
    names = [n for n, *_ in MEASURES] + [n for n, *_ in report_measures()]

    def one_row(dax: str) -> dict:
        rows = pbi.execute_dax(model_id, dax)
        if not rows:
            raise PowerBIError("query returned no rows (an expression failed)")
        return rows[0]

    def run_batch(batch):
        one_row("EVALUATE ROW ( " + ", ".join(f'"c{i}", [{n}]' for i, n in enumerate(batch)) + " )")
    log(f"Evaluating {len(names)} measures…")
    for i in range(0, len(names), 20):
        batch = names[i:i + 20]
        try:
            run_batch(batch)
        except PowerBIError:
            for n in batch:
                try:
                    run_batch([n])
                except PowerBIError as e:
                    result["measure_errors"][n] = str(e)[:400]
    log("Counting calculated-table rows…")
    counts = one_row("EVALUATE ROW ( " + ", ".join(
        f'"t{i}", COUNTROWS ( \'{t}\' )' for i, t in enumerate(list(REPORT_TABLES) + ["Chart Metric"])) + " )")
    no_perf = dataset["meta"].get("performance_start") is None
    for i, t in enumerate(list(REPORT_TABLES) + ["Chart Metric"]):
        if not _key(counts, f"t{i}") and not (no_perf and t == "Gain Breakdown"):
            result["empty_tables"].append(t)

    log("Comparing figures with the Python reference…")
    exp = expected_figures(dataset, prices)
    got = {}
    top = [n for n in ("Portfolio Value", "Net Deposits", "Total Gain", "Day Change", "Day Change %", "Money Weighted Return",
                       "Unrealized Gain", "Account Fees", "Dividends and Interest", "Gain Breakdown Gap", "Largest Holding Weight",
                       "Effective Holdings") if n in exp and n not in result["measure_errors"]]
    result["query_errors"] = {}

    def guarded(label, fn):
        try:
            fn()
        except PowerBIError as e:
            result["query_errors"][label] = str(e)[:400]

    def q_top():
        row = one_row("EVALUATE ROW ( " + ", ".join(f'"c{i}", [{n}]' for i, n in enumerate(top)) + " )")
        for i, n in enumerate(top):
            got[n] = _key(row, f"c{i}")
    guarded("headline figures", q_top)
    wm = [n for n in ("Window TWR", "Window Benchmark", "Window Max Drawdown", "Window Volatility", "Window Best Day", "Window Worst Day")
          if n not in result["measure_errors"]]

    def q_periods():
        for r in pbi.execute_dax(model_id, "EVALUATE ADDCOLUMNS ( VALUES ( Periods[Period] ), " +
                                 ", ".join(f'"c{i}", CALCULATE ( [{n}] )' for i, n in enumerate(wm)) + " )"):
            p = _key(r, "Period")
            for i, n in enumerate(wm):
                got[f"{n}|{p}"] = _key(r, f"c{i}")
    if wm:
        guarded("period figures", q_periods)
    hm = [n for n in ("H Value", "H Day %", "H Unrealized", "H Weight", "H Units") if n not in result["measure_errors"]]

    def q_holdings():
        for r in pbi.execute_dax(model_id, "EVALUATE ADDCOLUMNS ( VALUES ( 'Holding Rows'[Symbol] ), " +
                                 ", ".join(f'"c{i}", CALCULATE ( [{n}] )' for i, n in enumerate(hm)) + " )"):
            sym = _key(r, "Symbol")
            for i, n in enumerate(hm):
                got[f"{n}|{sym}"] = _key(r, f"c{i}")
    if hm:
        guarded("holding figures", q_holdings)

    def q_accounts():
        for r in pbi.execute_dax(model_id, "EVALUATE ADDCOLUMNS ( VALUES ( 'Account List'[AccountKey] ), \"c0\", CALCULATE ( [Acct Cash] ) )"):
            got[f"Acct Cash|{_key(r, 'AccountKey')}"] = _key(r, "c0") or 0.0
    if "Acct Cash" not in result["measure_errors"]:
        guarded("account cash", q_accounts)

    def q_gain():
        for r in pbi.execute_dax(model_id, "EVALUATE SELECTCOLUMNS ( 'Gain Breakdown', \"L\", 'Gain Breakdown'[Label], \"A\", 'Gain Breakdown'[Amount] )"):
            got[f"Gain|{_key(r, 'L')}"] = _key(r, "A")
    guarded("gain breakdown", q_gain)
    ok = True
    for k, e in exp.items():
        g = got.get(k)
        money = not any(x in k for x in ("%", "TWR", "Benchmark", "Drawdown", "Volatility", "Day|", "Weight", "Return", "Effective", "Best", "Worst"))
        tol = 1e-6 if k.startswith("H Units|") else (0.01 if money else 1e-4)
        passed = (e is None and g is None) or (e is not None and g is not None and abs(float(g) - e) <= tol)
        ok &= passed
        result["comparisons"].append({"figure": k, "python": e, "power_bi": g, "passed": passed})
    result["passed"] = ok and not result["measure_errors"] and not result["empty_tables"] and not result["query_errors"]
    return result


def run(*, demo: bool, log=print) -> int:
    from .powerbi import MicrosoftAuth, PowerBI
    from .sync import Publisher, _demo_prices_from_state, known_good, load_config
    config = load_config()
    name = config["demo_model_name"] if demo else config["model_name"]
    pbi = PowerBI(MicrosoftAuth(interactive=False))
    mid = Publisher(pbi, name, log).model_id()
    if demo:
        dataset, prices = _demo_prices_from_state(name)
    else:
        from .sync import fetch_tiingo_prices
        dataset, _ = known_good(name)
        if not dataset:
            log("No verified live sync yet. Run: folio sync")
            return 9
        row = pbi.execute_dax(mid, 'EVALUATE ROW ( "d", [Latest Value Date] )')
        model_date = str(_key(row[0], "d") or "")[:10] if row else ""
        log(f"Fetching Tiingo prices for {len(dataset['tickers'])} tickers (one request each), up to the model's close {model_date}…")
        prices = fetch_tiingo_prices(dataset["tickers"], dataset["meta"]["price_start"])
        if model_date:
            prices = {t: [r for r in rows if r[0] <= model_date] for t, rows in prices.items()}
    res = check(pbi, mid, dataset, prices, log)
    paths.write_private(paths.reports_dir() / f"check_report_{name}.json", json.dumps(res, indent=2, default=str) + "\n")
    for n, e in res["measure_errors"].items():
        log(f"  MEASURE ERROR  {n}: {e}")
    for q, e in res.get("query_errors", {}).items():
        log(f"  QUERY ERROR    {q}: {e}")
    for t in res["empty_tables"]:
        log(f"  EMPTY TABLE    {t}")
    fails = [c for c in res["comparisons"] if not c["passed"]]
    for c in fails:
        log(f"  MISMATCH       {c['figure']}: Python {c['python']}  Power BI {c['power_bi']}")
    log(f"{len(res['comparisons']) - len(fails)}/{len(res['comparisons'])} figures match; "
        f"{len(res['measure_errors'])} measure errors; {len(res['empty_tables'])} empty tables.")
    log("PASSED" if res["passed"] else "FAILED")
    return 0 if res["passed"] else 4
