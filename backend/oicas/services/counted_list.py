"""Count lines read from an uploaded COUNTED LIST workbook (Physical Counting upload, kind ``counted``).

Count History shows exactly what the uploaded LIST sheet says: one row per filled count cell, with the
location taken from the column the quantity sits in (WH-1..WH-4, PROD-1..PROD-4) and the line's REMARKS.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AmcImport

LOCATION_RE = re.compile(r"^COUNT\((WH|PROD)-?(\d+)\)$")


@dataclass(frozen=True)
class CountLine:
    row: int            # Excel row number on the LIST sheet
    count_date: date | None
    code: str
    description: str
    counted_by: str
    location: str       # WH-1 … PROD-4
    qty: float
    remarks: str


_CACHE: dict[str, list[CountLine]] = {}
_CACHE_MAX = 32  # Count History reads every upload at once


def _norm(h) -> str:
    return re.sub(r"\s+", "", str(h or "")).upper()


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _text(v)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m.%d.%Y", "%m.%d.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _text(v).replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse(data: bytes) -> list[CountLine]:
    """Count lines of the LIST sheet (or the first sheet with an RM CODE header)."""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheets = sorted(wb.worksheets, key=lambda ws: ws.title.strip().upper() != "LIST")
        for ws in sheets:
            it = ws.iter_rows(values_only=True)
            cols: dict[str, int] = {}
            locs: list[tuple[int, str]] = []
            header_at = 0
            for n, r in enumerate(it, start=1):
                heads = [_norm(h) for h in r]
                if "RMCODE" in heads:
                    cols = {h: i for i, h in enumerate(heads) if h}
                    locs = [(i, f"{m.group(1)}-{m.group(2)}") for i, h in enumerate(heads)
                            if (m := LOCATION_RE.match(h))]
                    header_at = n
                    break
                if n >= 15:
                    break
            if not header_at or not locs:
                continue

            def col(r, *names):
                for nm in names:
                    i = cols.get(nm)
                    if i is not None and i < len(r):
                        return r[i]
                return None

            out: list[CountLine] = []
            for n, r in enumerate(it, start=header_at + 1):
                code = _text(col(r, "RMCODE"))
                if not code:
                    continue
                d = _date(col(r, "DATECOUNTED", "DATE"))
                desc = _text(col(r, "DESCRIPTION"))
                who = _text(col(r, "COUNTEDBY"))
                remarks = _text(col(r, "REMARKS"))
                for i, loc in locs:
                    q = _num(r[i]) if i < len(r) else None
                    if q is None:
                        continue  # blank = not counted; 0 = a counted zero
                    out.append(CountLine(n, d, code, desc, who, loc, q, remarks))
            return out
        return []
    finally:
        wb.close()


def uploads(db: Session) -> list[AmcImport]:
    return list(db.scalars(select(AmcImport).where(AmcImport.kind == "counted").order_by(AmcImport.id.desc())))


def lines(imp: AmcImport) -> list[CountLine]:
    hit = _CACHE.get(imp.sha256)
    if hit is None:
        hit = parse(imp.content)
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[imp.sha256] = hit
    return hit
