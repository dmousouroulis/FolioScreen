"""Synthetic demo portfolio: fictional securities, generated prices, no external connections.

The generator emits data in SnapTrade's response shape, so the demo runs through exactly the
same normalize -> reconcile -> model pipeline as a real brokerage sync.

All securities are invented; tickers end in ".X" so they cannot be mistaken for real listings.
Scenario "issues" deliberately removes or corrupts records to exercise every reconciliation path.
"""
from __future__ import annotations

import math
import random
import uuid
from datetime import date, timedelta

BENCHMARK_SYMBOL = "MKT.X"
BENCHMARK = "MKT-X"  # Tiingo-style ticker produced by normalize.tiingo_ticker

SECURITIES = {
    # symbol: (name, kind, start price, annual drift, annual vol, quarterly dividend per share)
    "NRTH.X": ("Northwind Systems", "stock", 84.0, 0.14, 0.28, 0.0),
    "BRCH.X": ("Birchline Logistics", "stock", 120.0, 0.10, 0.24, 0.0),
    "SOLR.X": ("Solaris Grid", "stock", 42.0, 0.18, 0.35, 0.0),
    "QNTM.X": ("Quantum Broad Market ETF", "etf", 210.0, 0.09, 0.15, 0.0),
    "HRZN.X": ("Horizon Dividend ETF", "etf", 58.0, 0.06, 0.12, 0.42),
    BENCHMARK_SYMBOL: ("FolioScreen Demo Market Index", "etf", 400.0, 0.08, 0.16, 0.0),
}
SPLIT_SYMBOL, SPLIT_RATIO, SPLIT_DAY = "BRCH.X", 2.0, 300


def tiingo_style(symbol: str) -> str:
    return symbol.replace(".", "-")


def business_days(start: date, end: date) -> list:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def generate(as_of: date, scenario: str = "clean", days: int = 730) -> dict:
    """Returns {"snapshot": SnapTrade-shaped dict, "prices": {ticker: [(date, close, adj, div, split)]}}"""
    rng = random.Random(20261110)
    cal = business_days(as_of - timedelta(days=days), as_of - timedelta(days=1))
    if not cal:
        raise ValueError("Demo calendar is empty")

    # ------------------------------------------------ prices (raw close; split applied to raw)
    prices, close = {}, {}
    for sym, (_, _, p0, mu, vol, div) in SECURITIES.items():
        p, series = p0, []
        dt = 1 / 252
        for i, d in enumerate(cal):
            if i:
                p *= math.exp((mu - 0.5 * vol * vol) * dt + vol * math.sqrt(dt) * rng.gauss(0, 1))
            factor = SPLIT_RATIO if (sym == SPLIT_SYMBOL and i >= SPLIT_DAY) else 1.0
            raw = round(p / factor, 2)
            div_cash = div if (div and i % 63 == 40) else 0.0
            split = SPLIT_RATIO if (sym == SPLIT_SYMBOL and i == SPLIT_DAY) else 1.0
            series.append((d.isoformat(), raw, raw, div_cash, split))
            close[(sym, i)] = raw
        prices[tiingo_style(sym)] = series

    # ------------------------------------------------ transactions (the "truth")
    acts = {"A": [], "B": []}
    units = {"A": {}, "B": {}}
    cost = {"A": {}, "B": {}}
    cashbal = {"A": 0.0, "B": 0.0}

    def act(acct, i, typ, sym=None, qty=0.0, amount=0.0, fee=0.0, price=None):
        acts[acct].append({
            "id": str(uuid.UUID(int=rng.getrandbits(128))), "type": typ,
            "trade_date": cal[i].isoformat() + "T00:00:00Z", "settlement_date": None,
            "symbol": ({"symbol": sym, "raw_symbol": sym.split(".")[0], "currency": {"code": "USD"},
                        "exchange": None, "description": SECURITIES[sym][0]} if sym else None),
            "option_symbol": None, "units": qty, "price": price, "amount": round(amount, 2),
            "currency": {"code": "USD"}, "fee": fee, "description": typ.title(),
        })
        cashbal[acct] = round(cashbal[acct] + round(amount, 2), 2)

    def trade(acct, i, sym, qty, fee=0.0):
        px = close[(sym, i)]
        if qty > 0:
            act(acct, i, "BUY", sym, qty, -(qty * px) - fee, fee, px)
            cost[acct][sym] = cost[acct].get(sym, 0.0) + qty * px + fee
        else:
            held = units[acct].get(sym, 0.0)
            avg = cost[acct][sym] / held
            act(acct, i, "SELL", sym, qty, (-qty) * px - fee, fee, px)
            cost[acct][sym] -= avg * (-qty)
        units[acct][sym] = units[acct].get(sym, 0.0) + qty

    n = len(cal)
    act("A", 0, "CONTRIBUTION", amount=30000.0)
    trade("A", 1, "NRTH.X", 100, 1.0)
    trade("A", 1, "BRCH.X", 60, 1.0)
    trade("A", 2, "QNTM.X", 40, 1.0)
    act("B", 20, "CONTRIBUTION", amount=15000.0)
    trade("B", 21, "HRZN.X", 120, 0.0)
    trade("B", 21, "SOLR.X", 80, 0.0)
    month = None
    for i in range(3, n):
        d = cal[i]
        if d.month != month:
            month = d.month
            act("A", i, "CONTRIBUTION", amount=750.0)
            sym = "QNTM.X" if month % 2 else "HRZN.X"
            qty = math.floor(700 / close[(sym, i)])
            if qty:
                trade("A", i, sym, qty, 0.5)
            if i > 21:
                act("B", i, "INTEREST", amount=round(cashbal["B"] * 0.004 / 12, 2) or 0.01)
        if i == SPLIT_DAY:
            extra = units["A"].get(SPLIT_SYMBOL, 0.0) * (SPLIT_RATIO - 1)
            act("A", i, "SPLIT", SPLIT_SYMBOL, extra, 0.0)
            units["A"][SPLIT_SYMBOL] += extra
        if i == 200:
            trade("A", i, "NRTH.X", -30, 1.0)
        if i == 420:
            act("A", i, "WITHDRAWAL", amount=-2000.0)
        if i % 63 == 40:
            for acct in ("A", "B"):
                held = units[acct].get("HRZN.X", 0.0)
                if held:
                    act(acct, i, "DIVIDEND", "HRZN.X", 0.0, held * SECURITIES["HRZN.X"][5])
        if i % 63 == 10:
            act("A", i, "FEE", amount=-25.0)

    last = n - 1
    accounts_raw = []
    for acct, name in (("A", "Individual"), ("B", "Retirement")):
        acct_id = str(uuid.UUID(int=rng.getrandbits(128)))
        positions = []
        for sym, u in sorted(units[acct].items()):
            if abs(u) < 1e-9:
                continue
            positions.append({
                "instrument": {"kind": SECURITIES[sym][1], "symbol": sym, "raw_symbol": sym.split(".")[0],
                               "description": SECURITIES[sym][0], "currency": "USD", "exchange": None},
                "units": u, "price": close[(sym, last)], "cost_basis": round(cost[acct][sym] / u, 4),
                "currency": "USD", "cash_equivalent": False,
            })
        first_i = 0 if acct == "A" else 20
        activities = list(reversed(acts[acct]))  # SnapTrade returns newest first
        tx_first = cal[first_i].isoformat()
        if scenario == "issues" and acct == "B":
            # Brokerage history only reaches back to day 150: earlier buys are missing.
            cutoff = cal[150].isoformat()
            activities = [a for a in activities if a["trade_date"][:10] >= cutoff]
            tx_first = cutoff
        if scenario == "issues" and acct == "A":
            # An unmapped brokerage type, and a missing SELL record.
            activities.insert(5, {"id": str(uuid.UUID(int=rng.getrandbits(128))), "type": "JNL_ADJ",
                                  "trade_date": cal[500].isoformat() + "T00:00:00Z", "symbol": None,
                                  "option_symbol": None, "units": 0.0, "price": None, "amount": 100.0,
                                  "currency": {"code": "USD"}, "fee": 0.0, "description": "Journal"})
            activities = [a for a in activities if not (a["type"] == "SELL" and a["trade_date"][:10] == cal[200].isoformat())]
        accounts_raw.append({
            "account": {"id": acct_id, "brokerage_authorization": "demo-connection", "name": f"Demo {name}",
                        "number": "DEMO0000", "institution_name": "FolioScreen Demo Brokerage",
                        "sync_status": {"transactions": {"initial_sync_completed": True, "first_transaction_date": tx_first,
                                                         "last_successful_sync": cal[last].isoformat()},
                                        "holdings": {"initial_sync_completed": True,
                                                     "last_successful_sync": cal[last].isoformat() + " 22:00:00+00:00"}}},
            "balances": [{"currency": {"code": "USD"}, "cash": cashbal[acct], "buying_power": cashbal[acct]}],
            "positions": {"results": positions, "data_freshness": {"as_of": cal[last].isoformat() + "T22:00:00Z"}},
            "activities": activities,
        })
    snapshot = {
        "connections": [{"id": "demo-connection", "type": "read", "disabled": False,
                         "brokerage": {"name": "FolioScreen Demo Brokerage"}}],
        "accounts": accounts_raw,
        "fetch_stats": {"calls": 0, "retries": 0, "rate_headers": {}},
    }
    return {"snapshot": snapshot, "prices": prices}


def close_series(prices: dict) -> dict:
    """{ticker: [(date, close)]} for the reference engine."""
    return {t: [(r[0], r[1]) for r in rows] for t, rows in prices.items()}
