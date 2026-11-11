import pytest

from folio.snaptrade_source import SnapTradeError, SnapTradeReader


class Resp:
    def __init__(self, body, headers=None):
        self.body, self.headers = body, headers or {}


class ApiErr(Exception):
    def __init__(self, status, headers=None):
        self.status, self.reason, self.headers = status, "Too Many Requests" if status == 429 else "Error", headers or {}
        self.body = "SENSITIVE BODY with balances"


class FakeSDK:
    def __init__(self):
        self.calls = []
        self.fail_429 = 0
        outer = self

        class AI:
            def get_account_activities(self, account_id, offset, limit):
                outer.calls.append(("activities", offset))
                if outer.fail_429:
                    outer.fail_429 -= 1
                    raise ApiErr(429, {"Retry-After": "0"})
                data = [{"id": f"a{offset + i}"} for i in range(min(limit, 2500 - offset))]
                return Resp({"data": data, "pagination": {"offset": offset, "limit": limit, "total": 2500}},
                            {"X-RateLimit-Account-Remaining": "7"})

            def get_all_account_positions(self, account_id):
                return Resp({"results": [], "next": "https://api.snaptrade.com/…?page=2"})

        class Trading:
            def place_force_order(self, **kw):
                raise AssertionError("must never be called")

        self.account_information = AI()
        self.trading = Trading()


def test_activities_are_paged_completely():
    sdk = FakeSDK()
    r = SnapTradeReader("id", "key", sdk_client=sdk, sleep=lambda s: None)
    assert len(r.activities("x")) == 2500
    assert [c[1] for c in sdk.calls] == [0, 1000, 2000]
    assert r.rate_headers_seen == {"X-RateLimit-Account-Remaining": "7"}


def test_429_is_retried_then_succeeds():
    sdk = FakeSDK()
    sdk.fail_429 = 2
    r = SnapTradeReader("id", "key", sdk_client=sdk, sleep=lambda s: None)
    assert len(r.activities("x")) == 2500 and r.retries == 2


def test_errors_are_sanitized():
    sdk = FakeSDK()
    sdk.fail_429 = 99
    r = SnapTradeReader("id", "key", sdk_client=sdk, sleep=lambda s: None)
    with pytest.raises(SnapTradeError) as e:
        r.activities("x")
    assert "SENSITIVE" not in str(e.value) and "429" in str(e.value)


def test_paginated_positions_are_refused_not_truncated():
    r = SnapTradeReader("id", "key", sdk_client=FakeSDK())
    with pytest.raises(SnapTradeError, match="paginated"):
        r.positions("x")


def test_non_allowlisted_calls_are_refused():
    r = SnapTradeReader("id", "key", sdk_client=FakeSDK())
    with pytest.raises(SnapTradeError, match="Refusing"):
        r._call("trading.place_force_order")


def test_sandbox_dump_refuses_real_connections_and_scrubs_ids():
    from folio.probe import NotSandbox, _scrub, sandbox_dump

    class R:
        def __init__(self, broker):
            self.broker = broker

        def connections(self):
            return [{"id": "c1", "brokerage": {"name": self.broker}}]

    with pytest.raises(NotSandbox):
        sandbox_dump(R("Fidelity"))
    scrubbed = _scrub({"id": "acct-123", "display_name": "My IRA", "brokerage": {"name": "sandbox"},
                       "symbol": {"id": "sym-1", "symbol": "AAPL", "name": "Apple"}})
    assert scrubbed["id"] != "acct-123" and scrubbed["display_name"] != "My IRA"
    assert scrubbed["brokerage"]["name"] == "sandbox" and scrubbed["symbol"]["symbol"] == "AAPL"
    assert scrubbed["symbol"]["name"] == "Apple" and scrubbed["symbol"]["id"] != "sym-1"
