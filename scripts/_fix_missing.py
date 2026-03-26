#!/usr/bin/env python3
"""Re-fetch missing 3/24 and 3/25 limitup cache entries."""
import json
from mootdx.quotes import Quotes

client = Quotes.factory(market='std')
data = client.index(symbol='880006', frequency=9, start=0, offset=20)
print(data.tail(5)[['open', 'close']])

TOTAL_STOCKS = {2026: 5500}
cache = json.load(open('data/limitup_cache.json'))

for idx, row in data.iterrows():
    dt = idx.strftime('%Y-%m-%d')
    if dt in ('2026-03-24', '2026-03-25'):
        count = int(row['close'])
        ld_count = int(row['open']) if row['open'] > 0 else 0
        year = int(dt[:4])
        total = TOTAL_STOCKS.get(year, 5300)
        cache[dt] = {"count": count, "ratio": count / total, "limitdown_count": ld_count}
        print(f"  {dt}: limitup={count}, limitdown={ld_count}")

with open('data/limitup_cache.json', 'w') as f:
    json.dump(cache, f, ensure_ascii=False)
print(f"Cache now has {len(cache)} entries")
