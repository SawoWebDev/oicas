import io
from datetime import date, datetime

from openpyxl import Workbook

from oicas.services import counted_list


def _workbook() -> bytes:
    wb = Workbook()
    wb.active.title = "ODOO inv"
    ws = wb.create_sheet("LIST")
    ws.append(["DATE COUNTED", "RM CODE", "Description", "TOTAL COUNT (WH)", "TOTAL COUNT (PROD)", "REMARKS",
               "COUNTED BY", "COUNT (WH-1)", "COUNT (WH-2)", "COUNT (WH-3)", "COUNT (WH-4)", "COUNT \n(PROD- 1)",
               "COUNT \n(PROD- 2)", "COUNT \n(PROD- 3)", "COUNT \n(PROD- 4)", "Odoo WH", "Odoo Pre-prod"])
    ws.append([datetime(2026, 9, 1), "A-1", "Item A", 5, 2, "14 box", "Christine A",
               None, None, 5, None, None, 2, None, None, 9, 9])
    ws.append([datetime(2026, 9, 2), "B-2", "Item B", 0, None, None, "Giniemark",
               0, None, None, None, None, None, None, None, 1, 0])
    ws.append([datetime(2026, 9, 3), "C-3", "Item C", None, None, "not counted", "Giniemark"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_reads_list_sheet_locations_and_remarks():
    lines = counted_list.parse(_workbook())
    got = [(ln.code, ln.location, ln.qty, ln.remarks, ln.counted_by, ln.count_date) for ln in lines]
    assert got == [
        ("A-1", "WH-3", 5.0, "14 box", "Christine A", date(2026, 9, 1)),
        ("A-1", "PROD-2", 2.0, "14 box", "Christine A", date(2026, 9, 1)),
        ("B-2", "WH-1", 0.0, "", "Giniemark", date(2026, 9, 2)),  # 0 is a counted zero
    ]  # C-3 has no quantity in any location: not a count
    assert lines[0].row == 2 and lines[0].description == "Item A"
