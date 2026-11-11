"""Semantic-model additions behind the FolioScreen report (Phase 4).

Everything here reads the verified base tables (Positions, Cash, Activities, Prices, Units History, External Flows,
Position Daily, Portfolio Daily). There are no relationships: slicers write to small disconnected choice tables and
measures read them with SELECTEDVALUE, exactly like the period buttons proven in Marine Energy Screen.

Conventions
- A period window starts at the last trading day on or before (latest date − N months); ALL starts at the first
  day with a time-weighted index (the performance start). The Python reference uses the same rule.
- Portfolio values always use raw closes (the price actually traded). Price charts, 52-week ranges, trend lines and
  daily % changes use split-adjusted closes, built from Tiingo's splitFactor (not adjClose, which also strips dividends).
- Nothing is estimated: a figure that cannot be computed honestly is BLANK, and the status line says why.
"""
from __future__ import annotations

from .model_writer import lineage

SIGNED_PCT = "+0.00%;−0.00%;0.00%"
SIGNED_PCT1 = "+0.0%;−0.0%;0.0%"
ARROW_PCT = "▲ +0.00%;▼ −0.00%;0.00%"
MONEY = "$#,0.00;−$#,0.00;$0.00"
MONEY0 = "$#,0;−$#,0;$0"
SMONEY = "+$#,0.00;−$#,0.00;$0.00"
ARROW_MONEY = "▲ +$#,0.00;▼ −$#,0.00;$0.00"
TX_MONEY = "+$#,0.00;−$#,0.00;—"
PCT1 = "0.0%"
PTS = "+0.00 \"pts\";−0.00 \"pts\";0.00 \"pts\""

GAIN, LOSS, NEUTRAL, INK, INK2, CAUTION, PORTFOLIO, BENCHMARK = (
    "#3DCB95", "#FF7A7A", "#8F9DAE", "#E6ECF2", "#A3B2C4", "#E8B15A", "#6CB4FF", "#8F9DAE")

# ============================================================================ calculated tables
# (columns: (name, type[, {"sortBy": col, "hidden": bool, "format": str}]), dax)
SHORT_ACCOUNT = """VAR _lbl = {expr}
VAR _pos = SEARCH ( "·", _lbl, 1, 0 )
VAR _tail = IF ( _pos > 0, TRIM ( MID ( _lbl, _pos + 1, 200 ) ), _lbl )
RETURN UPPER ( LEFT ( _tail, 1 ) ) & MID ( _tail, 2, 200 )"""


def _short_account(expr: str) -> str:
    return "( " + SHORT_ACCOUNT.format(expr=expr).replace("\n", " ") + " )"


REPORT_TABLES = {
    "Price History": ([("Ticker", "text"), ("Date", "date"), ("Close", "number"), ("SplitAdjClose", "number")], """
VAR _splits =
    SELECTCOLUMNS (
        FILTER ( Prices, NOT ISBLANK ( Prices[SplitFactor] ) && Prices[SplitFactor] > 0 && Prices[SplitFactor] <> 1 ),
        "T", Prices[Ticker], "D", Prices[Date], "F", Prices[SplitFactor]
    )
RETURN
    ADDCOLUMNS (
        SELECTCOLUMNS ( Prices, "Ticker", Prices[Ticker], "Date", Prices[Date], "Close", Prices[Close] ),
        "SplitAdjClose",
            VAR _t = [Ticker]
            VAR _d = [Date]
            VAR _f = PRODUCTX ( FILTER ( _splits, [T] = _t && [D] > _d ), [F] )
            RETURN [Close] / IF ( ISBLANK ( _f ), 1, _f )
    )"""),
    "Holding Rows": ([("AccountKey", "text"), ("AccountLabel", "text"), ("Symbol", "text"), ("Ticker", "text"), ("Name", "text"),
                      ("Kind", "text"), ("IsCash", "logical"), ("Units", "number"), ("CostBasis", "number"), ("CashAmount", "number"),
                      ("LastDate", "date"), ("PrevDate", "date"), ("LastClose", "number"), ("LastAdj", "number"),
                      ("Lo52", "number"), ("Hi52", "number"), ("PrevAdj", "number"), ("Value", "number"), ("DayAbs", "number"),
                      ("DayPct", "number")], f"""
VAR _e = MAX ( 'Portfolio Daily'[Date] )
VAR _pos =
    SELECTCOLUMNS (
        FILTER ( Positions, Positions[Priced] = TRUE () ),
        "AccountKey", Positions[AccountKey],
        "AccountLabel", {_short_account("Positions[AccountLabel]")},
        "Symbol", Positions[InstrumentKey],
        "Ticker", Positions[Ticker],
        "Name", Positions[Description],
        "Kind", SWITCH ( LOWER ( Positions[Kind] ), "etf", "ETF", "stock", "Stock", "adr", "Stock", "cef", "Fund", "mutualfund", "Fund", "preferred_stock", "Preferred", "Other" ),
        "IsCash", FALSE (),
        "Units", Positions[Units],
        "CostBasis", Positions[Units] * Positions[BrokerCostBasis],
        "CashAmount", 0.0
    )
VAR _cash =
    SELECTCOLUMNS (
        Cash,
        "AccountKey", Cash[AccountKey],
        "AccountLabel", {_short_account("Cash[AccountLabel]")},
        "Symbol", "Cash",
        "Ticker", "",
        "Name", "Cash · " & Cash[Currency],
        "Kind", "Cash",
        "IsCash", TRUE (),
        "Units", 0.0,
        "CostBasis", 0.0,
        "CashAmount", Cash[Amount]
    )
VAR _rows = UNION ( _pos, _cash )
VAR _withLast =
    ADDCOLUMNS (
        _rows,
        "LastDate", VAR _t = [Ticker] RETURN IF ( _t <> "", CALCULATE ( MAX ( 'Price History'[Date] ), 'Price History'[Ticker] = _t, 'Price History'[Date] <= _e ) )
    )
VAR _withPx =
    ADDCOLUMNS (
        _withLast,
        "PrevDate", VAR _t = [Ticker] VAR _ld = [LastDate] RETURN IF ( _t <> "", CALCULATE ( MAX ( 'Price History'[Date] ), 'Price History'[Ticker] = _t, 'Price History'[Date] < _ld ) ),
        "LastClose", VAR _t = [Ticker] VAR _ld = [LastDate] RETURN IF ( _t <> "", CALCULATE ( MAX ( 'Price History'[Close] ), 'Price History'[Ticker] = _t, 'Price History'[Date] = _ld ) ),
        "LastAdj", VAR _t = [Ticker] VAR _ld = [LastDate] RETURN IF ( _t <> "", CALCULATE ( MAX ( 'Price History'[SplitAdjClose] ), 'Price History'[Ticker] = _t, 'Price History'[Date] = _ld ) ),
        "Lo52", VAR _t = [Ticker] VAR _ld = [LastDate] RETURN IF ( _t <> "", CALCULATE ( MIN ( 'Price History'[SplitAdjClose] ), 'Price History'[Ticker] = _t, 'Price History'[Date] > _ld - 365, 'Price History'[Date] <= _ld ) ),
        "Hi52", VAR _t = [Ticker] VAR _ld = [LastDate] RETURN IF ( _t <> "", CALCULATE ( MAX ( 'Price History'[SplitAdjClose] ), 'Price History'[Ticker] = _t, 'Price History'[Date] > _ld - 365, 'Price History'[Date] <= _ld ) )
    )
VAR _withPrev =
    ADDCOLUMNS (
        _withPx,
        "PrevAdj", VAR _t = [Ticker] VAR _pd = [PrevDate] RETURN IF ( _t <> "" && NOT ISBLANK ( _pd ), CALCULATE ( MAX ( 'Price History'[SplitAdjClose] ), 'Price History'[Ticker] = _t, 'Price History'[Date] = _pd ) )
    )
RETURN
    ADDCOLUMNS (
        _withPrev,
        "Value", IF ( [IsCash], [CashAmount], [Units] * [LastClose] ),
        "DayAbs", IF ( [IsCash] || ISBLANK ( [PrevAdj] ), BLANK (), [Units] * ( [LastAdj] - [PrevAdj] ) ),
        "DayPct", IF ( [IsCash] || ISBLANK ( [PrevAdj] ) || [PrevAdj] = 0, BLANK (), [LastAdj] / [PrevAdj] - 1 )
    )"""),
    "Account Choice": ([("Choice", "text", {"sortBy": "Order"}), ("AccountKey", "text"), ("Order", "number", {"hidden": True})], f"""
UNION (
    ROW ( "Choice", "All accounts", "AccountKey", "*", "Order", 0 ),
    SELECTCOLUMNS (
        Accounts,
        "Choice", {_short_account("Accounts[AccountLabel]")},
        "AccountKey", Accounts[AccountKey],
        "Order", 1
    )
)"""),
    "Account List": ([("Account", "text"), ("AccountKey", "text")], f"""
SELECTCOLUMNS ( Accounts, "Account", {_short_account("Accounts[AccountLabel]")}, "AccountKey", Accounts[AccountKey] )"""),
    "Type Choice": ([("Choice", "text", {"sortBy": "Order"}), ("Kind", "text"), ("Order", "number", {"hidden": True})], """
VAR _kinds = FILTER ( DISTINCT ( SELECTCOLUMNS ( 'Holding Rows', "K", 'Holding Rows'[Kind] ) ), [K] <> "Cash" )
RETURN
    UNION (
        ROW ( "Choice", "All types", "Kind", "*", "Order", 0 ),
        SELECTCOLUMNS (
            _kinds,
            "Choice", SWITCH ( [K], "Stock", "Stocks", "ETF", "ETFs", "Fund", "Funds", [K] ),
            "Kind", [K],
            "Order", SWITCH ( [K], "Stock", 1, "ETF", 2, "Fund", 3, "Preferred", 4, 9 )
        )
    )"""),
    "Periods": ([("Period", "text", {"sortBy": "Order"}), ("Order", "number", {"hidden": True})], """
DATATABLE ( "Period", STRING, "Order", INTEGER, { { "1M", 1 }, { "3M", 2 }, { "6M", 3 }, { "1Y", 4 }, { "ALL", 5 } } )"""),
    "Period Rows": ([("Label", "text", {"sortBy": "Order"}), ("Period", "text"), ("Order", "number", {"hidden": True})], """
DATATABLE (
    "Label", STRING, "Period", STRING, "Order", INTEGER,
    { { "1 month", "1M", 1 }, { "3 months", "3M", 2 }, { "6 months", "6M", 3 }, { "12 months", "1Y", 4 }, { "Since start", "ALL", 5 } }
)"""),
    "Income Months": ([("MonthIndex", "number", {"hidden": True}), ("MonthStart", "date", {"format": "mmm"}), ("Label", "text", {"sortBy": "MonthIndex"})], """
VAR _e = MAX ( 'Portfolio Daily'[Date] )
RETURN
    SELECTCOLUMNS (
        GENERATESERIES ( 1, 12, 1 ),
        "MonthIndex", [Value],
        "MonthStart", EOMONTH ( _e, [Value] - 13 ) + 1,
        "Label", LEFT ( FORMAT ( EOMONTH ( _e, [Value] - 13 ) + 1, "mmm" ), 1 ) & REPT ( UNICHAR ( 8203 ), [Value] )
    )"""),
    "Gain Breakdown": ([("Label", "text", {"sortBy": "Order"}), ("Amount", "number"), ("Group", "text"), ("Order", "number", {"hidden": True})], """
VAR _s = CALCULATE ( MIN ( 'Portfolio Daily'[Date] ), NOT ISBLANK ( 'Portfolio Daily'[TWRIndex] ) )
VAR _e = MAX ( 'Portfolio Daily'[Date] )
VAR _secKeys =
    DISTINCT (
        SELECTCOLUMNS (
            FILTER ( 'Units History', NOT ISBLANK ( 'Units History'[Ticker] ) && 'Units History'[Ticker] <> "" ),
            "K", 'Units History'[InstrumentKey], "T", 'Units History'[Ticker]
        )
    )
VAR _sec =
    ADDCOLUMNS (
        _secKeys,
        "A",
            VAR _k = [K]
            VAR _t = [T]
            VAR _vEnd = SUMX ( FILTER ( 'Position Daily', 'Position Daily'[Ticker] = _t && 'Position Daily'[Date] = _e ), 'Position Daily'[Value] )
            VAR _vStart = SUMX ( FILTER ( 'Position Daily', 'Position Daily'[Ticker] = _t && 'Position Daily'[Date] = _s ), 'Position Daily'[Value] )
            VAR _cash =
                SUMX (
                    FILTER ( Activities, Activities[InstrumentKey] = _k && Activities[TradeDate] > _s && Activities[TradeDate] <= _e
                        && NOT ( Activities[Class] IN { "EXTERNAL_ASSET", "EXTERNAL_CASH", "CASH_EQUIVALENT_TRADE" } ) ),
                    Activities[Amount]
                )
            VAR _assetIn =
                SUMX (
                    FILTER ( 'External Flows', 'External Flows'[Kind] <> "CASH" && 'External Flows'[Ticker] = _t
                        && 'External Flows'[Date] > _s && 'External Flows'[Date] <= _e ),
                    VAR _d = 'External Flows'[Date]
                    VAR _ld = CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] <= _d )
                    RETURN 'External Flows'[Units] * CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] = _ld )
                )
            RETURN COALESCE ( _vEnd, 0 ) - COALESCE ( _vStart, 0 ) + COALESCE ( _cash, 0 ) - COALESCE ( _assetIn, 0 )
    )
VAR _secList = SELECTCOLUMNS ( _secKeys, "K2", [K] )
VAR _other =
    FILTER (
        Activities,
        Activities[TradeDate] > _s && Activities[TradeDate] <= _e
            && NOT ( Activities[Class] IN { "EXTERNAL_ASSET", "EXTERNAL_CASH", "CASH_EQUIVALENT_TRADE" } )
            && NOT ( Activities[InstrumentKey] IN _secList )
    )
VAR _income = COALESCE ( SUMX ( FILTER ( _other, Activities[Class] = "INCOME" ), Activities[Amount] ), 0 )
VAR _costs = COALESCE ( SUMX ( FILTER ( _other, Activities[Class] = "COST" ), Activities[Amount] ), 0 )
VAR _misc = COALESCE ( SUMX ( FILTER ( _other, NOT ( Activities[Class] IN { "INCOME", "COST" } ) ), Activities[Amount] ), 0 )
VAR _u =
    UNION (
        SELECTCOLUMNS ( _sec, "Label", [K], "Amount", [A], "Group", "Security" ),
        ROW ( "Label", "Interest", "Amount", _income, "Group", "Cash" ),
        ROW ( "Label", "Fees", "Amount", _costs, "Group", "Cash" ),
        ROW ( "Label", "Adjustments", "Amount", _misc, "Group", "Cash" )
    )
VAR _kept = FILTER ( _u, NOT ISBLANK ( _s ) && ( [Group] = "Security" || [Amount] <> 0 ) )
RETURN
    ADDCOLUMNS (
        _kept,
        "Order",
            IF (
                [Group] = "Security",
                RANKX ( FILTER ( _kept, [Group] = "Security" ), [Amount], , DESC, DENSE ),
                SWITCH ( [Label], "Interest", 100, "Fees", 101, 102 )
            )
    )"""),
    "Activity Log": ([("Key", "text"), ("Date", "date"), ("Account", "text"), ("Type", "text"), ("Symbol", "text"),
                      ("Detail", "text"), ("Amount", "number"), ("InstrumentKey", "text")], f"""
SELECTCOLUMNS (
    Activities,
    "Key", Activities[ActivityKey],
    "Date", Activities[TradeDate],
    "Account", {_short_account("LOOKUPVALUE ( Accounts[AccountLabel], Accounts[AccountKey], Activities[AccountKey] )")},
    "Type",
        SWITCH (
            Activities[Type],
            "CONTRIBUTION", "Deposit", "WITHDRAWAL", "Withdrawal", "BUY", "Buy", "SELL", "Sell", "REI", "Reinvest",
            "DIVIDEND", "Dividend", "SUBSTITUTE_DIVIDEND", "Dividend", "INTEREST", "Interest", "DISTRIBUTION", "Distribution",
            "RETURN_OF_CAPITAL", "Return of capital", "REBATE", "Rebate", "FEE", "Fee", "TAX", "Tax",
            "SPLIT", "Split", "REVERSE_SPLIT", "Reverse split", "STOCK_DIVIDEND", "Stock dividend", "SPINOFF", "Spin-off",
            "STOCK_MERGER", "Merger", "ADJUSTMENT", "Adjustment",
            "INTERNAL_CASH_TRANSFER_IN", "Transfer in", "INTERNAL_CASH_TRANSFER_OUT", "Transfer out",
            "EXTERNAL_ASSET_TRANSFER_IN", "Shares in", "EXTERNAL_ASSET_TRANSFER_OUT", "Shares out",
            "INTERNAL_ASSET_TRANSFER_IN", "Shares in", "INTERNAL_ASSET_TRANSFER_OUT", "Shares out",
            "TRANSFER", "Transfer",
            Activities[Type]
        ),
    "Symbol", IF ( ISBLANK ( Activities[InstrumentKey] ) || Activities[InstrumentKey] = "", "—", Activities[InstrumentKey] ),
    "Detail",
        SWITCH (
            TRUE (),
            Activities[Type] IN {{ "BUY", "SELL", "REI" }} && Activities[Units] <> 0,
                IF ( INT ( Activities[Units] ) = Activities[Units], FORMAT ( ABS ( Activities[Units] ), "#,0" ), FORMAT ( ABS ( Activities[Units] ), "#,0.####" ) ) & " at " & FORMAT ( Activities[Price], "$#,0.00" )
                    & IF ( Activities[Fee] <> 0, " · fee " & FORMAT ( ABS ( Activities[Fee] ), "$#,0.00" ), "" ),
            Activities[Class] IN {{ "CORPORATE", "EXTERNAL_ASSET" }} && Activities[Units] <> 0,
                IF ( INT ( Activities[Units] ) = Activities[Units], FORMAT ( Activities[Units], "+#,0;−#,0" ), FORMAT ( Activities[Units], "+#,0.####;−#,0.####" ) ) & " units",
            ""
        ),
    "Amount",
        IF (
            Activities[Class] IN {{ "EXTERNAL_ASSET", "CASH_EQUIVALENT_TRADE", "CORPORATE" }},
            BLANK (),
            Activities[Amount]
        ),
    "InstrumentKey", Activities[InstrumentKey]
)"""),
    "Checks": ([("Order", "number", {"hidden": True}), ("Check", "text", {"sortBy": "Order"})], """
DATATABLE (
    "Order", INTEGER, "Check", STRING,
    {
        { 1, "No negative positions" },
        { 2, "All holdings priced" },
        { 3, "Splits confirmed" },
        { 4, "History complete" },
        { 5, "No open issues" }
    }
)"""),
}

CHART_METRIC = "Chart Metric"


def chart_metric_tmdl() -> str:
    """Field parameter. The switch filters the Mode column: Value → one field, Return → portfolio and benchmark.
    (Two rows sharing one display label made the slicer list 'Return' twice and select only one field.)"""
    t = CHART_METRIC
    return f"""table '{t}'
\tlineageTag: {lineage(t)}

\tcolumn '{t}'
\t\tdataType: string
\t\tlineageTag: {lineage(t, 'name')}
\t\tsummarizeBy: none
\t\tsourceColumn: [Value1]
\t\tsortByColumn: '{t} Order'

\t\trelatedColumnDetails
\t\t\tgroupByColumn: '{t} Fields'

\t\tannotation SummarizationSetBy = Automatic

\tcolumn '{t} Fields'
\t\tdataType: string
\t\tisHidden
\t\tlineageTag: {lineage(t, 'fields')}
\t\tsummarizeBy: none
\t\tsourceColumn: [Value2]
\t\tsortByColumn: '{t} Order'

\t\textendedProperty ParameterMetadata =
\t\t\t\t{{
\t\t\t\t  "version": 3,
\t\t\t\t  "kind": 2
\t\t\t\t}}

\t\tannotation SummarizationSetBy = Automatic

\tcolumn '{t} Order'
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: {lineage(t, 'order')}
\t\tsummarizeBy: sum
\t\tsourceColumn: [Value3]

\t\tannotation SummarizationSetBy = Automatic

\tcolumn Mode
\t\tdataType: string
\t\tlineageTag: {lineage(t, 'mode')}
\t\tsummarizeBy: none
\t\tsourceColumn: [Value4]
\t\tsortByColumn: 'Mode Order'

\t\tannotation SummarizationSetBy = Automatic

\tcolumn 'Mode Order'
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: {lineage(t, 'modeorder')}
\t\tsummarizeBy: sum
\t\tsourceColumn: [Value5]

\t\tannotation SummarizationSetBy = Automatic

\tpartition '{t}' = calculated
\t\tmode: import
\t\tsource =
\t\t\t\t{{
\t\t\t\t    ("Portfolio value", NAMEOF ( '_Measures'[Market value] ), 0, "Value", 0),
\t\t\t\t    ("Portfolio", NAMEOF ( '_Measures'[Portfolio return] ), 1, "Return", 1),
\t\t\t\t    ("Benchmark", NAMEOF ( '_Measures'[Benchmark return] ), 2, "Return", 1)
\t\t\t\t}}
"""


# ============================================================================ measure helpers
def window_start(period_expr: str) -> str:
    return f"""VAR _per = {period_expr}
VAR _end = CALCULATE ( MAX ( 'Portfolio Daily'[Date] ), REMOVEFILTERS ( 'Portfolio Daily' ) )
VAR _first = CALCULATE ( MIN ( 'Portfolio Daily'[Date] ), REMOVEFILTERS ( 'Portfolio Daily' ), NOT ISBLANK ( 'Portfolio Daily'[TWRIndex] ) )
VAR _months = SWITCH ( _per, "1M", 1, "3M", 3, "6M", 6, "1Y", 12, 0 )
VAR _target = IF ( _months = 0, _first, EDATE ( _end, - _months ) )
VAR _onOrBefore = CALCULATE ( MAX ( 'Portfolio Daily'[Date] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] <= _target, NOT ISBLANK ( 'Portfolio Daily'[TWRIndex] ) )
VAR _start = IF ( ISBLANK ( _onOrBefore ), _first, _onOrBefore )"""


def at_date(col: str, date_var: str) -> str:
    return f"CALCULATE ( MAX ( 'Portfolio Daily'[{col}] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] = {date_var} )"


BENCH_AT = ("CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = MAX ( 'Sync Info'[Benchmark] ), "
            "Prices[Date] = {d} )")


def window_twr(period_expr: str) -> str:
    return window_start(period_expr) + f"""
VAR _i0 = {at_date('TWRIndex', '_start')}
VAR _i1 = {at_date('TWRIndex', '_end')}
RETURN IF ( _i0 > 0 && NOT ISBLANK ( _i1 ), DIVIDE ( _i1, _i0 ) - 1 )"""


def window_bench(period_expr: str) -> str:
    return window_start(period_expr) + f"""
VAR _p0 = {BENCH_AT.format(d='_start')}
VAR _p1 = {BENCH_AT.format(d='_end')}
RETURN IF ( _p0 > 0 && NOT ISBLANK ( _p1 ), DIVIDE ( _p1, _p0 ) - 1 )"""


ROWS_IN_WINDOW = """VAR _rows = FILTER ( ALL ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] >= _start && 'Portfolio Daily'[Date] <= _end && NOT ISBLANK ( 'Portfolio Daily'[TWRIndex] ) )
VAR _after = FILTER ( _rows, 'Portfolio Daily'[Date] > _start )"""

# Holding Rows filtered by the Account and Type choices (both disconnected; "*" = all).
HR_VARS = """VAR _k = SELECTEDVALUE ( 'Account Choice'[AccountKey], "*" )
VAR _ty = SELECTEDVALUE ( 'Type Choice'[Kind], "*" )
VAR _acc = FILTER ( 'Holding Rows', _k = "*" || 'Holding Rows'[AccountKey] = _k )
VAR _f = FILTER ( _acc, _ty = "*" || 'Holding Rows'[Kind] = _ty )
VAR _sec = FILTER ( _f, NOT 'Holding Rows'[IsCash] )
VAR _allAcc = FILTER ( ALL ( 'Holding Rows' ), _k = "*" || 'Holding Rows'[AccountKey] = _k )
VAR _total = SUMX ( _allAcc, 'Holding Rows'[Value] )"""
ONE = "HASONEVALUE ( 'Holding Rows'[Symbol] )"
BY_SYM = """VAR _secAll = FILTER ( ALL ( 'Holding Rows' ), NOT 'Holding Rows'[IsCash] )
VAR _bySym = ADDCOLUMNS ( SUMMARIZE ( _secAll, 'Holding Rows'[Symbol] ), "@v", VAR _s = 'Holding Rows'[Symbol] RETURN SUMX ( FILTER ( _secAll, 'Holding Rows'[Symbol] = _s ), 'Holding Rows'[Value] ) )"""
TICKER = "VAR _t = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[Ticker] )"


def svg(body: str, w: int = 120, h: int = 16) -> str:
    return (f"\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>\" & "
            + body + " & \"</svg>\"")


def color_sign(expr: str) -> str:
    return f"VAR _v = {expr}\nRETURN IF ( ISBLANK ( _v ), \"{INK2}\", IF ( _v < 0, \"{LOSS}\", \"{GAIN}\" ) )"


def _hr_weight_bar(include_cash: bool) -> str:
    cond = "" if include_cash else " && NOT _isCash"
    return HR_VARS + f"""
VAR _v = SUMX ( _f, 'Holding Rows'[Value] )
VAR _isCash = SELECTEDVALUE ( 'Holding Rows'[Symbol] ) = "Cash"
VAR _bySym = ADDCOLUMNS ( SUMMARIZE ( _allAcc, 'Holding Rows'[Symbol] ), "@v", VAR _s = 'Holding Rows'[Symbol] RETURN SUMX ( FILTER ( _allAcc, 'Holding Rows'[Symbol] = _s ), 'Holding Rows'[Value] ) )
VAR _max = MAXX ( _bySym, [@v] )
VAR _px = FORMAT ( DIVIDE ( _v, _max ) * 116, "0.0" )
VAR _col = IF ( _isCash, "%238F9DAE", "%236CB4FF" )
RETURN
    IF (
        {ONE} && NOT ISBLANK ( _v ) && _v > 0{cond},
        {svg('''"<rect x='2' y='6' width='116' height='4' rx='2' fill='%231F2A37'/>" & "<rect x='2' y='6' width='" & _px & "' height='4' rx='2' fill='" & _col & "'/>"''')}
    )"""


# ============================================================================ measures
def report_measures() -> list:
    M = []

    def add(name, expr, fmt=None, props=None):
        M.append((name, expr.strip("\n"), fmt) + ((props,) if props else ()))

    # ---- selections
    add("Period Selected", "SELECTEDVALUE ( Periods[Period], \"1Y\" )")
    add("Period Label", """SWITCH ( [Period Selected], "1M", "Last month", "3M", "Last 3 months", "6M", "Last 6 months", "1Y", "Last 12 months",
    "Since " & FORMAT ( [Window Start], "d mmm yyyy" ) )""")
    add("Window Start", window_start("[Period Selected]") + "\nRETURN _start", "d mmm yyyy")
    add("Chart Metric Selected", f"SELECTEDVALUE ( '{CHART_METRIC}'[Mode], \"Value\" )")
    add("Hero Chart Title", "IF ( [Chart Metric Selected] = \"Return\" && ISBLANK ( [First Performance Date] ), \"Return vs benchmark · unavailable until transactions reconcile (Holdings › Data quality)\", IF ( [Chart Metric Selected] = \"Return\", \"Return vs benchmark\", \"Portfolio value\" ) & \" · \" & LOWER ( LEFT ( [Period Label], 1 ) ) & MID ( [Period Label], 2, 100 ) )")

    # ---- portfolio level
    add("First Performance Date", "CALCULATE ( MIN ( 'Portfolio Daily'[Date] ), REMOVEFILTERS ( 'Portfolio Daily' ), NOT ISBLANK ( 'Portfolio Daily'[TWRIndex] ) )", "d mmm yyyy")
    add("Net Deposits", f"""VAR _s = [First Performance Date]
VAR _e = [Latest Value Date]
VAR _v0 = {at_date('Value', '_s')}
VAR _fl = CALCULATE ( SUM ( 'Portfolio Daily'[Flow] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] > _s, 'Portfolio Daily'[Date] <= _e )
RETURN IF ( NOT ISBLANK ( _v0 ), _v0 + COALESCE ( _fl, 0 ) )""", MONEY)
    add("Total Gain", "VAR _d = [Net Deposits]\nRETURN IF ( NOT ISBLANK ( _d ), [Portfolio Value] - _d )", SMONEY)
    add("Total Gain %", "DIVIDE ( [Total Gain], [Net Deposits] )", SIGNED_PCT)
    add("Day Change", f"""VAR _e = [Latest Value Date]
RETURN CALCULATE ( SUM ( 'Portfolio Daily'[Value] ) - SUM ( 'Portfolio Daily'[Flow] ) - SUM ( 'Portfolio Daily'[PrevValue] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] = _e )""", ARROW_MONEY)
    add("Day Change %", f"VAR _e = [Latest Value Date]\nRETURN DIVIDE ( [Day Change], {at_date('PrevValue', '_e')} )", SIGNED_PCT)
    add("Day Change Text", "VAR _a = [Day Change]\nVAR _p = [Day Change %]\nRETURN IF ( NOT ISBLANK ( _a ), FORMAT ( _a, \"▲ +$#,0.00;▼ −$#,0.00;$0.00\" ) & \"   \" & FORMAT ( _p, \"+0.00%;−0.00%;0.00%\" ) )")
    add("Day Change Color", color_sign("[Day Change]"))
    add("Total Gain Text", "VAR _a = [Total Gain]\nRETURN IF ( NOT ISBLANK ( _a ), FORMAT ( _a, \"▲ +$#,0.00;▼ −$#,0.00;$0.00\" ) & \"   \" & FORMAT ( [Total Gain %], \"+0.00%;−0.00%;0.00%\" ) )")
    add("Total Gain Color", color_sign("[Total Gain]"))
    add("Other Income", "IF ( NOT ISBLANK ( [First Performance Date] ), CALCULATE ( SUM ( 'Gain Breakdown'[Amount] ), REMOVEFILTERS ( 'Gain Breakdown' ), 'Gain Breakdown'[Label] = \"Interest\" ) + 0 )", SMONEY)
    add("Account Fees", "IF ( NOT ISBLANK ( [First Performance Date] ), CALCULATE ( SUM ( 'Gain Breakdown'[Amount] ), REMOVEFILTERS ( 'Gain Breakdown' ), 'Gain Breakdown'[Label] = \"Fees\" ) + 0 )", MONEY)
    add("Dividends and Interest", "IF ( NOT ISBLANK ( [First Performance Date] ), [Security Income] + [Other Income] )", SMONEY)
    add("Unrealized Gain", "VAR _r = FILTER ( ALL ( 'Holding Rows' ), NOT 'Holding Rows'[IsCash] )\nRETURN IF ( COUNTROWS ( FILTER ( _r, ISBLANK ( 'Holding Rows'[CostBasis] ) ) ) = 0, SUMX ( _r, 'Holding Rows'[Value] - 'Holding Rows'[CostBasis] ) )", SMONEY)
    add("Security Income", """VAR _s = [First Performance Date]
VAR _e = [Latest Value Date]
VAR _keys = VALUES ( 'Units History'[InstrumentKey] )
RETURN
    IF ( ISBLANK ( _s ), BLANK (), CALCULATE (
        SUM ( Activities[Amount] ),
        REMOVEFILTERS ( Activities ),
        Activities[Class] = "INCOME",
        Activities[TradeDate] > _s,
        Activities[TradeDate] <= _e,
        Activities[InstrumentKey] IN _keys
    ) + 0 )""", SMONEY)
    add("Realized Gain", """VAR _sec = CALCULATE ( SUM ( 'Gain Breakdown'[Amount] ), REMOVEFILTERS ( 'Gain Breakdown' ), 'Gain Breakdown'[Group] = "Security" )
VAR _u = [Unrealized Gain]
RETURN IF ( [Performance Status] = "Complete" && NOT ISBLANK ( _u ), _sec - _u - [Security Income] )""", SMONEY)
    add("TWR Since Start Signed", "[TWR Since Start]", SIGNED_PCT)
    add("Money Weighted Return", f"""VAR _s = [First Performance Date]
VAR _e = [Latest Value Date]
VAR _v0 = {at_date('Value', '_s')}
VAR _v1 = {at_date('Value', '_e')}
VAR _flows =
    SELECTCOLUMNS (
        FILTER ( ALL ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] > _s && 'Portfolio Daily'[Date] <= _e && 'Portfolio Daily'[Flow] <> 0 ),
        "D", 'Portfolio Daily'[Date], "A", - 'Portfolio Daily'[Flow]
    )
VAR _cf = UNION ( ROW ( "D", _s, "A", - _v0 ), _flows, ROW ( "D", _e, "A", _v1 ) )
RETURN IF ( _v0 > 0 && _e > _s, IFERROR ( XIRR ( _cf, [A], [D] ), BLANK () ) )""", SIGNED_PCT)
    add("Gain Breakdown Gap", "[Total Gain] - CALCULATE ( SUM ( 'Gain Breakdown'[Amount] ), REMOVEFILTERS ( 'Gain Breakdown' ) )", MONEY)

    # ---- window (period slicer)
    add("Window TWR", window_twr("[Period Selected]"), SIGNED_PCT)
    add("Window Benchmark", window_bench("[Period Selected]"), SIGNED_PCT)
    add("Window Difference", "VAR _a = [Window TWR]\nVAR _b = [Window Benchmark]\nRETURN IF ( NOT ISBLANK ( _a ) && NOT ISBLANK ( _b ), ( _a - _b ) * 100 )", PTS)
    add("Window TWR Color", color_sign("[Window TWR]"))
    add("Window Difference Color", color_sign("[Window Difference]"))
    add("Window Max Drawdown", window_start("[Period Selected]") + "\n" + ROWS_IN_WINDOW + """
VAR _dd =
    MINX (
        _rows,
        VAR _d = 'Portfolio Daily'[Date]
        VAR _peak = MAXX ( FILTER ( _rows, 'Portfolio Daily'[Date] <= _d ), 'Portfolio Daily'[TWRIndex] )
        RETURN DIVIDE ( 'Portfolio Daily'[TWRIndex], _peak ) - 1
    )
RETURN IF ( COUNTROWS ( _rows ) > 1, MIN ( _dd, 0 ) )""", SIGNED_PCT)
    add("Window Volatility", window_start("[Period Selected]") + "\n" + ROWS_IN_WINDOW + "\nRETURN IF ( COUNTROWS ( _after ) > 1, STDEVX.P ( _after, 'Portfolio Daily'[DailyReturn] ) * SQRT ( 252 ) )", PCT1)
    add("Window Best Day", window_start("[Period Selected]") + "\n" + ROWS_IN_WINDOW + "\nRETURN MAXX ( _after, 'Portfolio Daily'[DailyReturn] )", SIGNED_PCT)
    add("Window Worst Day", window_start("[Period Selected]") + "\n" + ROWS_IN_WINDOW + "\nRETURN MINX ( _after, 'Portfolio Daily'[DailyReturn] )", SIGNED_PCT)

    # ---- returns-by-period table (one row per period, independent of the slicer)
    add("Row TWR", window_twr("SELECTEDVALUE ( 'Period Rows'[Period] )"), SIGNED_PCT)
    add("Row Benchmark", window_bench("SELECTEDVALUE ( 'Period Rows'[Period] )"), SIGNED_PCT)
    add("Row Difference", "VAR _a = [Row TWR]\nVAR _b = [Row Benchmark]\nRETURN IF ( NOT ISBLANK ( _a ) && NOT ISBLANK ( _b ), ( _a - _b ) * 100 )", PTS)
    add("Row TWR Color", color_sign("[Row TWR]"))
    add("Row Difference Color", color_sign("[Row Difference]"))
    add("Row Background", "IF ( SELECTEDVALUE ( 'Period Rows'[Period] ) = [Period Selected], \"#182230\", \"#111923\" )")

    # ---- chart series (date on the axis; blank outside the window so the axis follows the period)
    add("First Value Date", "CALCULATE ( MIN ( 'Portfolio Daily'[Date] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Value] <> 0 )", "d mmm yyyy")
    add("Chart Value", "VAR _d = MAX ( 'Portfolio Daily'[Date] )\nVAR _s = [Window Start]\nVAR _fv = [First Value Date]\nRETURN IF ( _d >= _s && _d >= _fv, SUM ( 'Portfolio Daily'[Value] ) )", MONEY0)
    add("Chart Return", f"""VAR _d = MAX ( 'Portfolio Daily'[Date] )
VAR _s = [Window Start]
VAR _i0 = {at_date('TWRIndex', '_s')}
VAR _i = MAX ( 'Portfolio Daily'[TWRIndex] )
RETURN IF ( _d >= _s && NOT ISBLANK ( _i ) && _i0 > 0, DIVIDE ( _i, _i0 ) - 1 )""", SIGNED_PCT)
    add("Chart Benchmark", f"""VAR _d = MAX ( 'Portfolio Daily'[Date] )
VAR _s = [Window Start]
VAR _p0 = {BENCH_AT.format(d='_s')}
VAR _p = {BENCH_AT.format(d='_d')}
RETURN IF ( _d >= _s && NOT ISBLANK ( _p ) && _p0 > 0, DIVIDE ( _p, _p0 ) - 1 )""", SIGNED_PCT)
    add("Chart Deposits", f"""VAR _d = MAX ( 'Portfolio Daily'[Date] )
VAR _s = [Window Start]
VAR _first = [First Performance Date]
VAR _v0 = {at_date('Value', '_first')}
VAR _fl = CALCULATE ( SUM ( 'Portfolio Daily'[Flow] ), REMOVEFILTERS ( 'Portfolio Daily' ), 'Portfolio Daily'[Date] > _first, 'Portfolio Daily'[Date] <= _d )
RETURN IF ( _d >= _s && NOT ISBLANK ( _v0 ), _v0 + COALESCE ( _fl, 0 ) )""", MONEY0)
    # display names for the field parameter's series (the legend shows the measure name)
    add("Market value", "[Chart Value]", MONEY0)
    add("Portfolio return", "[Chart Return]", SIGNED_PCT)
    add("Benchmark return", "[Chart Benchmark]", SIGNED_PCT)
    add("Tooltip Date", "MAX ( 'Portfolio Daily'[Date] )", "d mmm yyyy")
    add("Tooltip Value", "SUM ( 'Portfolio Daily'[Value] )", MONEY0)
    add("Window Gain Over Deposits", "VAR _e = [Latest Value Date]\nRETURN [Portfolio Value] - [Net Deposits]", SMONEY)

    # ---- holdings (Holding Rows, filtered by the Account and Type choices)
    add("H Value", HR_VARS + "\nRETURN SUMX ( _f, 'Holding Rows'[Value] )", MONEY)
    add("H Value Securities", HR_VARS + "\nRETURN SUMX ( _sec, 'Holding Rows'[Value] )", MONEY)
    add("H Cash", HR_VARS + "\nRETURN SUMX ( FILTER ( _acc, 'Holding Rows'[IsCash] ), 'Holding Rows'[Value] ) + 0", MONEY)
    add("H Weight", HR_VARS + "\nRETURN DIVIDE ( SUMX ( _f, 'Holding Rows'[Value] ), _total )", PCT1)
    add("H Weight Securities", HR_VARS + "\nRETURN DIVIDE ( SUMX ( _sec, 'Holding Rows'[Value] ), _total )", PCT1)
    add("H Units", HR_VARS + f"\nRETURN IF ( {ONE} && COUNTROWS ( _sec ) > 0, SUMX ( _sec, 'Holding Rows'[Units] ) )", "#,0.####")
    add("H Avg Cost", HR_VARS + f"\nRETURN IF ( {ONE} && COUNTROWS ( _sec ) > 0 && COUNTROWS ( FILTER ( _sec, ISBLANK ( 'Holding Rows'[CostBasis] ) ) ) = 0, DIVIDE ( SUMX ( _sec, 'Holding Rows'[CostBasis] ), SUMX ( _sec, 'Holding Rows'[Units] ) ) )", MONEY)
    add("H Price", HR_VARS + f"\nRETURN IF ( {ONE} && COUNTROWS ( _sec ) > 0, MAXX ( _sec, 'Holding Rows'[LastClose] ) )", MONEY)
    add("H Day %", HR_VARS + f"""
VAR _abs = SUMX ( _sec, 'Holding Rows'[DayAbs] )
VAR _v = SUMX ( _f, 'Holding Rows'[Value] )
RETURN IF ( {ONE}, IF ( COUNTROWS ( _sec ) > 0, MAXX ( _sec, 'Holding Rows'[DayPct] ) ), IF ( NOT ISBLANK ( _abs ), DIVIDE ( _abs, _v - _abs ) ) )""", ARROW_PCT)
    add("H Day $", HR_VARS + "\nRETURN IF ( COUNTROWS ( _sec ) > 0, SUMX ( _sec, 'Holding Rows'[DayAbs] ) )", ARROW_MONEY)
    add("H Unrealized", HR_VARS + "\nRETURN IF ( COUNTROWS ( _sec ) > 0 && COUNTROWS ( FILTER ( _sec, ISBLANK ( 'Holding Rows'[CostBasis] ) ) ) = 0, SUMX ( _sec, 'Holding Rows'[Value] - 'Holding Rows'[CostBasis] ) )", SMONEY)
    add("H Return", HR_VARS + "\nRETURN IF ( COUNTROWS ( _sec ) > 0 && COUNTROWS ( FILTER ( _sec, ISBLANK ( 'Holding Rows'[CostBasis] ) ) ) = 0, DIVIDE ( SUMX ( _sec, 'Holding Rows'[Value] - 'Holding Rows'[CostBasis] ), SUMX ( _sec, 'Holding Rows'[CostBasis] ) ) )", SIGNED_PCT1)
    add("H Count", HR_VARS + "\nRETURN COUNTROWS ( SUMMARIZE ( _sec, 'Holding Rows'[Symbol] ) ) + 0", "0")
    add("H Unrealized Text", "VAR _u = [H Unrealized]\nVAR _r = [H Return]\nRETURN IF ( NOT ISBLANK ( _u ), FORMAT ( _u, \"▲ +$#,0.00;▼ −$#,0.00;$0.00\" ) & \"   \" & FORMAT ( _r, \"+0.00%;−0.00%;0.00%\" ), \"—\" )")
    add("H Day Color", color_sign("[H Day %]"))
    add("H Day $ Color", color_sign("[H Day $]"))
    add("H Unrealized Color", color_sign("[H Unrealized]"))
    add("H Return Color", color_sign("[H Return]"))
    add("H Weight Bar SVG", _hr_weight_bar(True), None, {"dataCategory": "ImageUrl"})
    add("H Weight Bar SVG Securities", _hr_weight_bar(False), None, {"dataCategory": "ImageUrl"})
    add("H Trend SVG", HR_VARS + f"""
{TICKER}
VAR _last = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[LastDate] )
VAR _pts =
    SELECTCOLUMNS (
        FILTER ( ALL ( 'Price History' ), 'Price History'[Ticker] = _t && 'Price History'[Date] > _last - 90 && 'Price History'[Date] <= _last ),
        "d", 'Price History'[Date], "c", 'Price History'[SplitAdjClose]
    )
VAR _lo = MINX ( _pts, [c] )
VAR _hi = MAXX ( _pts, [c] )
VAR _d0 = MINX ( _pts, [d] )
VAR _span = MAX ( 1, INT ( _last ) - INT ( _d0 ) )
VAR _rng = IF ( _hi > _lo, _hi - _lo, 1 )
VAR _poly = CONCATENATEX ( _pts, FORMAT ( ( INT ( [d] ) - INT ( _d0 ) ) / _span * 112 + 4, "0.0" ) & "," & FORMAT ( 14 - ( [c] - _lo ) / _rng * 12, "0.0" ), " ", [d], ASC )
VAR _first = MAXX ( FILTER ( _pts, [d] = _d0 ), [c] )
VAR _lastc = MAXX ( FILTER ( _pts, [d] = _last ), [c] )
VAR _col = IF ( _lastc >= _first, "%233DCB95", "%23FF7A7A" )
RETURN
    IF (
        {ONE} && COUNTROWS ( _sec ) > 0 && NOT ISBLANK ( _t ) && COUNTROWS ( _pts ) > 1,
        {svg('''"<polyline fill='none' stroke='" & _col & "' stroke-width='1.5' stroke-linejoin='round' stroke-linecap='round' points='" & _poly & "'/>"''')}
    )""", None, {"dataCategory": "ImageUrl"})
    add("H Range SVG", HR_VARS + f"""
VAR _lo = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[Lo52] )
VAR _hi = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[Hi52] )
VAR _c = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[LastAdj] )
VAR _x = IF ( _hi > _lo, DIVIDE ( _c - _lo, _hi - _lo ) * 112 + 4, 60 )
RETURN
    IF (
        {ONE} && COUNTROWS ( _sec ) > 0 && NOT ISBLANK ( _c ),
        {svg('''"<rect x='4' y='7' width='112' height='2' rx='1' fill='%232C3B4D'/>" & "<circle cx='" & FORMAT ( _x, "0.0" ) & "' cy='8' r='3.5' fill='%23E6ECF2'/>"''')}
    )""", None, {"dataCategory": "ImageUrl"})
    add("Allocation Color", "IF ( SELECTEDVALUE ( 'Holding Rows'[Symbol] ) = \"Cash\", \"#8F9DAE\", \"#6CB4FF\" )")
    add("Largest Holding Weight", BY_SYM + """
RETURN DIVIDE ( MAXX ( _bySym, [@v] ), SUMX ( ALL ( 'Holding Rows' ), 'Holding Rows'[Value] ) )""", PCT1)
    add("Effective Holdings", BY_SYM + """
VAR _tot = SUMX ( _bySym, [@v] )
VAR _hhi = SUMX ( _bySym, DIVIDE ( [@v], _tot ) ^ 2 )
RETURN DIVIDE ( 1, _hhi )""", "0.0")

    # ---- accounts panel
    add("Acct Value", "VAR _a = SELECTEDVALUE ( 'Account List'[AccountKey] )\nRETURN IF ( NOT ISBLANK ( _a ), SUMX ( FILTER ( ALL ( 'Holding Rows' ), 'Holding Rows'[AccountKey] = _a ), 'Holding Rows'[Value] ) )", MONEY)
    add("Acct Cash", "VAR _a = SELECTEDVALUE ( 'Account List'[AccountKey] )\nRETURN IF ( NOT ISBLANK ( _a ), SUMX ( FILTER ( ALL ( 'Holding Rows' ), 'Holding Rows'[AccountKey] = _a && 'Holding Rows'[IsCash] ), 'Holding Rows'[Value] ) )", MONEY)
    add("Acct Holdings", "VAR _a = SELECTEDVALUE ( 'Account List'[AccountKey] )\nRETURN IF ( NOT ISBLANK ( _a ), COUNTROWS ( FILTER ( ALL ( 'Holding Rows' ), 'Holding Rows'[AccountKey] = _a && NOT 'Holding Rows'[IsCash] ) ) )", "0")
    add("Acct Status", "VAR _a = SELECTEDVALUE ( 'Account List'[AccountKey] )\nRETURN IF ( NOT ISBLANK ( _a ), LOOKUPVALUE ( Accounts[PerformanceStatus], Accounts[AccountKey], _a ) )")
    add("Acct Status Color", f"IF ( [Acct Status] = \"Complete\", \"{GAIN}\", \"{CAUTION}\" )")

    # ---- data checks
    add("Check Status", """VAR _c = SELECTEDVALUE ( Checks[Order] )
VAR _neg = CALCULATE ( COUNTROWS ( Issues ), REMOVEFILTERS ( Issues ), Issues[Code] = "NEGATIVE_UNITS_IN_HISTORY" ) + 0
VAR _stale = COUNTROWS ( FILTER ( ALL ( 'Holding Rows' ), NOT 'Holding Rows'[IsCash] && ( ISBLANK ( 'Holding Rows'[LastDate] ) || 'Holding Rows'[LastDate] < [Market Date] ) ) ) + 0
VAR _ok =
    SWITCH (
        _c,
        1, _neg = 0,
        2, _stale = 0 && [Missing Price Days] = 0,
        3, [Unconfirmed Splits] = 0,
        4, [Performance Status] = "Complete",
        5, [Errors] + [Warnings] = 0
    )
RETURN IF ( NOT ISBLANK ( _c ), IF ( _ok, "✓", "●" ) )""")
    add("Check Detail", """VAR _c = SELECTEDVALUE ( Checks[Order] )
VAR _neg = CALCULATE ( COUNTROWS ( Issues ), REMOVEFILTERS ( Issues ), Issues[Code] = "NEGATIVE_UNITS_IN_HISTORY" ) + 0
VAR _stale = COUNTROWS ( FILTER ( ALL ( 'Holding Rows' ), NOT 'Holding Rows'[IsCash] && ( ISBLANK ( 'Holding Rows'[LastDate] ) || 'Holding Rows'[LastDate] < [Market Date] ) ) ) + 0
RETURN
    SWITCH (
        _c,
        1, IF ( _neg = 0, FORMAT ( [Activity Count], "0" ) & " transactions", FORMAT ( _neg, "0" ) & " go negative" ),
        2, IF ( _stale = 0, "To " & FORMAT ( [Market Date], "d mmm" ),
               IF ( _stale <= 2, CONCATENATEX ( FILTER ( ALL ( 'Holding Rows' ), NOT 'Holding Rows'[IsCash] && ( ISBLANK ( 'Holding Rows'[LastDate] ) || 'Holding Rows'[LastDate] < [Market Date] ) ), 'Holding Rows'[Symbol], ", " ) & " behind",
                   FORMAT ( _stale, "0" ) & " not current" ) ),
        3, IF ( [Unconfirmed Splits] = 0, FORMAT ( [Split Count], "0" ) & " split" & IF ( [Split Count] = 1, "", "s" ), FORMAT ( [Unconfirmed Splits], "0" ) & " unreported" ),
        4, IF ( [Performance Status] = "Complete", "Since " & FORMAT ( [Performance Start], "mmm yyyy" ), [Performance Status] ),
        5, IF ( [Errors] + [Warnings] = 0, "None", FORMAT ( [Errors] + [Warnings], "0" ) & " open" )
    )""")
    add("Check Color", f"IF ( [Check Status] = \"✓\", \"{GAIN}\", \"{CAUTION}\" )")
    add("Activity Count", "MAX ( 'Sync Info'[ActivityCount] )", "0")
    add("Split Count", "COUNTROWS ( FILTER ( ALL ( Prices ), NOT ISBLANK ( Prices[SplitFactor] ) && Prices[SplitFactor] > 0 && Prices[SplitFactor] <> 1 ) ) + 0", "0")
    add("Quality Headline", f"IF ( [Errors] + [Warnings] = 0 && [Performance Status] = \"Complete\", \"● Complete\", \"● Needs attention\" )")
    add("Quality Headline Color", f"IF ( [Errors] + [Warnings] = 0 && [Performance Status] = \"Complete\", \"{GAIN}\", \"{CAUTION}\" )")

    # ---- status line
    add("Status Prices", """VAR _m = [Market Date]
VAR _age = IF ( NOT ISBLANK ( _m ), NETWORKDAYS ( _m, UTCTODAY () ) - 1 )
RETURN IF ( ISBLANK ( _m ), "No prices loaded", "Prices " & FORMAT ( _m, "d mmm yyyy" ) & " close" & IF ( _age > 1, " · " & FORMAT ( _age, "0" ) & " trading days old", "" ) )""")
    add("Status Prices Color", f"VAR _m = [Market Date]\nRETURN IF ( ISBLANK ( _m ) || NETWORKDAYS ( _m, UTCTODAY () ) - 1 > 1, \"{CAUTION}\", \"{INK2}\" )")
    add("Status Sync", """VAR _s = [Portfolio Synced UTC]
VAR _h = [Portfolio Sync Age Hours]
RETURN IF ( ISBLANK ( _s ), "Portfolio not synced", "Portfolio synced " & FORMAT ( _s, "d mmm, hh:nn" ) & " UTC" & IF ( _h > 36, " · " & FORMAT ( _h, "0" ) & " h ago", "" ) )""")
    add("Status Sync Color", f"IF ( [Portfolio Sync Age Hours] > 36 || ISBLANK ( [Portfolio Synced UTC] ), \"{CAUTION}\", \"{INK2}\" )")
    add("Status Issues", """VAR _n = [Errors] + [Warnings]
RETURN
    SWITCH (
        TRUE (),
        _n > 0, "● " & FORMAT ( _n, "0" ) & " data issue" & IF ( _n = 1, "", "s" ),
        [Performance Status] <> "Complete", "● Performance " & LOWER ( [Performance Status] ) & " before " & FORMAT ( [Performance Start], "d mmm yyyy" ),
        "● No data issues"
    )""")
    add("Status Issues Color", f"IF ( [Errors] + [Warnings] = 0 && [Performance Status] = \"Complete\", \"{GAIN}\", \"{CAUTION}\" )")
    add("Status Performance", "\"● Performance \" & LOWER ( [Performance Status] ) & \" since \" & FORMAT ( [Performance Start], \"d mmm yyyy\" )")
    add("Status Benchmark", "\"Benchmark \" & MAX ( 'Sync Info'[Benchmark] )")
    add("Status Phone", "[Status Prices] & \"   \" & [Status Issues]")
    add("Data Source Badge", "IF ( LEFT ( [Data Source], 4 ) = \"Demo\", \"● Demo data\", \" \" )")
    add("Badge Color", f"\"{CAUTION}\"")

    # ---- security detail (drillthrough on Holding Rows[Symbol])
    add("D Symbol", "SELECTEDVALUE ( 'Holding Rows'[Symbol], \"—\" )")
    add("D Subtitle", """VAR _n = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[Name] )
VAR _k = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[Kind] )
VAR _a = CONCATENATEX ( SUMMARIZE ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[AccountLabel] ), 'Holding Rows'[AccountLabel], ", " )
RETURN _n & "   " & _k & " · " & _a""")
    add("D Close", f"""{TICKER}
VAR _last = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[LastDate] )
VAR _d = MAX ( 'Price History'[Date] )
RETURN IF ( _d > _last - 365 && _d <= _last, CALCULATE ( MAX ( 'Price History'[SplitAdjClose] ), 'Price History'[Ticker] = _t ) )""", MONEY)
    add("D Average Cost", "VAR _c = [D Close]\nRETURN IF ( NOT ISBLANK ( _c ), CALCULATE ( [H Avg Cost], REMOVEFILTERS ( 'Price History' ) ) )", MONEY)
    add("D Price Change 12M", f"""{TICKER}
VAR _last = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[LastDate] )
VAR _d0 = CALCULATE ( MIN ( 'Price History'[Date] ), REMOVEFILTERS ( 'Price History' ), 'Price History'[Ticker] = _t, 'Price History'[Date] > _last - 365 )
VAR _p0 = CALCULATE ( MAX ( 'Price History'[SplitAdjClose] ), REMOVEFILTERS ( 'Price History' ), 'Price History'[Ticker] = _t, 'Price History'[Date] = _d0 )
VAR _p1 = CALCULATE ( MAX ( 'Price History'[SplitAdjClose] ), REMOVEFILTERS ( 'Price History' ), 'Price History'[Ticker] = _t, 'Price History'[Date] = _last )
RETURN IF ( _p0 > 0, DIVIDE ( _p1, _p0 ) - 1 )""", ARROW_PCT)
    add("D Range Text", """VAR _lo = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[Lo52] )
VAR _hi = MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[Hi52] )
RETURN IF ( NOT ISBLANK ( _lo ), FORMAT ( _lo, "$#,0.00" ) & " – " & FORMAT ( _hi, "$#,0.00" ) )""")
    add("D Contribution", "VAR _s = SELECTEDVALUE ( 'Holding Rows'[Symbol] )\nRETURN CALCULATE ( SUM ( 'Gain Breakdown'[Amount] ), REMOVEFILTERS ( 'Gain Breakdown' ), 'Gain Breakdown'[Label] = _s )", SMONEY)
    add("D Share Of Gain", "DIVIDE ( [D Contribution], [Total Gain] )", PCT1)
    add("D Dividends", "VAR _s = SELECTEDVALUE ( 'Holding Rows'[Symbol] )\nRETURN CALCULATE ( SUM ( Activities[Amount] ), REMOVEFILTERS ( Activities ), Activities[InstrumentKey] = _s, Activities[Class] = \"INCOME\" ) + 0", MONEY)
    add("D Units Reported", f"{TICKER}\nRETURN SUMX ( FILTER ( ALL ( Positions ), Positions[Ticker] = _t ), Positions[Units] )", "#,0.####")
    add("D Units Rebuilt", f"""{TICKER}
VAR _e = [Latest Value Date]
RETURN SUMX ( FILTER ( ALL ( 'Units History' ), 'Units History'[Ticker] = _t && 'Units History'[FromDate] <= _e && 'Units History'[ToDate] > _e ), 'Units History'[Units] )""", "#,0.####")
    add("D Corporate Actions", "VAR _s = SELECTEDVALUE ( 'Holding Rows'[Symbol] )\nRETURN COUNTROWS ( FILTER ( ALL ( Activities ), Activities[InstrumentKey] = _s && Activities[Class] = \"CORPORATE\" ) ) + 0", "0")
    add("D Last Close Date", "MAXX ( FILTER ( 'Holding Rows', NOT 'Holding Rows'[IsCash] ), 'Holding Rows'[LastDate] )", "d mmm yyyy")
    add("D Tx Amount", """VAR _s = SELECTEDVALUE ( 'Holding Rows'[Symbol] )
VAR _r = FILTER ( 'Activity Log', 'Activity Log'[InstrumentKey] = _s )
RETURN IF ( NOT ISBLANK ( _s ) && COUNTROWS ( _r ) > 0, SUMX ( _r, 'Activity Log'[Amount] ) + 0 )""", TX_MONEY)
    add("D Position Note", "\"Average cost per current unit. Closes before a split are adjusted for the chart; values use the price actually traded.\"")
    add("Tx Amount", "SUM ( 'Activity Log'[Amount] )", TX_MONEY)

    # ---- income
    add("Income Amount", """VAR _m = SELECTEDVALUE ( 'Income Months'[MonthStart] )
RETURN IF ( NOT ISBLANK ( _m ), CALCULATE ( SUM ( Activities[Amount] ), REMOVEFILTERS ( Activities ), Activities[Class] = "INCOME", Activities[TradeDate] >= _m, Activities[TradeDate] <= EOMONTH ( _m, 0 ) ) + 0 )""", MONEY0)
    add("Income 12 Months", """VAR _m0 = MIN ( 'Income Months'[MonthStart] )
VAR _m1 = EOMONTH ( MAX ( 'Income Months'[MonthStart] ), 0 )
RETURN CALCULATE ( SUM ( Activities[Amount] ), REMOVEFILTERS ( Activities ), Activities[Class] = "INCOME", Activities[TradeDate] >= _m0, Activities[TradeDate] <= _m1 ) + 0""", MONEY)
    add("Income Title", "\"Income   12 months · \" & FORMAT ( CALCULATE ( [Income 12 Months], REMOVEFILTERS ( 'Income Months' ) ), \"$#,0.00\" )")
    add("Gain Amount", "SUM ( 'Gain Breakdown'[Amount] )", SMONEY)
    add("Gain Bar SVG", """VAR _a = SUM ( 'Gain Breakdown'[Amount] )
VAR _g = SELECTEDVALUE ( 'Gain Breakdown'[Group] )
VAR _max = MAXX ( ALL ( 'Gain Breakdown' ), ABS ( 'Gain Breakdown'[Amount] ) )
VAR _w = MAX ( 1, DIVIDE ( ABS ( _a ), _max ) * 100 )
VAR _neg = _a < 0
VAR _x = IF ( _neg, 16 - MIN ( _w, 16 ), 16 )
VAR _len = IF ( _neg, MIN ( _w, 16 ), _w )
VAR _col = IF ( _neg, "%23FF7A7A", IF ( _g = "Cash", "%238F9DAE", "%236CB4FF" ) )
RETURN
    IF (
        HASONEVALUE ( 'Gain Breakdown'[Label] ) && NOT ISBLANK ( _a ),
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='16' viewBox='0 0 120 16'>"
            & "<rect x='" & FORMAT ( _x, "0.0" ) & "' y='4' width='" & FORMAT ( _len, "0.0" ) & "' height='8' rx='2' fill='" & _col & "'/>"
            & "<rect x='16' y='1' width='1' height='14' fill='%232C3B4D'/></svg>"
    )""", None, {"dataCategory": "ImageUrl"})
    add("Gain Amount Color", "IF ( SUM ( 'Gain Breakdown'[Amount] ) < 0, \"#FF7A7A\", \"#E6ECF2\" )")
    add("Income Color", f"\"{PORTFOLIO}\"")
    add("Perf Chart Title", "IF ( ISBLANK ( [First Performance Date] ), \"Return vs benchmark · unavailable until transactions reconcile (Holdings › Data quality)\", \"Return vs benchmark · \" & LOWER ( LEFT ( [Period Label], 1 ) ) & MID ( [Period Label], 2, 100 ) )")
    add("D Chart Title", "VAR _c = [D Price Change 12M]\nRETURN \"Price, split-adjusted · 12 months\" & IF ( NOT ISBLANK ( _c ), \"   \" & FORMAT ( _c, \"▲ +0.00%;▼ −0.00%;0.00%\" ), \"\" )")
    add("Tip Return Color", color_sign("[Chart Return]"))
    add("Gain Color", f"""VAR _a = SUM ( 'Gain Breakdown'[Amount] )
VAR _g = SELECTEDVALUE ( 'Gain Breakdown'[Group] )
RETURN IF ( _a < 0, "{LOSS}", IF ( _g = "Cash", "{NEUTRAL}", "{PORTFOLIO}" ) )""")
    return M


def report_tables_tmdl() -> dict:
    from .model_writer import _calc_table_tmdl
    out = {t: _calc_table_tmdl(t, cols, dax) for t, (cols, dax) in REPORT_TABLES.items()}
    out[CHART_METRIC] = chart_metric_tmdl()
    return out
