#!/usr/bin/env python3
"""Fetch all limitdown data from mootdx 880006 open column into limitdown_cache.json."""
import json, time, os
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from mootdx.quotes import Quotes
import pandas as pd

TOTAL_STOCKS = {
    2016: 3000, 2017: 3400, 2018: 3500, 2019: 3700, 2020: 4000,
    2021: 4400, 2022: 4800, 2023: 5200, 2024: 5300, 2025: 5400, 2026: 5500,
}

client = Quotes.factory(market='std')

all_data = []
for start in range(0, 5000, 800):
    data = client.index(symbol='880006', frequency=9, start=start, offset=800)
    if data is None or len(data) == 0:
        break
    all_data.append(data)
    print(f'  Fetched batch start={start}, got {len(data)} rows')
    if len(data) < 800:
        break
    time.sleep(1)

combined = pd.concat(all_data)
combined = combined[~combined.index.duplicated(keep='first')]
print(f'Total rows from mootdx: {len(combined)}')

ld_cache = {}
for idx, row in combined.iterrows():
    dt = idx.strftime('%Y-%m-%d')
    ld_count = int(row['open']) if row['open'] > 0 else 0
    year = int(dt[:4])
    total = TOTAL_STOCKS.get(year, 5300)
    ld_cache[dt] = {"count": ld_count, "ratio": ld_count / total}

with open('data/limitdown_cache.json', 'w') as f:
    json.dump(ld_cache, f, ensure_ascii=False, indent=2)

print(f'Created limitdown_cache.json: {len(ld_cache)} entries')
dates = sorted(ld_cache.keys())
for d in dates[-5:]:
    print(f'  {d}: {ld_cache[d]}')
