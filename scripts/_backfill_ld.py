#!/usr/bin/env python3
"""Backfill limitdown_count into limitup_cache.json from mootdx 880006 open column."""
import json, time
from mootdx.quotes import Quotes
import pandas as pd

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

ld_map = {}
for idx, row in combined.iterrows():
    dt = idx.strftime('%Y-%m-%d')
    ld_map[dt] = int(row['open']) if row['open'] > 0 else 0

cache = json.load(open('data/limitup_cache.json'))
updated = 0
for dt, entry in cache.items():
    if isinstance(entry, dict) and 'limitdown_count' not in entry:
        entry['limitdown_count'] = ld_map.get(dt, 0)
        updated += 1

with open('data/limitup_cache.json', 'w') as f:
    json.dump(cache, f, ensure_ascii=False)

print(f'Updated {updated} entries with limitdown_count')
dates = sorted(cache.keys())
print(f'Sample last: {dates[-1]} -> {cache[dates[-1]]}')
print(f'Sample -5:   {dates[-5]} -> {cache[dates[-5]]}')
