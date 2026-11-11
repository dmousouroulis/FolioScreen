"""Independent reference calculation, used to verify the DAX results in Power BI.

It implements exactly the documented rules (docs/methodology.md), not the DAX code:
- Trading calendar: the benchmark's price dates.
- Holdings and cash are end-of-day values from the reconstructed step tables.
- Each holding is valued at its last available close on or before the date (raw close, not adjusted).
- External flows dated after the previous trading date and up to the current one belong to the
  current date (weekend deposits land on the next trading day); flows are end-of-day.
- Daily return r_t = (V_t - F_t) / V_{t-1} - 1, with r_t = 0 when V_{t-1} is zero.
- TWR index starts at 1 on the first trading date on or after the performance start date.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Optional


class PriceBook:
    def __init__(self, prices: dict):
        """prices: {ticker: [(iso_date, close), ...]}"""
        self._dates = {}
        self._closes = {}
        for t, rows in prices.items():
            rows = sorted((d, c) for d, c in rows if c is not None)
            self._dates[t] = [d for d, _ in rows]
            self._closes[t] = [c for _, c in rows]

    def close_on_or_before(self, ticker: str, d: str) -> Optional[float]:
        dates = self._dates.get(ticker)
        if not dates:
            return None
        i = bisect_right(dates, d)
        return self._closes[ticker][i - 1] if i else None

    def dates(self, ticker: str) -> list:
        return list(self._dates.get(ticker, []))


def portfolio_daily(dataset: dict, prices: dict) -> dict:
    book = PriceBook(prices)
    cal = book.dates(dataset["meta"]["benchmark"])
    units = [u for u in dataset["units_history"] if u["ticker"]]
    cash = dataset["cash_history"]
    flows = dataset["flows"]
    missing_price_days = 0
    unvalued_asset_flows = 0
    rows = []
    for idx, d in enumerate(cal, start=1):
        sec = 0.0
        for u in units:
            if u["from_date"] <= d < u["to_date"]:
                px = book.close_on_or_before(u["ticker"], d)
                if px is None:
                    missing_price_days += 1
                else:
                    sec += u["units"] * px
        c = sum(r["cash"] for r in cash if r["from_date"] <= d < r["to_date"])
        prev_d = cal[idx - 2] if idx > 1 else "1900-01-01"
        flow = 0.0
        for f in flows:
            if prev_d < f["date"] <= d:
                if f["kind"] == "CASH":
                    flow += f["amount"]
                else:
                    px = book.close_on_or_before(f["ticker"], d) if f["ticker"] else None
                    if px is None:
                        unvalued_asset_flows += 1
                    else:
                        flow += f["units"] * px
        rows.append({"Date": d, "DateIndex": idx, "SecuritiesValue": sec, "Cash": c, "Flow": flow, "Value": sec + c})

    start = dataset["meta"]["performance_start"]
    start_idx = next((r["DateIndex"] for r in rows if start and r["Date"] >= start), None)
    index = None
    for i, r in enumerate(rows):
        r["PrevValue"] = rows[i - 1]["Value"] if i else None
        if start_idx is not None and r["DateIndex"] > start_idx:
            prev = r["PrevValue"]
            r["DailyReturn"] = 0.0 if not prev else (r["Value"] - r["Flow"]) / prev - 1
            index = index * (1 + r["DailyReturn"])
        else:
            r["DailyReturn"] = None
            if start_idx is not None and r["DateIndex"] == start_idx:
                index = 1.0
        r["TWRIndex"] = index if (start_idx is not None and r["DateIndex"] >= start_idx) else None
    return {"rows": rows, "missing_price_days": missing_price_days, "unvalued_asset_flows": unvalued_asset_flows}


def summary_metrics(dataset: dict, prices: dict) -> dict:
    res = portfolio_daily(dataset, prices)
    rows = res["rows"]
    last = rows[-1] if rows else None
    return {
        "latest_value_date": last["Date"] if last else None,
        "portfolio_value": last["Value"] if last else None,
        "securities_value": last["SecuritiesValue"] if last else None,
        "cash_value": last["Cash"] if last else None,
        "twr_since_start": (last["TWRIndex"] - 1) if last and last["TWRIndex"] is not None else None,
        "missing_price_days": res["missing_price_days"],
        "rows": len(rows),
    }
