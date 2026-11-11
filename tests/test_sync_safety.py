from datetime import date

import pytest

from conftest import acct, pos, snapshot
from folio import sync
from folio.snaptrade_source import SnapTradeError


@pytest.fixture(autouse=True)
def _reset_served():
    SERVED["hash"] = None
    yield


class FakePBI:
    """Records every call; refresh results are scripted."""

    def __init__(self, refresh_results, update_fails=False, hash_override=None, error_text=""):
        self.log = []
        self.error_text = error_text
        self.refresh_results = list(refresh_results)
        self.update_fails = update_fails
        self.hash_override = hash_override
        self.current_hash = SERVED["hash"]
        self.pending_hash = None

    def find_item(self, kind, name):
        return "model-1"

    def update_definition(self, kind, item_id, parts, fmt):
        self.log.append("update")
        if self.update_fails:
            from folio.powerbi import PowerBIError
            raise PowerBIError("HTTP 400 invalid definition")
        import base64
        sync_info = [p for p in parts if p["path"].endswith("Sync Info.tmdl")][0]
        text = base64.b64decode(sync_info["payload"]).decode()
        self.pending_hash = [h for h in sync.json.loads("[]")] or _hash_in(text)

    def trigger_refresh(self, mid):
        self.log.append("refresh")

    def wait_for_refresh(self, mid, started, progress=None):
        status = self.refresh_results.pop(0)
        if status == "Completed":
            self.current_hash = self.pending_hash
        return {"status": status, "error": "" if status == "Completed" else self.error_text}

    def refresh_schedule(self, mid):
        self.log.append("schedule")
        return {"enabled": True, "days": ["Monday"], "times": ["21:30"]} if not getattr(self, "schedule_lost", False) or "update" not in self.log else {"enabled": False}

    def datasources(self, mid):
        return [{"type": "Web", "url": "https://api.tiingo.com"}]

    def execute_dax(self, mid, dax):
        self.log.append("verify")
        return [{"[DataHash]": self.hash_override or self.current_hash, "[Positions]": 1}]


def _hash_in(tmdl_text):
    import re
    return re.search(r'#datetime\([^)]*\), "[^"]*", "([0-9a-f]{16})"', tmdl_text).group(1)


SERVED = {"hash": None}


def deploy_known_good():
    """A deployed model that has refreshed and verified: Power BI is serving the known-good data."""
    ds, prices, _ = sync.build_dataset(demo=True, today=date(2026, 11, 10))
    sync.remember_good("FolioScreen-Demo", ds, prices)
    SERVED["hash"] = ds["meta"]["data_hash"]
    return ds


def test_successful_sync_publishes_and_verifies():
    deploy_known_good()
    pbi = FakePBI(["Completed"])
    assert sync.run_sync(demo=True, pbi=pbi, log=lambda *a: None) == 0
    assert [x for x in pbi.log if x != "schedule"] == ["update", "refresh", "verify"]
    run = sync.load_state("last_run.json")
    assert run["outcome"] == "OK" and run["result"]["settings"]["preserved"] is True


def test_changed_schedule_is_reported():
    deploy_known_good()
    pbi = FakePBI(["Completed"])
    pbi.schedule_lost = True
    assert sync.run_sync(demo=True, pbi=pbi, log=lambda *a: None) == 0
    st = sync.load_state("last_run.json")["result"]["settings"]
    assert st["preserved"] is False and st["changed"] == ["schedule"]


def test_failed_refresh_restores_known_good_definition_without_a_second_refresh():
    good = deploy_known_good()
    pbi = FakePBI(["Failed"])
    code = sync.run_sync(demo=True, pbi=pbi, log=lambda *a: None)
    assert code == sync.EXIT["ROLLED_BACK"]
    # previous data is still served after the failed refresh, so restoring the definition is enough
    assert [x for x in pbi.log if x != "schedule"] == ["update", "refresh", "update", "verify"]
    assert pbi.current_hash == good["meta"]["data_hash"]
    assert sync.load_state("last_run.json")["result"]["rollback_refreshed"] is False
    assert sync.known_good("FolioScreen-Demo")[0]["meta"]["data_hash"] == good["meta"]["data_hash"]  # not replaced


def test_verification_mismatch_triggers_rollback():
    deploy_known_good()
    pbi = FakePBI(["Completed", "Completed"], hash_override="0000000000000000")
    assert sync.run_sync(demo=True, pbi=pbi, log=lambda *a: None) == sync.EXIT["ROLLBACK_FAILED"]
    assert pbi.log.count("update") == 2 and pbi.log.count("refresh") == 2   # restore needed a refresh, still wrong


def test_rejected_update_leaves_model_untouched():
    deploy_known_good()
    pbi = FakePBI([], update_fails=True)
    assert sync.run_sync(demo=True, pbi=pbi, log=lambda *a: None) == sync.EXIT["PUBLISH_FAILED_UNCHANGED"]
    assert [x for x in pbi.log if x != "schedule"] == ["update"]


def test_fetch_failure_never_reaches_power_bi(monkeypatch):
    class Broken:
        def fetch_snapshot(self):
            raise SnapTradeError("SnapTrade account_information.list_user_accounts failed: HTTP 503 Service Unavailable")
    monkeypatch.setattr("folio.secrets.account_salt", lambda: "s")
    with pytest.raises(sync.SyncError) as e:
        sync.build_dataset(demo=False, reader=Broken(), config=dict(sync.DEFAULT_CONFIG))
    assert e.value.outcome == "FETCH_FAILED"


def test_trade_connection_is_blocked_by_policy(monkeypatch):
    class Reader:
        def fetch_snapshot(self):
            return snapshot([{"account": acct(), "balances": [{"currency": {"code": "USD"}, "cash": 1.0}],
                              "positions": {"results": [pos("AAPL", 1)]}, "activities": []}], access="trade")
    monkeypatch.setattr("folio.secrets.account_salt", lambda: "s")
    cfg = dict(sync.DEFAULT_CONFIG)
    ds, _, _ = sync.build_dataset(demo=False, reader=Reader(), config=cfg)
    with pytest.raises(sync.SyncError) as e:
        sync.check_policy(ds, cfg)
    assert e.value.outcome == "POLICY_BLOCKED"


def test_validation_blocks_raw_identifiers():
    ds, _, _ = sync.build_dataset(demo=True, today=date(2026, 11, 10))
    ds["positions"][0]["description"] = "acct-0001-real-id"
    with pytest.raises(sync.SyncError) as e:
        sync.validate(ds, ["acct-0001-real-id"])
    assert e.value.outcome == "VALIDATION_FAILED"


def test_scheduled_run_skips_when_recent_success():
    sync.save_state("last_success.json", {"finished_utc": sync.utcnow(5)})
    assert sync.run_sync(demo=True, scheduled=True, pbi=FakePBI([]), log=lambda *a: None) == 0
    assert sync.load_state("last_run.json") is None


def test_safety_test_error_injection_keeps_tmdl_indentation():
    ds, prices, _ = sync.build_dataset(demo=True, today=date(2026, 11, 10))
    files = sync.render_model(ds, prices, "FolioScreen-Demo")
    bad = sync.inject_refresh_error(files["definition/tables/Prices.tmdl"])
    for line in bad.split("\n"):
        if "Intentional" in line or "Unused = #table(" in line:
            assert line.startswith("\t\t\t\t")


def test_known_good_round_trip_renders_identical_model():
    ds, prices, _ = sync.build_dataset(demo=True, today=date(2026, 11, 10))
    sync.remember_good("FolioScreen-Demo", ds, prices)
    ds2, prices2 = sync.known_good("FolioScreen-Demo")
    assert sync.render_model(ds, prices, "FolioScreen-Demo") == sync.render_model(ds2, prices2, "FolioScreen-Demo")


def test_missing_credential_is_reported_as_such():
    deploy_known_good()
    pbi = FakePBI(["Failed"], error_text='{"error":{"code":"DM_GWPipeline_Gateway_DataSourceAccessError","pbi.error":"credentials"}}')
    assert sync.run_sync(demo=True, pbi=pbi, log=lambda *a: None) == sync.EXIT["CREDENTIALS_REQUIRED"]


def test_failure_before_any_verified_version_is_not_called_a_rollback_failure():
    pbi = FakePBI(["Failed"], error_text="credentials missing")
    assert sync.run_sync(demo=True, pbi=pbi, log=lambda *a: None) == sync.EXIT["CREDENTIALS_REQUIRED"]
    pbi = FakePBI(["Failed"], error_text="something else")
    assert sync.run_sync(demo=True, pbi=pbi, log=lambda *a: None) == sync.EXIT["FAILED_NO_VERIFIED_VERSION"]
    assert [x for x in pbi.log if x != "schedule"] == ["update", "refresh"]   # nothing restored, nothing touched again


def test_scheduled_slot_logic():
    from datetime import datetime
    now = datetime(2026, 11, 10, 21, 31)
    assert sync.last_scheduled_slot("21:30", now) == "2026-11-10 21:30"
    assert sync.last_scheduled_slot("21:30", datetime(2026, 11, 11, 8, 0)) == "2026-11-10 21:30"
    # a manual sync at 12:52 today does not cancel tonight's run
    noon_utc = datetime(2026, 11, 10, 12, 52).astimezone().astimezone(sync.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    assert not sync._already_synced_since(noon_utc, "2026-11-10 21:30")
    # a sync at 21:35 does cancel the login catch-up run the next morning
    night_utc = datetime(2026, 11, 10, 21, 35).astimezone().astimezone(sync.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    assert sync._already_synced_since(night_utc, "2026-11-10 21:30")


def test_scheduled_run_after_daytime_manual_sync_is_not_skipped(monkeypatch):
    deploy_known_good()
    sync.save_state("last_success.json", {"finished_utc": "2000-01-01T00:00:00"})
    cfg = sync.load_config()
    cfg["schedule_time"] = "00:00"
    sync.save_state("config.json", cfg)
    pbi = FakePBI(["Completed"])
    lines = []
    assert sync.run_sync(demo=True, scheduled=True, pbi=pbi, log=lines.append) == 0
    assert "update" in pbi.log and lines[0].startswith("[")   # it ran, with timestamped log lines


def test_rate_limit_wait_is_read_from_power_bi():
    """A 429 from Power BI is retried after the wait it asks for (header, else message), capped at 3 minutes."""
    from folio.powerbi import _retry_after

    class R:
        def __init__(self, headers=None, text=""):
            self.headers, self.text = headers or {}, text
    assert _retry_after(R({"Retry-After": "30"})) == 30
    assert _retry_after(R(text='{"message":"... Retry in 120 seconds."}')) == 120
    assert _retry_after(R({"Retry-After": "900"})) == 180
    assert _retry_after(R(text="no hint")) == 60


def test_refresh_allowance_is_reported_not_retried():
    """HTTP 429 on 'start refresh' is the model's daily allowance: one request, a clear error, no waiting."""
    import time
    import pytest
    from folio import powerbi

    calls = []

    class Resp:
        status_code, headers = 429, {}
        text = '{"message":"You have exceeded the amount of requests allowed... Retry in 120 seconds."}'

    class Req:
        def request(self, *a, **k):
            calls.append(1)
            return Resp()

    class Auth:
        def token(self, scope):
            return "t"

    http_cls = next(c for c in vars(powerbi).values() if isinstance(c, type) and hasattr(c, "_wait_fabric"))
    http = http_cls.__new__(http_cls)
    http._requests, http.auth = Req(), Auth()
    pbi = powerbi.PowerBI.__new__(powerbi.PowerBI)
    pbi.http = http
    t = time.time()
    with pytest.raises(powerbi.RefreshLimitError, match="refresh allowance"):
        pbi.trigger_refresh("model")
    assert len(calls) == 1 and time.time() - t < 5
