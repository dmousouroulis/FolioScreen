"""Builds the PBIP files (TMDL semantic model + PBIR report) from a reconciled dataset.

Portfolio data is embedded as Power Query #table literals (no data source, so no credential and
no formula-firewall combination). Prices come from Tiingo at refresh time (live) or are embedded
(demo). Everything derived from prices is computed by DAX calculated tables during refresh.
"""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Optional

NS = uuid.UUID("6f1d3c52-6a0e-4a3b-9b9e-0f0115c0e5aa")
PROJECT = "FolioScreen"


def lineage(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# ============================================================================ M literals
def m_text(v) -> str:
    return "null" if v is None else '"' + str(v).replace('"', '""') + '"'


def m_number(v) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "null"
    if isinstance(v, bool):
        raise TypeError("bool passed as number")
    r = repr(float(v))
    if r.endswith(".0"):
        r = r[:-2]
    return r


def m_date(v) -> str:
    if not v:
        return "null"
    y, m, d = (int(x) for x in str(v)[:10].split("-"))
    return f"#date({y}, {m}, {d})"


def m_datetime(v) -> str:
    if not v:
        return "null"
    s = str(v).replace(" ", "T")
    y, mo, d = (int(x) for x in s[:10].split("-"))
    hh, mm, ss = (int(float(x)) for x in (s[11:19] or "00:00:00").split(":"))
    return f"#datetime({y}, {mo}, {d}, {hh}, {mm}, {ss})"


def m_logical(v) -> str:
    return "null" if v is None else ("true" if v else "false")


M_FMT = {"text": m_text, "number": m_number, "date": m_date, "datetime": m_datetime, "logical": m_logical}
TMDL_TYPE = {"text": "string", "number": "double", "date": "dateTime", "datetime": "dateTime", "logical": "boolean"}


def m_table(columns: list, rows: list) -> str:
    """columns: [(ColumnName, mtype, record_key)] ; rows: list of dicts."""
    header = ", ".join(f"{_m_ident(name)} = nullable {mt}" for name, mt, _ in columns)
    lines = []
    for r in rows:
        vals = ", ".join(M_FMT[mt](r.get(key)) for _, mt, key in columns)
        lines.append("{" + vals + "}")
    body = (",\n" + " " * 8).join(lines)
    return (f"let\n    Source = #table(\n        type table [{header}],\n        {{\n        {body}\n        }}\n    )\nin\n    Source"
            if lines else f"let\n    Source = #table(type table [{header}], {{}})\nin\n    Source")


def _m_ident(name: str) -> str:
    return name if name.replace("_", "").isalnum() and not name[0].isdigit() else f'#"{name}"'


# ============================================================================ table specs
EMBEDDED = {
    "Sync Info": [("SyncedUTC", "datetime", "synced_utc"), ("Source", "text", "source"), ("DataHash", "text", "data_hash"),
                  ("ToolVersion", "text", "tool_version"), ("Benchmark", "text", "benchmark"),
                  ("PerformanceStart", "date", "performance_start"), ("PerformanceStatus", "text", "performance_status"),
                  ("AccountCount", "number", "account_count"), ("ActivityCount", "number", "activity_count")],
    "Accounts": [("AccountKey", "text", "account_key"), ("AccountLabel", "text", "label"), ("Institution", "text", "institution"),
                 ("ConnectionAccess", "text", "connection_access"), ("ConnectionStatus", "text", "connection_status"),
                 ("HistoryStart", "date", "history_start"), ("TxSyncedThrough", "date", "tx_synced_through"),
                 ("HoldingsSyncedUTC", "datetime", "holdings_synced_utc"),
                 ("PerformanceStart", "date", "performance_start"), ("PerformanceStatus", "text", "performance_status")],
    "Positions": [("AccountKey", "text", "account_key"), ("AccountLabel", "text", "account_label"),
                  ("InstrumentKey", "text", "instrument_key"), ("Ticker", "text", "ticker"), ("Description", "text", "description"),
                  ("Kind", "text", "kind"), ("Units", "number", "units"), ("BrokerPrice", "number", "broker_price"),
                  ("BrokerCostBasis", "number", "broker_cost_basis"), ("Currency", "text", "currency"),
                  ("Priced", "logical", "priced"), ("CashEquivalent", "logical", "cash_equivalent")],
    "Cash": [("AccountKey", "text", "account_key"), ("AccountLabel", "text", "account_label"),
             ("Currency", "text", "currency"), ("Amount", "number", "amount")],
    "Activities": [("ActivityKey", "text", "activity_key"), ("AccountKey", "text", "account_key"),
                   ("TradeDate", "date", "trade_date"), ("Type", "text", "type"), ("Class", "text", "class"),
                   ("InstrumentKey", "text", "instrument_key"), ("Ticker", "text", "ticker"), ("Units", "number", "units"),
                   ("Price", "number", "price"), ("Amount", "number", "amount"), ("Fee", "number", "fee"),
                   ("Currency", "text", "currency")],
    "Units History": [("AccountKey", "text", "account_key"), ("InstrumentKey", "text", "instrument_key"),
                      ("Ticker", "text", "ticker"), ("FromDate", "date", "from_date"), ("ToDate", "date", "to_date"),
                      ("Units", "number", "units")],
    "Cash History": [("AccountKey", "text", "account_key"), ("FromDate", "date", "from_date"),
                     ("ToDate", "date", "to_date"), ("Cash", "number", "cash")],
    "External Flows": [("AccountKey", "text", "account_key"), ("Date", "date", "date"), ("Kind", "text", "kind"),
                       ("Amount", "number", "amount"), ("Ticker", "text", "ticker"), ("Units", "number", "units")],
    "Issues": [("IssueKey", "text", "issue_key"), ("Severity", "text", "severity"), ("Code", "text", "code"),
               ("AccountKey", "text", "account_key"), ("AccountLabel", "text", "account_label"),
               ("InstrumentKey", "text", "instrument_key"), ("Affects", "text", "affects"),
               ("AffectsFrom", "date", "affects_from"), ("AffectsTo", "date", "affects_to"), ("Message", "text", "message")],
}
DATASET_KEY = {"Accounts": "accounts", "Positions": "positions", "Cash": "cash", "Activities": "activities",
               "Units History": "units_history", "Cash History": "cash_history", "External Flows": "flows",
               "Issues": "issues"}
PRICE_COLS = [("Ticker", "text", 0), ("Date", "date", 1), ("Close", "number", 2), ("AdjClose", "number", 3),
              ("DivCash", "number", 4), ("SplitFactor", "number", 5)]

TIINGO_PRICES_M = """let
    // Tickers, PriceStartDate and TiingoToken are model parameters written by `folio sync`.
    TickerList = List.Distinct(List.Select(List.Transform(Text.Split(Tickers, ","), Text.Trim), each _ <> "")),
    GetTicker = (t as text) as table =>
        let
            Response = Web.Contents(
                "https://api.tiingo.com",
                [
                    RelativePath = "tiingo/daily/" & t & "/prices",
                    Query = [startDate = PriceStartDate, format = "json", token = TiingoToken]
                ]
            ),
            Body = Json.Document(Response),
            Checked = if Value.Is(Body, type list) then Body else error Error.Record("FolioScreen.Tiingo", "Unexpected Tiingo response for " & t),
            Tbl = Table.FromRecords(Checked, {"date", "close", "adjClose", "divCash", "splitFactor"}, MissingField.Error),
            NonEmpty = if Table.RowCount(Tbl) = 0 then error Error.Record("FolioScreen.Tiingo", "Tiingo returned no prices for " & t) else Tbl,
            Tagged = Table.AddColumn(NonEmpty, "Ticker", each t, type text)
        in
            Tagged,
    // No try/otherwise: a ticker that fails must fail the refresh, never silently drop a holding.
    Combined = Table.Combine(List.Transform(TickerList, GetTicker)),
    Typed = Table.TransformColumns(Combined, {
        {"date", each Date.From(DateTimeZone.FromText(_)), type date},
        {"close", each Number.From(_), type number},
        {"adjClose", each Number.From(_), type number},
        {"divCash", each Number.From(_), type number},
        {"splitFactor", each Number.From(_), type number}
    }),
    Renamed = Table.RenameColumns(Typed, {{"date", "Date"}, {"close", "Close"}, {"adjClose", "AdjClose"}, {"divCash", "DivCash"}, {"splitFactor", "SplitFactor"}}),
    Result = Table.SelectColumns(Renamed, {"Ticker", "Date", "Close", "AdjClose", "DivCash", "SplitFactor"})
in
    Result"""

REFRESH_INFO_M = """let
    // Time of the last successful refresh (UTC).
    Source = #table(type table [RefreshedUTC = datetime], {{DateTimeZone.RemoveZone(DateTimeZone.UtcNow())}})
in
    Source"""

# ---------------------------------------------------------------------------- calculated tables
CALC_TABLES = {
    "Trading Calendar": ([("Date", "date"), ("DateIndex", "number")], """
VAR _b = MAX ( 'Sync Info'[Benchmark] )
VAR _dates =
    SELECTCOLUMNS (
        CALCULATETABLE ( DISTINCT ( Prices[Date] ), Prices[Ticker] = _b ),
        "Date", Prices[Date]
    )
RETURN
    ADDCOLUMNS (
        _dates,
        "DateIndex", VAR _d = [Date] RETURN COUNTROWS ( FILTER ( _dates, [Date] <= _d ) )
    )"""),
    "Position Daily": ([("AccountKey", "text"), ("Ticker", "text"), ("Date", "date"), ("Units", "number"),
                        ("LastPriceDate", "date"), ("Close", "number"), ("IsFilled", "logical"), ("Value", "number")], """
VAR _rows =
    SELECTCOLUMNS (
        GENERATE (
            FILTER ( 'Units History', NOT ISBLANK ( 'Units History'[Ticker] ) ),
            FILTER (
                'Trading Calendar',
                'Trading Calendar'[Date] >= 'Units History'[FromDate]
                    && 'Trading Calendar'[Date] < 'Units History'[ToDate]
            )
        ),
        "AccountKey", 'Units History'[AccountKey],
        "Ticker", 'Units History'[Ticker],
        "Date", 'Trading Calendar'[Date],
        "Units", 'Units History'[Units]
    )
VAR _withDate =
    ADDCOLUMNS (
        _rows,
        "LastPriceDate",
            VAR _t = [Ticker]
            VAR _d = [Date]
            RETURN CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] <= _d )
    )
VAR _withClose =
    ADDCOLUMNS (
        _withDate,
        "Close",
            VAR _t = [Ticker]
            VAR _ld = [LastPriceDate]
            RETURN CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] = _ld ),
        "IsFilled", [LastPriceDate] <> [Date]
    )
RETURN
    ADDCOLUMNS ( _withClose, "Value", [Units] * [Close] )"""),
    "Cash Daily": ([("AccountKey", "text"), ("Date", "date"), ("Cash", "number")], """
SELECTCOLUMNS (
    GENERATE (
        'Cash History',
        FILTER (
            'Trading Calendar',
            'Trading Calendar'[Date] >= 'Cash History'[FromDate]
                && 'Trading Calendar'[Date] < 'Cash History'[ToDate]
        )
    ),
    "AccountKey", 'Cash History'[AccountKey],
    "Date", 'Trading Calendar'[Date],
    "Cash", 'Cash History'[Cash]
)"""),
    "Portfolio Daily": ([("Date", "date"), ("DateIndex", "number"), ("SecuritiesValue", "number"), ("Cash", "number"),
                         ("PrevDate", "date"), ("Flow", "number"), ("Value", "number"), ("PrevValue", "number"),
                         ("DailyReturn", "number"), ("TWRIndex", "number")], """
VAR _cal =
    SELECTCOLUMNS ( 'Trading Calendar', "Date", 'Trading Calendar'[Date], "DateIndex", 'Trading Calendar'[DateIndex] )
VAR _base =
    ADDCOLUMNS (
        _cal,
        "SecuritiesValue", VAR _d = [Date] RETURN SUMX ( FILTER ( 'Position Daily', 'Position Daily'[Date] = _d ), 'Position Daily'[Value] ) + 0,
        "Cash", VAR _d = [Date] RETURN SUMX ( FILTER ( 'Cash Daily', 'Cash Daily'[Date] = _d ), 'Cash Daily'[Cash] ) + 0,
        "PrevDate", VAR _i = [DateIndex] RETURN MAXX ( FILTER ( _cal, [DateIndex] = _i - 1 ), [Date] )
    )
VAR _withFlow =
    ADDCOLUMNS (
        _base,
        "Flow",
            VAR _d = [Date]
            VAR _p = IF ( ISBLANK ( [PrevDate] ), DATE ( 1900, 1, 1 ), [PrevDate] )
            RETURN
                SUMX (
                    FILTER ( 'External Flows', 'External Flows'[Date] > _p && 'External Flows'[Date] <= _d ),
                    IF (
                        'External Flows'[Kind] = "CASH",
                        'External Flows'[Amount],
                        VAR _t = 'External Flows'[Ticker]
                        VAR _ld = CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] <= _d )
                        RETURN 'External Flows'[Units] * CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] = _ld )
                    )
                ) + 0,
        "Value", [SecuritiesValue] + [Cash]
    )
VAR _withPrev =
    ADDCOLUMNS (
        _withFlow,
        "PrevValue", VAR _i = [DateIndex] RETURN MAXX ( FILTER ( _withFlow, [DateIndex] = _i - 1 ), [Value] )
    )
VAR _start = MAX ( 'Sync Info'[PerformanceStart] )
VAR _startIdx = IF ( ISBLANK ( _start ), BLANK (), MINX ( FILTER ( _withPrev, [Date] >= _start ), [DateIndex] ) )
VAR _withRet =
    ADDCOLUMNS (
        _withPrev,
        "DailyReturn",
            VAR _i = [DateIndex]
            RETURN
                IF (
                    NOT ISBLANK ( _startIdx ) && _i > _startIdx,
                    IF ( ISBLANK ( [PrevValue] ) || [PrevValue] = 0, 0, DIVIDE ( [Value] - [Flow], [PrevValue] ) - 1 )
                )
    )
RETURN
    ADDCOLUMNS (
        _withRet,
        "TWRIndex",
            VAR _i = [DateIndex]
            RETURN
                IF (
                    NOT ISBLANK ( _startIdx ) && _i >= _startIdx,
                    COALESCE ( PRODUCTX ( FILTER ( _withRet, [DateIndex] > _startIdx && [DateIndex] <= _i ), 1 + [DailyReturn] ), 1 )
                )
    )"""),
}

MEASURES = [
    # (name, expression, formatString or None)
    ("Portfolio Synced UTC", "MAX ( 'Sync Info'[SyncedUTC] )", "d mmm yyyy hh:nn"),
    ("Portfolio Sync Age Hours", "VAR _s = [Portfolio Synced UTC]\nRETURN IF ( NOT ISBLANK ( _s ), DATEDIFF ( _s, UTCNOW (), HOUR ) )", "0"),
    ("Portfolio Data Status", """VAR _s = [Portfolio Synced UTC]
VAR _h = [Portfolio Sync Age Hours]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( _s ), "No portfolio data loaded",
        _h > 36, "STALE: portfolio last synced " & FORMAT ( _s, "d mmm yyyy, hh:nn" ) & " UTC (" & FORMAT ( _h, "0" ) & " h ago)",
        "Portfolio synced " & FORMAT ( _s, "d mmm yyyy, hh:nn" ) & " UTC"
    )""", None),
    ("Price Refresh UTC", "MAX ( 'Refresh Info'[RefreshedUTC] )", "d mmm yyyy hh:nn"),
    ("Market Date", "VAR _b = MAX ( 'Sync Info'[Benchmark] )\nRETURN CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _b )", "d mmm yyyy"),
    ("Data Hash", "MAX ( 'Sync Info'[DataHash] )", None),
    ("Data Source", "MAX ( 'Sync Info'[Source] )", None),
    ("Performance Status", "MAX ( 'Sync Info'[PerformanceStatus] )", None),
    ("Performance Start", "MAX ( 'Sync Info'[PerformanceStart] )", "d mmm yyyy"),
    ("Latest Value Date", "CALCULATE ( MAX ( 'Portfolio Daily'[Date] ), REMOVEFILTERS ( 'Portfolio Daily' ) )", "d mmm yyyy"),
    ("Portfolio Value", "VAR _d = [Latest Value Date]\nRETURN CALCULATE ( SUM ( 'Portfolio Daily'[Value] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] = _d )", "$#,0.00;−$#,0.00;$0.00"),
    ("Securities Value", "VAR _d = [Latest Value Date]\nRETURN CALCULATE ( SUM ( 'Portfolio Daily'[SecuritiesValue] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] = _d )", "$#,0.00;−$#,0.00;$0.00"),
    ("Cash Value", "VAR _d = [Latest Value Date]\nRETURN CALCULATE ( SUM ( 'Portfolio Daily'[Cash] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] = _d )", "$#,0.00;−$#,0.00;$0.00"),
    ("Securities Value Check", """SUMX (
    FILTER ( Positions, Positions[Priced] = TRUE () ),
    VAR _t = Positions[Ticker]
    VAR _ld = CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t )
    RETURN Positions[Units] * CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] = _ld )
)""", "#,0.00"),
    ("Broker Securities Value", "SUMX ( FILTER ( Positions, Positions[Priced] = TRUE () ), Positions[Units] * Positions[BrokerPrice] )", "#,0.00"),
    ("Last Close", """VAR _t = SELECTEDVALUE ( Positions[Ticker] )
VAR _ld = CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t )
RETURN IF ( NOT ISBLANK ( _t ), CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] = _ld ) )""", "#,0.00"),
    ("TWR Since Start", """VAR _d = [Latest Value Date]
VAR _v = CALCULATE ( MAX ( 'Portfolio Daily'[TWRIndex] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] = _d )
RETURN IF ( NOT ISBLANK ( _v ), _v - 1 )""", "0.00%"),
    ("Daily Value", "SUM ( 'Portfolio Daily'[Value] )", "#,0"),
    ("Errors", "CALCULATE ( COUNTROWS ( Issues ), Issues[Severity] = \"Error\" ) + 0", "0"),
    ("Warnings", "CALCULATE ( COUNTROWS ( Issues ), Issues[Severity] = \"Warning\" ) + 0", "0"),
    ("Missing Price Days", "COUNTROWS ( FILTER ( 'Position Daily', ISBLANK ( 'Position Daily'[Close] ) ) ) + 0", "0"),
    ("Filled Price Days", "COUNTROWS ( FILTER ( 'Position Daily', 'Position Daily'[IsFilled] = TRUE () && NOT ISBLANK ( 'Position Daily'[Close] ) ) ) + 0", "0"),
    ("Unconfirmed Splits", """VAR _splits = FILTER ( Prices, Prices[SplitFactor] <> 1 )
RETURN
    COUNTROWS (
        FILTER (
            _splits,
            VAR _t = Prices[Ticker]
            VAR _d = Prices[Date]
            VAR _held = CALCULATE ( COUNTROWS ( 'Units History' ), REMOVEFILTERS ( 'Units History' ), 'Units History'[Ticker] = _t, 'Units History'[FromDate] <= _d, 'Units History'[ToDate] > _d, 'Units History'[Units] <> 0 )
            VAR _reported = CALCULATE ( COUNTROWS ( Activities ), REMOVEFILTERS ( Activities ), Activities[Ticker] = _t, Activities[Type] IN { "SPLIT", "REVERSE_SPLIT", "STOCK_DIVIDEND" }, Activities[TradeDate] >= _d - 5, Activities[TradeDate] <= _d + 5 )
            RETURN _held > 0 && ( ISBLANK ( _reported ) || _reported = 0 )
        )
    ) + 0""", "0"),
]


# ============================================================================ TMDL rendering
def _indent(text: str, tabs: int) -> str:
    return "\n".join(("\t" * tabs + line) if line.strip() else "" for line in text.strip("\n").split("\n"))


def _q(name: str) -> str:
    return name if name.replace("_", "").isalnum() else f"'{name}'"


def _column(table: str, name: str, mtype: str, *, calculated: bool = False, hidden: bool = False,
            sort_by: Optional[str] = None, fmt_override: Optional[str] = None) -> str:
    lines = [f"\tcolumn {_q(name)}", f"\t\tdataType: {TMDL_TYPE[mtype]}"]
    if calculated:
        lines += ["\t\tisNameInferred", "\t\tisDataTypeInferred"]
    if hidden:
        lines.append("\t\tisHidden")
    fmt = fmt_override or {"date": "d mmm yyyy", "datetime": "d mmm yyyy hh:nn"}.get(mtype)
    if fmt:
        lines.append(f"\t\tformatString: {fmt}")
    lines.append(f"\t\tlineageTag: {lineage(table, name)}")
    lines.append("\t\tsummarizeBy: none")
    lines.append(f"\t\tsourceColumn: [{name}]" if calculated else f"\t\tsourceColumn: {name}")
    if sort_by:
        lines.append(f"\t\tsortByColumn: {_q(sort_by)}")
    lines += ["", "\t\tannotation SummarizationSetBy = Automatic"]
    if mtype == "date":
        lines += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
    return "\n".join(lines)


def _m_table_tmdl(table: str, columns: list, m_source: str, *, hidden: bool = False) -> str:
    parts = [f"table {_q(table)}", f"\tlineageTag: {lineage(table)}"]
    if hidden:
        parts.append("\tisHidden")
    body = "\n".join(parts) + "\n\n"
    body += "\n\n".join(_column(table, n, t) for n, t in columns)
    body += f"\n\n\tpartition {_q(table)} = m\n\t\tmode: import\n\t\tsource =\n{_indent(m_source, 4)}\n\n\tannotation PBI_ResultType = Table\n"
    return body


def _calc_table_tmdl(table: str, columns: list, dax: str) -> str:
    body = f"table {_q(table)}\n\tlineageTag: {lineage(table)}\n\n"
    def col(spec):
        n, t = spec[0], spec[1]
        o = spec[2] if len(spec) > 2 else {}
        return _column(table, n, t, calculated=True, hidden=o.get("hidden", False), sort_by=o.get("sortBy"), fmt_override=o.get("format"))
    body += "\n\n".join(col(c) for c in columns)
    body += f"\n\n\tpartition {_q(table)} = calculated\n\t\tmode: import\n\t\tsource =\n{_indent(dax, 4)}\n"
    return body


def _measures_tmdl(extra: Optional[list] = None) -> str:
    """Measures are (name, expr, formatString) or (name, expr, formatString, {"dataCategory": ..., "formatStringDefinition": ...})."""
    out = [f"table _Measures\n\tlineageTag: {lineage('_Measures')}\n"]
    for item in list(MEASURES) + list(extra or []):
        name, expr, fmt = item[:3]
        props = item[3] if len(item) > 3 else {}
        if "\n" in expr:
            m = f"\tmeasure {_q(name)} =\n{_indent(expr, 3)}"
        else:
            m = f"\tmeasure {_q(name)} = {expr}"
        if fmt:
            m += f"\n\t\tformatString: {fmt}"
        if props.get("dataCategory"):
            m += f"\n\t\tdataCategory: {props['dataCategory']}"
        m += f"\n\t\tlineageTag: {lineage('_Measures', name)}"
        # Child objects must follow all plain properties in TMDL (probe round 1: "Invalid indentation").
        if props.get("formatStringDefinition"):
            m += f"\n\n\t\tformatStringDefinition = {props['formatStringDefinition']}"
        if props.get("formatStringDefinitionBlock"):
            m += f"\n\n\t\tformatStringDefinition =\n{_indent(props['formatStringDefinitionBlock'], 4)}"
        out.append(m)
    out.append(_column("_Measures", "_Hidden", "number", hidden=True).replace("dataType: double", "dataType: int64"))
    out.append("\tpartition _Measures = m\n\t\tmode: import\n\t\tsource =\n"
               + _indent("let\n    Source = #table(type table [_Hidden = Int64.Type], {{1}})\nin\n    Source", 4))
    return "\n\n".join(out) + "\n\n\tannotation PBI_ResultType = Table\n"


def _expressions_tmdl(dataset: dict, tiingo_token: Optional[str]) -> str:
    def param(name: str, value: str, doc: str) -> str:
        return (f"/// {doc}\nexpression {name} = {m_text(value)} meta [IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]\n"
                f"\tlineageTag: {lineage('expr', name)}\n\n\tannotation PBI_ResultType = Text\n")
    return "\n".join([
        param("TiingoToken", tiingo_token or "SET_BY_FOLIO_SYNC", "Tiingo API token, inserted by folio sync from the system credential store"),
        param("Tickers", ",".join(dataset["tickers"]), "Comma-separated Tiingo tickers (held securities + benchmark), written by folio sync"),
        param("PriceStartDate", dataset["meta"]["price_start"], "First price date requested from Tiingo (yyyy-mm-dd), written by folio sync"),
    ])


def render_semantic_model(dataset: dict, *, demo_prices: Optional[dict] = None, tiingo_token: Optional[str] = None,
                          name: str = PROJECT, extra_measures: Optional[list] = None,
                          extra_tables: Optional[dict] = None, include_report: bool = True) -> dict:
    """extra_tables: {table name: complete TMDL text} (used by the visual capability probe)."""
    """Returns {relative_path: text} for the .SemanticModel folder."""
    live = demo_prices is None
    files = {}
    tables = []
    meta = dataset["meta"]
    files["definition/tables/Sync Info.tmdl"] = _m_table_tmdl(
        "Sync Info", [(c[0], c[1]) for c in EMBEDDED["Sync Info"]], m_table(EMBEDDED["Sync Info"], [meta]), hidden=True)
    tables.append("Sync Info")
    for t, key in DATASET_KEY.items():
        files[f"definition/tables/{t}.tmdl"] = _m_table_tmdl(t, [(c[0], c[1]) for c in EMBEDDED[t]], m_table(EMBEDDED[t], dataset[key]))
        tables.append(t)
    if live:
        prices_m = TIINGO_PRICES_M
    else:
        rows = [{i: v for i, v in enumerate((t, *r[:5]))} for t, series in sorted(demo_prices.items()) for r in series]
        prices_m = m_table([(n, mt, i) for n, mt, i in PRICE_COLS], rows)
    files["definition/tables/Prices.tmdl"] = _m_table_tmdl("Prices", [(c[0], c[1]) for c in PRICE_COLS], prices_m)
    files["definition/tables/Refresh Info.tmdl"] = _m_table_tmdl("Refresh Info", [("RefreshedUTC", "datetime")], REFRESH_INFO_M, hidden=True)
    tables += ["Prices", "Refresh Info"]
    for t, (cols, dax) in CALC_TABLES.items():
        files[f"definition/tables/{t}.tmdl"] = _calc_table_tmdl(t, cols, dax)
        tables.append(t)
    from .report_model import report_measures, report_tables_tmdl
    report_tables = report_tables_tmdl() if include_report else {}
    for t, tmdl in list(report_tables.items()) + list((extra_tables or {}).items()):
        files[f"definition/tables/{t}.tmdl"] = tmdl
        tables.append(t)
    files["definition/tables/_Measures.tmdl"] = _measures_tmdl((report_measures() if include_report else []) + list(extra_measures or []))
    tables.append("_Measures")
    if live:
        files["definition/expressions.tmdl"] = _expressions_tmdl(dataset, tiingo_token)
    files["definition/database.tmdl"] = "database\n\tcompatibilityLevel: 1606\n"
    query_order = (["TiingoToken", "Tickers", "PriceStartDate"] if live else []) + \
        [t for t in tables if t not in CALC_TABLES and t not in (extra_tables or {}) and t not in report_tables]
    files["definition/model.tmdl"] = (
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        "annotation __PBI_TimeIntelligenceEnabled = 0\n\n"
        f"annotation PBI_QueryOrder = {json.dumps(query_order)}\n\n"
        "annotation PBI_ProTooling = [\"DevMode\"]\n\n"
        + "\n".join(f"ref table {_q(t)}" for t in tables) + "\n")
    files["definition.pbism"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}}, indent=2) + "\n"
    files[".platform"] = _platform("SemanticModel", name)
    return files


def _platform(kind: str, name: str) -> str:
    return json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": kind, "displayName": name},
        "config": {"version": "2.0", "logicalId": lineage("platform", kind, name)}}, indent=2) + "\n"


# ============================================================================ PBIR report (plain validation page)
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.10.0/schema.json"


def _lit(v: str) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def _field(kind: str, entity: str, prop: str, display: str) -> dict:
    return {"field": {kind: {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
            "queryRef": f"{entity}.{prop}", "nativeQueryRef": display, "displayName": display}


def _container_title(text: str) -> dict:
    return {"title": [{"properties": {"show": _lit("true"), "text": _lit("'" + text.replace("'", "''") + "'")}}]}


def _visual(name: str, x: int, y: int, w: int, h: int, z: int, visual: dict) -> dict:
    return {"$schema": VC_SCHEMA, "name": name,
            "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z}, "visual": visual}


def _table(name, x, y, w, h, z, title, fields):
    projections = [_field("Measure" if kind == "M" else "Column", ent, prop, disp) for kind, ent, prop, disp in fields]
    return _visual(name, x, y, w, h, z, {"visualType": "tableEx",
                                          "query": {"queryState": {"Values": {"projections": projections}}},
                                          "visualContainerObjects": _container_title(title)})


def render_report(name: str = PROJECT) -> dict:
    files = {}
    defn = "definition"
    files["definition.pbir"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}}, indent=2) + "\n"
    files[".platform"] = _platform("Report", name)
    files[f"{defn}/version.json"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"}, indent=2) + "\n"
    files[f"{defn}/report.json"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {"baseTheme": {"name": "CY26SU05", "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"},
                                          "type": "SharedResources"}},
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": "CY26SU05", "path": "BaseThemes/CY26SU05.json", "type": "BaseTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}},
        indent=2) + "\n"
    files[f"{defn}/pages/pages.json"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": ["validation"], "activePageName": "validation"}, indent=2) + "\n"
    files[f"{defn}/pages/validation/page.json"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
        "name": "validation", "displayName": "PoC validation", "displayOption": "FitToWidth",
        "height": 1180, "width": 1440}, indent=2) + "\n"
    M, C = "M", "C"
    visuals = [
        _visual("pageTitle", 24, 12, 1392, 40, 1000, {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [
            {"textRuns": [{"value": "FolioScreen · proof-of-concept validation page (data checks only, not the product design)",
                           "textStyle": {"fontSize": "14pt", "fontWeight": "bold"}}]}]}}]}}),
        _table("statusTable", 24, 60, 1392, 90, 2000, "Data status", [
            (M, "_Measures", "Portfolio Data Status", "Portfolio data"), (M, "_Measures", "Market Date", "Market date"),
            (M, "_Measures", "Price Refresh UTC", "Price refresh (UTC)"), (M, "_Measures", "Data Source", "Source"),
            (M, "_Measures", "Data Hash", "Data hash"), (M, "_Measures", "Errors", "Errors"), (M, "_Measures", "Warnings", "Warnings")]),
        _table("valueTable", 24, 160, 1392, 90, 3000, "Values and consistency checks", [
            (M, "_Measures", "Portfolio Value", "Portfolio value"), (M, "_Measures", "Securities Value", "Securities (daily table)"),
            (M, "_Measures", "Securities Value Check", "Securities (positions × last close)"),
            (M, "_Measures", "Broker Securities Value", "Securities (broker prices)"), (M, "_Measures", "Cash Value", "Cash"),
            (M, "_Measures", "Performance Status", "Performance"), (M, "_Measures", "Performance Start", "Perf. start"),
            (M, "_Measures", "TWR Since Start", "TWR since start"), (M, "_Measures", "Missing Price Days", "Missing price days"),
            (M, "_Measures", "Filled Price Days", "Filled price days"), (M, "_Measures", "Unconfirmed Splits", "Unconfirmed splits")]),
        _table("accountsTable", 24, 260, 1392, 130, 4000, "Accounts and coverage", [
            (C, "Accounts", "AccountLabel", "Account"), (C, "Accounts", "ConnectionAccess", "Access"),
            (C, "Accounts", "ConnectionStatus", "Connection"), (C, "Accounts", "HistoryStart", "History start"),
            (C, "Accounts", "TxSyncedThrough", "Transactions synced through"), (C, "Accounts", "HoldingsSyncedUTC", "Holdings synced (UTC)"),
            (C, "Accounts", "PerformanceStart", "Perf. start"), (C, "Accounts", "PerformanceStatus", "Perf. status")]),
        _table("holdingsTable", 24, 400, 1392, 260, 5000, "Holdings (as reported by the brokerage)", [
            (C, "Positions", "AccountLabel", "Account"), (C, "Positions", "InstrumentKey", "Symbol"), (C, "Positions", "Ticker", "Tiingo ticker"),
            (C, "Positions", "Units", "Units"), (C, "Positions", "BrokerPrice", "Broker price"), (M, "_Measures", "Last Close", "Last close"),
            (C, "Positions", "BrokerCostBasis", "Broker cost basis"), (C, "Positions", "Priced", "Priced")]),
        _table("issuesTable", 24, 670, 1392, 260, 6000, "Reconciliation issues (nothing is auto-corrected)", [
            (C, "Issues", "Severity", "Severity"), (C, "Issues", "Code", "Code"), (C, "Issues", "AccountLabel", "Account"),
            (C, "Issues", "InstrumentKey", "Symbol"), (C, "Issues", "AffectsFrom", "From"), (C, "Issues", "AffectsTo", "To"),
            (C, "Issues", "Message", "Message")]),
        _visual("valueChart", 24, 940, 1392, 220, 7000, {
            "visualType": "lineChart",
            "query": {"queryState": {
                "Category": {"projections": [{**_field("Column", "Portfolio Daily", "Date", "Date"), "active": True}]},
                "Y": {"projections": [_field("Measure", "_Measures", "Daily Value", "Portfolio value")]}},
                "sortDefinition": {"sort": [{"field": {"Column": {"Expression": {"SourceRef": {"Entity": "Portfolio Daily"}}, "Property": "Date"}},
                                             "direction": "Ascending"}]}},
            "visualContainerObjects": _container_title("Portfolio value (reconstructed, end of day)")}),
    ]
    for v in visuals:
        files[f"{defn}/pages/validation/visuals/{v['name']}/visual.json"] = json.dumps(v, indent=2) + "\n"
    return files


BASE_THEME_REL = "StaticResources/SharedResources/BaseThemes/CY26SU05.json"


def write_pbip(out_dir: Path, model_files: dict, report_files: dict, base_theme_path: Path, name: str = PROJECT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for rel, text in model_files.items():
        p = out_dir / f"{name}.SemanticModel" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for rel, text in report_files.items():
        p = out_dir / f"{name}.Report" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    theme = out_dir / f"{name}.Report" / BASE_THEME_REL
    theme.parent.mkdir(parents=True, exist_ok=True)
    theme.write_bytes(base_theme_path.read_bytes())
    (out_dir / f"{name}.pbip").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{name}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2) + "\n", encoding="utf-8")
