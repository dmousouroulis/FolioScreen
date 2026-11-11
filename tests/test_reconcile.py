from conftest import acct, act, pos, snapshot
from folio.normalize import normalize
from folio.reconcile import OPEN_END, reconcile


def run(accounts, today="2025-03-01"):
    norm = normalize(snapshot(accounts), "s", {}, today=today)
    return reconcile(norm, synced_utc="2025-03-01T22:00:00", today=today, benchmark="SPY", source="test", tool_version="t")


def full_history():
    return {"account": acct(first="2025-01-02"),
            "balances": [{"currency": {"code": "USD"}, "cash": 450.0}],
            "positions": {"results": [pos("AAPL", 5)]},
            "activities": [act(1, "CONTRIBUTION", "2025-01-02", amount=1000),
                           act(2, "BUY", "2025-01-03", "AAPL", 10, -500, 50),
                           act(3, "SELL", "2025-02-03", "AAPL", -5, 300, 60),
                           act(4, "FEE", "2025-02-10", amount=-350)]}


def test_complete_history_reconciles_with_no_issues():
    ds = run([full_history()])
    assert ds["issues"] == []
    assert ds["meta"]["performance_status"] == "Complete"
    assert ds["meta"]["performance_start"] == "2025-01-02"
    rows = [(u["from_date"], u["to_date"], u["units"]) for u in ds["units_history"]]
    assert rows == [("2025-01-02", "2025-01-03", 0), ("2025-01-03", "2025-02-03", 10), ("2025-02-03", OPEN_END, 5)]
    cash = [(c["from_date"], c["cash"]) for c in ds["cash_history"]]
    assert cash == [("2025-01-02", 1000), ("2025-01-03", 500), ("2025-02-03", 800), ("2025-02-10", 450)]
    assert [f["amount"] for f in ds["flows"]] == [1000]


def test_reported_values_are_preserved_and_nothing_is_invented():
    a = full_history()
    a["activities"] = a["activities"][1:]          # the deposit is missing from the brokerage history
    a["account"] = acct(first="2025-01-03")
    ds = run([a])
    assert len(ds["activities"]) == 3              # no synthetic deposit added
    assert {x["type"] for x in ds["activities"]} == {"BUY", "SELL", "FEE"}
    assert ds["flows"] == []                       # and no synthetic external flow
    end = [c["cash"] for c in ds["cash_history"] if c["to_date"] == OPEN_END][0]
    assert end == 450.0                            # today's cash is exactly what the broker reports
    # the history implies 1000 of cash before the first buy (end of the first day: 500); it is never
    # negative, so no warning, and no deposit is fabricated to "explain" it
    assert ds["cash_history"][0]["cash"] == 500
    assert not [i for i in ds["issues"] if i["code"] == "CASH_HISTORY_NEGATIVE"]


def test_holding_before_history_start_is_a_warning():
    a = full_history()
    a["positions"] = {"results": [pos("AAPL", 7)]}  # 2 more units than the transactions explain
    ds = run([a])
    issue = [i for i in ds["issues"] if i["code"] == "HELD_BEFORE_HISTORY_START"][0]
    assert issue["severity"] == "Warning" and issue["affects"].startswith("Cost basis")
    assert ds["units_history"][0]["units"] == 2
    assert ds["meta"]["performance_status"] == "Complete"   # value history from the start date is still valid


def test_missing_sale_makes_earlier_performance_unavailable():
    a = full_history()
    a["positions"] = {"results": [pos("AAPL", 2)]}  # 3 units sold somewhere outside the history
    ds = run([a])
    neg = [i for i in ds["issues"] if i["code"] == "NEGATIVE_UNITS_IN_HISTORY"]
    assert neg and neg[0]["affects_to"] == "2025-01-02"
    assert ds["accounts"][0]["performance_status"] == "Partial"
    assert ds["accounts"][0]["performance_start"] == "2025-01-03"


def test_unknown_type_moves_performance_start():
    a = full_history()
    a["activities"].append(act(9, "JNL", "2025-02-20", amount=10))
    a["balances"] = [{"currency": {"code": "USD"}, "cash": 460.0}]
    ds = run([a])
    assert ds["accounts"][0]["performance_start"] == "2025-02-21"
    assert ds["meta"]["performance_status"] == "Partial"


def test_account_without_transactions_has_no_performance():
    ds = run([{"account": acct(first=None), "balances": [{"currency": {"code": "USD"}, "cash": 10.0}],
               "positions": {"results": [pos("AAPL", 3)]}, "activities": []}])
    assert ds["accounts"][0]["performance_status"] == "Unavailable"
    assert ds["meta"]["performance_status"] == "Unavailable"
    assert [(u["from_date"], u["units"]) for u in ds["units_history"]] == [("2025-03-01", 3)]


def test_negative_cash_history_marks_incomplete():
    a = full_history()
    a["balances"] = [{"currency": {"code": "USD"}, "cash": -600.0}]   # implies opening cash of -50
    ds = run([a])
    assert any(i["code"] == "CASH_HISTORY_NEGATIVE" for i in ds["issues"])
    assert ds["meta"]["performance_status"] == "Incomplete"


def test_later_opened_account_does_not_limit_portfolio_start():
    b = full_history()
    b["account"] = acct(aid="acct-0002-real-id", first="2025-02-01")
    b["activities"] = [act(11, "CONTRIBUTION", "2025-02-01", amount=100)]
    b["balances"] = [{"currency": {"code": "USD"}, "cash": 100.0}]
    b["positions"] = {"results": []}
    ds = run([full_history(), b])
    assert ds["meta"]["performance_start"] == "2025-01-02"
    assert ds["meta"]["performance_status"] == "Complete"
