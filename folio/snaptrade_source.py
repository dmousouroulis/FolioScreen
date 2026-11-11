"""Read-only access to SnapTrade Personal.

Only the calls listed in READ_ONLY_CALLS are ever made. FolioScreen never calls
trading endpoints, never calls the "refresh connection" endpoint (SnapTrade says it
may be billed), and never registers users (that is the Commercial model).

Errors are reported as status code + reason only, because the SDK's own exception
text includes response bodies and headers that may contain financial data.
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable

READ_ONLY_CALLS = {
    "api_status.check",
    "connections.list_brokerage_authorizations",
    "account_information.list_all_user_accounts",
    "account_information.get_user_account_balance",
    "account_information.get_all_account_positions",
    "account_information.get_account_activities",
    "authentication.login_snap_trade_user",  # creates a Connection Portal link only
}

RATE_HEADERS = (
    "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
    "X-RateLimit-Account-Limit", "X-RateLimit-Account-Remaining", "X-RateLimit-Account-Reset",
)

ACTIVITY_PAGE = 1000  # SnapTrade's documented maximum page size


class SnapTradeError(RuntimeError):
    """Sanitized error: never contains response bodies."""


def to_plain(obj: Any) -> Any:
    """Convert SDK schema objects (or already-plain JSON) into plain Python values."""
    from decimal import Decimal
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "is_none_oapg") and obj.is_none_oapg():  # schemas.NoneClass
        return None
    if hasattr(obj, "is_true_oapg"):  # schemas.BoolClass
        return bool(obj.is_true_oapg())
    if isinstance(obj, dict) or hasattr(obj, "items"):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return str(obj)


class SnapTradeReader:
    def __init__(self, client_id: str, consumer_key: str, sdk_client: Any = None, sleep: Callable[[float], None] = time.sleep):
        if sdk_client is None:
            from snaptrade_client import SnapTrade, SnapTradeAuth
            sdk_client = SnapTrade(auth=SnapTradeAuth.personal_api_key(consumer_key=consumer_key, client_id=client_id))
        self._sdk = sdk_client
        self._sleep = sleep
        self.calls = 0
        self.rate_headers_seen: dict = {}
        self.retries = 0

    # ------------------------------------------------------------------ plumbing
    def _call(self, dotted: str, **kwargs):
        if dotted not in READ_ONLY_CALLS:
            raise SnapTradeError(f"Refusing non-allowlisted SnapTrade call: {dotted}")
        group, method = dotted.split(".")
        fn = getattr(getattr(self._sdk, group), method)
        attempt = 0
        while True:
            attempt += 1
            self.calls += 1
            try:
                resp = fn(**kwargs)
                self._note_headers(getattr(resp, "headers", None))
                return to_plain(resp.body)
            except Exception as exc:  # ApiException or transport errors
                status = getattr(exc, "status", None)
                headers = getattr(exc, "headers", None)
                self._note_headers(headers)
                if status == 429 and attempt <= 5:
                    self.retries += 1
                    self._sleep(self._retry_delay(headers, attempt))
                    continue
                if status in (500, 502, 503, 504) and attempt <= 3:
                    self.retries += 1
                    self._sleep(2 ** attempt + random.random())
                    continue
                reason = getattr(exc, "reason", None) or type(exc).__name__
                raise SnapTradeError(f"SnapTrade {dotted} failed: HTTP {status} {reason}") from None

    @staticmethod
    def _retry_delay(headers, attempt: int) -> float:
        try:
            if headers and headers.get("Retry-After"):
                return float(headers.get("Retry-After")) + random.random()
        except (TypeError, ValueError):
            pass
        return min(60.0, 2 ** attempt) + random.random()

    def _note_headers(self, headers) -> None:
        if not headers:
            return
        for h in RATE_HEADERS:
            try:
                v = headers.get(h)
            except Exception:
                v = None
            if v is not None:
                self.rate_headers_seen[h] = str(v)

    # ------------------------------------------------------------------ read calls
    def status(self) -> dict:
        return self._call("api_status.check")

    def connections(self) -> list:
        return self._call("connections.list_brokerage_authorizations") or []

    def accounts(self) -> list:
        """All accounts (list_all_user_accounts; list_user_accounts is deprecated).
        Returns investment accounts plus a list of other account kinds, which FolioScreen does not analyse."""
        body = self._call("account_information.list_all_user_accounts") or {}
        if isinstance(body, dict) and body.get("next"):
            raise SnapTradeError("Accounts response is paginated; this SDK version cannot page it. Sync aborted.")
        results = body.get("results", []) if isinstance(body, dict) else list(body)
        return results

    def balances(self, account_id: str) -> list:
        return self._call("account_information.get_user_account_balance", account_id=account_id) or []

    def positions(self, account_id: str) -> dict:
        body = self._call("account_information.get_all_account_positions", account_id=account_id) or {}
        if isinstance(body, dict) and body.get("next"):
            # The installed SDK exposes no paging parameters for this endpoint. Never silently
            # use a partial position list.
            raise SnapTradeError("Positions response is paginated; this SDK version cannot page it. Sync aborted.")
        return body

    def activities(self, account_id: str) -> list:
        out: list = []
        offset = 0
        while True:
            body = self._call("account_information.get_account_activities", account_id=account_id,
                              offset=offset, limit=ACTIVITY_PAGE) or {}
            page = body.get("data", []) if isinstance(body, dict) else list(body)
            out.extend(page)
            total = (body.get("pagination") or {}).get("total") if isinstance(body, dict) else None
            offset += len(page)
            if not page or (total is not None and offset >= int(total)) or (total is None and len(page) < ACTIVITY_PAGE):
                break
        return out

    def connection_portal_link(self, sandbox: bool = False) -> str:
        kwargs = {"connection_type": "read"}
        if sandbox:
            kwargs["broker"] = "SANDBOX"
        body = self._call("authentication.login_snap_trade_user", **kwargs) or {}
        url = body.get("redirectURI")
        if not url:
            raise SnapTradeError("SnapTrade did not return a Connection Portal link")
        return url

    # ------------------------------------------------------------------ snapshot
    def fetch_snapshot(self) -> dict:
        """Everything needed for one sync. Raises on any failure: no partial snapshots."""
        snapshot = {"connections": self.connections(), "accounts": [], "other_accounts": []}
        for acct in self.accounts():
            if (acct.get("kind") or "investment") != "investment":
                snapshot["other_accounts"].append({"kind": acct.get("kind")})
                continue
            aid = acct.get("id")
            snapshot["accounts"].append({
                "account": acct,
                "balances": self.balances(aid),
                "positions": self.positions(aid),
                "activities": self.activities(aid),
            })
        snapshot["fetch_stats"] = {"calls": self.calls, "retries": self.retries,
                                   "rate_headers": dict(self.rate_headers_seen)}
        return snapshot
