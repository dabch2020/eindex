#!/usr/bin/env python3
"""校验最近30个交易日的缓存数据是否与源API一致"""
import json, requests, socket, sys, time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'

# Load existing data
with open(DATA_DIR / 'eindex_data.json') as f:
    edata = json.load(f)

last30 = edata['data'][-30:]
dates = [d['date'] for d in last30]
print(f'校验范围: {dates[0]} ~ {dates[-1]} ({len(dates)} 天)\n')

# 1) Fetch fresh CJE from Tencent API
fresh_cje = {}
for code in ['sh000001', 'sz399001']:
    url = (f'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get'
           f'?param={code},day,{dates[0]},{dates[-1]},60,qfq')
    r = requests.get(url, timeout=15)
    data = r.json()
    key = list(data['data'].keys())[0]
    klines = data['data'][key].get('day') or data['data'][key].get('qfqday', [])
    mkt = 'sh' if 'sh' in code else 'sz'
    for row in klines:
        dt = row[0]
        amt_yi = float(str(row[8]).replace(',', '')) / 10000  # 万元→亿元
        if dt not in fresh_cje:
            fresh_cje[dt] = {}
        fresh_cje[dt][mkt] = round(amt_yi, 4)

# 2) Fetch fresh limitup/limitdown from mootdx 880006
socket.setdefaulttimeout(10)
from mootdx.quotes import Quotes
client = Quotes.factory(market='std')
import pandas as pd

all_mootdx = []
for start in range(0, 1600, 800):
    data = client.index(symbol='880006', frequency=9, start=start, offset=800)
    if data is None or len(data) == 0:
        break
    all_mootdx.append(data)
    if len(data) < 800:
        break
    time.sleep(0.3)

mootdx_df = pd.concat(all_mootdx)
mootdx_df = mootdx_df[~mootdx_df.index.duplicated(keep='first')]
fresh_lu = {}
fresh_ld = {}
for idx, row in mootdx_df.iterrows():
    dt = idx.strftime('%Y-%m-%d')
    fresh_lu[dt] = int(row['close'])
    fresh_ld[dt] = int(row['open'])

# 3) Compare
hdr = f'{"日期":>12} {"缓存CJE":>10} {"实际CJE":>10} {"CJE差":>8} {"缓存涨停":>8} {"实际涨停":>8} {"缓存跌停":>8} {"实际跌停":>8}'
print(hdr)
print('-' * len(hdr.encode('gbk')))

issues = []
for d in last30:
    dt = d['date']
    cached_cje = d.get('cje_amount', 0)
    fresh = fresh_cje.get(dt, {})
    actual_cje = round(fresh.get('sh', 0) + fresh.get('sz', 0), 2) if fresh else 0
    cje_diff = round(cached_cje - actual_cje, 2) if actual_cje > 0 else 0

    cached_lu = d.get('limitup_count', 0)
    actual_lu = fresh_lu.get(dt, 0)
    cached_ld = d.get('limitdown_count', 0)
    actual_ld = fresh_ld.get(dt, 0)

    flag = ''
    problems = []
    if actual_cje > 0 and abs(cje_diff) > 1:
        problems.append(f'CJE差{cje_diff:+.0f}')
    if actual_lu > 0 and cached_lu != actual_lu:
        problems.append(f'涨停{cached_lu}→{actual_lu}')
    if actual_ld > 0 and cached_ld != actual_ld:
        problems.append(f'跌停{cached_ld}→{actual_ld}')

    if problems:
        flag = ' ⚠ ' + ', '.join(problems)
        issues.append((dt, problems))

    print(f'{dt:>12} {cached_cje:>10.2f} {actual_cje:>10.2f} {cje_diff:>+8.2f} {cached_lu:>8} {actual_lu:>8} {cached_ld:>8} {actual_ld:>8}{flag}')

print()
if issues:
    print(f'⚠ 发现 {len(issues)} 天数据不一致:')
    for dt, probs in issues:
        print(f'  {dt}: {", ".join(probs)}')
else:
    print('✅ 最近30天数据全部一致')
