"""Regression test on real SnapTrade Sandbox output (Self-directed scenario, captured 10 Nov 2026,
identifiers replaced). The Sandbox is static simulated data: its transactions deliberately do not add up
to its reported holdings for some symbols, so the expected results below are hand-checked:

  NVDA  reported 12, transactions net +21  -> one NEGATIVE_UNITS issue (data inconsistent)
  GOOGL reported 3,  transactions net +4   -> one NEGATIVE_UNITS issue
  AAPL  reported 5,  transactions net +8.0692 -> one NEGATIVE_UNITS issue
  TSLA  reported 8,  transactions net +11  -> one NEGATIVE_UNITS issue
  MSFT  reported 10, transactions net +2.5 -> HELD_BEFORE_HISTORY_START (7.5 units)
  SPY   reported 15, bought 15             -> reconciles
  SPAXX money-market fund counted in cash  -> its BUY moves neither units nor cash
  BTC/ETH/SOL/USDC crypto                  -> UNPRICED_HOLDING, excluded from totals
"""
import json
from collections import Counter
from pathlib import Path

from folio.normalize import normalize
from folio.reconcile import OPEN_END, reconcile

FIXTURE = Path(__file__).parent / "fixtures" / "sandbox_self_directed.json"
TODAY = "2026-11-10"


def dataset():
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    norm = normalize(snap, "test-salt", {}, today=TODAY)
    return reconcile(norm, synced_utc="2026-11-10T17:11:00", today=TODAY, benchmark="SPY", source="sandbox", tool_version="t")


def test_issue_set_matches_hand_check():
    ds = dataset()
    by_code = Counter(i["code"] for i in ds["issues"])
    assert by_code == {"UNPRICED_HOLDING": 4, "CASH_EQUIVALENT_POSITION": 1, "NEGATIVE_UNITS_IN_HISTORY": 4,
                       "HELD_BEFORE_HISTORY_START": 1, "BROKER_ADJUSTMENT": 1}
    negative = sorted(i["instrument_key"] for i in ds["issues"] if i["code"] == "NEGATIVE_UNITS_IN_HISTORY")
    assert negative == ["AAPL", "GOOGL", "NVDA", "TSLA"]
    held = [i for i in ds["issues"] if i["code"] == "HELD_BEFORE_HISTORY_START"][0]
    assert held["instrument_key"] == "MSFT" and "7.5 units" in held["message"]


def test_money_market_trades_move_neither_units_nor_cash():
    ds = dataset()
    assert not [u for u in ds["units_history"] if u["instrument_key"] == "SPAXX"]
    spaxx = [a for a in ds["activities"] if a["instrument_key"] == "SPAXX"]
    assert [a["class"] for a in spaxx] == ["CASH_EQUIVALENT_TRADE"] and spaxx[0]["amount"] == -3500.0  # kept as reported


def test_asset_transfer_amounts_are_not_cash():
    ds = dataset()
    asset_flows = [f for f in ds["flows"] if f["kind"] == "ASSET"]
    # internal out -1 NVDA, internal in +1 GOOGL, external in +3 GOOGL, external out -2 NVDA (the spinoff is a corporate action)
    assert sorted((f["ticker"], f["units"]) for f in asset_flows) == sorted(
        [("NVDA", -1.0), ("GOOGL", 1.0), ("GOOGL", 3.0), ("NVDA", -2.0)])
    cash_flows = sorted(round(f["amount"], 2) for f in ds["flows"] if f["kind"] == "CASH")
    # cash flows: internal transfers out/in, generic cash transfer, withdrawal (acct 1); contribution (acct 2)
    assert cash_flows == sorted([-250.0, 750.0, 1000.0, -500.0, 5000.0])


def test_cash_reconstruction_ends_at_reported_balances_and_never_goes_negative():
    ds = dataset()
    end = sorted(c["cash"] for c in ds["cash_history"] if c["to_date"] == OPEN_END)
    assert end == [12500.0, 25000.0]
    assert min(c["cash"] for c in ds["cash_history"]) > 0
    assert not [i for i in ds["issues"] if i["code"] == "CASH_HISTORY_NEGATIVE"]


def test_nothing_is_invented():
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ds = dataset()
    assert len(ds["activities"]) == sum(len(a["activities"]) for a in snap["accounts"]) == 35
    end_units = {u["instrument_key"]: u["units"] for u in ds["units_history"] if u["to_date"] == OPEN_END}
    assert end_units["NVDA"] == 12 and end_units["AAPL"] == 5 and end_units["SPY"] == 15


def test_performance_status():
    ds = dataset()
    status = sorted(a["performance_status"] for a in ds["accounts"])
    assert status == ["Partial", "Unavailable"]        # acct 1 partial (inconsistent NVDA/GOOGL); acct 2 has crypto
    assert ds["meta"]["performance_status"] == "Unavailable"


def test_report_reference_on_sandbox_without_performance():
    """The Sandbox history does not reconcile (4 symbols), so performance is Unavailable: the report reference
    must still check values, units and cash, and expect every 'since start' and period figure to be BLANK."""
    from datetime import date, timedelta
    from folio.report_check import expected_figures
    ds = dataset()
    assert ds["meta"]["performance_start"] is None
    prices, d = {}, date.fromisoformat(ds["meta"]["price_start"])
    while d <= date(2026, 11, 9):
        if d.weekday() < 5:
            for t in ds["tickers"]:
                prices.setdefault(t, []).append((d.isoformat(), 100.0, 100.0, 0.0, 1.0))
        d += timedelta(days=1)
    e = expected_figures(ds, prices)
    assert e["Total Gain"] is None and e["Window TWR|1Y"] is None and e["Money Weighted Return"] is None
    assert e["H Units|FXAIX"] == 120.5432 and e["H Units|NVDA"] == 12
    assert sum(v for k, v in e.items() if k.startswith("Acct Cash|")) == sum(c["amount"] for c in ds["cash"])
    assert not any(k.startswith("Gain|") for k in e)
