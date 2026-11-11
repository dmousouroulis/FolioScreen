"""FolioScreen report (Phase 4): Overview, Holdings, Performance, Security detail, chart tooltip, phone layouts.

Built only from techniques verified in Power BI Service and the iPhone app (docs/visual-probe-results.md).
Layout follows the approved design canvas ("FolioScreen design"); figures are px on a 1440 × 900 page and pt in
Power BI (pt = px × 0.75).
"""
from __future__ import annotations

import json
from typing import Optional

from .model_writer import PROJECT, _platform
from .report_model import CHART_METRIC

VC = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.10.0/schema.json"
MOBILE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainerMobileState/2.5.0/schema.json"
PAGE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"

# design tokens (FolioScreen design system)
GROUND, SURFACE, RAISED, LINE, LINE2 = "#0B1118", "#111923", "#182230", "#1F2A37", "#2C3B4D"
INK, INK2, INK3 = "#E6ECF2", "#A3B2C4", "#7C8EA2"
PORTFOLIO, BENCH, GAIN, LOSS, CAUTION = "#6CB4FF", "#8F9DAE", "#3DCB95", "#FF7A7A", "#E8B15A"
F_REG = "'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif"
F_LIGHT = "'Segoe UI Light', wf_segoe-ui_light, helvetica, arial, sans-serif"
F_SEMIBOLD = "'Segoe UI Semibold', wf_segoe-ui_semibold, helvetica, arial, sans-serif"

PAGES = {"overview": "Overview", "holdings": "Holdings", "performance": "Performance"}
DETAIL, TIP, QA = "securityDetail", "chartTip", "qaSwitch"


# ============================================================================ primitives
def lit(v) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def txt(s: str) -> dict:
    return lit("'" + s.replace("'", "''") + "'")


def num(v, kind: str = "D") -> dict:
    return lit(f"{v}{kind}")


def color(hexv: str) -> dict:
    return {"solid": {"color": lit(f"'{hexv}'")}}


def m(prop: str, entity: str = "_Measures") -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def c(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def color_by(measure: str) -> dict:
    """Colour from a measure that returns a hex string (Power BI 'field value' formatting)."""
    return {"solid": {"color": {"expr": m(measure)}}}


def qref(field: dict) -> str:
    k = next(iter(field))
    return f"{field[k]['Expression']['SourceRef']['Entity']}.{field[k]['Property']}"


def proj(field: dict, label: str, active: bool = False) -> dict:
    out = {"field": field, "queryRef": qref(field), "nativeQueryRef": label, "displayName": label}
    if active:
        out["active"] = True
    return out


def container(title: Optional[str] = None, panel: bool = False, radius: int = 8, pad=(12, 12, 16, 16), bg: str = SURFACE) -> dict:
    o = {"visualHeader": [{"properties": {"show": lit("false")}}],
         "dropShadow": [{"properties": {"show": lit("false")}}]}
    if title:
        o["title"] = [{"properties": {"show": lit("true"), "text": txt(title), "fontColor": color(INK), "fontSize": num(10),
                                      "fontFamily": txt(F_SEMIBOLD), "alignment": txt("left")}}]
    else:
        o["title"] = [{"properties": {"show": lit("false")}}]
    if panel:
        o["background"] = [{"properties": {"show": lit("true"), "color": color(bg), "transparency": num(0)}}]
        o["border"] = [{"properties": {"show": lit("true"), "color": color(LINE), "radius": num(radius), "width": num(1)}}]
        t, b, l, r = pad
        o["padding"] = [{"properties": {"top": num(t), "bottom": num(b), "left": num(l), "right": num(r)}}]
    else:
        o["background"] = [{"properties": {"show": lit("false")}}]
        o["border"] = [{"properties": {"show": lit("false")}}]
    return o


def with_tooltip(cont: dict, page: str) -> dict:
    cont = dict(cont)
    cont["visualTooltip"] = [{"properties": {"show": lit("true"), "type": txt("Canvas"), "section": txt(page)}}]
    return cont


class Page:
    def __init__(self, name: str, display: str, width: int = 1440, height: int = 900, **extra):
        self.name, self.display, self.width, self.height, self.extra = name, display, width, height, extra
        self.visuals, self.mobile = [], {}
        self._z = 1000

    def add(self, vname: str, x: int, y: int, w: int, h: int, visual: dict,
            mobile: Optional[tuple] = None, mobile_objects: Optional[dict] = None) -> None:
        self._z += 1000
        self.visuals.append({"$schema": VC, "name": vname,
                             "position": {"x": x, "y": y, "z": self._z, "height": h, "width": w, "tabOrder": self._z},
                             "visual": visual})
        if mobile:
            mx, my, mw, mh = mobile
            mob = {"$schema": MOBILE, "position": {"x": mx, "y": my, "z": self._z, "height": mh, "width": mw, "tabOrder": self._z}}
            if mobile_objects:
                mob["objects"] = mobile_objects
            self.mobile[vname] = mob

    def page_json(self) -> dict:
        d = {"$schema": PAGE, "name": self.name, "displayName": self.display,
             "displayOption": self.extra.get("displayOption", "FitToWidth"), "height": self.height, "width": self.width,
             "objects": {"background": [{"properties": {"color": color(self.extra.get("bg", GROUND)), "transparency": num(0)}}],
                         "outspace": [{"properties": {"color": color(GROUND), "transparency": num(0)}}]}}
        for k in ("type", "pageBinding", "visibility", "filterConfig"):
            if k in self.extra:
                d[k] = self.extra[k]
        return d


# ============================================================================ visual builders
def textbox(runs: list, cont: Optional[dict] = None) -> dict:
    """runs: list of paragraphs; each paragraph a list of (text, font, size_pt, colour)."""
    paragraphs = [{"textRuns": [{"value": t, "textStyle": {"fontFamily": f, "fontSize": f"{sz}pt", "color": col}}
                                for (t, f, sz, col) in para]} for para in runs]
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "visualContainerObjects": cont or container()}


def card(values: list, size: int = 15, font: str = F_LIGHT, label: bool = True, colors: Optional[dict] = None,
         label_size: int = 9, cont: Optional[dict] = None, align: str = "left") -> dict:
    """values: [(measure name, label)]; colors: {measure name: colour measure}. Labels sit beneath values (R1)."""
    fields = [(m(name), lbl) for name, lbl in values]
    obj = {"value": [{"properties": {"show": lit("true"), "fontSize": num(size), "fontFamily": txt(font), "fontColor": color(INK),
                                     "horizontalAlignment": txt(align), "labelDisplayUnits": num(1)}, "selector": {"id": "default"}}],
           "label": [{"properties": {"show": lit("true" if label else "false"), "fontSize": num(label_size), "fontFamily": txt(F_REG),
                                     "fontColor": color(INK3), "horizontalAlignment": txt(align)}, "selector": {"id": "default"}}],
           "layout": [{"properties": {"backgroundShow": lit("false"), "topOuterMargin": num(0, "L"), "bottomOuterMargin": num(0, "L"),
                                      "leftOuterMargin": num(0, "L"), "rightOuterMargin": num(0, "L"), "paddingUniform": num(0, "L")},
                       "selector": {"id": "default"}}],
           "cardCalloutArea": [{"properties": {"paddingUniform": num(0, "L"), "paddingIndividual": lit("false")}, "selector": {"id": "default"}}],
           "fillCustom": [{"properties": {"show": lit("false")}}],
           "outline": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
           "divider": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}]}
    for name, cm in (colors or {}).items():
        obj["value"].append({"properties": {"fontColor": color_by(cm)}, "selector": {"metadata": f"_Measures.{name}"}})
    return {"visualType": "cardVisual", "query": {"queryState": {"Data": {"projections": [proj(f, l) for f, l in fields]}}},
            "objects": obj, "visualContainerObjects": cont or container()}


def table(cols: list, *, right: tuple = (), colors: Optional[dict] = None, back: Optional[str] = None, totals: bool = False,
          sort: Optional[tuple] = None, widths: Optional[dict] = None, cont: Optional[dict] = None, text_size: int = 10,
          row_padding: int = 7) -> dict:
    """cols: [(field, label)]; right: query refs to right-align; colors: {query ref: colour measure};
    back: colour measure for every cell's background; widths: {query ref: px}."""
    projections = [proj(f, l) for f, l in cols]
    refs = [p["queryRef"] for p in projections]
    o = {"grid": [{"properties": {"gridHorizontal": lit("true"), "gridHorizontalColor": color(LINE), "gridHorizontalWeight": num(1),
                                  "gridVertical": lit("false"), "rowPadding": num(row_padding, "L"), "outlineWeight": num(0),
                                  "textSize": num(text_size), "imageHeight": num(16), "imageWidth": num(120)}}],
         "columnHeaders": [{"properties": {"fontColor": color(INK3), "backColor": color(SURFACE), "fontSize": num(9),
                                           "fontFamily": txt(F_REG), "wordWrap": lit("false"), "outlineStyle": num(0)}}],
         "values": [{"properties": {"fontColorPrimary": color(INK), "backColorPrimary": color(SURFACE), "fontColorSecondary": color(INK),
                                    "backColorSecondary": color(SURFACE), "fontSize": num(text_size), "fontFamily": txt(F_REG),
                                    "wordWrap": lit("false"), "urlIcon": lit("false")}}],
         "total": [{"properties": {"totals": lit("true" if totals else "false"), "fontColor": color(INK), "backColor": color(SURFACE),
                                   "fontFamily": txt(F_SEMIBOLD), "fontSize": num(text_size)}}],
         "columnFormatting": [{"properties": {"alignment": txt("Right"), "styleHeader": lit("true"), "styleValues": lit("true"),
                                              "styleTotal": lit("true")},
                               "selector": {"metadata": r}} for r in right]}
    for r, cm in (colors or {}).items():
        o["values"].append({"properties": {"fontColor": color_by(cm)},
                            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": r}})
    if back:
        for r in refs:
            o["values"].append({"properties": {"backColor": color_by(back)},
                                "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": r}})
    if widths:
        o["columnWidth"] = [{"properties": {"value": num(w)}, "selector": {"metadata": r}} for r, w in widths.items()]
    q = {"queryState": {"Values": {"projections": projections}}}
    if sort:
        q["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}]}
    return {"visualType": "tableEx", "query": q, "objects": o, "visualContainerObjects": cont or container(panel=True)}


def axes(zero_line: bool = False, legend: bool = True, label_size: int = 9) -> dict:
    o = {"legend": [{"properties": {"show": lit("true" if legend else "false"), "position": txt("Top"), "labelColor": color(INK2),
                                    "showTitle": lit("false"), "fontSize": num(9), "fontFamily": txt(F_REG)}}],
         "categoryAxis": [{"properties": {"show": lit("true"), "labelColor": color(INK3), "fontSize": num(label_size), "fontFamily": txt(F_REG),
                                          "showAxisTitle": lit("false"), "gridlineShow": lit("false")}}],
         "valueAxis": [{"properties": {"show": lit("true"), "switchAxisPosition": lit("true"), "labelColor": color(INK3),
                                       "fontSize": num(label_size), "fontFamily": txt(F_REG), "showAxisTitle": lit("false"),
                                       "gridlineShow": lit("true"), "gridlineColor": color(LINE), "gridlineStyle": txt("dashed"),
                                       "gridlineThickness": num(1, "L")}}],
         "lineStyles": [{"properties": {"strokeWidth": num(2, "L"), "showMarker": lit("false"), "lineChartType": txt("straight")}}],
         "labels": [{"properties": {"show": lit("false")}}],
         "zoom": [{"properties": {"show": lit("false")}}]}
    if zero_line:
        o["y1AxisReferenceLine"] = [{"properties": {"show": lit("true"), "value": num(0), "lineColor": color(LINE2), "transparency": num(0),
                                                    "style": txt("solid"), "width": num(1)}, "selector": {"id": "1"}}]
    return o


def series_colors(pairs: list) -> list:
    return [{"properties": {"fill": color(col)}, "selector": {"metadata": f"_Measures.{name}"}} for name, col in pairs]


def line_chart(category: dict, measures: list, colors: list, *, field_parameter: Optional[dict] = None, zero_line: bool = False,
               tooltip: Optional[str] = None, cont: Optional[dict] = None, label_size: int = 9) -> dict:
    y = {"projections": [proj(m(n), l) for n, l in measures]}
    if field_parameter:
        y["fieldParameters"] = [{"parameterExpr": field_parameter, "index": 0, "length": len(measures)}]
    cnt = cont or container(panel=True, pad=(40, 6, 14, 10))
    if tooltip:
        cnt = with_tooltip(cnt, tooltip)
    return {"visualType": "lineChart",
            "query": {"queryState": {"Category": {"projections": [proj(category, "Date", active=True)]}, "Y": y},
                      "sortDefinition": {"sort": [{"field": category, "direction": "Ascending"}]}},
            "objects": {**axes(zero_line=zero_line, label_size=label_size), "dataPoint": series_colors(colors)},
            "visualContainerObjects": cnt}


def bar_chart(category: dict, cat_label: str, measure: str, label: str, color_measure: str, *, sort: tuple, column: bool = False,
              labels: bool = True, cont: Optional[dict] = None, axis_size: int = 9, category_width: Optional[int] = None,
              scalar: bool = False) -> dict:
    cat_props = {"show": lit("true"), "labelColor": color(INK2), "fontSize": num(axis_size), "fontFamily": txt(F_REG),
                 "showAxisTitle": lit("false"), "gridlineShow": lit("false")}
    if category_width:
        cat_props["preferredCategoryWidth"] = num(category_width)
        cat_props["innerPadding"] = num(30, "L")
    if scalar:
        cat_props["axisType"] = txt("Scalar")
    obj = {"categoryAxis": [{"properties": cat_props}],
           "valueAxis": [{"properties": {"show": lit("true" if column else "false"), "switchAxisPosition": lit("true"), "showAxisTitle": lit("false"),
                                         "labelColor": color(INK3), "fontSize": num(axis_size), "fontFamily": txt(F_REG),
                                         "gridlineShow": lit("true" if column else "false"), "gridlineColor": color(LINE),
                                         "gridlineStyle": txt("dashed")}}],
           "labels": [{"properties": {"show": lit("true" if labels else "false"), "color": color(INK2), "fontSize": num(9),
                                      "fontFamily": txt(F_REG), "labelDisplayUnits": num(1)}}],
           "legend": [{"properties": {"show": lit("false")}}],
           "dataPoint": [{"properties": {"fill": color_by(color_measure)},
                          "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]}
    return {"visualType": "clusteredColumnChart" if column else "clusteredBarChart",
            "query": {"queryState": {"Category": {"projections": [proj(category, cat_label, active=True)]},
                                     "Y": {"projections": [proj(m(measure), label)]}},
                      "sortDefinition": {"sort": [{"field": sort[0], "direction": sort[1]}]}},
            "objects": obj, "visualContainerObjects": cont or container(panel=True)}


def slicer_filter(entity: str, prop: str, value: str) -> dict:
    return {"filter": {"Version": 2, "From": [{"Name": "s", "Entity": entity, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": prop}}],
                                                       "Values": [[{"Literal": {"Value": "'" + value.replace("'", "''") + "'"}}]]}}}]}}


F_DIN = "DIN, 'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif"


def buttons(field: dict, label: str, columns: int, default: Optional[tuple] = None, size: str = "10.0") -> dict:
    """Button slicer, copied from Marine Energy Screen's working period buttons (text verified on screen).
    The inner padding block matters: without it the default padding pushes the text out of a 32-36 px button."""
    obj = {"selection": [{"properties": {"singleSelect": lit("true"), "strictSingleSelect": lit("true")}}],
           "layout": [{"properties": {"rowCount": num(1, "L"), "columnCount": num(columns, "L"), "cellPadding": num(3, "L")}}],
           "shapeCustomRectangle": [{"properties": {"rectangleRoundedCurve": num(4, "L")}, "selector": {"id": "default"}}],
           "value": [{"properties": {"fontFamily": txt(F_DIN), "fontSize": lit(f"{size}D"), "fontColor": color("#9AABBD"),
                                     "horizontalAlignment": txt("center")}, "selector": {"id": "default"}},
                     {"properties": {"fontColor": color(INK)}, "selector": {"id": "interaction:hover"}},
                     {"properties": {"fontColor": color(INK)}, "selector": {"id": "selection:selected"}}],
           "label": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
           "fillCustom": [{"properties": {"fillColor": color("#131B24"), "transparency": num(100)}, "selector": {"id": "default"}},
                          {"properties": {"fillColor": color("#1E2B38"), "transparency": num(0)}, "selector": {"id": "interaction:hover"}},
                          {"properties": {"fillColor": color(RAISED), "transparency": num(0)}, "selector": {"id": "selection:selected"}}],
           "outline": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}},
                       {"properties": {"show": lit("true"), "lineColor": color(LINE2), "weight": num(1)}, "selector": {"id": "selection:selected"}}],
           "accentBar": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
           "padding": [{"properties": {"paddingSelection": txt("Custom"), "topMargin": num(0, "L"), "bottomMargin": num(0, "L")},
                        "selector": {"id": "default"}}]}
    if default:
        obj["general"] = [{"properties": {"filter": slicer_filter(*default)}}]
    cont = container()
    cont["padding"] = [{"properties": {"top": num(3), "bottom": num(3), "left": num(3), "right": num(3)}}]
    return {"visualType": "advancedSlicerVisual", "query": {"queryState": {"Values": {"projections": [proj(field, label)]}}},
            "objects": obj, "visualContainerObjects": cont, "drillFilterOtherVisuals": True}


def classic_tiles(field: dict, label: str, default: Optional[tuple] = None) -> dict:
    """Classic slicer in tile mode (QA candidate for the field-parameter switch)."""
    obj = {"data": [{"properties": {"mode": txt("Basic")}}],
           "general": [{"properties": {"orientation": num(1)}}],
           "selection": [{"properties": {"singleSelect": lit("true"), "strictSingleSelect": lit("true"), "selectAllCheckboxEnabled": lit("false")}}],
           "header": [{"properties": {"show": lit("false")}}],
           "items": [{"properties": {"fontColor": color(INK), "background": color(SURFACE), "outline": txt("Frame"), "outlineColor": color(LINE2),
                                     "textSize": num(10), "fontFamily": txt(F_SEMIBOLD)}}]}
    if default:
        obj["general"][0]["properties"]["filter"] = slicer_filter(*default)
    return {"visualType": "slicer", "query": {"queryState": {"Values": {"projections": [proj(field, label)]}}},
            "objects": obj, "visualContainerObjects": container()}


def nav_button(label: str, target: Optional[str], active: bool = False, back: bool = False, size: str = "10.0") -> dict:
    """Page navigation / Back button, structured like Marine Energy Screen's working navigation buttons:
    text.show sits in an entry without a selector; colours sit under the default and hover states."""
    obj = {"icon": [{"properties": {"shapeType": txt("blank")}, "selector": {"id": "default"}}],
           "text": [{"properties": {"show": lit("true")}},
                    {"properties": {"text": txt(label), "fontColor": color(INK if (active or back) else "#9AABBD"), "fontSize": lit(f"{size}D"),
                                    "fontFamily": txt(F_SEMIBOLD if active else F_REG), "horizontalAlignment": txt("center")},
                     "selector": {"id": "default"}},
                    {"properties": {"fontColor": color(INK)}, "selector": {"id": "hover"}}]}
    if active or back:
        obj["fill"] = [{"properties": {"show": lit("true")}},
                       {"properties": {"fillColor": color(RAISED), "transparency": num(0)}, "selector": {"id": "default"}}]
        obj["outline"] = [{"properties": {"show": lit("true")}},
                          {"properties": {"lineColor": color(LINE2), "weight": num(1), "roundEdge": num(4)}, "selector": {"id": "default"}}]
    else:
        obj["fill"] = [{"properties": {"show": lit("false")}}]
        obj["outline"] = [{"properties": {"show": lit("false")}}]
    cont = container()
    cont["padding"] = [{"properties": {"top": num(0), "bottom": num(0), "left": num(0), "right": num(0)}}]
    if back:
        cont["visualLink"] = [{"properties": {"show": lit("true"), "type": txt("Back"), "tooltip": txt("Back to the previous page")}}]
    elif target and not active:
        cont["visualLink"] = [{"properties": {"show": lit("true"), "type": txt("PageNavigation"), "navigationSection": txt(target),
                                              "tooltip": txt(f"Go to {label}")}}]
    return {"visualType": "actionButton", "objects": obj, "visualContainerObjects": cont, "drillFilterOtherVisuals": True}


# ============================================================================ shared header
def header(p: Page, active: Optional[str], phone_y: int = 0) -> None:
    p.add("wordmark", 24, 18, 140, 36, textbox([[("FolioScreen", F_SEMIBOLD, 11, INK)]]), mobile=(0, phone_y, 180, 32))
    x = 176
    for key, label in PAGES.items():
        w = {"overview": 96, "holdings": 92, "performance": 118}[key]
        p.add(f"nav_{key}", x, 20, w, 32, nav_button(label, key, active=(key == active)))
        x += w + 4
    status = [("statusPrices", "Status Prices", "Status Prices Color", 668, 228),
              ("statusSync", "Status Sync", "Status Sync Color", 900, 250),
              ("statusIssues", "Status Issues", "Status Issues Color", 1156, 152)]
    for vname, meas, col, x, w in status:
        p.add(vname, x, 23, w, 28, card([(meas, "")], size=9, font=F_REG, label=False, colors={meas: col}))
    p.add("badge", 1316, 22, 100, 30, badge(), mobile=(220, phone_y + 2, 100, 30))
    p.add("statusPhone", 0, 0, 1, 1, card([("Status Phone", "")], size=9, font=F_REG, label=False,
                                          colors={"Status Phone": "Status Issues Color"}), mobile=(0, phone_y + 34, 320, 24))


def badge() -> dict:
    cont = container()
    cont["padding"] = [{"properties": {"top": num(3), "bottom": num(1), "left": num(2), "right": num(2)}}]
    return card([("Data Source Badge", "")], size=9, font=F_SEMIBOLD, label=False, cont=cont, align="right",
                colors={"Data Source Badge": "Badge Color"})


def title_card(measure: str, size: int = 10) -> dict:
    return card([(measure, "")], size=size, font=F_SEMIBOLD, label=False)


# ============================================================================ phone helpers
PHONE_PANEL = {"background": [{"properties": {"show": lit("true"), "color": color(SURFACE), "transparency": num(0)}}],
               "border": [{"properties": {"show": lit("true"), "color": color(LINE), "radius": num(12), "width": num(1)}}],
               "padding": [{"properties": {"top": num(8), "bottom": num(8), "left": num(12), "right": num(12)}}]}


def phone_font(size: int) -> dict:
    return {"value": [{"properties": {"fontSize": num(size)}, "selector": {"id": "default"}}]}


def card_row(p: Page, base: str, x: int, y: int, w: int, h: int, items: list, *, size: int = 15, colors: Optional[dict] = None,
             weights: Optional[list] = None, panel: bool = True, pad=(14, 20), phone: Optional[tuple] = None,
             phone_size: int = 14, phone_wide: tuple = ()) -> int:
    """One card per figure, side by side on a shared panel (desktop looks like one multi-value card).
    Separate cards let the phone layout arrange them two per row; the multi-value card cannot reflow (phone test).
    phone = (y0, row_height): returns the phone y after the last row."""
    if panel:
        p.add(f"{base}Panel", x, y, w, h, textbox([[(" ", F_REG, 8, SURFACE)]], container(panel=True)))
    weights = weights or [1] * len(items)
    inner_x, inner_w = x + pad[1], w - 2 * pad[1]
    cx = inner_x
    y_end = None
    slot = 0  # phone grid position: two per row, full-width items take a whole row
    for i, ((meas, label), wt) in enumerate(zip(items, weights)):
        cw = round(inner_w * wt / sum(weights))
        mob, mobj = None, None
        if phone:
            y0, rh = phone
            if meas in phone_wide:
                slot += slot % 2
                row = slot // 2
                mob = (0, y0 + row * rh, 320, rh - 6)
                slot += 2
            else:
                col, row = slot % 2, slot // 2
                mob = (col * 162, y0 + row * rh, 158, rh - 6)
                slot += 1
            mobj = dict(phone_font(phone_size))
            mobj["label"] = [{"properties": {"fontSize": num(8)}, "selector": {"id": "default"}}]
            y_end = y0 + ((slot + 1) // 2) * rh
        col_measure = (colors or {}).get(meas)
        p.add(f"{base}{i}", cx, y + pad[0], cw - 8, h - 2 * pad[0],
              card([(meas, label)], size=size, colors={meas: col_measure} if col_measure else None),
              mobile=mob, mobile_objects=mobj)
        if phone:
            p.mobile[f"{base}{i}"]["visualContainerObjects"] = PHONE_PANEL
        cx += cw
    return y_end or 0


# ============================================================================ pages
def page_overview() -> Page:
    p = Page("overview", "Overview")
    header(p, "overview")
    p.add("heroValue", 24, 64, 300, 82, card([("Portfolio Value", "Portfolio value")], size=30),
          mobile=(0, 64, 320, 64), mobile_objects=phone_font(24))
    p.add("heroToday", 344, 76, 236, 66, card([("Day Change Text", "Today")], colors={"Day Change Text": "Day Change Color"}),
          mobile=(0, 132, 320, 48), mobile_objects=phone_font(13))
    p.add("heroGain", 600, 76, 340, 66, card([("Total Gain Text", "Total gain on invested capital")], colors={"Total Gain Text": "Total Gain Color"}),
          mobile=(0, 182, 320, 48), mobile_objects=phone_font(13))
    fp = c(CHART_METRIC, CHART_METRIC)
    p.add("metricSwitch", 960, 106, 172, 36, buttons(c(CHART_METRIC, "Mode"), "Metric", 2, default=(CHART_METRIC, "Mode", "Value")),
          mobile=(0, 238, 320, 40))
    p.add("periodSwitch", 1148, 106, 268, 36, buttons(c("Periods", "Period"), "Period", 5, default=("Periods", "Period", "1Y")),
          mobile=(0, 530, 320, 40))
    p.add("heroChart", 24, 162, 944, 404, line_chart(
        c("Portfolio Daily", "Date"), [("Market value", "Market value")],
        [("Market value", PORTFOLIO), ("Portfolio return", PORTFOLIO), ("Benchmark return", BENCH)],
        field_parameter=fp, zero_line=False, tooltip=TIP), mobile=(0, 284, 320, 240))
    p.add("heroChartTitle", 40, 172, 600, 26, title_card("Hero Chart Title"), mobile=(8, 290, 300, 24))
    p.add("allocation", 984, 162, 432, 196, bar_chart(c("Holding Rows", "Symbol"), "Holding", "H Weight", "Share of value",
                                                     "Allocation Color", sort=(m("H Weight"), "Descending"),
                                                     cont=container("Allocation", panel=True)), mobile=(0, 840, 320, 220))
    p.add("movers", 984, 374, 432, 192, table(
        [(c("Holding Rows", "Symbol"), "Symbol"), (m("H Day %"), "Today"), (m("H Day $"), "Change")],
        right=("_Measures.H Day %", "_Measures.H Day $"), colors={"_Measures.H Day %": "H Day Color", "_Measures.H Day $": "H Day $ Color"},
        sort=(m("H Day %"), "Descending"), row_padding=2, cont=container("Today's movers", panel=True)), mobile=(0, 1068, 320, 220))
    card_row(p, "rail", 24, 582, 1392, 84, [
        ("Net Deposits", "Invested capital"), ("Unrealized Gain", "Unrealized gain"), ("Realized Gain", "Realized gain"),
        ("Dividends and Interest", "Dividends, interest"), ("Account Fees", "Fees"), ("TWR Since Start Signed", "Return since start"),
        ("Money Weighted Return", "Money-weighted p.a.")], phone=(576, 66))
    p.add("holdingsPreview", 24, 682, 1392, 194, table(
        [(c("Holding Rows", "Symbol"), "Symbol"), (c("Holding Rows", "Name"), "Name"), (m("H Units"), "Units"), (m("H Price"), "Price"),
         (m("H Value Securities"), "Value"), (m("H Weight Securities"), "Weight"), (m("H Weight Bar SVG Securities"), " "),
         (m("H Day %"), "Today"), (m("H Unrealized"), "Unrealized"), (m("H Return"), "Return"),
         (m("H Trend SVG"), "90-day trend"), (m("H Range SVG"), "52-week range")],
        right=tuple(f"_Measures.{n}" for n in ("H Units", "H Price", "H Value Securities", "H Weight Securities", "H Day %", "H Unrealized", "H Return")),
        colors={"_Measures.H Day %": "H Day Color", "_Measures.H Unrealized": "H Unrealized Color", "_Measures.H Return": "H Return Color"},
        sort=(m("H Value Securities"), "Descending"), row_padding=3, cont=container("Holdings", panel=True, pad=(8, 6, 16, 16))))
    p.add("toHoldings", 1288, 690, 116, 26, nav_button("All holdings →", "holdings", size="9.0"))
    return p


def page_holdings() -> Page:
    p = Page("holdings", "Holdings")
    header(p, "holdings")
    p.add("hSec", 24, 64, 260, 72, card([("H Value Securities", "Securities value")], size=21),
          mobile=(0, 64, 320, 60), mobile_objects=phone_font(20))
    card_row(p, "hSum", 300, 76, 820, 60, [("H Cash", "Cash"), ("H Unrealized", "Unrealized gain"), ("H Day $", "Today"), ("H Count", "Holdings")],
             colors={"H Unrealized": "H Unrealized Color", "H Day $": "H Day $ Color"}, panel=False, pad=(0, 0), phone=(128, 64))
    p.add("acctSwitch", 24, 148, 420, 36, buttons(c("Account Choice", "Choice"), "Account", 3, default=("Account Choice", "Choice", "All accounts")),
          mobile=(0, 260, 320, 40))
    p.add("typeSwitch", 468, 148, 470, 36, buttons(c("Type Choice", "Choice"), "Type", 5, default=("Type Choice", "Choice", "All types")),
          mobile=(0, 304, 320, 40))
    right_h = tuple(f"_Measures.{n}" for n in ("H Units", "H Avg Cost", "H Price", "H Value", "H Weight", "H Day %", "H Unrealized", "H Return"))
    colors_h = {"_Measures.H Day %": "H Day Color", "_Measures.H Unrealized": "H Unrealized Color", "_Measures.H Return": "H Return Color"}
    # phone-only compact table, placed behind the full table on desktop (hidden by its opaque panel)
    p.add("holdingsPhone", 40, 214, 600, 290, table(
        [(c("Holding Rows", "Symbol"), "Symbol"), (m("H Value"), "Value"), (m("H Day %"), "Today"), (m("H Weight"), "Weight")],
        right=("_Measures.H Value", "_Measures.H Day %", "_Measures.H Weight"), colors={"_Measures.H Day %": "H Day Color"},
        totals=True, sort=(m("H Value"), "Descending"), row_padding=8, cont=container(panel=True)), mobile=(0, 352, 320, 330))
    p.add("holdingsTable", 24, 194, 1392, 328, table(
        [(c("Holding Rows", "Symbol"), "Symbol"), (c("Holding Rows", "Name"), "Name"), (c("Holding Rows", "Kind"), "Type"),
         (m("H Units"), "Units"), (m("H Avg Cost"), "Avg cost"), (m("H Price"), "Price"), (m("H Value"), "Value"),
         (m("H Weight"), "Weight"), (m("H Weight Bar SVG"), " "), (m("H Day %"), "Today"), (m("H Unrealized"), "Unrealized"),
         (m("H Return"), "Return"), (m("H Trend SVG"), "90-day trend"), (m("H Range SVG"), "52-week range")],
        right=right_h, colors=colors_h, totals=True, sort=(m("H Value"), "Descending"), row_padding=9,
        cont=container(panel=True, pad=(8, 10, 16, 16))))
    p.add("accountsPhone", 40, 580, 360, 200, table(
        [(c("Account List", "Account"), "Account"), (m("Acct Value"), "Value"), (m("Acct Status"), "History")],
        right=("_Measures.Acct Value",), sort=(c("Account List", "Account"), "Ascending"),
        colors={"_Measures.Acct Status": "Acct Status Color"}, cont=container("Accounts", panel=True)), mobile=(0, 690, 320, 150))
    p.add("accounts", 24, 538, 408, 338, table(
        [(c("Account List", "Account"), "Account"), (m("Acct Value"), "Value"), (m("Acct Cash"), "Cash"), (m("Acct Holdings"), "Holdings"),
         (m("Acct Status"), "History")],
        right=("_Measures.Acct Value", "_Measures.Acct Cash", "_Measures.Acct Holdings"), sort=(c("Account List", "Account"), "Ascending"),
        colors={"_Measures.Acct Status": "Acct Status Color"}, cont=container("Accounts", panel=True)))
    p.add("activityPhone", 464, 560, 400, 280, table(
        [(c("Activity Log", "Date"), "Date"), (c("Activity Log", "Type"), "Type"), (m("Tx Amount"), "Amount")],
        right=("_Measures.Tx Amount",), sort=(c("Activity Log", "Date"), "Descending"), row_padding=6,
        cont=container("Recent activity", panel=True)), mobile=(0, 848, 320, 300))
    p.add("activity", 448, 538, 600, 338, table(
        [(c("Activity Log", "Date"), "Date"), (c("Activity Log", "Account"), "Account"), (c("Activity Log", "Type"), "Type"),
         (c("Activity Log", "Symbol"), "Symbol"), (c("Activity Log", "Detail"), "Detail"), (m("Tx Amount"), "Amount")],
        right=("_Measures.Tx Amount",), sort=(c("Activity Log", "Date"), "Descending"), row_padding=5,
        cont=container("Recent activity", panel=True)))
    p.add("quality", 1064, 538, 352, 338, table(
        [(m("Check Status"), " "), (c("Checks", "Check"), "Check"), (m("Check Detail"), "Detail")],
        colors={"_Measures.Check Status": "Check Color"}, sort=(c("Checks", "Check"), "Ascending"), row_padding=8,
        cont=container("Data quality", panel=True)), mobile=(0, 1156, 320, 260))
    p.add("qualityHeadline", 1236, 548, 170, 24, card([("Quality Headline", "")], size=9, font=F_REG, label=False,
                                                      colors={"Quality Headline": "Quality Headline Color"}, align="right"))
    return p


def page_performance() -> Page:
    p = Page("performance", "Performance")
    header(p, "performance")
    p.add("pTwr", 24, 64, 300, 72, card([("Window TWR", "Time-weighted return")], size=21, colors={"Window TWR": "Window TWR Color"}),
          mobile=(0, 108, 320, 56), mobile_objects=phone_font(20))
    card_row(p, "pFig", 340, 76, 620, 60, [("Window Benchmark", "Benchmark"), ("Window Difference", "Difference"),
                                          ("Money Weighted Return", "Money-weighted p.a.")],
             colors={"Window Difference": "Window Difference Color"}, panel=False, pad=(0, 0), phone=(168, 64))
    p.add("periodSwitch", 1148, 100, 268, 36, buttons(c("Periods", "Period"), "Period", 5, default=("Periods", "Period", "1Y")),
          mobile=(0, 64, 320, 40))
    p.add("perfChart", 24, 150, 904, 340, line_chart(
        c("Portfolio Daily", "Date"), [("Chart Return", "Portfolio"), ("Chart Benchmark", "Benchmark")],
        [("Chart Return", PORTFOLIO), ("Chart Benchmark", BENCH)], zero_line=True, tooltip=TIP), mobile=(0, 300, 320, 240))
    p.add("perfChartTitle", 40, 160, 600, 26, title_card("Perf Chart Title"), mobile=(8, 306, 300, 24))
    p.add("periodTable", 944, 150, 472, 340, table(
        [(c("Period Rows", "Label"), "Period"), (m("Row TWR"), "Portfolio"), (m("Row Benchmark"), "Benchmark"), (m("Row Difference"), "Difference")],
        right=("_Measures.Row TWR", "_Measures.Row Benchmark", "_Measures.Row Difference"),
        colors={"_Measures.Row TWR": "Row TWR Color", "_Measures.Row Difference": "Row Difference Color"}, back="Row Background",
        sort=(c("Period Rows", "Label"), "Ascending"), row_padding=11, cont=container("Returns by period", panel=True)),
        mobile=(0, 548, 320, 310))
    p.add("valueDeposits", 24, 506, 440, 370, line_chart(
        c("Portfolio Daily", "Date"), [("Chart Value", "Value"), ("Chart Deposits", "Net deposits")],
        [("Chart Value", PORTFOLIO), ("Chart Deposits", INK2)], cont=container("Value and net deposits", panel=True, pad=(12, 6, 14, 10))),
        mobile=(0, 866, 320, 230))
    p.add("contribution", 480, 506, 300, 370, table(
        [(c("Gain Breakdown", "Label"), "Source"), (m("Gain Bar SVG"), " "), (m("Gain Amount"), "Amount")],
        right=("_Measures.Gain Amount",), colors={"_Measures.Gain Amount": "Gain Amount Color"},
        sort=(c("Gain Breakdown", "Label"), "Ascending"), row_padding=8,
        cont=container("Contribution to gain, since start", panel=True)), mobile=(0, 1104, 320, 400))
    p.add("income", 796, 506, 300, 370, bar_chart(c("Income Months", "MonthStart"), "Month", "Income Amount", "Income", "Income Color",
                                                 sort=(c("Income Months", "MonthStart"), "Ascending"), column=True, labels=False,
                                                 scalar=True, cont=container("Income, last 12 months", panel=True)),
          mobile=(0, 1512, 320, 220))
    p.add("risk1", 1112, 506, 304, 115, card([("Window Max Drawdown", "Largest fall"), ("Window Volatility", "Volatility, a year")],
                                             cont=container(panel=True)), mobile=(0, 1740, 320, 76))
    p.add("risk2", 1112, 629, 304, 115, card([("Window Best Day", "Best day"), ("Window Worst Day", "Worst day")],
                                             cont=container(panel=True)), mobile=(0, 1824, 320, 76))
    p.add("concentration", 1112, 752, 304, 124, card([("Largest Holding Weight", "Largest holding"), ("Effective Holdings", "Effective holdings")],
                                                     cont=container(panel=True)), mobile=(0, 1908, 320, 76))
    return p


def page_detail() -> Page:
    flt = {"filters": [{"name": "detailSymbol", "field": c("Holding Rows", "Symbol"), "type": "Categorical", "howCreated": "Drillthrough"}]}
    p = Page(DETAIL, "Security detail", type="Drillthrough", visibility="HiddenInViewMode", filterConfig=flt,
             pageBinding={"name": "detailBinding", "type": "Drillthrough", "acceptsFilterContext": "None",
                          "parameters": [{"name": "detailParam", "boundFilter": "detailSymbol"}]})
    p.add("back", 24, 20, 112, 32, nav_button("← Back", None, back=True), mobile=(0, 0, 100, 36))
    p.add("dSymbol", 152, 16, 180, 40, card([("D Symbol", "")], size=15, font=F_SEMIBOLD, label=False), mobile=(0, 44, 320, 32))
    p.add("dSubtitle", 336, 22, 640, 30, card([("D Subtitle", "")], size=10, font=F_REG, label=False), mobile=(0, 76, 320, 30))
    p.add("statusPrices", 1064, 23, 236, 28, card([("Status Prices", "")], size=9, font=F_REG, label=False, colors={"Status Prices": "Status Prices Color"}))
    p.add("badge", 1316, 22, 100, 30, badge())
    p.add("dPrice", 24, 66, 220, 80, card([("H Price", "Price")], size=30), mobile=(0, 110, 320, 60), mobile_objects=phone_font(22))
    card_row(p, "dFig", 252, 82, 1164, 62, [("H Day %", "Today"), ("H Value", "Value"), ("H Weight", "Share of portfolio"), ("H Units", "Units"),
                                           ("H Avg Cost", "Average cost"), ("H Unrealized Text", "Unrealized gain"), ("D Range Text", "52-week range")],
             size=13, colors={"H Day %": "H Day Color", "H Unrealized Text": "H Unrealized Color"},
             weights=[0.9, 1, 1, 0.7, 0.95, 1.6, 1.3], panel=False, pad=(0, 0), phone=(174, 62), phone_size=13,
             phone_wide=("H Unrealized Text", "D Range Text"))
    p.add("dChart", 24, 162, 944, 424, line_chart(
        c("Price History", "Date"), [("D Close", "Close, split-adjusted"), ("D Average Cost", "Average cost")],
        [("D Close", PORTFOLIO), ("D Average Cost", BENCH)]), mobile=(0, 498, 320, 240))
    p.add("dChartTitle", 40, 172, 700, 26, title_card("D Chart Title"), mobile=(8, 504, 300, 24),
          mobile_objects=phone_font(9))
    p.add("dTxPhone", 1000, 210, 400, 200, table(
        [(c("Activity Log", "Date"), "Date"), (c("Activity Log", "Type"), "Type"), (m("D Tx Amount"), "Amount")],
        right=("_Measures.D Tx Amount",), sort=(c("Activity Log", "Date"), "Descending"), cont=container("Transactions", panel=True)),
        mobile=(0, 746, 320, 200))
    p.add("dTx", 984, 162, 432, 268, table(
        [(c("Activity Log", "Date"), "Date"), (c("Activity Log", "Type"), "Type"), (c("Activity Log", "Detail"), "Detail"), (m("D Tx Amount"), "Amount")],
        right=("_Measures.D Tx Amount",), sort=(c("Activity Log", "Date"), "Descending"), cont=container("Transactions", panel=True)))
    p.add("dHeld", 984, 446, 432, 140, table(
        [(c("Holding Rows", "AccountLabel"), "Account"), (m("H Units"), "Units"), (m("H Value"), "Value")],
        right=("_Measures.H Units", "_Measures.H Value"), cont=container("Held in", panel=True)), mobile=(0, 954, 320, 120))
    y = card_row(p, "dRet", 24, 602, 600, 120, [("H Return", "On cost basis"), ("D Price Change 12M", "Price, 12 months"),
                                               ("D Contribution", "Contribution"), ("D Share Of Gain", "Share of gain")],
                 size=13, colors={"H Return": "H Return Color"}, phone=(1082, 66), phone_size=13)
    p.add("dIncome", 640, 602, 220, 120, card([("D Dividends", "Dividends received")], size=13, cont=container(panel=True)),
          mobile=(0, y, 320, 66))
    card_row(p, "dData", 876, 602, 540, 120, [("D Units Reported", "Units at broker"), ("D Units Rebuilt", "Units rebuilt"),
                                              ("D Last Close Date", "Latest close"), ("D Corporate Actions", "Splits and actions")],
             size=13, phone=(y + 72, 66), phone_size=13)
    p.add("dNote", 24, 738, 1392, 40, textbox([[("Average cost is per current unit. The chart adjusts closes before a split so the line is continuous; "
                                                 "values and gains always use the price actually traded.", F_REG, 9, INK3)]]))
    return p


def page_tooltip() -> Page:
    p = Page(TIP, "Chart tooltip", width=360, height=150, displayOption="ActualSize", type="Tooltip",
             pageBinding={"name": "chartTipBinding", "type": "Tooltip"}, visibility="HiddenInViewMode", bg=RAISED)
    p.add("tipA", 14, 12, 332, 60, card([("Tooltip Date", "Date"), ("Tooltip Value", "Value")], size=12))
    p.add("tipB", 14, 78, 332, 60, card([("Chart Return", "Portfolio"), ("Chart Benchmark", "Benchmark")], size=12,
                                         colors={"Chart Return": "Tip Return Color"}))
    return p


def page_qa() -> Page:
    """Temporary: confirms the corrected button slicer shows its text; a classic tile slicer is the fallback."""
    p = Page(QA, "QA · switch", height=320)
    p.add("qaNote", 24, 18, 1392, 44, textbox([[("Temporary QA page. ", F_SEMIBOLD, 10, INK),
                                                 ("Do the buttons in A show 1M 3M 6M 1Y ALL? B is the fallback. This page is removed afterwards.",
                                                  F_REG, 10, INK2)]]))
    rows = [("A · button slicer, Marine Energy Screen structure", buttons(c("Periods", "Period"), "Period", 5, default=("Periods", "Period", "1Y"))),
            ("B · classic slicer, tiles", classic_tiles(c("Periods", "Period"), "Period"))]
    for i, (label, vis) in enumerate(rows):
        y = 80 + i * 100
        p.add(f"qaLabel{i}", 24, y, 520, 30, textbox([[(label, F_SEMIBOLD, 10, INK)]]))
        p.add(f"qaSwitch{i}", 24, y + 34, 268, 36, vis)
    return p


ALL_PAGES = (page_overview, page_holdings, page_performance, page_detail, page_tooltip)

THEME = {
    "name": "FolioScreen Night",
    "dataColors": [PORTFOLIO, BENCH, INK2, GAIN, LOSS, CAUTION, "#B69CFF", "#4FD1C5"],
    "background": GROUND, "foreground": INK, "tableAccent": PORTFOLIO, "good": GAIN, "neutral": INK2, "bad": LOSS,
    "maximum": PORTFOLIO, "center": INK3, "minimum": LINE2,
    "textClasses": {"callout": {"fontSize": 24, "fontFace": F_LIGHT, "color": INK},
                    "title": {"fontSize": 10, "fontFace": F_SEMIBOLD, "color": INK},
                    "header": {"fontSize": 10, "fontFace": F_SEMIBOLD, "color": INK},
                    "label": {"fontSize": 9, "fontFace": F_REG, "color": INK3}},
    "visualStyles": {"*": {"*": {"visualHeader": [{"show": False}],
                                 "visualTooltip": [{"background": {"solid": {"color": RAISED}},
                                                    "titleFontColor": {"solid": {"color": INK3}},
                                                    "valueFontColor": {"solid": {"color": INK}}}]}},
                     "page": {"*": {"background": [{"color": {"solid": {"color": GROUND}}, "transparency": 0}],
                                    "outspace": [{"color": {"solid": {"color": GROUND}}, "transparency": 0}]}}},
}


def render_full_report(name: str = PROJECT) -> dict:
    files = {}
    files["definition.pbir"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}}, indent=2) + "\n"
    files[".platform"] = _platform("Report", name)
    files["definition/version.json"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"}, indent=2) + "\n"
    files["definition/report.json"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY26SU05", "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"},
                          "type": "SharedResources"},
            "customTheme": {"name": "FolioScreenNight.json", "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"},
                            "type": "RegisteredResources"}},
        "objects": {"outspacePane": [{"properties": {"expanded": lit("false")}}]},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources", "items": [{"name": "CY26SU05", "path": "BaseThemes/CY26SU05.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "FolioScreenNight.json", "path": "FolioScreenNight.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized", "defaultDrillFilterOtherVisuals": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}}, indent=2) + "\n"
    files["StaticResources/RegisteredResources/FolioScreenNight.json"] = json.dumps(THEME, indent=2) + "\n"
    pages = [f() for f in ALL_PAGES]
    files["definition/pages/pages.json"] = json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": "overview"}, indent=2) + "\n"
    for p in pages:
        files[f"definition/pages/{p.name}/page.json"] = json.dumps(p.page_json(), indent=2) + "\n"
        for v in p.visuals:
            files[f"definition/pages/{p.name}/visuals/{v['name']}/visual.json"] = json.dumps(v, indent=2) + "\n"
        for vname, mob in p.mobile.items():
            files[f"definition/pages/{p.name}/visuals/{vname}/mobile.json"] = json.dumps(mob, indent=2) + "\n"
    return files
