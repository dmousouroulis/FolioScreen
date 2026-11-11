import pytest

from folio.engine import portfolio_daily


def ds(units, cash, flows, start="2025-01-02"):
    return {"meta": {"benchmark": "BM", "performance_start": start}, "units_history": units, "cash_history": cash, "flows": flows}


def test_twr_excludes_deposits_and_handles_weekend_flows():
    prices = {"BM": [("2025-01-02", 1), ("2025-01-03", 1), ("2025-01-06", 1)],
              "X": [("2025-01-02", 10.0), ("2025-01-03", 11.0), ("2025-01-06", 11.0)]}
    units = [{"ticker": "X", "from_date": "2025-01-02", "to_date": "9999-12-31", "units": 100}]
    # 500 deposited on Saturday 4 Jan: it belongs to Monday 6 Jan
    cash = [{"from_date": "2025-01-02", "to_date": "2025-01-04", "cash": 0.0},
            {"from_date": "2025-01-04", "to_date": "9999-12-31", "cash": 500.0}]
    flows = [{"date": "2025-01-04", "kind": "CASH", "amount": 500.0, "ticker": None, "units": 0}]
    rows = portfolio_daily(ds(units, cash, flows), prices)["rows"]
    assert [r["Value"] for r in rows] == [1000.0, 1100.0, 1600.0]
    assert [r["Flow"] for r in rows] == [0.0, 0.0, 500.0]
    assert rows[0]["TWRIndex"] == 1.0
    assert rows[1]["DailyReturn"] == pytest.approx(0.10)
    assert rows[2]["DailyReturn"] == pytest.approx(0.0)       # the deposit is not a return
    assert rows[2]["TWRIndex"] == pytest.approx(1.10)


def test_price_carried_forward_and_missing_counted():
    prices = {"BM": [("2025-01-02", 1), ("2025-01-03", 1)], "X": [("2025-01-02", 5.0)]}
    units = [{"ticker": "X", "from_date": "2025-01-02", "to_date": "9999-12-31", "units": 2},
             {"ticker": "Y", "from_date": "2025-01-02", "to_date": "9999-12-31", "units": 1}]
    res = portfolio_daily(ds(units, [], []), prices)
    assert [r["SecuritiesValue"] for r in res["rows"]] == [10.0, 10.0]
    assert res["missing_price_days"] == 2


def test_no_performance_start_means_no_twr():
    prices = {"BM": [("2025-01-02", 1), ("2025-01-03", 1)]}
    rows = portfolio_daily(ds([], [], [], start=None), prices)["rows"]
    assert all(r["TWRIndex"] is None for r in rows)
