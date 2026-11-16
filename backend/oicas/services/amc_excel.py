"""How Excel draws a sheet, for the AMC Import viewer.

Reads what openpyxl's read-only mode does not expose (sheet XML: column widths, row heights, hidden rows and
columns, frozen panes, gridlines, AutoFilter, merged cells, conditional formatting) and turns cell styles (font, fill,
borders, alignment) into CSS. Borders are resolved like Excel shows them: a line between two cells is drawn once,
as the right / bottom edge of the cell before it, so the grid can use ``border-collapse: separate`` and keep its
lines on frozen (sticky) rows and columns.
"""
from __future__ import annotations

import datetime as _dt
import html
import re
from dataclasses import dataclass, field

from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils import column_index_from_string, range_boundaries

THEME_ORDER = ("lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
               "hlink", "folHlink")  # theme colour index -> clrScheme entry, as Excel maps it
MDW = 7  # maximum digit width (px) of Calibri 11, the Normal font: Excel column width units -> pixels
DEFAULT_COL_PX = 64
DEFAULT_ROW_PT = 15.0
BORDER_CSS = {"thin": "1px solid", "hair": "1px dotted", "dotted": "1px dotted", "dashed": "1px dashed",
              "dashDot": "1px dashed", "dashDotDot": "1px dotted", "medium": "2px solid", "mediumDashed": "2px dashed",
              "mediumDashDot": "2px dashed", "mediumDashDotDot": "2px dotted", "slantDashDot": "2px dashed",
              "thick": "3px solid", "double": "3px double"}
FONT_STACK = {"calibri": "Calibri, Carlito, 'Segoe UI', Arial, sans-serif",
              "calibri light": "'Calibri Light', Calibri, Carlito, Arial, sans-serif",
              "arial": "Arial, Helvetica, sans-serif", "cambria": "Cambria, Caladea, Georgia, serif",
              "times new roman": "'Times New Roman', Times, serif", "tahoma": "Tahoma, Verdana, sans-serif",
              "verdana": "Verdana, sans-serif", "segoe ui": "'Segoe UI', Arial, sans-serif"}
V_ALIGN = {"top": "top", "center": "middle", "bottom": "bottom", "justify": "middle", "distributed": "middle"}
H_ALIGN = {"left": "left", "center": "center", "right": "right", "justify": "justify", "distributed": "center",
           "centerContinuous": "center", "fill": "left"}
ERRORS = {"#N/A", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!", "#SPILL!", "#CALC!"}


def pt_px(pt: float) -> int:
    return round(pt * 96 / 72)


def width_px(w: float) -> int:
    return max(0, round(w * MDW))


# ------------------------------------------------------------------ colours
def tint(hex6: str, t: float) -> str:
    rgb = [int(hex6[i:i + 2], 16) for i in (0, 2, 4)]
    if t < 0:
        rgb = [round(c * (1 + t)) for c in rgb]
    elif t > 0:
        rgb = [round(c + (255 - c) * t) for c in rgb]
    return "#" + "".join(f"{max(0, min(255, c)):02X}" for c in rgb)


def theme_colors(theme_xml) -> dict[int, str]:
    if not theme_xml:
        return {}
    if isinstance(theme_xml, bytes):
        theme_xml = theme_xml.decode("utf-8", "replace")
    out = {}
    for i, key in enumerate(THEME_ORDER):
        m = re.search(rf"<a:{key}>.*?(?:lastClr|val)=\"([0-9A-Fa-f]{{6}})\"", theme_xml, re.S)
        if m:
            out[i] = m.group(1).upper()
    return out


def color(c, theme: dict[int, str]) -> str | None:
    """openpyxl Color -> '#RRGGBB' (None = automatic / not set)."""
    if c is None:
        return None
    try:
        kind = c.type
        if kind == "rgb":
            v = c.rgb
            if not isinstance(v, str) or len(v) < 6:
                return None
            base = v[-6:].upper()
        elif kind == "theme":
            base = theme.get(c.theme)
        elif kind == "indexed":
            idx = c.indexed
            base = COLOR_INDEX[idx][-6:] if idx is not None and idx < len(COLOR_INDEX) else None
        else:
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    if not base:
        return None
    return tint(base, float(c.tint or 0)) if getattr(c, "tint", 0) else "#" + base


# ------------------------------------------------------------------ sheet XML
@dataclass
class SheetLayout:
    merges: list[list[int]] = field(default_factory=list)
    col_widths: dict[int, float] = field(default_factory=dict)  # 1-based col -> Excel width units
    hidden_cols: set[int] = field(default_factory=set)
    default_col_w: float | None = None
    default_row_pt: float = DEFAULT_ROW_PT
    row_pt: dict[int, float] = field(default_factory=dict)
    hidden_rows: set[int] = field(default_factory=set)
    grid: bool = True
    freeze_rows: int = 0
    freeze_cols: int = 0
    filter: list[int] | None = None  # [r1, c1, r2, c2]
    filter_cols: set[int] = field(default_factory=set)  # columns with an active filter
    cf: list[tuple[list[list[int]], list[dict]]] = field(default_factory=list)  # (ranges, rules by priority)


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def _formula_const(f: str):
    f = html.unescape(f.strip())
    if len(f) >= 2 and f[0] == f[-1] == '"':
        return f[1:-1].replace('""', '"')
    try:
        return float(f)
    except ValueError:
        return f.upper() if f.upper() in ("TRUE", "FALSE") else None  # formulas we cannot evaluate


def read_sheet_xml(xml: str) -> SheetLayout:
    lay = SheetLayout()
    lay.merges = [list(range_boundaries(ref)) for ref in re.findall(r'<mergeCell\b[^>]*\bref="([A-Z]+\d+:[A-Z]+\d+)"', xml)]
    lay.merges = [[r1, c1, r2, c2] for c1, r1, c2, r2 in lay.merges]
    fmt = re.search(r"<sheetFormatPr\b[^>]*>", xml)
    if fmt:
        if _attr(fmt.group(0), "defaultColWidth"):
            lay.default_col_w = float(_attr(fmt.group(0), "defaultColWidth"))
        elif _attr(fmt.group(0), "baseColWidth"):
            lay.default_col_w = int(_attr(fmt.group(0), "baseColWidth")) + 5 / MDW
        if _attr(fmt.group(0), "defaultRowHeight"):
            lay.default_row_pt = float(_attr(fmt.group(0), "defaultRowHeight"))
    for tag in re.findall(r"<col\b[^>]*/?>", xml):
        lo, hi = int(_attr(tag, "min") or 0), int(_attr(tag, "max") or 0)
        w, hid = _attr(tag, "width"), _attr(tag, "hidden") in ("1", "true")
        for c in range(lo, min(hi, 16384) + 1):
            if w is not None:
                lay.col_widths[c] = float(w)
            if hid:
                lay.hidden_cols.add(c)
    for r, attrs in re.findall(r'<row\b[^>]*?\br="(\d+)"([^>]*)>', xml):
        ht = _attr(attrs, "ht")
        if ht:
            lay.row_pt[int(r)] = float(ht)
        if _attr(attrs, "hidden") in ("1", "true"):
            lay.hidden_rows.add(int(r))
    view = re.search(r"<sheetView\b[^>]*>", xml)
    if view and _attr(view.group(0), "showGridLines") in ("0", "false"):
        lay.grid = False
    pane = re.search(r"<pane\b[^>]*/?>", xml)
    if pane and _attr(pane.group(0), "state") in ("frozen", "frozenSplit"):
        lay.freeze_rows = int(float(_attr(pane.group(0), "ySplit") or 0))
        lay.freeze_cols = int(float(_attr(pane.group(0), "xSplit") or 0))
    af = re.search(r"<autoFilter\b([^>]*?)(/>|>(.*?)</autoFilter>)", xml, re.S)
    if af and _attr(af.group(1), "ref"):
        try:
            c1, r1, c2, r2 = range_boundaries(_attr(af.group(1), "ref"))
            lay.filter = [r1, c1, r2, c2]
            for col_id in re.findall(r'<filterColumn\b[^>]*\bcolId="(\d+)"', af.group(3) or ""):
                lay.filter_cols.add(c1 + int(col_id))
        except (ValueError, TypeError):
            pass
    for sqref, body in re.findall(r'<conditionalFormatting\b[^>]*\bsqref="([^"]*)"[^>]*>(.*?)</conditionalFormatting>',
                                  xml, re.S):
        ranges = []
        for ref in sqref.split():
            try:
                c1, r1, c2, r2 = range_boundaries(ref if ":" in ref else f"{ref}:{ref}")
                ranges.append([r1, c1, r2, c2])
            except (ValueError, TypeError):
                continue
        rules = []
        for attrs, inner in re.findall(r"<cfRule\b([^>]*?)(?:/>|>(.*?)</cfRule>)", body, re.S):
            if _attr(attrs, "type") != "cellIs" or _attr(attrs, "dxfId") is None:
                continue  # only "cell value is …" rules (all the AMC workbook uses)
            consts = [_formula_const(f) for f in re.findall(r"<formula>(.*?)</formula>", inner or "", re.S)]
            if not consts or any(c is None for c in consts):
                continue
            rules.append({"op": _attr(attrs, "operator") or "equal", "args": consts, "dxf": int(_attr(attrs, "dxfId")),
                          "prio": int(_attr(attrs, "priority") or 0), "stop": _attr(attrs, "stopIfTrue") == "1"})
        if ranges and rules:
            lay.cf.append((ranges, sorted(rules, key=lambda r: r["prio"])))
    return lay


def cf_matches(rule: dict, value) -> bool:
    """Excel 'Cell value is …' on a cached value (blank counts as 0 against numbers and "" against text)."""
    args = rule["args"]
    a = args[0]
    if isinstance(a, float):
        if value is None or value == "":
            v = 0.0
        elif isinstance(value, bool):
            return False
        elif isinstance(value, (int, float)):
            v = float(value)
        else:
            return rule["op"] == "notEqual"
    else:
        v = "" if value is None else str(value).upper() if not isinstance(value, (int, float)) else None
        if v is None:
            return rule["op"] == "notEqual"
        args = [str(x).upper() for x in args]
        a = args[0]
    op = rule["op"]
    try:
        if op == "equal":
            return v == a
        if op == "notEqual":
            return v != a
        if op == "greaterThan":
            return v > a
        if op == "lessThan":
            return v < a
        if op == "greaterThanOrEqual":
            return v >= a
        if op == "lessThanOrEqual":
            return v <= a
        if op in ("between", "notBetween") and len(args) > 1:
            lo, hi = sorted(args[:2])
            inside = lo <= v <= hi
            return inside if op == "between" else not inside
    except TypeError:
        return False
    return False


# ------------------------------------------------------------------ styles -> CSS
class Styler:
    """CSS for openpyxl style ids of one workbook, cached."""

    def __init__(self, wb, theme: dict[int, str]):
        self.wb, self.theme = wb, theme
        self._base: dict[tuple, dict] = {}
        self._borders: dict[int, tuple[str, str, str, str]] = {}
        self._dxf: dict[int, dict] = {}

    def _array(self, sid: int):
        try:
            return self.wb._cell_styles[sid]
        except (IndexError, TypeError):
            return self.wb._cell_styles[0] if len(self.wb._cell_styles) else None

    def font_css(self, font) -> dict:
        css = {}
        if font is None:
            return css
        name = re.sub(r"[^\w \-]", "", font.name or "Calibri").strip() or "Calibri"  # it ends up inside CSS
        css["font-family"] = FONT_STACK.get(name.lower(), f"'{name}', Calibri, Arial, sans-serif")
        css["font-size"] = f"{float(font.sz or 11):g}pt"
        css["font-weight"] = "700" if font.b else "400"
        if font.i:
            css["font-style"] = "italic"
        deco = (["underline"] if font.u else []) + (["line-through"] if font.strike else [])
        if deco:
            css["text-decoration"] = " ".join(deco)
        col = color(font.color, self.theme)
        if col:
            css["color"] = col
        return css

    def base(self, sid: int, kind: str) -> dict:
        """Font, fill and alignment. ``kind``: n number, t text, b boolean, x error, e empty."""
        key = (sid, kind)
        if key in self._base:
            return self._base[key]
        sa = self._array(sid)
        css: dict[str, str] = {}
        if sa is not None:
            wb = self.wb
            css.update(self.font_css(wb._fonts[sa.fontId] if sa.fontId < len(wb._fonts) else None))
            fill = wb._fills[sa.fillId] if sa.fillId < len(wb._fills) else None
            if fill is not None and getattr(fill, "fill_type", None) not in (None, "none"):
                bg = color(fill.fgColor, self.theme) or color(getattr(fill, "bgColor", None), self.theme)
                if bg:
                    css["background-color"] = bg
            al = wb._alignments[sa.alignmentId] if sa.alignmentId < len(wb._alignments) else None
            h = al.horizontal if al is not None else None
            css["text-align"] = H_ALIGN.get(h) or {"n": "right", "b": "center", "x": "center"}.get(kind, "left")
            css["vertical-align"] = V_ALIGN.get(al.vertical if al is not None else None, "bottom")
            if al is not None and al.wrap_text:
                css["white-space"] = "pre-wrap"
                css["overflow-wrap"] = "anywhere"
            if al is not None and al.indent:
                css["padding-left"] = f"{3 + int(al.indent) * 9}px"
        self._base[key] = css
        return css

    def borders(self, sid: int) -> tuple[str, str, str, str]:
        """(left, right, top, bottom) as CSS border values ('' = none)."""
        if sid in self._borders:
            return self._borders[sid]
        out = ("", "", "", "")
        sa = self._array(sid)
        if sa is not None and sa.borderId < len(self.wb._borders):
            b = self.wb._borders[sa.borderId]

            def side(s):
                if s is None or not s.style or s.style not in BORDER_CSS:
                    return ""
                return f"{BORDER_CSS[s.style]} {color(s.color, self.theme) or '#000000'}"
            out = (side(b.left), side(b.right), side(b.top), side(b.bottom))
        self._borders[sid] = out
        return out

    def dxf(self, i: int) -> dict:
        if i in self._dxf:
            return self._dxf[i]
        css: dict[str, str] = {}
        try:
            d = self.wb._differential_styles[i]
        except (IndexError, TypeError, KeyError):
            d = None
        if d is not None:
            f = d.fill
            if f is not None:
                bg = color(getattr(f, "bgColor", None), self.theme) or color(getattr(f, "fgColor", None), self.theme)
                if bg and getattr(f, "fill_type", "solid") not in ("none",):
                    css["background-color"] = bg
            if d.font is not None:
                if d.font.b is not None:
                    css["font-weight"] = "700" if d.font.b else "400"
                if d.font.i:
                    css["font-style"] = "italic"
                col = color(d.font.color, self.theme)
                if col:
                    css["color"] = col
        self._dxf[i] = css
        return css


def css_text(props: dict) -> str:
    return ";".join(f"{k}:{v}" for k, v in props.items())


def value_kind(v) -> str:
    if v is None or v == "":
        return "e"
    if isinstance(v, bool):
        return "b"
    if isinstance(v, (int, float, _dt.date, _dt.time, _dt.timedelta)):
        return "n"  # Excel stores dates and times as numbers: right-aligned by default
    if isinstance(v, str) and v in ERRORS:
        return "x"
    return "t"


def col_index(letters: str) -> int:
    return column_index_from_string(letters)
