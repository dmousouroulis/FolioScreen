"""`folio setup` flow, offline: every external call is faked through Env."""
from folio.setup import Env, run


class Fake(Env):
    def __init__(self, answers=(), **state):
        super().__init__(ask=self._ask, log=self._log)
        self.answers, self.lines, self.calls = list(answers), [], []
        self.s = {"signed_in": True, "demo": True, "keys": True, "tiingo": True, "conns": [{"brokerage": {"name": "Sandbox"}, "type": "read"}],
                  "live": True, "synced": "2026-11-10T22:32", "schedule": {"installed": True, "loaded": True, "time": {"Hour": 21, "Minute": 30}},
                  "price": {"enabled": True, "times": ["07:00"], "localTimeZoneId": "Eastern Standard Time"}}
        self.s.update(state)

    def _ask(self, q):
        self.calls.append(("ask", q))
        if not self.answers:
            raise AssertionError(f"unexpected prompt: {q}")
        return self.answers.pop(0)

    def _log(self, line):
        self.lines.append(line)

    def config(self):
        return {"demo_model_name": "FolioScreen-Demo", "model_name": "FolioScreen-PoC", "allow_trade_connections": False}

    def python_ok(self):
        return True, []

    def ms_signed_in(self):
        return "" if self.s["signed_in"] else "expired"

    def ms_login(self):
        self.calls.append("login")
        self.s["signed_in"] = True
        return "user@example.com"

    def find(self, kind, name):
        return "id" if (self.s["demo"] if name.endswith("Demo") else self.s["live"]) else None

    def deploy(self, demo):
        self.calls.append(("deploy", demo))
        self.s["demo" if demo else "live"] = True
        return 0

    def secret_set(self, name):
        return self.s["tiingo"] if name == "tiingo_token" else self.s["keys"]

    def snaptrade_connections(self):
        return self.s["conns"]

    def tiingo_ok(self):
        return ""

    def last_live_success(self, name):
        return self.s["synced"]

    def last_outcome(self):
        return ""

    def schedule_status(self):
        return self.s["schedule"]

    def price_schedule(self, mid):
        return self.s["price"]

    def set_price_schedule(self, mid, time_hhmm, time_zone):
        self.calls.append(("price", time_hhmm, time_zone))
        self.s["price"] = {"enabled": True, "times": [time_hhmm], "localTimeZoneId": time_zone}

    def local_timezone(self):
        return "America/New_York"


def test_new_user_gets_the_demo_and_may_stop_there():
    env = Fake(answers=["", "", "n"], signed_in=False, demo=False, keys=False)
    assert run(env=env) == 0
    assert "login" in env.calls and ("deploy", True) in env.calls
    assert not any(c == ("deploy", False) for c in env.calls)
    assert any("Own data" in line and "optional" in line for line in env.lines)


def test_check_only_on_a_complete_setup_changes_nothing():
    env = Fake()
    assert run(check_only=True, env=env) == 0
    assert env.calls == []  # no prompts, no deploys
    assert any("Setup complete." in line for line in env.lines)
    assert sum(line.strip().startswith("✓") for line in env.lines) == 10


def test_check_only_without_snaptrade_keys_stops_after_the_demo_without_prompting():
    env = Fake(keys=False)
    assert run(check_only=True, env=env) == 0
    assert env.calls == []
    assert any("SnapTrade keys" in line and "optional" in line for line in env.lines)


def test_trading_connection_is_refused():
    env = Fake(conns=[{"brokerage": {"name": "Real Broker"}, "type": "trade"}])
    assert run(check_only=True, env=env) == 1
    assert any("trading access" in line for line in env.lines)


def test_price_refresh_in_another_time_zone_is_compared_at_the_same_moment():
    """The case seen in Service: 18:30 Pacific is 21:30 Eastern, the same moment as the Mac's sync."""
    from datetime import date
    from folio.setup import price_refresh_state
    winter, summer = date(2026, 11, 11), date(2026, 7, 1)
    pacific = {"enabled": True, "times": ["18:30"], "localTimeZoneId": "Pacific Standard Time"}
    for d in (winter, summer):
        state, detail = price_refresh_state(pacific, "21:30", "America/New_York", d)
        assert state == "todo" and "21:30 your time" in detail
    assert price_refresh_state({"enabled": True, "times": ["02:30"], "localTimeZoneId": "UTC"}, "21:30", "America/New_York", winter)[0] == "todo"
    assert price_refresh_state({"enabled": True, "times": ["07:00"], "localTimeZoneId": "Eastern Standard Time"}, "21:30", "America/New_York", summer)[0] == "ok"
    assert price_refresh_state({"enabled": True, "times": ["07:00"], "localTimeZoneId": "Martian Standard Time"}, "21:30", "America/New_York")[0] == "todo"
    assert price_refresh_state({"enabled": False}, "21:30", "America/New_York")[0] == "todo"


def test_clashing_price_refresh_is_moved_to_07_00_in_your_own_time_zone():
    env = Fake(answers=["y"], price={"enabled": True, "times": ["18:30"], "localTimeZoneId": "Pacific Standard Time"})
    assert run(env=env) == 0
    assert ("price", "07:00", "Eastern Standard Time") in env.calls
    assert any("Price refresh in Power BI" in line and "18:30" not in line and "07:00 your time" in line for line in env.lines)
    found = [i for i, line in enumerate(env.lines) if "Price refresh in Power BI" in line and "compete" in line]
    asked = [i for i, (kind, q) in enumerate(c for c in env.calls if isinstance(c, tuple) and c[0] == "ask") if "07:00" in q]
    assert found, "setup should say what it found before asking"
