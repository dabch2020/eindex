#!/usr/bin/env python3
"""补漏测试日期的深市融资余额数据"""
import json, time, sys
sys.path.insert(0, '.')
import akshare as ak

CACHE_FILE = 'data/margin_cache.json'

with open(CACHE_FILE) as f:
    cache = json.load(f)

dates = ['2025-04-08', '2025-04-09', '2025-04-10']
for dt in dates:
    if 'sz' in cache.get(dt, {}):
        print(f'{dt}: already have sz={cache[dt]["sz"]}')
        continue
    date_str = dt.replace('-', '')
    for attempt in range(5):
        try:
            df = ak.stock_margin_szse(date=date_str)
            bal = float(df['融资余额'].iloc[0])
            if dt not in cache:
                cache[dt] = {}
            cache[dt]['sz'] = round(bal, 4)
            print(f'{dt}: filled sz={bal:.4f}')
            break
        except Exception as e:
            if attempt < 4:
                print(f'{dt}: attempt {attempt+1} failed, wait 5s...')
                time.sleep(5)
            else:
                print(f'{dt}: all 5 attempts failed: {e}')

with open(CACHE_FILE, 'w', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)
print('cache saved')
