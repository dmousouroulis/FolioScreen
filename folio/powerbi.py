"""Microsoft sign-in, Fabric item deployment and Power BI REST calls.

Sign-in: azure-identity InteractiveBrowserCredential with a persistent token cache. On macOS that
cache is stored in the login Keychain; on Windows it is encrypted with DPAPI. `folio auth login` signs in once in the browser; scheduled
runs use disable_automatic_authentication=True so they never open a browser: if the cached sign-in
can no longer be renewed they raise AuthRequired, and the sync stops without touching Power BI.

Deployment reuses the Marine Energy Screen method (Fabric item definition APIs in My workspace).
"""
from __future__ import annotations

import base64
import json
import time
from typing import Optional

from . import paths

FABRIC = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
PBI = "https://api.powerbi.com/v1.0/myorg"
PBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
RECORD_FILE = "microsoft_auth_record.json"  # account identifier only, no tokens


class AuthRequired(RuntimeError):
    pass


def _dax_error_text(err) -> str:
    """The useful part of an executeQueries error (the engine's message), else the raw object, shortened."""
    if isinstance(err, dict):
        details = (err.get("pbi.error") or {}).get("details") or []
        for d in details:
            if d.get("code") in ("DetailsMessage", "Message"):
                return _short(str((d.get("detail") or {}).get("value", "")))
        if err.get("message"):
            return _short(str(err["message"]))
    return _short(json.dumps(err))


class PowerBIError(RuntimeError):
    pass


# ============================================================================ auth
class MicrosoftAuth:
    def __init__(self, interactive: bool = False):
        from azure.identity import AuthenticationRecord, InteractiveBrowserCredential, TokenCachePersistenceOptions
        self._record_path = paths.state_dir() / RECORD_FILE
        record = None
        if self._record_path.exists():
            record = AuthenticationRecord.deserialize(self._record_path.read_text(encoding="utf-8"))
        elif not interactive:
            raise AuthRequired("No saved Microsoft sign-in. Run: folio auth login")
        self._cred = InteractiveBrowserCredential(
            cache_persistence_options=TokenCachePersistenceOptions(name="folioscreen"),
            authentication_record=record,
            disable_automatic_authentication=not interactive,
        )
        self._interactive = interactive
        self._tokens: dict = {}

    def login(self) -> str:
        record = self._cred.authenticate(scopes=[FABRIC_SCOPE])
        paths.write_private(self._record_path, record.serialize())
        self.token(PBI_SCOPE)  # consent / cache the Power BI scope too
        return record.username

    def token(self, scope: str) -> str:
        cached = self._tokens.get(scope)
        if cached and cached.expires_on - time.time() > 300:
            return cached.token
        from azure.identity import AuthenticationRequiredError
        from azure.core.exceptions import ClientAuthenticationError
        try:
            tok = self._cred.get_token(scope)
        except AuthenticationRequiredError:
            raise AuthRequired("The saved Microsoft sign-in has expired or needs interaction. Run: folio auth login") from None
        except ClientAuthenticationError as exc:
            raise AuthRequired(f"Microsoft sign-in failed ({type(exc).__name__}). Run: folio auth login") from None
        self._tokens[scope] = tok
        return tok.token

    def describe(self) -> dict:
        out = {"record_saved": self._record_path.exists()}
        for label, scope in (("fabric", FABRIC_SCOPE), ("powerbi", PBI_SCOPE)):
            tok = self.token(scope)
            out[f"{label}_token_minutes_left"] = int((self._tokens[scope].expires_on - time.time()) / 60) if tok else None
        return out

    @staticmethod
    def logout() -> None:
        p = paths.state_dir() / RECORD_FILE
        if p.exists():
            p.unlink()


# ============================================================================ HTTP helpers
class _Http:
    def __init__(self, auth: MicrosoftAuth):
        import requests
        self._requests = requests
        self.auth = auth

    def call(self, method: str, url: str, scope: str, body=None, expect_json: bool = True, retry_429: bool = True):
        for attempt in range(4 if retry_429 else 1):
            headers = {"Authorization": f"Bearer {self.auth.token(scope)}", "Content-Type": "application/json"}
            r = self._requests.request(method, url, headers=headers, data=json.dumps(body) if body is not None else None, timeout=120)
            if r.status_code != 429 or attempt == 3 or not retry_429:
                break
            wait = _retry_after(r)
            print(f"   Power BI asked to wait {wait} s (too many requests); retrying…", flush=True)
            time.sleep(wait)
        if r.status_code == 202 and "fabric.microsoft.com" in url:
            return self._wait_fabric(r, scope)
        if r.status_code >= 400:
            raise PowerBIError(f"{method} {_redact(url)} failed (HTTP {r.status_code}): {_short(r.text)}")
        if not expect_json or not r.text:
            return {"_status": r.status_code, "_location": r.headers.get("Location")}
        return r.json()

    def _wait_fabric(self, r, scope: str):
        op_url = r.headers.get("Location")
        op_id = r.headers.get("x-ms-operation-id")
        for _ in range(400):
            time.sleep(int(r.headers.get("Retry-After", 3)))
            r = self._requests.get(op_url, headers={"Authorization": f"Bearer {self.auth.token(scope)}"}, timeout=60)
            state = r.json().get("status")
            if state == "Succeeded":
                if op_id:
                    res = self._requests.get(f"{FABRIC}/operations/{op_id}/result",
                                             headers={"Authorization": f"Bearer {self.auth.token(scope)}"}, timeout=120)
                    if res.status_code == 200 and res.text:
                        return res.json()
                return {}
            if state in ("Failed", "Undefined"):
                raise PowerBIError(f"Fabric operation failed: {_short(json.dumps(r.json()))}")
        raise PowerBIError("Fabric operation timed out")


class RefreshLimitError(PowerBIError):
    """The model's daily refresh allowance is used up; retrying within minutes does not help."""


def _retry_after(r, cap: int = 180) -> int:
    """Seconds to wait from a 429: the Retry-After header, else 'Retry in N seconds' in the body, else 60."""
    import re
    try:
        return max(1, min(cap, int(r.headers.get("Retry-After"))))
    except (TypeError, ValueError):
        m = re.search(r"Retry in (\d+) seconds", r.text or "")
        return max(1, min(cap, int(m.group(1)) if m else 60))


def _short(text: str, n: int = 600) -> str:
    text = (text or "").replace("\n", " ")
    return text[:n] + ("…" if len(text) > n else "")


def _redact(url: str) -> str:
    return url.split("?")[0]


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def parts_from_files(files: dict, skip=(".platform",)) -> list:
    return [{"path": rel, "payload": b64(text) if isinstance(text, str) else base64.b64encode(text).decode("ascii"),
             "payloadType": "InlineBase64"} for rel, text in sorted(files.items()) if rel not in skip]


# ============================================================================ client
class PowerBI:
    def __init__(self, auth: MicrosoftAuth):
        self.http = _Http(auth)
        self._ws_id: Optional[str] = None

    # ---------------------------------------------------------------- Fabric items
    def _list(self, url: str) -> list:
        items, cont = [], url
        while cont:
            page = self.http.call("GET", cont, FABRIC_SCOPE)
            items += page.get("value", [])
            cont = page.get("continuationUri")
        return items

    def my_workspace_id(self) -> str:
        if not self._ws_id:
            ws = [w for w in self._list(f"{FABRIC}/workspaces") if w.get("type") == "Personal"]
            if not ws:
                raise PowerBIError("My workspace was not found for this account.")
            self._ws_id = ws[0]["id"]
        return self._ws_id

    def find_item(self, kind: str, name: str) -> Optional[str]:
        ws = self.my_workspace_id()
        hits = [i for i in self._list(f"{FABRIC}/workspaces/{ws}/{kind}") if i["displayName"] == name]
        return hits[0]["id"] if hits else None

    def create_item(self, kind: str, name: str, parts: list, fmt: str) -> str:
        ws = self.my_workspace_id()
        created = self.http.call("POST", f"{FABRIC}/workspaces/{ws}/{kind}", FABRIC_SCOPE,
                                 {"displayName": name, "definition": {"format": fmt, "parts": parts}})
        return created.get("id") or self.find_item(kind, name)

    def update_definition(self, kind: str, item_id: str, parts: list, fmt: str) -> None:
        ws = self.my_workspace_id()
        self.http.call("POST", f"{FABRIC}/workspaces/{ws}/{kind}/{item_id}/updateDefinition", FABRIC_SCOPE,
                       {"definition": {"format": fmt, "parts": parts}})

    def get_definition(self, kind: str, item_id: str, fmt: str) -> list:
        ws = self.my_workspace_id()
        res = self.http.call("POST", f"{FABRIC}/workspaces/{ws}/{kind}/{item_id}/getDefinition?format={fmt}", FABRIC_SCOPE)
        return (res.get("definition") or {}).get("parts", [])

    # ---------------------------------------------------------------- Power BI REST (My workspace = /myorg)
    def trigger_refresh(self, dataset_id: str) -> None:
        """Starts a refresh. HTTP 429 here is the per-model refresh allowance (8 per rolling 24 h on shared capacity,
        scheduled and API refreshes together), not a short throttle, so it is reported instead of retried."""
        try:
            self.http.call("POST", f"{PBI}/datasets/{dataset_id}/refreshes", PBI_SCOPE, {"notifyOption": "NoNotification"},
                           expect_json=False, retry_429=False)
        except PowerBIError as exc:
            if "HTTP 429" in str(exc):
                raise RefreshLimitError(
                    "Power BI refused to start a refresh: this model has most likely used its refresh allowance "
                    "(8 per rolling 24 hours in a free or Pro workspace, scheduled and API refreshes together). "
                    "It frees up as earlier refreshes age past 24 hours.") from exc
            raise

    def refresh_history(self, dataset_id: str, top: int = 5) -> list:
        return self.http.call("GET", f"{PBI}/datasets/{dataset_id}/refreshes?$top={top}", PBI_SCOPE).get("value", [])

    def wait_for_refresh(self, dataset_id: str, started_after: str, timeout_s: int = 2400, progress=None) -> dict:
        """Polls until the newest refresh that started after `started_after` (ISO UTC) finishes."""
        t0 = time.time()
        deadline = t0 + timeout_s
        last_note = 0.0
        while time.time() < deadline:
            state = "not listed yet"
            for r in self.refresh_history(dataset_id, 5):
                if (r.get("startTime") or "") >= started_after[:19]:
                    if r.get("status") in ("Completed", "Failed", "Cancelled", "Disabled"):
                        return {"status": r.get("status"), "startTime": r.get("startTime"), "endTime": r.get("endTime"),
                                "error": _short(r.get("serviceExceptionJson") or "", 800)}
                    state = r.get("status") or "Unknown"
                    break
            if progress and time.time() - last_note >= 60:
                progress(f"   … refresh {state.lower()} ({int((time.time() - t0) / 60)} min elapsed)")
                last_note = time.time()
            time.sleep(20)
        return {"status": "Timeout"}

    def refresh_schedule(self, dataset_id: str) -> dict:
        s = self.http.call("GET", f"{PBI}/datasets/{dataset_id}/refreshSchedule", PBI_SCOPE)
        return {k: s.get(k) for k in ("enabled", "days", "times", "localTimeZoneId", "notifyOption")}

    def set_refresh_schedule(self, dataset_id: str, time_hhmm: str, time_zone: str = "UTC") -> None:
        """Daily Power BI refresh (prices) at one time in a Windows time zone ID; email on failure."""
        days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        self.http.call("PATCH", f"{PBI}/datasets/{dataset_id}/refreshSchedule", PBI_SCOPE,
                       {"value": {"days": days, "times": [time_hhmm], "enabled": True, "localTimeZoneId": time_zone,
                                  "notifyOption": "MailOnFailure"}}, expect_json=False)

    def datasources(self, dataset_id: str) -> list:
        rows = self.http.call("GET", f"{PBI}/datasets/{dataset_id}/datasources", PBI_SCOPE).get("value", [])
        return [{"type": d.get("datasourceType"), "url": (d.get("connectionDetails") or {}).get("url"),
                 "gatewayBound": bool(d.get("gatewayId"))} for d in rows]

    def report_binding(self, report_id: str) -> dict:
        r = self.http.call("GET", f"{PBI}/reports/{report_id}", PBI_SCOPE)
        return {"datasetId": r.get("datasetId"), "name": r.get("name")}

    def execute_dax(self, dataset_id: str, dax: str) -> list:
        res = self.http.call("POST", f"{PBI}/datasets/{dataset_id}/executeQueries", PBI_SCOPE,
                             {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}})
        # A failing DAX expression can come back as HTTP 200 with an "error" object and no (or empty) rows.
        r0 = (res.get("results") or [{}])[0] if isinstance(res, dict) else {}
        t0 = (r0.get("tables") or [{}])[0]
        err = (res.get("error") if isinstance(res, dict) else None) or r0.get("error") or t0.get("error")
        if err:
            raise PowerBIError(f"DAX error: {_dax_error_text(err)}")
        if "rows" not in t0:
            raise PowerBIError(f"executeQueries returned no rows: {_short(json.dumps(res))}")
        return t0["rows"]
