"""Visual capability probe (Phase 2b).

Deploys a separate report + model, "FolioScreen-Probe", on the fictional demo data. Every tile tests one
technique the FolioScreen design may rely on, and is labelled with an ID and the expected result, so a
screenshot (desktop and iPhone) shows exactly which techniques render in Power BI Service.

Deployment is layered: if an optional model feature or a report page breaks deployment or refresh, it is
dropped and recorded, so one unsupported technique cannot hide the results of the others.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import paths
from .model_writer import BASE_THEME_REL, lineage, render_report

NAME = "FolioScreen-Probe"
ROUND = 2  # the deploy command runs the latest round; round 1 remains available for reference
BG, PANEL, LINE, TEXT, MUTED, ACCENT, BENCH, UP, DOWN = (
    "#0B1118", "#121A24", "#1F2A37", "#E6ECF2", "#8EA0B4", "#6CB4FF", "#A9B8C8", "#3DCB95", "#FF7A7A")
F_REG = "'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif"
F_LIGHT = "'Segoe UI Light', wf_segoe-ui_light, helvetica, arial, sans-serif"
F_SEMILIGHT = "'Segoe UI Semilight', wf_segoe-ui_semilight, helvetica, arial, sans-serif"
F_SEMIBOLD = "'Segoe UI Semibold', wf_segoe-ui_semibold, helvetica, arial, sans-serif"
F_BOLD = "'Segoe UI Bold', wf_segoe-ui_bold, helvetica, arial, sans-serif"
F_DIN = "DIN, 'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif"

# ============================================================================ model extras
SIGNED_PCT = "+0.00%;−0.00%;0.00%"
PROBE_MEASURES = [
    ("Portfolio Return %", "VAR _v = SUM ( 'Portfolio Daily'[TWRIndex] )\nRETURN IF ( NOT ISBLANK ( _v ), _v - 1 )", SIGNED_PCT),
    ("Benchmark Return %", """VAR _b = MAX ( 'Sync Info'[Benchmark] )
VAR _start = MAX ( 'Sync Info'[PerformanceStart] )
VAR _d = MAX ( 'Portfolio Daily'[Date] )
VAR _d0 = CALCULATE ( MIN ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _b, Prices[Date] >= _start )
VAR _p0 = CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _b, Prices[Date] = _d0 )
VAR _p = CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _b, Prices[Date] = _d )
RETURN IF ( NOT ISBLANK ( _p ) && NOT ISBLANK ( _p0 ) && _d >= _d0, DIVIDE ( _p, _p0 ) - 1 )""", SIGNED_PCT),
    ("TWR Signed", "[TWR Since Start]", SIGNED_PCT),
    ("Tooltip Date", "MAX ( 'Portfolio Daily'[Date] )", "d mmm yyyy"),
    ("Weight", "DIVIDE ( [Securities Value Check], CALCULATE ( [Securities Value Check], REMOVEFILTERS ( Positions ) ) )", "0.0%"),
    ("Selected Ticker", "SELECTEDVALUE ( Positions[Ticker], \"—\" )", None),
    ("Close Trend", """VAR _t = SELECTEDVALUE ( Positions[Ticker] )
VAR _last = CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t )
RETURN CALCULATE ( AVERAGE ( Prices[Close] ), Prices[Ticker] = _t, KEEPFILTERS ( Prices[Date] >= _last - 180 ) )""", "#,0.00"),
]
# Optional features, each deployable on its own
DYNAMIC_FORMAT_MEASURES = [
    ("Value Compact", "[Portfolio Value]", None, {"formatStringDefinition":
        'VAR _v = ABS ( [Portfolio Value] ) RETURN IF ( _v >= 1000000, "$#,0.00,,""M""", IF ( _v >= 1000, "$#,0.0,""K""", "$#,0" ) )'}),
]
SVG_MEASURES = [
    ("Weight Bar SVG", """VAR _w = [Weight]
VAR _px = FORMAT ( MIN ( _w, 1 ) * 116, "0.0" )
RETURN
    IF (
        NOT ISBLANK ( _w ),
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='12' viewBox='0 0 120 12'>"
            & "<rect x='2' y='4' width='116' height='4' rx='2' fill='%231F2A37'/>"
            & "<rect x='2' y='4' width='" & _px & "' height='4' rx='2' fill='%236CB4FF'/></svg>"
    )""", None, {"dataCategory": "ImageUrl"}),
    ("Range Bar SVG", """VAR _t = SELECTEDVALUE ( Positions[Ticker] )
VAR _last = CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t )
VAR _lo = CALCULATE ( MIN ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] >= _last - 90 )
VAR _hi = CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] >= _last - 90 )
VAR _c = CALCULATE ( MAX ( Prices[Close] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] = _last )
VAR _x = IF ( _hi > _lo, DIVIDE ( _c - _lo, _hi - _lo ) * 112 + 4, 60 )
RETURN
    IF (
        NOT ISBLANK ( _c ),
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='12' viewBox='0 0 120 12'>"
            & "<rect x='4' y='5' width='112' height='2' rx='1' fill='%232A3A4D'/>"
            & "<circle cx='" & FORMAT ( _x, "0.0" ) & "' cy='6' r='3.5' fill='%23E6ECF2'/></svg>"
    )""", None, {"dataCategory": "ImageUrl"}),
]
FIELD_PARAMETER_TABLE = "Chart Metric"


def field_parameter_tmdl() -> str:
    t = FIELD_PARAMETER_TABLE
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

\tpartition '{t}' = calculated
\t\tmode: import
\t\tsource =
\t\t\t\t{{
\t\t\t\t    ("Value", NAMEOF ( '_Measures'[Daily Value] ), 0),
\t\t\t\t    ("Return", NAMEOF ( '_Measures'[Portfolio Return %] ), 1)
\t\t\t\t}}
"""


MODEL_FEATURES = ["field_parameter", "dynamic_format", "svg_measures"]


def model_extras(features: list) -> tuple:
    measures = list(PROBE_MEASURES)
    tables = {}
    if "dynamic_format" in features:
        measures += DYNAMIC_FORMAT_MEASURES
    if "svg_measures" in features:
        measures += SVG_MEASURES
    if "field_parameter" in features:
        tables[FIELD_PARAMETER_TABLE] = field_parameter_tmdl()
    return measures, tables


# ============================================================================ PBIR helpers
VC = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.10.0/schema.json"
MOBILE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainerMobileState/2.5.0/schema.json"


def lit(v) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def txt(s: str) -> dict:
    return lit("'" + s.replace("'", "''") + "'")


def color(hexv: str) -> dict:
    return {"solid": {"color": lit(f"'{hexv}'")}}


def num(v, kind: str = "D") -> dict:
    return lit(f"{v}{kind}")


def font(f: str) -> dict:
    return txt(f)


def m(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def c(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field: dict, label: str, active: bool = False) -> dict:
    kind = next(iter(field))
    ent = field[kind]["Expression"]["SourceRef"]["Entity"] if kind in ("Measure", "Column") else "q"
    prop = field[kind]["Property"] if kind in ("Measure", "Column") else label
    out = {"field": field, "queryRef": f"{ent}.{prop}", "nativeQueryRef": label, "displayName": label}
    if active:
        out["active"] = True
    return out


def plain_container(title: Optional[str] = None, panel: bool = False, radius: int = 8) -> dict:
    o = {"visualHeader": [{"properties": {"show": lit("false")}}],
         "dropShadow": [{"properties": {"show": lit("false")}}]}
    if title:
        o["title"] = [{"properties": {"show": lit("true"), "text": txt(title), "fontColor": color(MUTED),
                                      "fontSize": num(10), "fontFamily": font(F_SEMIBOLD)}}]
    else:
        o["title"] = [{"properties": {"show": lit("false")}}]
    if panel:
        o["background"] = [{"properties": {"show": lit("true"), "color": color(PANEL), "transparency": num(0)}}]
        o["border"] = [{"properties": {"show": lit("true"), "color": color(LINE), "radius": num(radius), "width": num(1)}}]
        o["padding"] = [{"properties": {"top": num(12), "bottom": num(12), "left": num(14), "right": num(14)}}]
    else:
        o["background"] = [{"properties": {"show": lit("false")}}]
        o["border"] = [{"properties": {"show": lit("false")}}]
    return o


class Page:
    def __init__(self, name: str, display: str, width: int = 1440, height: int = 900, **extra):
        self.name, self.display, self.width, self.height, self.extra = name, display, width, height, extra
        self.visuals, self.mobile = [], {}
        self._z = 1000

    def add(self, vname: str, x: int, y: int, w: int, h: int, visual: dict, mobile: Optional[tuple] = None) -> None:
        self._z += 1000
        self.visuals.append({"$schema": VC, "name": vname,
                             "position": {"x": x, "y": y, "z": self._z, "height": h, "width": w, "tabOrder": self._z},
                             "visual": visual})
        if mobile:
            mx, my, mw, mh = mobile
            self.mobile[vname] = {"$schema": MOBILE, "position": {"x": mx, "y": my, "z": self._z, "height": mh, "width": mw,
                                                                    "tabOrder": self._z}}

    def page_json(self) -> dict:
        d = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
             "name": self.name, "displayName": self.display, "displayOption": self.extra.get("displayOption", "FitToWidth"),
             "height": self.height, "width": self.width,
             "objects": {"background": [{"properties": {"color": color(BG), "transparency": num(0)}}],
                         "outspace": [{"properties": {"color": color(BG), "transparency": num(0)}}]}}
        for k in ("type", "pageBinding", "visibility", "filterConfig"):
            if k in self.extra:
                d[k] = self.extra[k]
        return d


def textbox(lines: list, container: Optional[dict] = None) -> dict:
    """lines: [(text, fontFamily, sizePt, color, bold?)] or a single tuple per paragraph with several runs."""
    paragraphs = []
    for line in lines:
        runs = line if isinstance(line, list) else [line]
        paragraphs.append({"textRuns": [{"value": t, "textStyle": {"fontFamily": f, "fontSize": f"{sz}pt", "color": col,
                                                                    **({"fontWeight": "bold"} if len(r) > 4 and r[4] else {})}}
                                        for r in runs for (t, f, sz, col) in [r[:4]]]})
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "visualContainerObjects": container or plain_container()}


def caption(tid: str, what: str, expect: str) -> dict:
    return textbox([[(f"{tid}  ", F_SEMIBOLD, 10, ACCENT), (what, F_SEMIBOLD, 10, TEXT)],
                    [(f"Expect: {expect}", F_REG, 9, MUTED)]])


def card(fields: list, value_font=F_DIN, value_size=20, container=None, extra_roles: Optional[dict] = None) -> dict:
    q = {"Data": {"projections": [proj(f, label) for f, label in fields]}}
    if extra_roles:
        q.update(extra_roles)
    return {"visualType": "cardVisual", "query": {"queryState": q},
            "objects": {"value": [{"properties": {"show": lit("true"), "fontSize": num(value_size), "fontFamily": font(value_font),
                                                  "fontColor": color(TEXT), "horizontalAlignment": txt("left")},
                                   "selector": {"id": "default"}}],
                        "label": [{"properties": {"show": lit("true"), "fontSize": num(9), "fontFamily": font(F_REG),
                                                  "fontColor": color(MUTED)},
                                   "selector": {"id": "default"}}],
                        "fillCustom": [{"properties": {"show": lit("false")}}],
                        "outline": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}]},
            "visualContainerObjects": container or plain_container()}


def table(fields: list, right: list = (), extra_objects: Optional[dict] = None, container=None) -> dict:
    o = {"grid": [{"properties": {"gridHorizontal": lit("true"), "gridHorizontalColor": color(LINE), "gridHorizontalWeight": num(1),
                                  "gridVertical": lit("false"), "rowPadding": num(8, "L"), "outlineWeight": num(0), "textSize": num(10)}}],
         "columnHeaders": [{"properties": {"fontColor": color(MUTED), "backColor": color(PANEL), "fontSize": num(9),
                                           "fontFamily": font(F_SEMIBOLD), "wordWrap": lit("false"), "outlineStyle": num(0)}}],
         "values": [{"properties": {"fontColorPrimary": color(TEXT), "backColorPrimary": color(PANEL), "fontColorSecondary": color(TEXT),
                                    "backColorSecondary": color(PANEL), "fontSize": num(10), "fontFamily": font(F_DIN), "wordWrap": lit("false")}}],
         "total": [{"properties": {"totals": lit("false")}}],
         "columnFormatting": [{"properties": {"alignment": txt("Right"), "styleHeader": lit("true"), "styleValues": lit("true")},
                               "selector": {"metadata": r}} for r in right]}
    o.update(extra_objects or {})
    return {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": fields}}},
            "objects": o, "visualContainerObjects": container or plain_container(panel=True)}


def axis_objects(right_axis: bool = True, zero_line: bool = False) -> dict:
    o = {"legend": [{"properties": {"show": lit("true"), "position": txt("Top"), "labelColor": color(MUTED), "showTitle": lit("false"),
                                    "fontSize": num(10), "fontFamily": font(F_REG)}}],
         "categoryAxis": [{"properties": {"show": lit("true"), "labelColor": color(MUTED), "fontSize": num(9), "fontFamily": font(F_REG),
                                          "showAxisTitle": lit("false"), "gridlineShow": lit("false")}}],
         "valueAxis": [{"properties": {"show": lit("true"), "switchAxisPosition": lit("true" if right_axis else "false"),
                                       "labelColor": color(MUTED), "fontSize": num(9), "fontFamily": font(F_DIN), "showAxisTitle": lit("false"),
                                       "gridlineShow": lit("true"), "gridlineColor": color(LINE), "gridlineStyle": txt("dashed"),
                                       "gridlineThickness": num(1, "L")}}],
         "lineStyles": [{"properties": {"strokeWidth": num(2, "L"), "showMarker": lit("false"), "lineChartType": txt("straight")}}],
         "labels": [{"properties": {"show": lit("false")}}],
         "zoom": [{"properties": {"show": lit("false")}}]}
    if zero_line:
        o["y1AxisReferenceLine"] = [{"properties": {"show": lit("true"), "value": num(0), "lineColor": color("#3A4A5C"),
                                                    "transparency": num(0), "style": txt("solid"), "width": num(1)},
                                     "selector": {"id": "1"}}]
    return o


def series_colors(pairs: list) -> list:
    return [{"properties": {"fill": color(col)}, "selector": {"metadata": qref}} for qref, col in pairs]


DATE = c("Portfolio Daily", "Date")
DATE_SORT = {"sort": [{"field": DATE, "direction": "Ascending"}]}


def header(page: Page, subtitle: str) -> None:
    page.add("hdr", 32, 16, 1376, 44, textbox([[("FolioScreen visual capability probe", F_SEMIBOLD, 14, TEXT),
                                                 (f"   {subtitle}   ·   demo data, fictional", F_REG, 10, MUTED)]]),
             mobile=(0, 0, 320, 52))


# ============================================================================ pages
def page_type(features: list) -> Page:
    p = Page("probeType", "Probe 1 · Type & cards")
    header(p, "Page 1 of 3: typography, numbers, cards, containers")
    p.add("t1cap", 32, 72, 660, 40, caption("T1", "Typography ladder", "no serif fallback anywhere; Light, Semilight, Regular, Semibold and Bold look distinct"))
    ladder = [[("$72,921.39", F_LIGHT, 32, TEXT), ("   Segoe UI Light 32", F_REG, 9, MUTED)],
              [("$72,921.39", F_SEMILIGHT, 26, TEXT), ("   Semilight 26", F_REG, 9, MUTED)],
              [("Portfolio value", F_SEMIBOLD, 18, TEXT), ("   Semibold 18", F_REG, 9, MUTED)],
              [("Northwind Systems · 120 shares · +1.24%", F_REG, 13, TEXT), ("   Regular 13", F_REG, 9, MUTED)],
              [("Northwind Systems · 120 shares · +1.24%", F_REG, 11, TEXT), ("   Regular 11", F_REG, 9, MUTED)],
              [("Northwind Systems · 120 shares · +1.24%", F_REG, 9, TEXT), ("   Regular 9", F_REG, 9, MUTED)],
              [("BOLD LABEL 10", F_BOLD, 10, TEXT), ("   Bold 10", F_REG, 9, MUTED)],
              [("1,234,567.89  −12.34", F_DIN, 16, TEXT), ("   DIN 16 (falls back to Segoe UI if absent)", F_REG, 9, MUTED)]]
    p.add("t1", 32, 112, 660, 330, textbox(ladder, plain_container(panel=True)), mobile=(0, 60, 320, 330))
    p.add("t2cap", 720, 72, 688, 40, caption("T2", "Numeric alignment in a table", "numbers and their headers right-aligned; digits line up in columns"))
    p.add("t2", 720, 112, 688, 230, table([
        proj(c("Positions", "InstrumentKey"), "Symbol"), proj(c("Positions", "Units"), "Units"),
        proj(c("Positions", "BrokerPrice"), "Price"), proj(m("_Measures", "Securities Value Check"), "Value"),
        proj(m("_Measures", "Weight"), "Weight")],
        right=["Positions.Units", "Positions.BrokerPrice", "_Measures.Securities Value Check", "_Measures.Weight"]))
    p.add("t3cap", 32, 456, 1376, 34, caption("T3", "KPI rail: one card visual, four values", "four compact values side by side, label above each value"))
    p.add("t3", 32, 492, 1376, 100, card([(m("_Measures", "Portfolio Value"), "Portfolio value"), (m("_Measures", "Cash Value"), "Cash"),
                                          (m("_Measures", "TWR Since Start"), "Return since start"), (m("_Measures", "Errors"), "Data issues")],
                                         container=plain_container(panel=True)), mobile=(0, 400, 320, 200))
    p.add("t4cap", 32, 608, 440, 40, caption("T4", "Card reference labels", "Portfolio value with a smaller 'Return since start' line beneath it"))
    p.add("t4", 32, 648, 440, 120, card([(m("_Measures", "Portfolio Value"), "Portfolio value")], value_size=24,
                                        container=plain_container(panel=True),
                                        extra_roles={"ReferenceLabels": {"projections": [proj(m("_Measures", "TWR Signed"), "Return since start")]}}))
    p.add("t5cap", 488, 608, 440, 40, caption("T5", "Container corner radius and shadow", "left: radius 6 · right: radius 14 with a soft shadow"))
    rounded6 = plain_container(panel=True, radius=6)
    rounded14 = plain_container(panel=True, radius=14)
    rounded14["dropShadow"] = [{"properties": {"show": lit("true"), "preset": txt("Custom"), "color": color("#000000"), "transparency": num(70),
                                               "shadowBlur": num(14), "shadowDistance": num(3), "shadowSpread": num(0), "angle": num(90),
                                               "position": txt("Outer")}}]
    p.add("t5a", 488, 648, 212, 120, textbox([[("radius 6", F_REG, 11, TEXT)]], rounded6))
    p.add("t5b", 716, 648, 212, 120, textbox([[("radius 14 + shadow", F_REG, 11, TEXT)]], rounded14))
    p.add("t6cap", 944, 608, 464, 40, caption("T6", "Dynamic format strings", "'$72.9K' (compact) and '+20.84%' (signed); a blank card means unsupported"))
    t6 = [(m("_Measures", "TWR Signed"), "Signed return")]
    if "dynamic_format" in features:
        t6.insert(0, (m("_Measures", "Value Compact"), "Compact value"))
    p.add("t6", 944, 648, 464, 120, card(t6, container=plain_container(panel=True)), mobile=(0, 610, 320, 110))
    p.add("t7cap", 32, 782, 1376, 34, caption("T7", "Symbols", "arrows and dots render as clean glyphs, not boxes"))
    p.add("t7", 32, 816, 1376, 60, textbox([[("▲ +1.24%   ▼ −0.86%   ●  ◆  ↗  ↘  ·  —  ✓  ⚠", F_REG, 14, TEXT)]], plain_container(panel=True)),
          mobile=(0, 730, 320, 70))
    return p


def page_charts(features: list) -> Page:
    p = Page("probeCharts", "Probe 2 · Charts")
    header(p, "Page 2 of 3: charts, tooltips, metric switch")
    p.add("c1cap", 32, 72, 676, 40, caption("C1", "Area chart, default styling", "a filled area under the portfolio value line; note how dark the fill is"))
    p.add("c1", 32, 112, 676, 300, {"visualType": "areaChart",
        "query": {"queryState": {"Category": {"projections": [proj(DATE, "Date", active=True)]},
                                 "Y": {"projections": [proj(m("_Measures", "Daily Value"), "Portfolio value")]}}, "sortDefinition": DATE_SORT},
        "objects": {**axis_objects(), "dataPoint": series_colors([("_Measures.Daily Value", ACCENT)])},
        "visualContainerObjects": plain_container(panel=True)}, mobile=(0, 60, 320, 240))
    p.add("c2cap", 732, 72, 676, 40, caption("C2", "Return vs benchmark + custom tooltip", "two lines (blue portfolio, grey benchmark), right axis, zero line; hover shows a custom tooltip card"))
    c2 = plain_container(panel=True)
    c2["visualTooltip"] = [{"properties": {"show": lit("true"), "type": txt("Canvas"), "section": txt("probeTooltip")}}]
    p.add("c2", 732, 112, 676, 300, {"visualType": "lineChart",
        "query": {"queryState": {"Category": {"projections": [proj(DATE, "Date", active=True)]},
                                 "Y": {"projections": [proj(m("_Measures", "Portfolio Return %"), "Portfolio"),
                                                       proj(m("_Measures", "Benchmark Return %"), "Benchmark")]}}, "sortDefinition": DATE_SORT},
        "objects": {**axis_objects(zero_line=True),
                    "dataPoint": series_colors([("_Measures.Portfolio Return %", ACCENT), ("_Measures.Benchmark Return %", BENCH)])},
        "visualContainerObjects": c2}, mobile=(0, 310, 320, 240))
    if "field_parameter" in features:
        fp = c(FIELD_PARAMETER_TABLE, FIELD_PARAMETER_TABLE)
        p.add("c3cap", 32, 430, 676, 40, caption("C3", "Metric switch (field parameter)", "clicking Value / Return switches the chart between dollars and percent"))
        p.add("c3s", 32, 470, 676, 40, {"visualType": "advancedSlicerVisual",
            "query": {"queryState": {"Values": {"projections": [proj(fp, "Metric")]}}},
            "objects": {"selection": [{"properties": {"singleSelect": lit("true"), "strictSingleSelect": lit("true")}}],
                        "layout": [{"properties": {"rowCount": num(1, "L"), "columnCount": num(2, "L"), "cellPadding": num(3, "L")}}],
                        "shapeCustomRectangle": [{"properties": {"rectangleRoundedCurve": num(4, "L")}, "selector": {"id": "default"}}],
                        "value": [{"properties": {"fontFamily": font(F_SEMIBOLD), "fontSize": num(10), "fontColor": color(MUTED),
                                                  "horizontalAlignment": txt("center")}, "selector": {"id": "default"}},
                                  {"properties": {"fontColor": color(TEXT)}, "selector": {"id": "selection:selected"}}],
                        "label": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
                        "fillCustom": [{"properties": {"fillColor": color(PANEL), "transparency": num(0)}, "selector": {"id": "default"}},
                                       {"properties": {"fillColor": color("#223041"), "transparency": num(0)}, "selector": {"id": "selection:selected"}}]},
            "visualContainerObjects": plain_container()}, mobile=(0, 560, 320, 40))
        p.add("c3", 32, 514, 676, 256, {"visualType": "lineChart",
            "query": {"queryState": {"Category": {"projections": [proj(DATE, "Date", active=True)]},
                                     "Y": {"projections": [proj(fp, "Metric")]}}, "sortDefinition": DATE_SORT},
            "objects": axis_objects(), "visualContainerObjects": plain_container(panel=True)}, mobile=(0, 604, 320, 220))
    p.add("c4cap", 732, 430, 676, 40, caption("C4", "Allocation bars, sorted", "one bar per holding, largest first, value labels at the bar end"))
    p.add("c4", 732, 470, 676, 300, {"visualType": "clusteredBarChart",
        "query": {"queryState": {"Category": {"projections": [proj(c("Positions", "InstrumentKey"), "Holding", active=True)]},
                                 "Y": {"projections": [proj(m("_Measures", "Securities Value Check"), "Value")]}},
                  "sortDefinition": {"sort": [{"field": m("_Measures", "Securities Value Check"), "direction": "Descending"}]}},
        "objects": {"categoryAxis": [{"properties": {"show": lit("true"), "labelColor": color(TEXT), "fontSize": num(10), "fontFamily": font(F_REG),
                                                     "showAxisTitle": lit("false")}}],
                    "valueAxis": [{"properties": {"show": lit("false"), "gridlineShow": lit("false")}}],
                    "labels": [{"properties": {"show": lit("true"), "color": color(MUTED), "fontSize": num(9), "fontFamily": font(F_DIN)}}],
                    "dataPoint": series_colors([("_Measures.Securities Value Check", ACCENT)])},
        "visualContainerObjects": plain_container(panel=True)})
    p.add("c5", 32, 790, 1376, 50, textbox([[("C2 tooltip: hover over the C2 lines. ", F_SEMIBOLD, 10, TEXT),
                                             ("A small dark card with the date, portfolio value and both returns should replace the default tooltip.",
                                              F_REG, 10, MUTED)]]))
    return p


def page_tooltip() -> Page:
    p = Page("probeTooltip", "Probe tooltip", width=320, height=180, displayOption="ActualSize", type="Tooltip",
             pageBinding={"name": "probeTooltipBinding", "type": "Tooltip"}, visibility="HiddenInViewMode")
    p.add("tt", 0, 0, 320, 180, card([(m("_Measures", "Tooltip Date"), "Date"), (m("_Measures", "Daily Value"), "Value"),
                                      (m("_Measures", "Portfolio Return %"), "Portfolio"), (m("_Measures", "Benchmark Return %"), "Benchmark")],
                                     value_size=14, container=plain_container(panel=True, radius=6)))
    return p


def page_tables(features: list) -> Page:
    p = Page("probeTables", "Probe 3 · Tables")
    header(p, "Page 3 of 3: image columns, sparklines, drillthrough")
    fields = [proj(c("Positions", "InstrumentKey"), "Symbol"), proj(m("_Measures", "Weight"), "Weight")]
    if "svg_measures" in features:
        fields += [proj(m("_Measures", "Weight Bar SVG"), "Weight bar"), proj(m("_Measures", "Range Bar SVG"), "90-day range")]
    p.add("b1cap", 32, 72, 1376, 40, caption("B1", "Image columns from DAX SVG measures, and drillthrough",
                                             "thin blue weight bars and a dot on a range line in every row; right-click a row → Drill through → Security detail"))
    p.add("b1", 32, 112, 1376, 260, table(fields, right=["_Measures.Weight"]), mobile=(0, 60, 320, 260))
    p.add("b2cap", 32, 392, 1376, 40, caption("B2", "Native sparklines in a table", "a small price-trend line in each row"))
    spark = {"field": {"SparklineData": {"Measure": m("_Measures", "Close Trend"), "Groupings": [c("Prices", "Date")], "PointsPerSparkline": 52}},
             "queryRef": "SparklineData(_Measures.Close Trend_[Prices.Date])", "nativeQueryRef": "Trend", "displayName": "Trend"}
    p.add("b2", 32, 432, 1376, 260, table([proj(c("Positions", "InstrumentKey"), "Symbol"), spark]), mobile=(0, 330, 320, 260))
    p.add("b3", 32, 712, 1376, 60, textbox([[("If B2 shows an error and B1 does not, sparklines need a different definition; ", F_REG, 10, MUTED),
                                             ("that result is useful too.", F_SEMIBOLD, 10, TEXT)]]))
    return p


def page_detail() -> Page:
    flt = {"filters": [{"name": "probeTickerFilter", "field": c("Positions", "Ticker"), "type": "Categorical", "howCreated": "Drillthrough"}]}
    p = Page("probeDetail", "Security detail", type="Drillthrough", visibility="HiddenInViewMode", filterConfig=flt,
             pageBinding={"name": "probeDetailBinding", "type": "Drillthrough",
                          "parameters": [{"name": "probeTickerParam", "boundFilter": "probeTickerFilter"}]})
    header(p, "Drillthrough target")
    p.add("d1cap", 32, 72, 1376, 40, caption("D1", "Drillthrough page", "the ticker you drilled from, and its price history"))
    p.add("d1", 32, 112, 440, 100, card([(m("_Measures", "Selected Ticker"), "Security")], value_size=24, container=plain_container(panel=True)))
    p.add("d2", 32, 228, 1376, 400, {"visualType": "lineChart",
        "query": {"queryState": {"Category": {"projections": [proj(c("Prices", "Date"), "Date", active=True)]},
                                 "Y": {"projections": [proj(m("_Measures", "Close Trend"), "Close")]}},
                  "sortDefinition": {"sort": [{"field": c("Prices", "Date"), "direction": "Ascending"}]}},
        "objects": axis_objects(), "visualContainerObjects": plain_container(panel=True)})
    return p


REPORT_PAGES = ["type", "charts", "tables"]


def build_pages(model_features: list, report_pages: list) -> list:
    pages = []
    if "type" in report_pages:
        pages.append(page_type(model_features))
    if "charts" in report_pages:
        pages += [page_charts(model_features), page_tooltip()]
    if "tables" in report_pages:
        pages += [page_tables(model_features), page_detail()]
    return pages


THEME = {
    "name": "FolioScreen Probe Dark", "dataColors": [ACCENT, BENCH, "#B69CFF", "#4FD1C5", "#F2A541", "#F28DB2"],
    "background": BG, "foreground": TEXT, "tableAccent": ACCENT, "good": UP, "neutral": MUTED, "bad": DOWN,
    "textClasses": {"callout": {"fontSize": 24, "fontFace": F_DIN, "color": TEXT},
                    "title": {"fontSize": 12, "fontFace": F_SEMIBOLD, "color": TEXT},
                    "header": {"fontSize": 11, "fontFace": F_SEMIBOLD, "color": TEXT},
                    "label": {"fontSize": 10, "fontFace": F_REG, "color": MUTED}},
    "visualStyles": {"*": {"*": {"visualHeader": [{"show": False}],
                                 "visualTooltip": [{"background": {"solid": {"color": "#18222D"}},
                                                    "titleFontColor": {"solid": {"color": MUTED}},
                                                    "valueFontColor": {"solid": {"color": TEXT}}}]}},
                     "page": {"*": {"background": [{"color": {"solid": {"color": BG}}, "transparency": 0}],
                                    "outspace": [{"color": {"solid": {"color": BG}}, "transparency": 0}]}},
                     "tableEx": {"*": {"total": [{"totals": False}]}}},
}


def render_probe_report(model_features: list, report_pages: list) -> dict:
    files = {k: v for k, v in render_report(NAME).items() if "/pages/" not in k}
    pages = build_pages_r2(model_features, report_pages) if report_pages and report_pages[0].startswith("r2") \
        else build_pages(model_features, report_pages)
    files["definition/pages/pages.json"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name}, indent=2) + "\n"
    for p in pages:
        files[f"definition/pages/{p.name}/page.json"] = json.dumps(p.page_json(), indent=2) + "\n"
        for v in p.visuals:
            files[f"definition/pages/{p.name}/visuals/{v['name']}/visual.json"] = json.dumps(v, indent=2) + "\n"
        for vname, mob in p.mobile.items():
            files[f"definition/pages/{p.name}/visuals/{vname}/mobile.json"] = json.dumps(mob, indent=2) + "\n"
    report = json.loads(files["definition/report.json"])
    report["themeCollection"]["customTheme"] = {"name": "FolioScreenProbeDark.json",
                                                "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"},
                                                "type": "RegisteredResources"}
    report["resourcePackages"].append({"name": "RegisteredResources", "type": "RegisteredResources",
                                       "items": [{"name": "FolioScreenProbeDark.json", "path": "FolioScreenProbeDark.json", "type": "CustomTheme"}]})
    report["objects"] = {"outspacePane": [{"properties": {"expanded": lit("false")}}]}
    files["definition/report.json"] = json.dumps(report, indent=2) + "\n"
    files["StaticResources/RegisteredResources/FolioScreenProbeDark.json"] = json.dumps(THEME, indent=2) + "\n"
    return files


# ============================================================================ build & deploy
def probe_dataset():
    from datetime import date
    from .sync import build_dataset
    return build_dataset(demo=True, scenario="clean", today=date.today())


def render_probe_model(dataset: dict, prices: dict, features: list) -> dict:
    from .model_writer import render_semantic_model
    measures, tables = model_extras_r2(features) if any(f.startswith("dynamic_format_") for f in features) or ROUND else model_extras(features)
    return render_semantic_model(dataset, demo_prices=prices, name=NAME, extra_measures=measures, extra_tables=tables, include_report=False)


def write_probe_pbip(out_dir: Path, base_theme: Path, features: Optional[list] = None, pages: Optional[list] = None) -> None:
    from .model_writer import write_pbip
    ds, prices, _ = probe_dataset()
    features = ROUND2_FEATURES if features is None else features
    write_pbip(out_dir, render_probe_model(ds, prices, features), render_probe_report(features, pages or ROUND2_PAGES), base_theme, NAME)


def deploy(base_theme: Path, log=print) -> dict:
    from .powerbi import MicrosoftAuth, PowerBI, PowerBIError, parts_from_files
    from .sync import Publisher, utcnow
    pbi = PowerBI(MicrosoftAuth(interactive=False))
    ds, prices, _ = probe_dataset()
    result = {"model_features": {}, "report_pages": {}}

    # ---- model: all optional features first; drop one at a time if deployment or refresh fails
    mid = pbi.find_item("semanticModels", NAME)
    FEATS = ROUND2_FEATURES
    candidates = [FEATS] + [[f for f in FEATS if f != drop] for drop in FEATS] + [[]]
    chosen = None
    for feats in candidates:
        log(f"Model with features {feats or ['(none)']}…")
        parts = parts_from_files(render_probe_model(ds, prices, feats))
        try:
            if mid:
                pbi.update_definition("semanticModels", mid, parts, "TMDL")
            else:
                mid = pbi.create_item("semanticModels", NAME, parts, "TMDL")
        except PowerBIError as exc:
            log(f"   definition rejected: {str(exc)[:300]}")
            result.setdefault("model_errors", []).append({"features": feats, "stage": "definition", "error": str(exc)[:600]})
            continue
        started = utcnow(-60)
        pbi.trigger_refresh(mid)
        res = pbi.wait_for_refresh(mid, started, progress=log)
        if res["status"] == "Completed":
            chosen = feats
            break
        log(f"   refresh {res['status']}: {res.get('error', '')[:300]}")
        result.setdefault("model_errors", []).append({"features": feats, "stage": "refresh", "error": res.get("error", "")[:600]})
    if chosen is None:
        raise RuntimeError("The probe model could not be deployed even without optional features. See reports/visual_probe.json.")
    for f in FEATS:
        result["model_features"][f] = "deployed" if f in chosen else "failed (dropped)"

    # ---- report: all pages first; otherwise add pages one by one
    rid = pbi.find_item("reports", NAME)

    def push(pages: list) -> bool:
        nonlocal rid
        files = render_probe_report(chosen, pages)
        files["definition.pbir"] = json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0", "datasetReference": {"byConnection": {"connectionString": f"semanticmodelid={mid}"}}}, indent=2)
        files[BASE_THEME_REL] = base_theme.read_bytes()
        parts = parts_from_files(files)
        try:
            if rid:
                pbi.update_definition("reports", rid, parts, "PBIR")
            else:
                rid = pbi.create_item("reports", NAME, parts, "PBIR")
            return True
        except PowerBIError as exc:
            result.setdefault("report_errors", []).append({"pages": pages, "error": str(exc)[:600]})
            log(f"   report rejected with pages {pages}: {str(exc)[:300]}")
            return False

    PAGES = ROUND2_PAGES
    log("Report with all probe pages…")
    if push(PAGES):
        ok_pages = list(PAGES)
    else:
        ok_pages = []
        for pg in PAGES:
            if push(ok_pages + [pg]):
                ok_pages.append(pg)
        if ok_pages:
            push(ok_pages)
    for pg in PAGES:
        result["report_pages"][pg] = "deployed" if pg in ok_pages else "failed (dropped)"
    result["report_url"] = f"https://app.powerbi.com/groups/me/reports/{rid}" if rid else None
    paths.write_private(paths.reports_dir() / "visual_probe.json", json.dumps(result, indent=2) + "\n")
    return result


# ============================================================================ ROUND 2 (targeted retests)
# Round 1 results (10 Nov 2026) are summarised in docs/visual-probe-results.md.
DYNAMIC_FORMAT_VARIANTS = {
    "dynamic_format_end": [("Value Compact", "[Portfolio Value]", None, {"formatStringDefinition":
        'VAR _v = ABS ( [Portfolio Value] ) RETURN IF ( _v >= 1000000, "$#,0.00,,""M""", IF ( _v >= 1000, "$#,0.0,""K""", "$#,0" ) )'})],
    "dynamic_format_block": [("Value Compact B", "[Portfolio Value]", None, {"formatStringDefinitionBlock":
        'VAR _v = ABS ( [Portfolio Value] )\nRETURN\n    IF ( _v >= 1000000, "$#,0.00,,""M""", IF ( _v >= 1000, "$#,0.0,""K""", "$#,0" ) )'})],
}
TREND_SVG = ("Trend SVG", """VAR _t = SELECTEDVALUE ( Positions[Ticker] )
VAR _last = CALCULATE ( MAX ( Prices[Date] ), REMOVEFILTERS ( Prices ), Prices[Ticker] = _t )
VAR _pts =
    CALCULATETABLE (
        SELECTCOLUMNS ( Prices, "d", Prices[Date], "c", Prices[Close] ),
        REMOVEFILTERS ( Prices ), Prices[Ticker] = _t, Prices[Date] > _last - 90
    )
VAR _lo = MINX ( _pts, [c] )
VAR _hi = MAXX ( _pts, [c] )
VAR _d0 = MINX ( _pts, [d] )
VAR _span = MAX ( 1, INT ( _last ) - INT ( _d0 ) )
VAR _rng = IF ( _hi > _lo, _hi - _lo, 1 )
VAR _poly =
    CONCATENATEX (
        _pts,
        FORMAT ( ( INT ( [d] ) - INT ( _d0 ) ) / _span * 116 + 2, "0.0" ) & "," & FORMAT ( 14 - ( [c] - _lo ) / _rng * 12, "0.0" ),
        " ", [d], ASC
    )
VAR _first = MAXX ( FILTER ( _pts, [d] = _d0 ), [c] )
VAR _lastc = MAXX ( FILTER ( _pts, [d] = _last ), [c] )
RETURN
    IF (
        NOT ISBLANK ( _t ) && COUNTROWS ( _pts ) > 1,
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='16' viewBox='0 0 120 16'>"
            & "<polyline fill='none' stroke='" & IF ( _lastc >= _first, "%233DCB95", "%23FF7A7A" )
            & "' stroke-width='1.5' stroke-linejoin='round' stroke-linecap='round' points='" & _poly & "'/></svg>"
    )""", None, {"dataCategory": "ImageUrl"})
ROUND2_FEATURES = ["field_parameter", "dynamic_format_end", "dynamic_format_block", "svg_measures"]


def model_extras_r2(features: list) -> tuple:
    measures = list(PROBE_MEASURES)
    tables = {}
    for f in ("dynamic_format_end", "dynamic_format_block"):
        if f in features:
            measures += DYNAMIC_FORMAT_VARIANTS[f]
    if "svg_measures" in features:
        measures += SVG_MEASURES + [TREND_SVG]
    if "field_parameter" in features:
        tables[FIELD_PARAMETER_TABLE] = field_parameter_tmdl()
    return measures, tables


def caption2(tid: str, what: str, expect: str) -> dict:
    """Single paragraph so it never needs a scrollbar (round 1: two-paragraph captions overflowed)."""
    return textbox([[(f"{tid}  ", F_SEMIBOLD, 10, ACCENT), (what + "  ", F_SEMIBOLD, 10, TEXT), (expect, F_REG, 9, MUTED)]])


def card2(fields: list, value_size=20, container=None) -> dict:
    """Card with the inner background removed and no automatic display units (round 1: dark inner box, '72.92K')."""
    return {"visualType": "cardVisual", "query": {"queryState": {"Data": {"projections": [proj(f, label) for f, label in fields]}}},
            "objects": {"value": [{"properties": {"show": lit("true"), "fontSize": num(value_size), "fontFamily": font(F_LIGHT),
                                                  "fontColor": color(TEXT), "horizontalAlignment": txt("left"),
                                                  "labelDisplayUnits": num(1)}, "selector": {"id": "default"}}],
                        "label": [{"properties": {"show": lit("true"), "fontSize": num(9), "fontFamily": font(F_REG),
                                                  "fontColor": color(MUTED)}, "selector": {"id": "default"}}],
                        "layout": [{"properties": {"backgroundShow": lit("false"), "topOuterMargin": num(0, "L"), "bottomOuterMargin": num(0, "L"),
                                                   "leftOuterMargin": num(0, "L"), "rightOuterMargin": num(0, "L"), "paddingUniform": num(0, "L")},
                                    "selector": {"id": "default"}}],
                        "cardCalloutArea": [{"properties": {"paddingUniform": num(0, "L"), "paddingIndividual": lit("false")},
                                             "selector": {"id": "default"}}],
                        "fillCustom": [{"properties": {"show": lit("false")}}],
                        "outline": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
                        "divider": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}]},
            "visualContainerObjects": container or plain_container(panel=True)}


def mobile_override(objects: dict) -> dict:
    return {"objects": objects}


def page_r2_cards(features: list) -> Page:
    p = Page("r2Cards", "Round 2 · Cards", height=820)
    header(p, "Round 2, page 1 of 3: cards, number formats, phone overrides")
    p.add("r1cap", 32, 72, 1376, 30, caption2("R1", "KPI rail, corrected", "no dark inner box; full figures (72,921.39), not 72.92K. On the phone: smaller type via a phone-only override, nothing cut off."))
    p.add("r1", 32, 104, 1376, 100, card2([(m("_Measures", "Portfolio Value"), "Portfolio value"), (m("_Measures", "Cash Value"), "Cash"),
                                           (m("_Measures", "TWR Signed"), "Return since start"), (m("_Measures", "Errors"), "Data issues")], value_size=24),
          mobile=(0, 60, 320, 150))
    p.mobile["r1"].update(mobile_override({"value": [{"properties": {"fontSize": num(14)}, "selector": {"id": "default"}}]}))
    p.add("r2cap", 32, 224, 1376, 30, caption2("R2", "Dynamic number formats", "left card '$72.9K' (single-line definition), right card '$72.9K' (block definition). A missing card means that form failed to deploy."))
    left = [(m("_Measures", "Value Compact"), "Compact (single-line)")] if "dynamic_format_end" in features else []
    right = [(m("_Measures", "Value Compact B"), "Compact (block)")] if "dynamic_format_block" in features else []
    if left:
        p.add("r2a", 32, 256, 676, 100, card2(left), mobile=(0, 220, 320, 90))
    if right:
        p.add("r2b", 732, 256, 676, 100, card2(right), mobile=(0, 320, 320, 90))
    p.add("r3cap", 32, 376, 1376, 30, caption2("R3", "Phone-only text override", "desktop: 14 pt. Phone: the same text at 10 pt, fitting on two lines."))
    t = textbox([[("Holdings value is shown at the latest close. Cash includes money-market funds.", F_REG, 14, TEXT)]], plain_container(panel=True))
    p.add("r3", 32, 408, 1376, 70, t, mobile=(0, 420, 320, 80))
    p.mobile["r3"].update(mobile_override({"general": [{"properties": {"paragraphs": [{"textRuns": [{
        "value": "Holdings value is shown at the latest close. Cash includes money-market funds.",
        "textStyle": {"fontFamily": F_REG, "fontSize": "10pt", "color": TEXT}}]}]}}]}))
    return p


def page_r2_charts(features: list) -> Page:
    p = Page("r2Charts", "Round 2 · Charts", height=820)
    header(p, "Round 2, page 2 of 3: metric switch, tooltip, axis title")
    if "field_parameter" in features:
        fp = c(FIELD_PARAMETER_TABLE, FIELD_PARAMETER_TABLE)
        p.add("r4cap", 32, 72, 676, 30, caption2("R4", "Metric switch with the schema's field-parameter binding", "buttons read Value / Return; the chart switches between dollars and percent"))
        # Button slicer: identical settings to Marine Energy Screen's working window buttons
        p.add("r4s", 32, 104, 676, 40, {"visualType": "advancedSlicerVisual",
            "query": {"queryState": {"Values": {"projections": [proj(fp, "Metric")]}}},
            "objects": {"selection": [{"properties": {"singleSelect": lit("true"), "strictSingleSelect": lit("true")}}],
                        "layout": [{"properties": {"rowCount": num(1, "L"), "columnCount": num(2, "L"), "cellPadding": num(3, "L")}}],
                        "shapeCustomRectangle": [{"properties": {"rectangleRoundedCurve": num(4, "L")}, "selector": {"id": "default"}}],
                        "value": [{"properties": {"fontFamily": font(F_SEMIBOLD), "fontSize": num(10), "fontColor": color("#9AABBD"),
                                                  "horizontalAlignment": txt("center")}, "selector": {"id": "default"}},
                                  {"properties": {"fontColor": color(TEXT)}, "selector": {"id": "interaction:hover"}},
                                  {"properties": {"fontColor": color(TEXT)}, "selector": {"id": "selection:selected"}}],
                        "label": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
                        "fillCustom": [{"properties": {"fillColor": color("#131B24"), "transparency": num(100)}, "selector": {"id": "default"}},
                                       {"properties": {"fillColor": color("#1E2B38"), "transparency": num(0)}, "selector": {"id": "interaction:hover"}},
                                       {"properties": {"fillColor": color("#223041"), "transparency": num(0)}, "selector": {"id": "selection:selected"}}]},
            "visualContainerObjects": plain_container()}, mobile=(0, 60, 320, 40))
        p.add("r4", 32, 148, 676, 260, {"visualType": "lineChart",
            "query": {"queryState": {"Category": {"projections": [proj(DATE, "Date", active=True)]},
                                     "Y": {"projections": [proj(m("_Measures", "Daily Value"), "Metric")],
                                           "fieldParameters": [{"parameterExpr": fp, "index": 0, "length": 1}]}},
                      "sortDefinition": DATE_SORT},
            "objects": axis_objects(), "visualContainerObjects": plain_container(panel=True)}, mobile=(0, 104, 320, 220))
        p.add("r4tcap", 32, 424, 676, 30, caption2("R4b", "Parameter table contents", "two rows: Value / Return, with their field references"))
        p.add("r4t", 32, 456, 676, 120, table([proj(c(FIELD_PARAMETER_TABLE, FIELD_PARAMETER_TABLE), "Metric"),
                                               proj(c(FIELD_PARAMETER_TABLE, f"{FIELD_PARAMETER_TABLE} Order"), "Order")]))
    p.add("r5cap", 732, 72, 676, 30, caption2("R5", "Tooltip page, resized", "hover the lines: a 380×140 card with date, value and both returns, nothing cut off"))
    c5 = plain_container(panel=True)
    c5["visualTooltip"] = [{"properties": {"show": lit("true"), "type": txt("Canvas"), "section": txt("r2Tooltip")}}]
    p.add("r5", 732, 104, 676, 300, {"visualType": "lineChart",
        "query": {"queryState": {"Category": {"projections": [proj(DATE, "Date", active=True)]},
                                 "Y": {"projections": [proj(m("_Measures", "Portfolio Return %"), "Portfolio"),
                                                       proj(m("_Measures", "Benchmark Return %"), "Benchmark")]}}, "sortDefinition": DATE_SORT},
        "objects": {**axis_objects(zero_line=True),
                    "dataPoint": series_colors([("_Measures.Portfolio Return %", ACCENT), ("_Measures.Benchmark Return %", BENCH)])},
        "visualContainerObjects": c5}, mobile=(0, 340, 320, 220))
    p.add("r6cap", 732, 424, 676, 30, caption2("R6", "Allocation bars without the axis title", "no 'Value' caption under the bars"))
    p.add("r6", 732, 456, 676, 300, {"visualType": "clusteredBarChart",
        "query": {"queryState": {"Category": {"projections": [proj(c("Positions", "InstrumentKey"), "Holding", active=True)]},
                                 "Y": {"projections": [proj(m("_Measures", "Securities Value Check"), "Value")]}},
                  "sortDefinition": {"sort": [{"field": m("_Measures", "Securities Value Check"), "direction": "Descending"}]}},
        "objects": {"categoryAxis": [{"properties": {"show": lit("true"), "labelColor": color(TEXT), "fontSize": num(10), "fontFamily": font(F_REG),
                                                     "showAxisTitle": lit("false")}}],
                    "valueAxis": [{"properties": {"show": lit("false"), "showAxisTitle": lit("false"), "gridlineShow": lit("false")}}],
                    "labels": [{"properties": {"show": lit("true"), "color": color(MUTED), "fontSize": num(9), "fontFamily": font(F_DIN),
                                               "labelDisplayUnits": num(1)}}],
                    "dataPoint": series_colors([("_Measures.Securities Value Check", ACCENT)])},
        "visualContainerObjects": plain_container(panel=True)}, mobile=(0, 570, 320, 240))
    return p


def page_r2_tooltip() -> Page:
    p = Page("r2Tooltip", "Round 2 tooltip", width=380, height=140, displayOption="ActualSize", type="Tooltip",
             pageBinding={"name": "r2TooltipBinding", "type": "Tooltip"}, visibility="HiddenInViewMode")
    p.add("tt", 0, 0, 380, 140, card2([(m("_Measures", "Tooltip Date"), "Date"), (m("_Measures", "Daily Value"), "Value"),
                                       (m("_Measures", "Portfolio Return %"), "Portfolio"), (m("_Measures", "Benchmark Return %"), "Benchmark")],
                                      value_size=13, container=plain_container(panel=True, radius=6)))
    return p


def page_r2_tables(features: list) -> Page:
    p = Page("r2Tables", "Round 2 · Tables", height=820)
    header(p, "Round 2, page 3 of 3: image row height, image trend lines, drillthrough")
    if "svg_measures" in features:
        variants = [("r7a", "grid.imageHeight", {"grid": [{"properties": {"imageHeight": num(18)}}]}),
                    ("r7b", "values.imageHeight", {"values": [{"properties": {"imageHeight": num(18)}}]}),
                    ("r7c", "imageSize", {"imageSize": [{"properties": {"height": num(18), "width": num(120)}}]})]
        p.add("r7cap", 32, 72, 1376, 30, caption2("R7", "Image row height: three candidate settings", "whichever table has compact rows (about 30 px, like a normal table) shows the right setting"))
        for i, (vname, label, extra) in enumerate(variants):
            x = 32 + i * 464
            p.add(f"{vname}cap", x, 104, 448, 24, textbox([[(label, F_SEMIBOLD, 9, MUTED)]]))
            tbl = table([proj(c("Positions", "InstrumentKey"), "Symbol"), proj(m("_Measures", "Weight Bar SVG"), "Weight")])
            base = tbl["objects"]
            for k, v in extra.items():
                if k in base:
                    base[k] = [{"properties": {**base[k][0]["properties"], **v[0]["properties"]}}]
                else:
                    base[k] = v
            p.add(vname, x, 128, 448, 240, tbl, mobile=(0, 60 + i * 250, 320, 240) if i == 0 else None)
        p.add("r8cap", 32, 388, 1376, 30, caption2("R8", "Trend lines drawn as images, and drillthrough", "a small green or red 90-day line per row; right-click a row → Drill through → Security detail"))
        trend = table([proj(c("Positions", "InstrumentKey"), "Symbol"), proj(m("_Measures", "Weight"), "Weight"),
                       proj(m("_Measures", "Trend SVG"), "90-day trend"), proj(m("_Measures", "Range Bar SVG"), "90-day range")],
                      right=["_Measures.Weight"],
                      extra_objects={"grid": [{"properties": {"gridHorizontal": lit("true"), "gridHorizontalColor": color(LINE),
                                                              "gridHorizontalWeight": num(1), "gridVertical": lit("false"), "rowPadding": num(8, "L"),
                                                              "outlineWeight": num(0), "textSize": num(10), "imageHeight": num(18)}}]})
        p.add("r8", 32, 420, 1376, 300, trend, mobile=(0, 320, 320, 300))
    return p


def page_r2_detail() -> Page:
    flt = {"filters": [{"name": "r2SymbolFilter", "field": c("Positions", "InstrumentKey"), "type": "Categorical", "howCreated": "Drillthrough"}]}
    p = Page("r2Detail", "Security detail", height=700, type="Drillthrough", visibility="HiddenInViewMode", filterConfig=flt,
             pageBinding={"name": "r2DetailBinding", "type": "Drillthrough",
                          "parameters": [{"name": "r2SymbolParam", "boundFilter": "r2SymbolFilter"}]})
    header(p, "Drillthrough target")
    p.add("d1cap", 32, 72, 1376, 30, caption2("R9", "Drillthrough page", "the symbol you drilled from and its price history; Power BI adds a back arrow"))
    p.add("d1", 32, 104, 440, 100, card2([(m("_Measures", "Selected Ticker"), "Security")], value_size=24))
    p.add("d2", 32, 220, 1376, 400, {"visualType": "lineChart",
        "query": {"queryState": {"Category": {"projections": [proj(c("Prices", "Date"), "Date", active=True)]},
                                 "Y": {"projections": [proj(m("_Measures", "Close Trend"), "Close")]}},
                  "sortDefinition": {"sort": [{"field": c("Prices", "Date"), "direction": "Ascending"}]}},
        "objects": axis_objects(), "visualContainerObjects": plain_container(panel=True)})
    return p


ROUND2_PAGES = ["r2_cards", "r2_charts", "r2_tables"]


def build_pages_r2(features: list, pages: list) -> list:
    out = []
    if "r2_cards" in pages:
        out.append(page_r2_cards(features))
    if "r2_charts" in pages:
        out += [page_r2_charts(features), page_r2_tooltip()]
    if "r2_tables" in pages:
        out += [page_r2_tables(features), page_r2_detail()]
    return out
