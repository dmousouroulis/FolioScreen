"""Turn raw SnapTrade payloads into FolioScreen's canonical records.

Rules (see docs/reconciliation-policy.md):
- Brokerage values are preserved exactly as reported. Nothing is corrected, netted or invented.
- Anything that cannot be interpreted becomes an Issue record that the report shows.
- SnapTrade account/connection IDs, account numbers and account names never leave this module:
  accounts are identified by a salted hash ("account key") instead.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# SnapTrade's normalized activity types (docs.snaptrade.com/docs/sandbox) -> FolioScreen class
TYPE_CLASS = {
    "BUY": "TRADE", "SELL": "TRADE", "REI": "TRADE",
    "CONTRIBUTION": "EXTERNAL_CASH", "WITHDRAWAL": "EXTERNAL_CASH",
    "INTERNAL_CASH_TRANSFER_IN": "EXTERNAL_CASH", "INTERNAL_CASH_TRANSFER_OUT": "EXTERNAL_CASH",
    "EXTERNAL_ASSET_TRANSFER_IN": "EXTERNAL_ASSET", "EXTERNAL_ASSET_TRANSFER_OUT": "EXTERNAL_ASSET",
    "INTERNAL_ASSET_TRANSFER_IN": "EXTERNAL_ASSET", "INTERNAL_ASSET_TRANSFER_OUT": "EXTERNAL_ASSET",
    "TRANSFER": "TRANSFER_GENERIC",
    "DIVIDEND": "INCOME", "SUBSTITUTE_DIVIDEND": "INCOME", "INTEREST": "INCOME",
    "DISTRIBUTION": "INCOME", "RETURN_OF_CAPITAL": "INCOME", "REBATE": "INCOME",
    "FEE": "COST", "TAX": "COST",
    "SPLIT": "CORPORATE", "REVERSE_SPLIT": "CORPORATE", "STOCK_DIVIDEND": "CORPORATE",
    "SPINOFF": "CORPORATE", "STOCK_MERGER": "CORPORATE",
    "ADJUSTMENT": "ADJUSTMENT",
    "OPTIONEXPIRATION": "OPTION", "OPTIONASSIGNMENT": "OPTION", "OPTIONEXERCISE": "OPTION",
}
EXTERNAL_CLASSES = {"EXTERNAL_CASH", "EXTERNAL_ASSET"}
# Classes whose `amount` is NOT a cash movement:
# - EXTERNAL_ASSET: SnapTrade reports the transferred shares' market value (sign follows the units),
#   e.g. INTERNAL_ASSET_TRANSFER_OUT units -1, amount -120 (verified on the SnapTrade Sandbox).
# - CASH_EQUIVALENT_TRADE: buying/selling a money-market fund that the brokerage already counts in cash.
NON_CASH_AMOUNT_CLASSES = {"EXTERNAL_ASSET", "CASH_EQUIVALENT_TRADE"}
SECURITY_KINDS = {"stock", "etf", "adr", "cef", "preferred_stock", "mutualfund"}
US_MICS = {"XNYS", "XNAS", "ARCX", "BATS", "XASE", "IEXG", "XCBO", "EDGX", "EDGA", "BATY",
           "XBOS", "XPHL", "XCHI", "OOTC", "XOTC", "OTCM", "PINX"}
SPLIT_TYPES = {"SPLIT", "REVERSE_SPLIT", "STOCK_DIVIDEND"}
EPS = 1e-6


@dataclass
class Issue:
    severity: str            # Error | Warning | Info
    code: str
    message: str
    account_key: Optional[str] = None
    instrument_key: Optional[str] = None
    affects: str = "Performance"   # what the issue limits
    affects_from: Optional[str] = None
    affects_to: Optional[str] = None
    perf_effect: Optional[str] = None  # "unavailable_until" | "unavailable" | "incomplete" | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Normalized:
    accounts: list = field(default_factory=list)
    positions: list = field(default_factory=list)
    cash: list = field(default_factory=list)
    activities: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    connections: list = field(default_factory=list)


def pseudonym(salt: str, prefix: str, raw_id: str) -> str:
    digest = hmac.new(salt.encode(), str(raw_id).encode(), hashlib.sha256).hexdigest()
    return f"{prefix}{digest[:10]}"


def num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def code_of(v: Any) -> Optional[str]:
    """Currency/exchange fields arrive either as a string or as {code: ...}."""
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("code") or v.get("mic_code")
    return str(v)


def tiingo_ticker(symbol: Optional[str], currency: Optional[str], mic: Optional[str], kind: Optional[str]) -> Optional[str]:
    """Map a brokerage symbol to a Tiingo ticker, or None when it cannot be priced in USD."""
    if not symbol or (currency or "").upper() != "USD":
        return None
    if kind and kind.lower() not in SECURITY_KINDS:
        return None
    if mic and mic.upper() not in US_MICS:
        return None
    return symbol.upper().replace(".", "-").replace("/", "-").replace(" ", "")


def _date_part(v: Any) -> Optional[str]:
    if not v:
        return None
    s = str(v)
    return s[:10] if len(s) >= 10 and s[4] == "-" else None


def holdings_sync(sync: dict) -> dict:
    """Holdings sync status in either SnapTrade shape:
    - list_user_accounts (deprecated): sync_status.holdings = {initial_sync_completed, last_successful_sync}
    - list_all_user_accounts: sync_status.positions = a timestamp string (or null)"""
    hold = sync.get("holdings")
    if isinstance(hold, dict):
        return hold
    pos = sync.get("positions")
    if isinstance(pos, dict):
        return pos
    if isinstance(pos, str) and pos:
        return {"last_successful_sync": pos, "initial_sync_completed": True}
    return {}


def normalize(snapshot: dict, salt: str, config: Optional[dict] = None, today: Optional[str] = None) -> Normalized:
    config = config or {}
    labels = config.get("account_labels", {})
    type_overrides = {k.upper(): v for k, v in (config.get("type_map") or {}).items()}
    out = Normalized()

    # ---------------------------------------------------------------- connections
    conn_by_id = {}
    for c in snapshot.get("connections", []):
        ref = pseudonym(salt, "C", c.get("id"))
        access = str(c.get("type") or "unknown").lower()
        broker = (c.get("brokerage") or {}).get("name") if isinstance(c.get("brokerage"), dict) else None
        rec = {"connection_ref": ref, "broker": broker or "Unknown", "access": access,
               "disabled": bool(c.get("disabled")),
               "freshness": c.get("data_freshness_mode")}
        conn_by_id[c.get("id")] = rec
        out.connections.append(rec)
        if access not in ("read",):
            out.issues.append(Issue("Error" if access == "trade" else "Warning", "CONNECTION_NOT_READ_ONLY",
                                    f"{rec['broker']} connection reports access type '{access}'. FolioScreen expects read-only connections.",
                                    affects="Security"))
        if rec["disabled"]:
            out.issues.append(Issue("Error", "CONNECTION_DISABLED",
                                    f"{rec['broker']} connection is disabled at SnapTrade; data is the last cached state. Reconnect in the SnapTrade dashboard.",
                                    affects="Freshness"))

    for other in snapshot.get("other_accounts", []):
        out.issues.append(Issue("Info", "NON_INVESTMENT_ACCOUNT",
                                f"A {other.get('kind') or 'non-investment'} account is connected; it is not part of the portfolio analysis.",
                                affects="Scope"))

    # ---------------------------------------------------------------- accounts
    rows = snapshot.get("accounts", [])
    keyed = sorted(((pseudonym(salt, "A", r["account"].get("id")), r) for r in rows), key=lambda kv: kv[0])
    for n, (akey, r) in enumerate(keyed, start=1):
        acct = r["account"]
        conn = conn_by_id.get(acct.get("connection_id") or acct.get("brokerage_authorization"), {})
        inst = acct.get("institution_name") or conn.get("broker") or "Brokerage"
        sync = acct.get("sync_status") or {}
        tx = sync.get("transactions") or {}
        hold = holdings_sync(sync)
        label = labels.get(akey) or f"{inst} · account {n}"
        out.accounts.append({
            "account_key": akey, "label": label, "institution": inst,
            "connection_access": conn.get("access", "unknown"),
            "connection_status": "Disabled" if conn.get("disabled") else "OK",
            "tx_first_date": _date_part(tx.get("first_transaction_date")),
            "tx_synced_through": _date_part(tx.get("last_successful_sync")),
            "tx_initial_sync_completed": bool(tx.get("initial_sync_completed")),
            "holdings_synced_utc": (str(hold.get("last_successful_sync"))[:19].replace(" ", "T")
                                    if hold.get("last_successful_sync") else None),
        })
        if not tx.get("initial_sync_completed", True):
            out.issues.append(Issue("Warning", "TX_INITIAL_SYNC_PENDING",
                                    "SnapTrade has not finished the initial transaction sync for this account.",
                                    account_key=akey, perf_effect="incomplete"))
        _positions(out, akey, label, r.get("positions") or {})
        _cash(out, akey, label, r.get("balances") or [])
        cash_eq = {p["instrument_key"] for p in out.positions if p["account_key"] == akey and p["cash_equivalent"]}
        _activities(out, salt, akey, r.get("activities") or [], type_overrides, today, cash_eq)
    return out


def _positions(out: Normalized, akey: str, label: str, body: Any) -> None:
    results = body.get("results", []) if isinstance(body, dict) else list(body)
    for p in results:
        ins = p.get("instrument") or {}
        kind = (ins.get("kind") or "").lower() or None
        symbol = (ins.get("symbol") or ins.get("raw_symbol") or "").upper() or None
        currency = code_of(p.get("currency")) or code_of(ins.get("currency"))
        mic = code_of(ins.get("exchange"))
        units = num(p.get("units"))
        rec = {
            "account_key": akey, "account_label": label,
            "instrument_key": symbol or f"UNKNOWN:{ins.get('id', '')}"[:40],
            "ticker": None, "description": ins.get("description"), "kind": kind,
            "units": units, "broker_price": num(p.get("price")), "broker_cost_basis": num(p.get("cost_basis")),
            "currency": currency, "priced": False, "cash_equivalent": bool(p.get("cash_equivalent")),
        }
        if rec["cash_equivalent"]:
            # SnapTrade: these positions are already counted in the cash balance. Counting them
            # again as securities would double count, so they are listed but not valued.
            out.issues.append(Issue("Info", "CASH_EQUIVALENT_POSITION",
                                    f"{symbol} is reported as a cash equivalent and is already included in cash.",
                                    account_key=akey, instrument_key=rec["instrument_key"], affects="Holdings"))
        else:
            rec["ticker"] = tiingo_ticker(symbol, currency, mic, kind)
            rec["priced"] = rec["ticker"] is not None
            if not rec["priced"]:
                out.issues.append(Issue("Error", "UNPRICED_HOLDING",
                                        f"{symbol or 'Unknown instrument'} ({kind or 'unknown kind'}, {currency or 'no currency'}) cannot be priced in USD by Tiingo; it is excluded from totals.",
                                        account_key=akey, instrument_key=rec["instrument_key"], affects="Totals",
                                        perf_effect="unavailable"))
        if units is not None and units < -EPS:
            out.issues.append(Issue("Error", "SHORT_POSITION",
                                    f"{symbol} is a short position; shorts are not supported in this version.",
                                    account_key=akey, instrument_key=rec["instrument_key"], perf_effect="unavailable"))
        out.positions.append(rec)


def _cash(out: Normalized, akey: str, label: str, balances: list) -> None:
    for b in balances:
        cur = code_of(b.get("currency")) or "UNKNOWN"
        amt = num(b.get("cash"))
        out.cash.append({"account_key": akey, "account_label": label, "currency": cur, "amount": amt})
        if cur != "USD" and amt and abs(amt) > EPS:
            out.issues.append(Issue("Error", "NON_USD_CASH",
                                    f"{cur} cash balance is excluded from USD totals (no FX conversion in this version).",
                                    account_key=akey, affects="Totals", perf_effect="unavailable"))
        if amt is None:
            out.issues.append(Issue("Error", "CASH_MISSING", f"{cur} cash balance was not reported.",
                                    account_key=akey, affects="Totals", perf_effect="unavailable"))


def _activities(out: Normalized, salt: str, akey: str, acts: list, type_overrides: dict, today: Optional[str],
                cash_eq: set = frozenset()) -> None:
    seen = set()
    for a in acts:
        raw_id = a.get("id")
        if raw_id in seen:
            out.issues.append(Issue("Info", "DUPLICATE_ACTIVITY_ID",
                                    "The same activity was returned twice; it is counted once.", account_key=akey,
                                    affects="Data quality"))
            continue
        seen.add(raw_id)
        raw_type = str(a.get("type") or "").upper()
        klass = type_overrides.get(raw_type) or TYPE_CLASS.get(raw_type) or "UNCLASSIFIED"
        sym = a.get("symbol") if isinstance(a.get("symbol"), dict) else None
        symbol = ((sym or {}).get("symbol") or (sym or {}).get("raw_symbol") or "").upper() or None
        units = num(a.get("units")) or 0.0
        amount = num(a.get("amount")) or 0.0
        currency = code_of(a.get("currency")) or (code_of((sym or {}).get("currency")) if sym else None)
        if a.get("option_symbol"):
            klass = "OPTION"
        if klass == "TRANSFER_GENERIC":
            klass = "EXTERNAL_ASSET" if (symbol and abs(units) > EPS) else "EXTERNAL_CASH"
        if klass == "TRADE" and symbol in cash_eq:
            klass = "CASH_EQUIVALENT_TRADE"
        d = _date_part(a.get("trade_date")) or _date_part(a.get("settlement_date"))
        rec = {
            "activity_key": pseudonym(salt, "T", raw_id if raw_id is not None else repr(sorted(a.items(), key=lambda kv: kv[0]))[:200]),
            "account_key": akey, "trade_date": d, "type": raw_type, "class": klass,
            "instrument_key": symbol, "ticker": None,
            "units": units, "price": num(a.get("price")), "amount": amount, "fee": num(a.get("fee")),
            "currency": currency,
        }
        if sym:
            rec["ticker"] = tiingo_ticker(symbol, code_of(sym.get("currency")) or currency,
                                          code_of(sym.get("exchange")), None)
        out.activities.append(rec)
        _check_activity(out, rec, today)


def _check_activity(out: Normalized, r: dict, today: Optional[str]) -> None:
    akey, d, t, k = r["account_key"], r["trade_date"], r["type"], r["class"]
    if d is None:
        out.issues.append(Issue("Error", "ACTIVITY_WITHOUT_DATE",
                                f"A {t or 'transaction'} has no trade or settlement date and cannot be placed in history.",
                                account_key=akey, perf_effect="unavailable"))
        return
    if r["currency"] and r["currency"] != "USD" and (abs(r["amount"]) > EPS or abs(r["units"]) > EPS):
        out.issues.append(Issue("Error", "NON_USD_ACTIVITY", f"{t} on {d} is in {r['currency']}.",
                                account_key=akey, instrument_key=r["instrument_key"], affects_from=d, affects_to=d,
                                perf_effect="unavailable"))
    if k == "UNCLASSIFIED" and (abs(r["amount"]) > EPS or abs(r["units"]) > EPS):
        out.issues.append(Issue("Error", "UNCLASSIFIED_ACTIVITY",
                                f"Brokerage transaction type '{t}' on {d} is not recognised, so it is unknown whether it is a deposit/withdrawal. "
                                f"Performance before this date is unavailable until the type is mapped in config (type_map).",
                                account_key=akey, instrument_key=r["instrument_key"], affects_from=d, affects_to=d,
                                perf_effect="unavailable_until"))
    if k == "ADJUSTMENT" and abs(r["amount"]) > EPS and abs(r["units"]) <= EPS:
        out.issues.append(Issue("Info", "BROKER_ADJUSTMENT",
                                f"Brokerage cash adjustment on {d} is counted as part of investment return, not as a deposit or withdrawal.",
                                account_key=akey, affects_from=d, affects_to=d))
    if k == "OPTION":
        out.issues.append(Issue("Error", "OPTION_ACTIVITY", f"Option event {t} on {d} is not supported in this version.",
                                account_key=akey, instrument_key=r["instrument_key"], affects_from=d, affects_to=d,
                                perf_effect="unavailable_until"))
    expected = {"BUY": (1, -1), "REI": (1, -1), "SELL": (-1, 1), "CONTRIBUTION": (0, 1), "WITHDRAWAL": (0, -1)}.get(t)
    if expected:
        u_sign, a_sign = expected
        bad = (u_sign and r["units"] * u_sign < -EPS) or (a_sign and r["amount"] * a_sign < -EPS)
        if bad:
            out.issues.append(Issue("Error", "UNEXPECTED_SIGN",
                                    f"{t} on {d} has units {r['units']:+g} and amount {r['amount']:+.2f}, which contradicts SnapTrade's sign convention. "
                                    f"Values are kept as reported; performance before this date is unavailable.",
                                    account_key=akey, instrument_key=r["instrument_key"], affects_from=d, affects_to=d,
                                    perf_effect="unavailable_until"))
    if today and d > today:
        out.issues.append(Issue("Warning", "FUTURE_DATED_ACTIVITY", f"{t} is dated {d}, after today.",
                                account_key=akey, affects_from=d, perf_effect="incomplete"))
