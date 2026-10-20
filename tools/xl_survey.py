"""Survey Excel workbooks: sheets, visibility, dims, headers, formulas, names, validations."""
import sys, glob, os, re
from collections import Counter, defaultdict
import openpyxl

def norm(f):
    # normalise a formula to a pattern: replace row numbers to find column patterns
    return re.sub(r'(?<=[A-Z])\d+', 'n', f)

for path in sorted(glob.glob(sys.argv[1] + '/*.xlsx')):
    print('=' * 100); print('WORKBOOK:', os.path.basename(path))
    wb = openpyxl.load_workbook(path, data_only=False)
    wbv = openpyxl.load_workbook(path, data_only=True)
    print('Defined names:', [(n, wb.defined_names[n].attr_text) for n in wb.defined_names] if hasattr(wb.defined_names,'__iter__') else wb.defined_names)
    print('External links:', [l.file_link.Target if l.file_link else None for l in wb._external_links])
    for ws in wb.worksheets:
        wv = wbv[ws.title]
        print('-' * 100)
        print(f'SHEET {ws.title!r} state={ws.sheet_state} dims={ws.dimensions} max_row={ws.max_row} max_col={ws.max_column}')
        print('  merged:', list(ws.merged_cells.ranges)[:15])
        print('  tables:', list(ws.tables.keys()))
        print('  data validations:', [(dv.type, dv.formula1, str(dv.sqref)[:60]) for dv in ws.data_validations.dataValidation][:10])
        print('  cond formats:', [(str(r.sqref)[:40], [ (x.type, x.operator, x.formula) for x in r.rules]) for r in ws.conditional_formatting][:10])
        hidden_cols = [k for k, d in ws.column_dimensions.items() if d.hidden]
        hidden_rows = [k for k, d in ws.row_dimensions.items() if d.hidden]
        print('  hidden cols:', hidden_cols[:30], 'hidden rows count:', len(hidden_rows), hidden_rows[:10])
        print('  freeze:', ws.freeze_panes, 'autofilter:', ws.auto_filter.ref)
        print('  drawings/images:', len(getattr(ws, '_images', [])), 'charts:', len(getattr(ws, '_charts', [])))
        # first 8 rows raw (formulas) and values
        maxc = min(ws.max_column, 60)
        for r in range(1, min(ws.max_row, 8) + 1):
            row = [ws.cell(r, c).value for c in range(1, maxc + 1)]
            vrow = [wv.cell(r, c).value for c in range(1, maxc + 1)]
            if any(v is not None for v in row):
                print(f'  R{r} F:', [(openpyxl.utils.get_column_letter(i+1), v) for i, v in enumerate(row) if v is not None])
                if row != vrow:
                    print(f'  R{r} V:', [(openpyxl.utils.get_column_letter(i+1), v) for i, v in enumerate(vrow) if v is not None])
        # formula patterns per column
        pats = defaultdict(Counter); comments = []
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=maxc):
            for c in row:
                if isinstance(c.value, str) and c.value.startswith('='):
                    pats[c.column_letter][norm(c.value)[:220]] += 1
                if c.comment: comments.append((c.coordinate, c.comment.text[:120]))
        for col in sorted(pats, key=lambda x: (len(x), x)):
            for p, n in pats[col].most_common(4):
                print(f'  FORMULA {col}: x{n}: {p}')
        if comments: print('  comments:', comments[:20])
