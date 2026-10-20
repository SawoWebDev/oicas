"""Data-level checks used to build the formula register and data-quality register.

Run:  docker run --rm -v "$PWD:/w" -w /w oicas-xl python tools/xl_data_checks.py
"""
import collections

import openpyxl

R = 'docs/reference/'
FAMILIES = ['RM', 'Box ABC Analysis', 'MS ABC Analysis', 'PA ABC Analysis', 'Stone ABC Analysis',
            'T&D ABC Analysis', 'PIM ABC Analysis', 'CU ABC Analysis', 'WS ABC Analysis',
            'List excluded', 'SF Wood ABC Analysis']


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def qty_class(cum):
    return 'A' if cum < .8 else ('C' if cum >= .95 else 'B')


amc = openpyxl.load_workbook(R + '03_AMC Sep-Jul  ABC Analysis.xlsx', data_only=True)
allcodes = collections.Counter()
for s in FAMILIES:
    ws = amc[s]
    rows = []
    for r in range(3, ws.max_row + 1):
        code = ws.cell(r, 2).value
        if code in (None, ''):
            continue
        rows.append([ws.cell(r, c).value for c in range(1, 31)])
        allcodes[str(code).strip()] += 1
    P = [v[15] if num(v[15]) else 0 for v in rows]
    inversions = sum(1 for i in range(len(P) - 1) if P[i] < P[i + 1] - 1e-9)
    tot = sum(P)
    cum = 0
    mism_legacy = 0
    vcount = collections.Counter()
    for v, p in zip(rows, P):
        cum += p / tot if tot else 0
        if qty_class(cum) != v[21]:
            mism_legacy += 1
        vcount[v[21]] += 1
    order = sorted(range(len(rows)), key=lambda i: -P[i])
    cum = 0
    pareto = collections.Counter()
    diff = 0
    for i in order:
        cum += P[i] / tot if tot else 0
        c = qty_class(cum)
        pareto[c] += 1
        if c != rows[i][21]:
            diff += 1
    freq_mism = sum(1 for v in rows if v[22] != ('A' if (v[20] or 0) > .8 else ('C' if (v[20] or 0) <= .5 else 'B')))

    def amc_of(v):
        xs = [x for x in v[3:15] if num(x)]
        return sum(xs) / len(xs) if xs else 0
    amc_mism = sum(1 for v in rows if num(v[27]) and abs(v[27] - amc_of(v)) > 1e-6)
    print(f'{s:22s} n={len(rows):5d} total={tot:14.2f} inversions={inversions} legacyRecalcMismatch={mism_legacy} '
          f'V-dist={dict(vcount)} paretoDist={dict(pareto)} paretoDiffs={diff} freqMism={freq_mism} amcMism={amc_mism} P1={ws["P1"].value}')
print('codes in >1 family sheet:', sum(1 for n in allcodes.values() if n > 1),
      [(c, n) for c, n in allcodes.items() if n > 1][:10])
ws = amc['RM']
print('RM col O (Aug) non-empty:', sum(1 for r in range(3, ws.max_row + 1) if ws.cell(r, 15).value not in (None, '')))

d = amc['Demand']
dc = collections.Counter()
neg = 0
texts = collections.Counter()
for r in range(3, d.max_row + 1):
    c = d.cell(r, 1).value
    if c:
        dc[str(c).strip()] += 1
    for col in range(3, 15):
        v = d.cell(r, col).value
        if num(v) and v < 0:
            neg += 1
        if isinstance(v, str):
            texts[v] += 1
print('Demand rows', sum(dc.values()), 'dupe codes', sum(1 for n in dc.values() if n > 1), 'negatives', neg,
      'text cells', texts.most_common(3))
print('Demand row1:', [d.cell(1, c).value for c in range(1, 19)], 'row2 O-R:', [d.cell(2, c).value for c in range(15, 19)])

cs = amc['CONSOLIDATED']
cc = collections.Counter()
notfound = 0
cls = collections.Counter()
for r in range(2, cs.max_row + 1):
    c = cs.cell(r, 2).value
    if c in (None, '', 0):
        continue
    cc[str(c).strip()] += 1
    cls[cs.cell(r, 27).value] += 1
    if cs.cell(r, 32).value == '- Not Found':
        notfound += 1
print('CONSOLIDATED rows', sum(cc.values()), 'unique', len(cc), 'dupes', [(k, n) for k, n in cc.items() if n > 1][:10],
      'AF NotFound', notfound, 'class dist', dict(cls))

m = openpyxl.load_workbook(R + '10.13.26 INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx', data_only=True)
ms = m['Master']
mc = collections.Counter()
stats = collections.Counter()
dist = collections.defaultdict(collections.Counter)
master = {}
for r in range(2, ms.max_row + 1):
    a = ms.cell(r, 1).value
    if a in (None, ''):
        continue
    a = str(a).strip()
    mc[a] += 1
    row = [ms.cell(r, c).value for c in range(1, 22)]
    master[a] = row
    for name, idx in (('class', 3), ('action', 2), ('section', 5), ('plant', 6), ('remark', 19), ('interval', 8)):
        dist[name][row[idx]] += 1
    if row[9] == '- not found':
        stats['uom_not_found'] += 1
    if row[10] not in (None, ''):
        stats['has_count_date'] += 1
    if row[20] == 1:
        stats['disc_flag'] += 1
    if num(row[4]) and row[4] == 0:
        stats['amc_zero'] += 1
    if row[14] in (None, ''):
        stats['stock_months_blank'] += 1
    if row[10] not in (None, '') and row[12] == 0 and row[13] == 0:
        stats['counted_but_zero_qty'] += 1
    if row[10] in (None, '') and row[20] == 1:
        stats['uncounted_but_flagged'] += 1
    if row[10] in (None, '') and (num(row[17]) and row[17] != 0):
        stats['uncounted_nonzero_disc'] += 1
print('Master rows', sum(mc.values()), 'unique', len(mc), 'dupes', [(k, n) for k, n in mc.items() if n > 1][:10])
print('Master stats', dict(stats))
for k, v in dist.items():
    print('Master', k, v.most_common(20))
print('Master codes not in CONSOLIDATED:', len(set(mc) - set(cc)), list(set(mc) - set(cc))[:8],
      '| CONSOLIDATED not in Master:', len(set(cc) - set(mc)))
diffcls = sum(1 for r in range(2, cs.max_row + 1)
              if cs.cell(r, 2).value and str(cs.cell(r, 2).value).strip() in master
              and master[str(cs.cell(r, 2).value).strip()][3] != cs.cell(r, 27).value)
print('Master vs CONSOLIDATED classification differences:', diffcls)
dd = m['DATA']
print('DATA headers', [dd.cell(1, c).value for c in range(1, 14)])
print('DATA B LOCATION dist', collections.Counter(dd.cell(r, 2).value for r in range(2, dd.max_row + 1)).most_common(6))
print('DATA C,D,H,I sample', [(dd.cell(r, 3).value, dd.cell(r, 4).value, dd.cell(r, 8).value, dd.cell(r, 9).value) for r in range(2, 6)])
print('DATA remark1 dist', collections.Counter(dd.cell(r, 12).value for r in range(2, dd.max_row + 1) if dd.cell(r, 10).value).most_common(10))
print('UOM dist', collections.Counter(dd.cell(r, 7).value for r in range(2, dd.max_row + 1) if dd.cell(r, 6).value).most_common(30))
fc = collections.Counter(dd.cell(r, 6).value for r in range(2, dd.max_row + 1) if dd.cell(r, 6).value)
print('DATA F dup codes', sum(1 for n in fc.values() if n > 1))

cl = openpyxl.load_workbook(R + 'COUNTED LIST.xlsx', data_only=True)
L = cl['LIST']
keys = collections.Counter()
by_date = collections.Counter()
counters = collections.Counter()
ucol = collections.Counter()
remk = collections.Counter()
prodcnt = multi = 0
rows = []
for r in range(2, L.max_row + 1):
    b = L.cell(r, 2).value
    if not b:
        continue
    row = [L.cell(r, c).value for c in range(1, 22)]
    rows.append(row)
    keys[(row[0], str(b).strip())] += 1
    by_date[row[0]] += 1
    counters[row[6]] += 1
    ucol[row[20]] += 1
    remk[row[5]] += 1
    if any(num(x) for x in row[11:15]):
        prodcnt += 1
    if sum(1 for x in row[7:11] if num(x)) > 1:
        multi += 1
print('LIST rows', len(rows), 'dupe (date,code)', sum(1 for n in keys.values() if n > 1), 'prod entries', prodcnt,
      'rows with >1 WH entries', multi)
print('LIST dates', sorted((k.date() if k else None, n) for k, n in by_date.items()))
print('counters', counters.most_common(10))
print('U col', ucol.most_common(10))
print('remarks', remk.most_common(10))
has_r = [x for x in rows if num(x[17])]
print('R = D - P holds', sum(1 for x in has_r if num(x[3]) and num(x[15]) and abs(x[17] - (x[3] - x[15])) < 1e-6), 'of', len(has_r))
print('E filled', sum(1 for x in rows if num(x[4])), 'E != SUM(L:O)',
      sum(1 for x in rows if num(x[4]) and abs(x[4] - sum(y for y in x[11:15] if num(y))) > 1e-6))
oi = cl['ODOO inv']
od = collections.defaultdict(list)
for r in range(2, oi.max_row + 1):
    if oi.cell(r, 2).value:
        od[str(oi.cell(r, 2).value).strip()].append((oi.cell(r, 1).value, oi.cell(r, 4).value, oi.cell(r, 5).value))
tot = match = 0
for x in rows:
    if num(x[15]) and str(x[1]).strip() in od:
        tot += 1
        if any(num(w) and abs(w - x[15]) < 1e-6 for _, w, _ in od[str(x[1]).strip()]):
            match += 1
print('LIST P matches some ODOO inv WH value', match, 'of', tot, '; LIST rows with P', sum(1 for x in rows if num(x[15])),
      '; ODOO inv distinct codes', len(od), 'rows', sum(len(v) for v in od.values()))
print('ODOO inv neg prod', sum(1 for v in od.values() for _, w, p in v if num(p) and p < 0),
      'neg wh', sum(1 for v in od.values() for _, w, p in v if num(w) and w < 0))
dcl = cl['DATA']
c3 = collections.Counter(dcl.cell(r, 3).value for r in range(2, dcl.max_row + 1))
print('COUNTED DATA rows', sum(c3.values()), 'dupe codes', sum(1 for n in c3.values() if n > 1))
latest = {}
for x in rows:
    if x[0]:
        k = str(x[1]).strip()
        latest[k] = max(latest.get(k, x[0]), x[0])
print('Master K != max(LIST date):', sum(1 for c, row in master.items() if c in latest and row[10] and row[10] != latest[c]),
      '; counted codes not in Master:', len(set(latest) - set(master)), list(set(latest) - set(master))[:8])
po = m['PROGRESS-overall']
print('PROGRESS overall', [[po.cell(r, c).value for c in range(1, 6)] for r in range(1, 9)])
# Weekly parity: counted items per class per week (Sun-Sat, WEEKNUM type 2 = weeks start Monday)
