#!/usr/bin/env python3
"""Patch eindex_data.json to add limitdown_count from limitup_cache.json."""
import json

cache = json.load(open('data/limitup_cache.json'))
data = json.load(open('data/eindex_data.json'))

patched = 0
for record in data['data']:
    dt = record['date']
    if dt in cache:
        entry = cache[dt]
        if isinstance(entry, dict):
            record['limitdown_count'] = entry.get('limitdown_count', 0)
            record['limitup_count'] = entry.get('count', record.get('limitup_count', 0))
            record['limitup_ratio'] = round(entry.get('ratio', record.get('limitup_ratio', 0)), 6)
        else:
            record['limitdown_count'] = 0
        patched += 1
    else:
        record['limitdown_count'] = 0

with open('data/eindex_data.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)

# Also update eindex_data.js
js_text = 'var EINDEX_DATA = ' + json.dumps(data, ensure_ascii=False) + ';\n'
with open('data/eindex_data.js', 'w', encoding='utf-8') as f:
    f.write(js_text)

print(f'Patched {patched} records with limitdown_count')
# Verify
last = data['data'][-1]
print(f"Last: {last['date']} limitup={last['limitup_count']} limitdown={last['limitdown_count']}")
prev = data['data'][-5]
print(f"-5: {prev['date']} limitup={prev['limitup_count']} limitdown={prev['limitdown_count']}")
