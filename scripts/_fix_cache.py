#!/usr/bin/env python3
"""手动补充缓存数据（从之前成功的API调用结果）"""
import json
import sys
sys.path.insert(0, 'scripts')
from update_data import get_float_mcap

# Data from earlier successful _fetch_index_amount_em call
amounts = {
    '2026-03-23': {'sh': 10862.4800, 'sz': 13452.9900},
    '2026-03-24': {'sh': 9314.1900, 'sz': 11514.4900},
    '2026-03-25': {'sh': 6539.7400, 'sz': 8129.3300},
}

# Update cje_cache
with open('data/cje_cache.json') as f:
    cje = json.load(f)
for dt, v in amounts.items():
    cje[dt] = {'sh': v['sh'], 'sz': v['sz']}
with open('data/cje_cache.json', 'w') as f:
    json.dump(cje, f, ensure_ascii=False, indent=2)
print('cje_cache updated')

# Update turn_rate_cache
with open('data/turn_rate_cache.json') as f:
    tc = json.load(f)

for dt, v in amounts.items():
    total_yuan = (v['sh'] + v['sz']) * 1e8
    mcap = get_float_mcap(dt)
    if mcap and mcap > 0:
        rate = total_yuan / (mcap * 1e8)
        tc[dt] = {'sh_amount': v['sh'], 'sz_amount': v['sz'], 'turnover_rate': round(rate, 8)}
        print(f'{dt}: mcap={mcap:.0f} turnover={rate:.8f} OK')
    else:
        print(f'{dt}: mcap=None SKIP')

with open('data/turn_rate_cache.json', 'w') as f:
    json.dump(tc, f, ensure_ascii=False, indent=2)
print('turn_rate_cache updated')
