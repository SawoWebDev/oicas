"""AMC Import: keep uploaded copies of the AMC / ABC Analysis workbook ("03_AMC Sep-Jul  ABC Analysis.xlsx").

Each upload is a session: the original file (for download, byte for byte) plus a display copy of every visible
sheet, with cell values formatted the way Excel shows them (number formats ``0``, ``0.00%``, ``#,##0``, General…)
and merged cells. Hidden sheets (raw Odoo exports, pivot caches) stay in the original file only, as in Excel.

The display copy is read with cached values (``data_only``): the workbook must have been saved by Excel.
"""
from __future__ import annotations

import hashlib
import html
import io
import re
import zipfile
from datetime import date, datetime, time

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AmcImport, AmcImportSheet, User
from . import amc_excel, audit

MAX_BYTES = 30 * 1024 * 1024
MAX_ROWS = 50_000  # per visible sheet (the reference workbook's largest visible sheet has 7,445)
MAX_COLS = 200
PAGE_SIZE = 200


class AmcImportError(Exception):
    pass


# ------------------------------------------------------------------ Excel-like value formatting
_DEC = re.compile(r"0\.(0+)")


def _clean_format(fmt: str) -> str:
    """First section of a number format, without literals, colours and conditions."""
    fmt = (fmt or "General").split(";")[0]
    fmt = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", fmt)
    return fmt.strip()


def format_value(v, number_format: str | None = "General") -> str:
    """Show a cell value as Excel would for the common formats in the AMC workbook."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, datetime):
        return v.strftime("%d-%m-%Y %H:%M") if v.time() != time(0) else v.strftime("%d-%m-%Y")
    if isinstance(v, date):
        return v.strftime("%d-%m-%Y")
    if isinstance(v, (int, float)):
        fmt = _clean_format(number_format or "General")
        if fmt.lower() in ("general", "@", ""):
            if isinstance(v, int) or float(v).is_integer():
                return str(int(v))
            return f"{v:.10g}"
        m = _DEC.search(fmt)
        dec = len(m.group(1)) if m else 0
        pct = "%" in fmt
        val = v * 100 if pct else v
        sep = "," if "," in fmt else ""
        text = f"{val:{sep}.{dec}f}"
        if text in ("-0", "-0.0") or re.fullmatch(r"-0\.0+", text):
            text = text[1:]
        return text + ("%" if pct else "")
    return str(v)


NUMERIC = re.compile(r"-?[\d,]*\.?\d+%?")


def is_numeric(text: str) -> bool:
    return bool(text) and bool(NUMERIC.fullmatch(text))


# ------------------------------------------------------------------ parsing
def _merges(data: bytes, sheet_path: str | None) -> list[str]:
    """Merged ranges of a sheet, read from its XML (read-only mode does not expose them)."""
    if not sheet_path:
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read(sheet_path.lstrip("/")).decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile):
        return []
    return re.findall(r'<mergeCell[^>]*\bref="([A-Z]+\d+:[A-Z]+\d+)"', xml)


def _header_row(filter_ref: str | None, rows: list[list[str]]) -> int:
    """1-based row holding the column titles: the AutoFilter row when there is one, else the first text row."""
    if filter_ref:
        try:
            _, r1, _, _ = range_boundaries(filter_ref)
            if r1 and r1 <= len(rows):
                return r1
        except ValueError:
            pass
    for i, row in enumerate(rows[:30], start=1):
        texts = [c for c in row if c and not is_numeric(c)]
        if len(texts) >= 3:
            return i
    return 0


def active_sheet_name(data: bytes) -> str | None:
    """Name of the sheet Excel opens on (the tab that was active when the file was saved)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("xl/workbook.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile):
        return None
    m = re.search(r'<workbookView\b[^>]*\bactiveTab="(\d+)"', xml)
    names = [html.unescape(n) for n in re.findall(r'<sheet\b[^>]*\bname="([^"]*)"', xml)]
    idx = int(m.group(1)) if m else 0
    return names[idx] if idx < len(names) else None


_THEME_ORDER = ("lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
                "hlink", "folHlink")  # theme colour index -> clrScheme entry, as Excel maps it


def _tint(hex6: str, tint: float) -> str:
    rgb = [int(hex6[i:i + 2], 16) for i in (0, 2, 4)]
    if tint < 0:
        rgb = [round(c * (1 + tint)) for c in rgb]
    elif tint > 0:
        rgb = [round(c + (255 - c) * tint) for c in rgb]
    return "#" + "".join(f"{max(0, min(255, c)):02X}" for c in rgb)


def tab_colors(data: bytes) -> dict[str, str]:
    """Sheet-tab colours by sheet name, as ``#RRGGBB`` (sheets without a colour are left out)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        wbx = z.read("xl/workbook.xml").decode("utf-8", "replace")
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile):
        return {}
    with z:
        targets = {}
        for rel in re.findall(r"<Relationship\b[^>]*>", rels):
            rid, tgt = re.search(r'\bId="([^"]+)"', rel), re.search(r'\bTarget="([^"]+)"', rel)
            if rid and tgt:
                t = tgt.group(1)
                targets[rid.group(1)] = t.lstrip("/") if t.startswith("/") else "xl/" + t
        theme: dict[int, str] = {}
        try:
            scheme = z.read("xl/theme/theme1.xml").decode("utf-8", "replace")
            for i, key in enumerate(_THEME_ORDER):
                m = re.search(rf"<a:{key}>.*?(?:val|lastClr)=\"([0-9A-Fa-f]{{6}})\"", scheme, re.S)
                if m:
                    theme[i] = m.group(1).upper()
        except KeyError:
            pass
        out = {}
        for attrs in re.findall(r"<sheet\b([^>]*)/?>", wbx):
            name, rid = re.search(r'\bname="([^"]*)"', attrs), re.search(r'\br:id="([^"]*)"', attrs)
            if not (name and rid) or rid.group(1) not in targets:
                continue
            try:
                head = z.read(targets[rid.group(1)]).decode("utf-8", "replace")[:4000]
            except KeyError:
                continue
            m = re.search(r"<tabColor\b([^>]*)/?>", head)
            if not m:
                continue
            a = m.group(1)
            rgb, th = re.search(r'\brgb="([0-9A-Fa-f]{6,8})"', a), re.search(r'\btheme="(\d+)"', a)
            tint = re.search(r'\btint="(-?[\d.Ee-]+)"', a)
            base = rgb.group(1)[-6:].upper() if rgb else theme.get(int(th.group(1))) if th else None
            if base:
                out[html.unescape(name.group(1))] = _tint(base, float(tint.group(1)) if tint else 0.0)
        return out


def active_position(data: bytes, sheet_names: list[str]) -> int:
    """Position (among the visible sheets kept for viewing) of Excel's active sheet; the first one otherwise."""
    name = active_sheet_name(data)
    return sheet_names.index(name) if name in sheet_names else 0


def _sheet_paths(z: zipfile.ZipFile) -> dict[str, str]:
    """Sheet name -> path of its XML inside the .xlsx."""
    try:
        wbx = z.read("xl/workbook.xml").decode("utf-8", "replace")
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    except KeyError:
        return {}
    targets = {}
    for rel in re.findall(r"<Relationship\b[^>]*>", rels):
        rid, tgt = re.search(r'\bId="([^"]+)"', rel), re.search(r'\bTarget="([^"]+)"', rel)
        if rid and tgt:
            t = tgt.group(1)
            targets[rid.group(1)] = t.lstrip("/") if t.startswith("/") else "xl/" + t
    out = {}
    for attrs in re.findall(r"<sheet\b([^>]*)/?>", wbx):
        name, rid = re.search(r'\bname="([^"]*)"', attrs), re.search(r'\br:id="([^"]*)"', attrs)
        if name and rid and rid.group(1) in targets:
            out[html.unescape(name.group(1))] = targets[rid.group(1)]
    return out


def parse_workbook(data: bytes) -> list[dict]:
    """Visible sheets as Excel draws them: ``{name, rows, n_rows, n_cols, header_row, merges, layout, style_grid,
    style_table}``. ``rows`` are display texts; ``style_grid`` holds one index per cell into ``style_table``
    (CSS + borders, conditional formatting already applied); ``layout`` has widths, heights, hidden rows / columns,
    frozen panes, gridlines and the AutoFilter."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        z = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:  # not an xlsx, encrypted, corrupt
        raise AmcImportError(f"Could not read the workbook: {e}") from e
    sheets = []
    try:
        paths = _sheet_paths(z)
        styler = amc_excel.Styler(wb, amc_excel.theme_colors(getattr(wb, "loaded_theme", None)))
        for ws in wb.worksheets:
            if getattr(ws, "sheet_state", "visible") != "visible":
                continue
            try:
                lay = amc_excel.read_sheet_xml(z.read(paths[ws.title]).decode("utf-8", "replace"))
            except KeyError:
                lay = amc_excel.SheetLayout()
            table: list[dict] = []
            index: dict[tuple, int] = {}

            def style_index(sid: int, kind: str, dxfs: tuple) -> int:
                key = (sid, kind, dxfs)
                i = index.get(key)
                if i is None:
                    css = dict(styler.base(sid, kind))
                    for d in dxfs:
                        for k, v in styler.dxf(d).items():
                            css[k] = v  # dxfs are listed lowest priority first, so the top rule wins
                    i = index[key] = len(table)
                    table.append({"c": amc_excel.css_text(css), "b": list(styler.borders(sid))})
                return i

            rows: list[list[str]] = []
            grid: list[list[int]] = []
            fmts: dict[int, str] = {}
            last_row = n_cols = 0
            for rn, row in enumerate(ws.iter_rows(), start=1):
                vals, ids = [], []
                for cn, c in enumerate(row[:MAX_COLS], start=1):
                    v = c.value
                    sid = getattr(c, "_style_id", 0)
                    nf = fmts.get(sid)
                    if nf is None:
                        nf = fmts[sid] = getattr(c, "number_format", "General") or "General"
                    vals.append(format_value(v, nf))
                    dxfs = ()
                    for ranges, rules in lay.cf:
                        if any(r1 <= rn <= r2 and c1 <= cn <= c2 for r1, c1, r2, c2 in ranges):
                            dxfs += tuple(r["dxf"] for r in reversed(rules) if amc_excel.cf_matches(r, v))
                    ids.append(style_index(sid, amc_excel.value_kind(v), dxfs))
                keep = len(vals)
                while keep and vals[keep - 1] == "":
                    keep -= 1
                rows.append(vals)
                grid.append(ids)
                if keep:
                    last_row = rn
                    n_cols = max(n_cols, keep)
                if rn > MAX_ROWS + 5000 and last_row < rn - 5000:
                    break  # long blank tail (formatted-but-empty rows)
            rows, grid = rows[:last_row], grid[:last_row]
            if len(rows) > MAX_ROWS:
                raise AmcImportError(f"Sheet '{ws.title}' has {len(rows):,} rows; the limit is {MAX_ROWS:,}.")
            blank = style_index(0, "e", ())
            rows = [(r + [""] * n_cols)[:n_cols] for r in rows]
            grid = [(g + [blank] * n_cols)[:n_cols] for g in grid]
            merges = [[r1, c1, min(r2, len(rows)), min(c2, n_cols)] for r1, c1, r2, c2 in lay.merges
                      if r1 <= len(rows) and c1 <= n_cols]
            dw = lay.default_col_w if lay.default_col_w is not None else 8.43
            layout = {"colpx": [0 if c in lay.hidden_cols else amc_excel.width_px(lay.col_widths.get(c, dw))
                                for c in range(1, n_cols + 1)],
                      "rowpx": {str(r): amc_excel.pt_px(h) for r, h in lay.row_pt.items() if r <= len(rows)},
                      "defrow": amc_excel.pt_px(lay.default_row_pt), "grid": lay.grid,
                      "fr": min(lay.freeze_rows, len(rows)), "fc": min(lay.freeze_cols, n_cols),
                      "filter": lay.filter, "fcols": sorted(lay.filter_cols),
                      "hrows": sorted(r for r in lay.hidden_rows if r <= len(rows))}
            flt = lay.filter
            sheets.append({"name": ws.title, "rows": rows, "n_rows": len(rows), "n_cols": n_cols,
                           "header_row": _header_row(f"A{flt[0]}:A{flt[2]}" if flt else None, rows), "merges": merges,
                           "layout": layout, "style_grid": grid, "style_table": table})
    finally:
        wb.close()
        z.close()
    if not sheets:
        raise AmcImportError("The workbook has no visible sheets.")
    return sheets


# ------------------------------------------------------------------ sessions
def create(db: Session, user: User, data: bytes, filename: str, uploaded_by: str, ip: str | None = None) -> AmcImport:
    filename = (filename or "upload.xlsx").replace("\\", "/").rsplit("/", 1)[-1][:250]
    uploaded_by = (uploaded_by or "").strip()[:200]
    if not uploaded_by:
        raise AmcImportError("Enter who uploaded the file.")
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise AmcImportError("Upload an Excel workbook (.xlsx).")
    if not data:
        raise AmcImportError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise AmcImportError(f"File too large (max {MAX_BYTES // (1024 * 1024)} MB).")
    sheets = parse_workbook(data)
    imp = AmcImport(filename=filename, uploaded_by=uploaded_by, uploaded_by_user_id=user.id, size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(), content=data, sheet_count=len(sheets),
                    row_count=sum(s["n_rows"] for s in sheets),
                    active_sheet=active_position(data, [s["name"] for s in sheets]))
    colors = tab_colors(data)
    for pos, s in enumerate(sheets):
        imp.sheets.append(AmcImportSheet(position=pos, name=s["name"][:120], n_rows=s["n_rows"], n_cols=s["n_cols"],
                                         header_row=s["header_row"], rows=s["rows"], merges=s["merges"],
                                         layout=s["layout"], style_grid=s["style_grid"], style_table=s["style_table"],
                                         tab_color=colors.get(s["name"])))
    db.add(imp)
    db.flush()
    audit.record(db, user, "amc_import.upload", "amc_import", imp.id,
                 {"filename": filename, "uploaded_by": uploaded_by, "bytes": len(data), "sheets": len(sheets),
                  "sha256": imp.sha256}, ip)
    return imp


def listing(db: Session) -> list[AmcImport]:
    return list(db.scalars(select(AmcImport).order_by(AmcImport.id.desc())).all())


def get(db: Session, iid: int) -> AmcImport:
    imp = db.get(AmcImport, iid)
    if imp is None:
        raise AmcImportError(f"AMC import #{iid} not found.")
    return imp


def sheet(db: Session, iid: int, pos: int) -> AmcImportSheet:
    s = db.scalars(select(AmcImportSheet).where(AmcImportSheet.import_id == iid,
                                                AmcImportSheet.position == pos)).first()
    if s is None:
        raise AmcImportError("Sheet not found.")
    return s


def delete(db: Session, user: User, iid: int, ip: str | None = None) -> AmcImport:
    imp = get(db, iid)
    audit.record(db, user, "amc_import.delete", "amc_import", imp.id,
                 {"filename": imp.filename, "uploaded_by": imp.uploaded_by, "uploaded_at": imp.uploaded_at,
                  "sha256": imp.sha256}, ip)
    db.delete(imp)
    db.flush()
    return imp


def record_download(db: Session, user: User, imp: AmcImport, ip: str | None = None) -> None:
    audit.record(db, user, "amc_import.download", "amc_import", imp.id, {"filename": imp.filename}, ip)


def count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AmcImport)) or 0


# ------------------------------------------------------------------ display
RN_W = 46  # row-number column, px
NO_BORDER = ["", "", "", ""]


def page(s: AmcImportSheet, page_no: int = 1, q: str = "", per_page: int = PAGE_SIZE, show_hidden: bool = False) -> dict:
    """One page of a sheet as Excel draws it. Frozen title rows stay on top; body rows are searched and paged;
    rows hidden in Excel (e.g. by a filter) are left out unless ``show_hidden``."""
    rows = s.rows or []
    grid = s.style_grid or []
    table = s.style_table or []
    lay = s.layout or {}
    n_rows, n_cols = len(rows), s.n_cols
    fr, fc = lay.get("fr", 0), lay.get("fc", 0)
    hidden = set(lay.get("hrows", []))
    colpx = lay.get("colpx") or [64] * n_cols
    rowpx = {int(k): v for k, v in (lay.get("rowpx") or {}).items()}
    vcols = [c for c in range(1, n_cols + 1) if colpx[c - 1] > 0]
    head_n = [n for n in range(1, fr + 1) if show_hidden or n not in hidden]
    body_all = list(range(fr + 1, n_rows + 1))
    hidden_n = sum(1 for n in body_all if n in hidden)
    body = body_all if show_hidden else [n for n in body_all if n not in hidden]
    q = (q or "").strip()
    if q:
        needle = q.casefold()
        body = [n for n in body if any(needle in c.casefold() for c in rows[n - 1] if c)]
    pages = max(1, -(-len(body) // per_page))
    page_no = min(max(1, page_no), pages)
    start = (page_no - 1) * per_page
    shown = body[start:start + per_page]

    spans: dict[tuple[int, int], tuple[int, int]] = {}
    covered: set[tuple[int, int]] = set()
    if not q:
        visible = set(head_n) | set(shown)
        limit = shown[-1] if shown else fr
        for r1, c1, r2, c2 in s.merges or []:
            if r1 not in visible:
                continue
            r2 = min(r2, fr) if r1 <= fr else min(r2, limit)
            spans[(r1, c1)] = (r2 - r1 + 1, c2 - c1 + 1)
            covered.update((r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1) if (r, c) != (r1, c1))

    def borders(n: int, c: int) -> list[str]:
        return table[grid[n - 1][c - 1]]["b"] if 1 <= n <= n_rows and 1 <= c <= n_cols else NO_BORDER

    used_styles: set[int] = set()
    border_ids: dict[tuple, int] = {}
    left_of: dict[int, int] = {}
    x = RN_W
    for c in vcols:
        if c <= fc:
            left_of[c] = x
        x += colpx[c - 1]
    flt = lay.get("filter")
    fcols = set(lay.get("fcols", []))
    last_head = head_n[-1] if head_n else 0
    last_fz = max((c for c in vcols if c <= fc), default=0)

    def build(n: int) -> list[dict]:
        out = []
        for c in vcols:
            if (n, c) in covered:
                continue
            sp = spans.get((n, c))
            c2 = c + (sp[1] - 1 if sp else 0)
            n2 = n + (sp[0] - 1 if sp else 0)
            L, R, T, B = borders(n, c)
            if sp:
                R = R or borders(n, c2)[1]
                B = B or borders(n2, c)[3]
            # a line between two cells is drawn once: as the right / bottom edge of the cell before it
            eff = (L if not borders(n, c - 1)[1] else "", R or borders(n, c2 + 1)[0],
                   T if not borders(n - 1, c)[3] else "", B or borders(n2 + 1, c)[2])
            idx = grid[n - 1][c - 1]
            used_styles.add(idx)
            cls = [f"xs{idx}"]
            if any(eff):
                cls.append(f"xb{border_ids.setdefault(eff, len(border_ids))}")
            if c <= fc:
                cls.append("fz")
                if c == last_fz:
                    cls.append("fzl")
            if n == last_head:
                cls.append("fzb")
            if flt and n == flt[0] and flt[1] <= c <= flt[3]:
                cls.append("af on" if c in fcols else "af")
            out.append({"t": rows[n - 1][c - 1], "cls": " ".join(cls), "rs": sp[0] if sp and sp[0] > 1 else 0,
                        "cs": sp[1] if sp and sp[1] > 1 else 0, "left": left_of.get(c)})
        return out

    head = [(n, build(n), rowpx.get(n)) for n in head_n]
    body_rows = [(n, build(n), rowpx.get(n)) for n in shown]
    css = [f".amc-xl td.xs{i}{{{table[i]['c']}}}" for i in sorted(used_styles)]
    for eff, k in border_ids.items():
        side = "".join(f"border-{name}:{v};" for name, v in zip(("left", "right", "top", "bottom"), eff) if v)
        css.append(f".amc-xl td.xb{k}{{{side}}}")
    return {"head": head, "rows": body_rows, "page": page_no, "pages": pages, "count": len(body), "q": q,
            "start": start + 1 if shown else 0, "end": start + len(shown), "css": "\n".join(css),
            "letters": [{"L": get_column_letter(c), "left": left_of.get(c), "fz": c <= fc, "last": c == last_fz}
                        for c in vcols],
            "cols": [colpx[c - 1] for c in vcols], "width": x, "rn": RN_W, "grid": lay.get("grid", True),
            "defrow": lay.get("defrow", 20), "hidden_n": hidden_n, "show_hidden": show_hidden, "per_page": per_page,
            "n_cols": len(vcols)}
