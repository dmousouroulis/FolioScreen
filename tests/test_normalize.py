import json

from conftest import acct, act, pos, snapshot
from folio.normalize import normalize, tiingo_ticker


def test_identifiers_are_pseudonymised():
    snap = snapshot([{"account": acct(), "balances": [{"currency": {"code": "USD"}, "cash": 100.0}],
                      "positions": {"results": [pos("AAPL", 5)]}, "activities": [act(1, "BUY", "2025-01-02", "AAPL", 5, -50, 10)]}])
    norm = normalize(snap, "salt", {}, today="2025-03-02")
    blob = json.dumps(norm.__dict__, default=str)
    for raw in ("acct-0001-real-id", "conn-0001", "XX123456789", "Jane Doe IRA", "act-0001"):
        assert raw not in blob
    assert norm.accounts[0]["account_key"].startswith("A")
    # deterministic for the same salt, different for another salt
    assert normalize(snap, "salt", {}).accounts[0]["account_key"] == norm.accounts[0]["account_key"]
    assert normalize(snap, "other", {}).accounts[0]["account_key"] != norm.accounts[0]["account_key"]


def test_ticker_mapping():
    assert tiingo_ticker("BRK.B", "USD", "XNYS", "stock") == "BRK-B"
    assert tiingo_ticker("VAB.TO", "CAD", "XTSE", "etf") is None
    assert tiingo_ticker("AAPL", "USD", None, "stock") == "AAPL"
    assert tiingo_ticker("AAPL260116C00200000", "USD", "XNAS", "option") is None


def test_problem_records_become_issues_not_corrections():
    acts = [act(1, "SELL", "2025-01-05", "AAPL", units=3, amount=30, price=10),      # wrong unit sign
            act(2, "MYSTERY", "2025-01-06", amount=12.5),                             # unknown type with cash
            act(3, "DIVIDEND", "2025-01-07", "SHOP", amount=4, currency="CAD")]       # non-USD
    snap = snapshot([{"account": acct(), "balances": [{"currency": {"code": "USD"}, "cash": 0}, {"currency": {"code": "CAD"}, "cash": 4}],
                      "positions": {"results": [pos("AAPL", 2), pos("VMFXX", 100, 1, 1, kind="mutualfund", cash_eq=True),
                                                pos("SHOP", 1, currency="CAD", exchange="XTSE")]}, "activities": acts}])
    norm = normalize(snap, "s", {}, today="2025-03-01")
    codes = sorted(i.code for i in norm.issues)
    assert codes == sorted(["UNEXPECTED_SIGN", "UNCLASSIFIED_ACTIVITY", "NON_USD_ACTIVITY", "NON_USD_CASH",
                            "CASH_EQUIVALENT_POSITION", "UNPRICED_HOLDING"])
    sell = [a for a in norm.activities if a["type"] == "SELL"][0]
    assert sell["units"] == 3 and sell["amount"] == 30  # kept exactly as reported
    assert len(norm.activities) == 3


def test_type_map_override_resolves_unclassified():
    snap = snapshot([{"account": acct(), "balances": [], "positions": {"results": []},
                      "activities": [act(1, "MYSTERY", "2025-01-06", amount=12.5)]}])
    norm = normalize(snap, "s", {"type_map": {"MYSTERY": "INCOME"}})
    assert norm.activities[0]["class"] == "INCOME"
    assert not [i for i in norm.issues if i.code == "UNCLASSIFIED_ACTIVITY"]


def test_trade_access_connection_flagged():
    norm = normalize(snapshot([], access="trade"), "s", {})
    assert [i.code for i in norm.issues] == ["CONNECTION_NOT_READ_ONLY"]


def test_list_all_user_accounts_shape_and_other_kinds():
    new_acct = {"id": "acct-new-0001", "kind": "investment", "connection_id": "conn-0001", "display_name": "Jane Roth IRA",
                "masked_account_number": "****6789", "institution_id": "inst-77",
                "sync_status": {"transactions": {"initial_sync_completed": True, "first_transaction_date": "2025-01-02",
                                                 "last_successful_sync": "2025-03-01"},
                                "positions": "2025-03-01T22:00:00.417307+00:00", "balances": "2025-03-01T22:00:00+00:00",
                                "orders": None}}
    snap = snapshot([{"account": new_acct, "balances": [], "positions": {"results": []}, "activities": []}])
    snap["other_accounts"] = [{"kind": "deposit"}]
    norm = normalize(snap, "s", {})
    a = norm.accounts[0]
    assert a["institution"] == "Example Brokerage"          # taken from the connection
    assert a["connection_access"] == "read"
    assert a["holdings_synced_utc"] == "2025-03-01T22:00:00"
    assert [i.code for i in norm.issues] == ["NON_INVESTMENT_ACCOUNT"]
    assert "Jane Roth" not in json.dumps(norm.__dict__, default=str)
