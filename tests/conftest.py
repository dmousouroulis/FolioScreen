import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLIO_HOME", str(tmp_path / "home"))
    yield


def acct(aid="acct-0001-real-id", first="2025-01-02", inst="Example Brokerage"):
    return {"id": aid, "brokerage_authorization": "conn-0001", "name": "Jane Doe IRA", "number": "XX123456789",
            "institution_name": inst,
            "sync_status": {"transactions": {"initial_sync_completed": True, "first_transaction_date": first,
                                             "last_successful_sync": "2025-03-01"},
                            "holdings": {"initial_sync_completed": True, "last_successful_sync": "2025-03-01 22:00:00+00:00"}}}


def pos(symbol, units, price=10.0, cost=8.0, kind="stock", currency="USD", exchange="XNAS", cash_eq=False):
    return {"instrument": {"kind": kind, "symbol": symbol, "raw_symbol": symbol, "currency": currency, "exchange": exchange},
            "units": units, "price": price, "cost_basis": cost, "currency": currency, "cash_equivalent": cash_eq}


def act(i, typ, d, symbol=None, units=0.0, amount=0.0, price=None, fee=0.0, currency="USD"):
    return {"id": f"act-{i:04d}", "type": typ, "trade_date": f"{d}T00:00:00Z",
            "symbol": ({"symbol": symbol, "raw_symbol": symbol, "currency": {"code": currency}, "exchange": {"mic_code": "XNAS"}}
                       if symbol else None),
            "option_symbol": None, "units": units, "amount": amount, "price": price, "fee": fee, "currency": {"code": currency}}


def snapshot(accounts, access="read"):
    return {"connections": [{"id": "conn-0001", "type": access, "disabled": False, "brokerage": {"name": "Example Brokerage"}}],
            "accounts": accounts}
