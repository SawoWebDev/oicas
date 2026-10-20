import openpyxl, zipfile, re, sys
from openpyxl.worksheet.formula import ArrayFormula
R = 'docs/reference/'
def af(c):
    v = c.value
    return f'ARRAY[{v.ref}] {v.text}' if isinstance(v, ArrayFormula) else v

amc = openpyxl.load_workbook(R + '03_AMC Sep-Jul  ABC Analysis.xlsx')
print('== ABC array formula A col:', af(amc['RM']['A3']), '|', af(amc['CONSOLIDATED']['A2']))
ws = amc['CLASS']
print('== CLASS sheet')
for r in ws.iter_rows(min_row=1, max_row=40):
    vals = [(c.coordinate, c.value) for c in r if c.value is not None]
    if vals: print(vals)

m = openpyxl.load_workbook(R + '10.13.26 INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx')
print('== Master P2/Q2:', af(m['Master']['P2']), '||', af(m['Master']['Q2']))
for c in ['B3','C3','D3','E3']: print('== PROGRESS-overall', c, af(m['PROGRESS-overall'][c]))
print('== DATA A1', af(m['DATA']['A1']))
ws = m['PROGRESS-overall']
for r in ws.iter_rows(min_row=9, max_row=22):
    vals = [(c.coordinate, af(c)) for c in r if c.value is not None]
    if vals: print('PO', vals)
ws = m['PROGRESS-weekly']
for r in ws.iter_rows(min_row=1, max_row=35):
    vals = [(c.coordinate, af(c)) for c in r if c.value is not None and c.column > 7]
    if vals and r[0].row < 4: print('PW', vals)
ws = m['Master']
print('Master V..AB header/r2:', [(c.coordinate, af(c)) for c in ws[1][21:28]], [(c.coordinate, af(c)) for c in ws[2][21:28]])
# external link cache target sheets
z = zipfile.ZipFile(R + '10.13.26 INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx')
for n in z.namelist():
    if 'externalLink' in n and n.endswith('.xml') and 'rels' not in n:
        x = z.read(n).decode('utf8', 'ignore'); print(n, re.findall(r'sheetName val="([^"]+)"', x))

cl = openpyxl.load_workbook(R + 'COUNTED LIST.xlsx')
ws = cl['LIST']
import collections
fcols = collections.Counter()
for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
    for c in row:
        if isinstance(c.value, str) and c.value.startswith('='): fcols[(c.column_letter, re.sub(r'(?<=[A-Z])\d+','n',c.value))] += 1
        elif isinstance(c.value, ArrayFormula): fcols[(c.column_letter, 'ARRAY '+re.sub(r'(?<=[A-Z])\d+','n',c.value.text))] += 1
for k, v in fcols.most_common(40): print('LIST formula', k, v)
print('LIST header T,U:', ws['T1'].value, ws['U1'].value)
for r in (2830, 2835, 2840, 2841):
    print('LIST row', r, [(c.coordinate, af(c)) for c in ws[r] if c.value is not None])
ws = cl['ODOO inv']
print('ODOO inv G-I hdr', [ws.cell(1,c).value for c in range(1,10)])
dl = collections.Counter((ws.cell(r,1).value, ws.cell(r,6).value) for r in range(2, ws.max_row+1))
print('ODOO inv snapshots:', dl.most_common(20))

af2 = openpyxl.load_workbook(R + 'automation flow 2.xlsx')
for ws in af2.worksheets:
    print('== AF sheet', ws.title)
    for r in ws.iter_rows():
        vals = [(c.coordinate, af(c)) for c in r if c.value is not None]
        if vals: print(vals)
z = zipfile.ZipFile(R + 'automation flow 2.xlsx')
for n in z.namelist():
    if 'drawing' in n or 'media' in n: print('ZIP', n)
    if re.match(r'xl/drawings/drawing\d+\.xml$', n):
        x = z.read(n).decode('utf8', 'ignore')
        shapes = re.findall(r'<xdr:(?:sp|cxnSp)>.*?</xdr:(?:sp|cxnSp)>', x, re.S)
        print(n, 'shapes:', len(shapes))
        for s in shapes:
            name = re.search(r'name="([^"]*)"', s); txt = ' '.join(re.findall(r'<a:t>([^<]*)</a:t>', s))
            frm = re.search(r'<xdr:from><xdr:col>(\d+)</xdr:col>.*?<xdr:row>(\d+)</xdr:row>', s, re.S)
            st = re.search(r'stCxn id="(\d+)"', s); en = re.search(r'endCxn id="(\d+)"', s); sid = re.search(r'cNvPr id="(\d+)"', s)
            print('  SHAPE', sid.group(1) if sid else '', name.group(1) if name else '', '|', txt[:200], '| conn', st and st.group(1), '->', en and en.group(1))
