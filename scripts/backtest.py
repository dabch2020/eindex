#!/usr/bin/env python3
"""回测：人工标注恐惧/贪婪日期 vs eIndex 信号命中率"""
import json
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data" / "eindex_data.json"

d = json.load(open(DATA_FILE))['data']
by_date = {r['date']: r for r in d}
all_dates = sorted(by_date.keys())
date_idx = {dt: i for i, dt in enumerate(all_dates)}

fear_dates = ['2022-04-27','2022-10-31','2023-06-26','2023-10-23',
              '2024-02-05','2024-09-18','2025-04-09','2025-06-23']
greed_dates = ['2022-01-04','2022-07-04','2023-01-30','2023-07-31',
               '2024-05-10','2024-10-08','2025-05-14','2025-10-09']

def get_sig(r):
    ft = r.get('fear_threshold', 10)
    gt = r.get('greed_threshold', 85)
    ei = r['eindex']
    if ei <= ft: return 'FEAR'
    if ei >= gt: return 'GREED'
    return 'NEUTRAL'

def find_nearby(target, expected, tol):
    if target not in date_idx:
        return None, None
    idx = date_idx[target]
    for off in range(0, tol+1):
        for sign in ([0] if off == 0 else [off, -off]):
            j = idx + sign
            if 0 <= j < len(all_dates):
                r = by_date[all_dates[j]]
                if get_sig(r) == expected:
                    return all_dates[j], sign
    return None, None

print('=' * 90)
print('eIndex Backtest - Human-labeled Fear/Greed Hit Rate')
print('=' * 90)
print(f'Data: {all_dates[0]} ~ {all_dates[-1]}, {len(all_dates)} trading days')
print(f'Params: LOOKBACK=3, WINDOW=200, FEAR=10, GREED=85')
print()

# --- Fear ---
print('-' * 90)
print('FEAR dates (expect: eIndex <= fear_threshold)')
print('-' * 90)
print(f'{"Date":>12} | {"eIndex":>7} | {"FearTh":>7} | {"GreedTh":>7} | {"Signal":>8} | {"Exact":>5} | {"+-3d":>12} | {"+-5d":>12}')
print('-' * 90)

fear_exact = 0; fear_t3 = 0; fear_t5 = 0
for dt in fear_dates:
    r = by_date.get(dt)
    if not r:
        print(f'{dt:>12} | NO DATA')
        continue
    sig = get_sig(r)
    exact = 'Y' if sig == 'FEAR' else 'N'
    if sig == 'FEAR': fear_exact += 1

    hit3, off3 = find_nearby(dt, 'FEAR', 3)
    hit5, off5 = find_nearby(dt, 'FEAR', 5)
    t3 = f'Y({hit3[-5:]}{off3:+d})' if hit3 else 'N'
    t5 = f'Y({hit5[-5:]}{off5:+d})' if hit5 else 'N'
    if hit3: fear_t3 += 1
    if hit5: fear_t5 += 1

    print(f'{dt:>12} | {r["eindex"]:7.1f} | {r.get("fear_threshold",10):7.1f} | {r.get("greed_threshold",85):7.1f} | {sig:>8} | {exact:>5} | {t3:>12} | {t5:>12}')

print()

# --- Greed ---
print('-' * 90)
print('GREED dates (expect: eIndex >= greed_threshold)')
print('-' * 90)
print(f'{"Date":>12} | {"eIndex":>7} | {"FearTh":>7} | {"GreedTh":>7} | {"Signal":>8} | {"Exact":>5} | {"+-3d":>12} | {"+-5d":>12}')
print('-' * 90)

greed_exact = 0; greed_t3 = 0; greed_t5 = 0
for dt in greed_dates:
    r = by_date.get(dt)
    if not r:
        print(f'{dt:>12} | NO DATA')
        continue
    sig = get_sig(r)
    exact = 'Y' if sig == 'GREED' else 'N'
    if sig == 'GREED': greed_exact += 1

    hit3, off3 = find_nearby(dt, 'GREED', 3)
    hit5, off5 = find_nearby(dt, 'GREED', 5)
    t3 = f'Y({hit3[-5:]}{off3:+d})' if hit3 else 'N'
    t5 = f'Y({hit5[-5:]}{off5:+d})' if hit5 else 'N'
    if hit3: greed_t3 += 1
    if hit5: greed_t5 += 1

    print(f'{dt:>12} | {r["eindex"]:7.1f} | {r.get("fear_threshold",10):7.1f} | {r.get("greed_threshold",85):7.1f} | {sig:>8} | {exact:>5} | {t3:>12} | {t5:>12}')

print()

# --- Summary ---
print('=' * 90)
print('HIT RATE SUMMARY')
print('=' * 90)
print(f'{"":>12} | {"Exact":>12} | {"+-3 days":>12} | {"+-5 days":>12}')
print('-' * 60)
print(f'{"Fear":>12} | {fear_exact}/8 ({fear_exact/8*100:5.1f}%) | {fear_t3}/8 ({fear_t3/8*100:5.1f}%) | {fear_t5}/8 ({fear_t5/8*100:5.1f}%)')
print(f'{"Greed":>12} | {greed_exact}/8 ({greed_exact/8*100:5.1f}%) | {greed_t3}/8 ({greed_t3/8*100:5.1f}%) | {greed_t5}/8 ({greed_t5/8*100:5.1f}%)')
te = fear_exact + greed_exact
t3 = fear_t3 + greed_t3
t5 = fear_t5 + greed_t5
print(f'{"Total":>12} | {te}/16 ({te/16*100:5.1f}%) | {t3}/16 ({t3/16*100:5.1f}%) | {t5}/16 ({t5/16*100:5.1f}%)')
print()

# --- Global signal stats ---
print('=' * 90)
print('GLOBAL SIGNAL DISTRIBUTION')
print('=' * 90)
fear_cnt = sum(1 for r in d if get_sig(r) == 'FEAR')
greed_cnt = sum(1 for r in d if get_sig(r) == 'GREED')
neutral_cnt = len(d) - fear_cnt - greed_cnt
print(f'Fear signals:    {fear_cnt:4d} days ({fear_cnt/len(d)*100:5.1f}%)')
print(f'Greed signals:   {greed_cnt:4d} days ({greed_cnt/len(d)*100:5.1f}%)')
print(f'Neutral:         {neutral_cnt:4d} days ({neutral_cnt/len(d)*100:5.1f}%)')
print(f'Signal density:  {(fear_cnt+greed_cnt)/len(d)*100:.1f}% (fear+greed / total)')
print()

# --- Miss analysis ---
print('=' * 90)
print('MISS ANALYSIS (not hit even within +-5 days)')
print('=' * 90)
miss_count = 0
for dt in fear_dates:
    hit5, _ = find_nearby(dt, 'FEAR', 5)
    if not hit5:
        r = by_date[dt]
        ft = r.get('fear_threshold', 10)
        gap = r['eindex'] - ft
        print(f'  FEAR  {dt}: eIndex={r["eindex"]:.1f}, threshold={ft:.1f}, gap={gap:+.1f}')
        miss_count += 1

for dt in greed_dates:
    hit5, _ = find_nearby(dt, 'GREED', 5)
    if not hit5:
        r = by_date[dt]
        gt = r.get('greed_threshold', 85)
        gap = r['eindex'] - gt
        print(f'  GREED {dt}: eIndex={r["eindex"]:.1f}, threshold={gt:.1f}, gap={gap:+.1f}')
        miss_count += 1

if miss_count == 0:
    print('  (none)')
print()

# --- Nearby context for each labeled date ---
print('=' * 90)
print('DETAILED CONTEXT: eIndex values around each labeled date (+-3 days)')
print('=' * 90)
for label, dates_list, expected in [('FEAR', fear_dates, 'FEAR'), ('GREED', greed_dates, 'GREED')]:
    for dt in dates_list:
        if dt not in date_idx:
            continue
        idx = date_idx[dt]
        sig = get_sig(by_date[dt])
        marker = ' <<HIT>>' if sig == expected else ' <<MISS>>'
        print(f'\n  {label} {dt}{marker}')
        for off in range(-3, 4):
            j = idx + off
            if 0 <= j < len(all_dates):
                r = by_date[all_dates[j]]
                s = get_sig(r)
                arrow = ' <--' if off == 0 else ''
                print(f'    {all_dates[j]}  eI={r["eindex"]:5.1f}  fear_th={r.get("fear_threshold",0):5.1f}  greed_th={r.get("greed_threshold",0):5.1f}  [{s:>7}]{arrow}')
