#!/usr/bin/env python3
"""Split limitdown_count from limitup_cache.json into a separate limitdown_cache.json."""
import json, sys, os

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

TOTAL_STOCKS = {
    2016: 3000, 2017: 3400, 2018: 3500, 2019: 3700, 2020: 4000,
    2021: 4400, 2022: 4800, 2023: 5200, 2024: 5300, 2025: 5400, 2026: 5500,
}

lu_cache = json.load(open('data/limitup_cache.json'))
ld_cache = {}

for dt, entry in lu_cache.items():
    if isinstance(entry, dict):
        ld_count = entry.pop('limitdown_count', 0)
        year = int(dt[:4])
        total = TOTAL_STOCKS.get(year, 5300)
        ld_cache[dt] = {"count": ld_count, "ratio": ld_count / total}

# Save limitdown_cache
with open('data/limitdown_cache.json', 'w') as f:
    json.dump(ld_cache, f, ensure_ascii=False, indent=2)

# Save cleaned limitup_cache (without limitdown_count)
with open('data/limitup_cache.json', 'w') as f:
    json.dump(lu_cache, f, ensure_ascii=False, indent=2)

print(f"Created limitdown_cache.json: {len(ld_cache)} entries")
print(f"Cleaned limitup_cache.json: {len(lu_cache)} entries")

# Verify
dates = sorted(ld_cache.keys())
print(f"Sample last: {dates[-1]} -> {ld_cache[dates[-1]]}")
print(f"Sample -5: {dates[-5]} -> {ld_cache[dates[-5]]}")
dates_lu = sorted(lu_cache.keys())
print(f"limitup last: {dates_lu[-1]} -> {lu_cache[dates_lu[-1]]}")
