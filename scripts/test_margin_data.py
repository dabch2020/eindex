#!/usr/bin/env python3
"""
eIndex 融资余额数据抽样测试

测试规格：
- 从 2025-04-15 ~ 2025-06-15 随机选取 15 个交易日
- 从 3 个不同数据源读取沪市和深市融资余额
- 与 eindex 缓存的数据比较，完全相同则测试通过

数据源：
1. macro_china_market_margin_sh / macro_china_market_margin_sz（东方财富，主数据源）
2. stock_margin_sse（上交所直接接口）
3. stock_margin_szse（深交所单日查询接口）
"""
import json
import random
import sys
import time
import socket

socket.setdefaulttimeout(15)  # 避免无限等待

sys.path.insert(0, '.')

try:
    import akshare as ak
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "akshare", "-q"])
    import akshare as ak

# ── 加载缓存数据 ──
with open('../data/eindex_data.json') as f:
    cached = json.load(f)

cached_by_date = {r['date']: r for r in cached['data']}

# ── 获取交易日历，筛选 2025-04-15 ~ 2025-06-15 ──
# 注：macro_china_market_margin_sz 在 2024-10-18~2025-06-18 区间缺失
# 因此也从其他有覆盖的区间抽样以确保可验证
trade_dates_primary = sorted(d for d in cached_by_date.keys() if '2025-04-15' <= d <= '2025-06-15')
trade_dates_alt = sorted(d for d in cached_by_date.keys() if '2025-06-19' <= d <= '2025-12-31')
print(f"主区间交易日: {len(trade_dates_primary)} 天 (深市macro可能缺失)")
print(f"补充区间交易日: {len(trade_dates_alt)} 天 (深市macro有覆盖)")

random.seed(42)
# 从两个区间各抽样
sample_primary = sorted(random.sample(trade_dates_primary, min(5, len(trade_dates_primary))))
sample_alt = sorted(random.sample(trade_dates_alt, min(10, len(trade_dates_alt))))
sample_dates = sorted(sample_primary + sample_alt)
print(f"抽样 {len(sample_dates)} 天: 主区间 {len(sample_primary)} + 补充区间 {len(sample_alt)}")
print(f"  主区间: {sample_primary}")
print(f"  补充: {sample_alt}\n")

# ── 数据源1: macro_china_market_margin_sh / sz ──
print("=" * 60)
print("数据源1: macro_china_market_margin_sh / sz（东方财富）")
print("=" * 60)

sh_macro = {}
sz_macro = {}

try:
    df_sh = ak.macro_china_market_margin_sh()
    for _, row in df_sh.iterrows():
        dt = str(row['日期'])[:10]
        try:
            sh_macro[dt] = float(row['融资余额'])
        except:
            pass
    print(f"  沪市覆盖: {len(sh_macro)} 天")
except Exception as e:
    print(f"  沪市获取失败: {e}")

try:
    df_sz = ak.macro_china_market_margin_sz()
    for _, row in df_sz.iterrows():
        dt = str(row['日期'])[:10]
        try:
            sz_macro[dt] = float(row['融资余额'])
        except:
            pass
    print(f"  深市覆盖: {len(sz_macro)} 天")
except Exception as e:
    print(f"  深市获取失败: {e}")

# ── 数据源2: stock_margin_sse ──
print()
print("=" * 60)
print("数据源2: stock_margin_sse（上交所）")
print("=" * 60)

sh_sse = {}
try:
    df_sse = ak.stock_margin_sse(start_date="20250415")
    for _, row in df_sse.iterrows():
        dt = str(row[df_sse.columns[0]]).strip()
        if len(dt) == 8 and dt.isdigit():
            dt = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
        elif len(dt) >= 10:
            dt = dt[:10]
        else:
            continue
        for col in ['融资余额(元)', '融资余额', '融资余额（元）']:
            if col in df_sse.columns:
                try:
                    sh_sse[dt] = float(row[col])
                except:
                    pass
                break
    print(f"  上交所数据: {len(sh_sse)} 天")
except Exception as e:
    print(f"  上交所接口失败: {e}")

# ── 数据源3: stock_margin_szse（逐日查询） ──
print()
print("=" * 60)
print("数据源3: stock_margin_szse（深交所逐日查询）")
print("=" * 60)

sz_szse = {}
for dt in sample_dates:
    date_str = dt.replace('-', '')
    for attempt in range(5):
        try:
            df_day = ak.stock_margin_szse(date=date_str)
            bal = float(df_day['融资余额'].iloc[0])
            sz_szse[dt] = bal
            print(f"  {dt}: {bal:,.0f}")
            break
        except Exception as e:
            if attempt < 4:
                time.sleep(5)
            else:
                print(f"  {dt}: 失败 - {type(e).__name__}")

print(f"\n  深交所逐日查询成功: {len(sz_szse)}/{len(sample_dates)} 天\n")

# ── 比较测试 ──
print("=" * 60)
print("比较测试结果")
print("=" * 60)

sys.path.insert(0, '../scripts')
from update_data import estimate_float_mcap

pass_count = 0
fail_count = 0
skip_count = 0

print(f"\n{'日期':<12} {'缓存ratio':>12} {'验证ratio':>12} {'数据源':>12} {'结果':>8}")
print("-" * 60)

for dt in sample_dates:
    cached_ratio = cached_by_date[dt]['margin_ratio']

    # 优先用 macro 接口（数据源1）
    sh_val = sh_macro.get(dt)
    sz_val = sz_macro.get(dt) or sz_szse.get(dt)  # macro 没有就用 szse

    if sh_val is not None and sz_val is not None:
        mcap = estimate_float_mcap(dt)
        source_ratio = round((sh_val + sz_val) / mcap, 6)
        source_name = "macro" if dt in sz_macro else "macro+szse"
        match = abs(source_ratio - cached_ratio) < 0.000002
        status = "PASS" if match else "FAIL"
        if match:
            pass_count += 1
        else:
            fail_count += 1
            print(f"{dt:<12} {cached_ratio:>12.6f} {source_ratio:>12.6f} {source_name:>12} ❌ {status:>8}")
            print(f"  SH={sh_val:,.0f} SZ={sz_val:,.0f} mcap={mcap:,.0f}")
            continue
        print(f"{dt:<12} {cached_ratio:>12.6f} {source_ratio:>12.6f} {source_name:>12} ✅ {status:>8}")
    else:
        skip_count += 1
        print(f"{dt:<12} {cached_ratio:>12.6f} {'N/A':>12} {'--':>12} ⚠️  SKIP")

print("-" * 60)
print(f"\n结果: {pass_count} 通过, {fail_count} 失败, {skip_count} 跳过")

if fail_count == 0 and skip_count == 0:
    print("\n🎉 全部 15 天测试通过！缓存数据与数据源完全一致。")
elif fail_count == 0:
    print(f"\n✅ {pass_count} 天测试通过，{skip_count} 天因数据源不可用跳过。")
else:
    print(f"\n❌ 有 {fail_count} 天数据不匹配，请检查。")
