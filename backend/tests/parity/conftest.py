"""Loads the legacy reference workbooks (cached values) once per test session.

Parity tests are skipped when docs/reference/ is not available (e.g. a public mirror).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

REF = Path(os.environ.get("OICAS_REFERENCE_DIR", Path(__file__).resolve().parents[3] / "docs" / "reference"))
AMC_FILE = REF / "03_AMC Sep-Jul  ABC Analysis.xlsx"
MASTER_FILE = REF / "10.13.26 INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx"
COUNTED_FILE = REF / "COUNTED LIST.xlsx"

FAMILY_SHEETS = ["RM", "Box ABC Analysis", "MS ABC Analysis", "PA ABC Analysis", "Stone ABC Analysis",
                 "T&D ABC Analysis", "PIM ABC Analysis", "CU ABC Analysis", "WS ABC Analysis",
                 "List excluded", "SF Wood ABC Analysis"]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _rows(ws, min_row, max_col):
    for row in ws.iter_rows(min_row=min_row, max_col=max_col, values_only=True):
        yield list(row) + [None] * (max_col - len(row))


@dataclass
class FamilySheet:
    name: str
    denominator: float  # P1
    rows: list[list]  # columns A..AD (0-based index)


def _load_amc():
    from openpyxl import load_workbook
    wb = load_workbook(AMC_FILE, data_only=True, read_only=True)
    fams = []
    for s in FAMILY_SHEETS:
        ws = wb[s]
        p1 = next(ws.iter_rows(min_row=1, max_row=1, min_col=16, max_col=16, values_only=True))[0]
        rows = [r for r in _rows(ws, 3, 30) if r[1] not in (None, "")]
        fams.append(FamilySheet(s, p1, rows))
    cons = [r for r in _rows(wb["CONSOLIDATED"], 2, 32) if r[1] not in (None, "", 0)]
    wb.close()
    return fams, cons


def _load_master():
    from openpyxl import load_workbook
    wb = load_workbook(MASTER_FILE, data_only=True, read_only=True)
    master = [r for r in _rows(wb["Master"], 2, 21) if r[0] not in (None, "")]
    po = [r for r in _rows(wb["PROGRESS-overall"], 1, 5)][:8]
    pw = [r for r in _rows(wb["PROGRESS-weekly"], 1, 65)][:35]
    wb.close()
    return master, po, pw


def _load_counted():
    from openpyxl import load_workbook
    wb = load_workbook(COUNTED_FILE, data_only=True, read_only=True)
    lst = [r for r in _rows(wb["LIST"], 2, 21) if r[1] not in (None, "")]
    wb.close()
    for r in lst:
        if isinstance(r[0], datetime):
            r[0] = r[0].date()
    return lst


@pytest.fixture(scope="session")
def amc_wb():
    if not AMC_FILE.exists():
        pytest.skip("reference workbooks not available")
    return _load_amc()


@pytest.fixture(scope="session")
def master_wb():
    if not MASTER_FILE.exists():
        pytest.skip("reference workbooks not available")
    master, po, pw = _load_master()
    for r in master:
        if isinstance(r[10], datetime):
            r[10] = r[10].date()
        if isinstance(r[11], datetime):
            r[11] = r[11].date()
    return master, po, pw


@pytest.fixture(scope="session")
def counted_wb():
    if not COUNTED_FILE.exists():
        pytest.skip("reference workbooks not available")
    return _load_counted()


num = _num
