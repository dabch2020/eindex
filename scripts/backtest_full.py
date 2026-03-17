#!/usr/bin/env python3
"""
扩展回测：16 个人工标注 + 880008 全A等权指数阶段高低点自动检测
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_FILE = DATA_DIR / "eindex_data.json"
RETURN_CACHE = DATA_DIR / "return_cache.json"

# ── 加载数据 ──
d = json.load(open(DATA_FILE))['data']
by_date = {r['date']: r for r in d}
all_dates = sorted(by_date.keys())
date_idx = {dt: i for i, dt in enumerate(all_dates)}

returns = json.load(open(RETURN_CACHE))

# ── 人工标注 ──
HUMAN_FEAR = ['2022-04-27','2022-10-31','2023-06-26','2023-10-23',
              '2024-02-05','2024-09-18','2025-04-09','2025-06-23']
HUMAN_GREED = ['2022-01-04','2022-07-04','2023-01-30','2023-07-31',
               '2024-05-10','2024-10-08','2025-05-14','2025-10-09']

# ── 从 880008 收益率重建价格序列，检测阶段高低点 ──
# 用 return_cache 中的累积收益来近似价格走势
ret_dates = sorted(dt for dt in returns.keys() if dt in by_date)
# 重建价格指数（从 100 开始）
price = {}
p = 100.0
for dt in ret_dates:
    # 3日收益率 → 近似日收益率（取 1/3 作为日变化）
    p *= (1 + returns[dt] / 3)
    price[dt] = p

price_dates = sorted(price.keys())
price_list = [price[dt] for dt in price_dates]


def find_local_extrema(dates, values, window=20, min_gap=10):
    """检测局部极值点。
    window: 前后各看 window 个交易日
    min_gap: 相邻极值点最少间隔交易日数
    """
    n = len(dates)
    highs = []  # (date, price) - 阶段高点 → 贪婪
    lows = []   # (date, price) - 阶段低点 → 恐惧

    for i in range(window, n - window):
        v = values[i]
        local = values[i - window: i + window + 1]
        if v == max(local):
            highs.append((dates[i], v))
        elif v == min(local):
            lows.append((dates[i], v))

    # 去掉间隔过近的点（保留更极端的）
    def dedupe(points, keep_max=True):
        if not points:
            return points
        result = [points[0]]
        for dt, v in points[1:]:
            prev_dt = result[-1][0]
            prev_idx = date_idx.get(prev_dt, 0)
            cur_idx = date_idx.get(dt, 0)
            if cur_idx - prev_idx < min_gap:
                # 保留更极端的
                if keep_max and v > result[-1][1]:
                    result[-1] = (dt, v)
                elif not keep_max and v < result[-1][1]:
                    result[-1] = (dt, v)
            else:
                result.append((dt, v))
        return result

    highs = dedupe(highs, keep_max=True)
    lows = dedupe(lows, keep_max=False)
    return highs, lows


# 用不同窗口大小来获取更多点
all_highs = {}
all_lows = {}
for w in [15, 20, 30, 40, 60]:
    highs, lows = find_local_extrema(price_dates, price_list, window=w, min_gap=8)
    for dt, v in highs:
        if dt not in all_highs or v > all_highs[dt]:
            all_highs[dt] = v
    for dt, v in lows:
        if dt not in all_lows or v < all_lows[dt]:
            all_lows[dt] = v

# 排除人工标注的日期（±5日范围内）
def is_near_human(dt, human_dates, tol=5):
    if dt not in date_idx:
        return False
    idx = date_idx[dt]
    for hd in human_dates:
        if hd in date_idx:
            if abs(date_idx[hd] - idx) <= tol:
                return True
    return False

auto_greed = sorted(dt for dt in all_highs if not is_near_human(dt, HUMAN_GREED + HUMAN_FEAR))
auto_fear = sorted(dt for dt in all_lows if not is_near_human(dt, HUMAN_FEAR + HUMAN_GREED))

# 限制到合理数量（各约50个），取分布均匀的
def sample_evenly(dates, target=50):
    if len(dates) <= target:
        return dates
    step = len(dates) / target
    return [dates[int(i * step)] for i in range(target)]

auto_greed = sample_evenly(auto_greed, 50)
auto_fear = sample_evenly(auto_fear, 50)

print(f'880008 自动检测: 高点(贪婪) {len(auto_greed)} 个, 低点(恐惧) {len(auto_fear)} 个')

# ── 信号判定 ──
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
    for off in range(0, tol + 1):
        for sign in ([0] if off == 0 else [off, -off]):
            j = idx + sign
            if 0 <= j < len(all_dates):
                r = by_date[all_dates[j]]
                if get_sig(r) == expected:
                    return all_dates[j], sign
    return None, None

def test_group(label, expected, dates, show_detail=False):
    exact = 0; t3 = 0; t5 = 0; t10 = 0
    total = len(dates)
    for dt in dates:
        r = by_date.get(dt)
        if not r:
            continue
        sig = get_sig(r)
        if sig == expected:
            exact += 1

        h3, _ = find_nearby(dt, expected, 3)
        h5, _ = find_nearby(dt, expected, 5)
        h10, _ = find_nearby(dt, expected, 10)
        if h3: t3 += 1
        if h5: t5 += 1
        if h10: t10 += 1

        if show_detail:
            e_str = 'Y' if sig == expected else 'N'
            t3s = 'Y' if h3 else 'N'
            t5s = 'Y' if h5 else 'N'
            print(f'    {dt}  eI={r["eindex"]:5.1f}  th={r.get("fear_threshold",0):5.1f}/{r.get("greed_threshold",0):5.1f}  [{sig:>7}]  exact={e_str} ±3={t3s} ±5={t5s}')

    return total, exact, t3, t5, t10


# ── 输出 ──
print()
print('=' * 90)
print('eIndex 扩展回测 — 人工标注 + 880008 阶段高低点')
print('=' * 90)
print(f'数据: {all_dates[0]} ~ {all_dates[-1]}, {len(all_dates)} 交易日')
print(f'参数: LOOKBACK=3, WINDOW=200, FEAR=10, GREED=85')
print()

# 1. 人工标注
print('━' * 90)
print('【1. 人工标注恐惧日】(8个)')
print('━' * 90)
hf_n, hf_e, hf_3, hf_5, hf_10 = test_group('HUMAN_FEAR', 'FEAR', HUMAN_FEAR, show_detail=True)

print()
print('━' * 90)
print('【2. 人工标注贪婪日】(8个)')
print('━' * 90)
hg_n, hg_e, hg_3, hg_5, hg_10 = test_group('HUMAN_GREED', 'GREED', HUMAN_GREED, show_detail=True)

print()
print('━' * 90)
print(f'【3. 880008 自动检测低点（恐惧）】({len(auto_fear)}个)')
print('━' * 90)
af_n, af_e, af_3, af_5, af_10 = test_group('AUTO_FEAR', 'FEAR', auto_fear, show_detail=True)

print()
print('━' * 90)
print(f'【4. 880008 自动检测高点（贪婪）】({len(auto_greed)}个)')
print('━' * 90)
ag_n, ag_e, ag_3, ag_5, ag_10 = test_group('AUTO_GREED', 'GREED', auto_greed, show_detail=True)

# ── 汇总 ──
print()
print('=' * 90)
print('命中率汇总')
print('=' * 90)
print(f'{"类别":>20} | {"数量":>4} | {"精确":>12} | {"±3日":>12} | {"±5日":>12} | {"±10日":>12}')
print('-' * 90)

def fmt(n, total):
    return f'{n}/{total} ({n/total*100:5.1f}%)' if total > 0 else 'N/A'

print(f'{"人工-恐惧":>20} | {hf_n:>4} | {fmt(hf_e,hf_n):>12} | {fmt(hf_3,hf_n):>12} | {fmt(hf_5,hf_n):>12} | {fmt(hf_10,hf_n):>12}')
print(f'{"人工-贪婪":>20} | {hg_n:>4} | {fmt(hg_e,hg_n):>12} | {fmt(hg_3,hg_n):>12} | {fmt(hg_5,hg_n):>12} | {fmt(hg_10,hg_n):>12}')
print(f'{"自动-恐惧(低点)":>20} | {af_n:>4} | {fmt(af_e,af_n):>12} | {fmt(af_3,af_n):>12} | {fmt(af_5,af_n):>12} | {fmt(af_10,af_n):>12}')
print(f'{"自动-贪婪(高点)":>20} | {ag_n:>4} | {fmt(ag_e,ag_n):>12} | {fmt(ag_3,ag_n):>12} | {fmt(ag_5,ag_n):>12} | {fmt(ag_10,ag_n):>12}')
print('-' * 90)

# 人工合计
h_n = hf_n + hg_n
h_e = hf_e + hg_e
h_3 = hf_3 + hg_3
h_5 = hf_5 + hg_5
h_10 = hf_10 + hg_10
print(f'{"人工合计":>20} | {h_n:>4} | {fmt(h_e,h_n):>12} | {fmt(h_3,h_n):>12} | {fmt(h_5,h_n):>12} | {fmt(h_10,h_n):>12}')

# 自动合计
a_n = af_n + ag_n
a_e = af_e + ag_e
a_3 = af_3 + ag_3
a_5 = af_5 + ag_5
a_10 = af_10 + ag_10
print(f'{"自动合计":>20} | {a_n:>4} | {fmt(a_e,a_n):>12} | {fmt(a_3,a_n):>12} | {fmt(a_5,a_n):>12} | {fmt(a_10,a_n):>12}')

# 总计
t_n = h_n + a_n
t_e = h_e + a_e
t_3 = h_3 + a_3
t_5 = h_5 + a_5
t_10 = h_10 + a_10
print(f'{"全部合计":>20} | {t_n:>4} | {fmt(t_e,t_n):>12} | {fmt(t_3,t_n):>12} | {fmt(t_5,t_n):>12} | {fmt(t_10,t_n):>12}')

# ── 信号分布 ──
print()
print('=' * 90)
print('信号分布')
print('=' * 90)
fear_cnt = sum(1 for r in d if get_sig(r) == 'FEAR')
greed_cnt = sum(1 for r in d if get_sig(r) == 'GREED')
neutral_cnt = len(d) - fear_cnt - greed_cnt
print(f'恐惧: {fear_cnt} 天 ({fear_cnt/len(d)*100:.1f}%)')
print(f'贪婪: {greed_cnt} 天 ({greed_cnt/len(d)*100:.1f}%)')
print(f'中性: {neutral_cnt} 天 ({neutral_cnt/len(d)*100:.1f}%)')

# ── 随机基准对比 ──
print()
print('=' * 90)
print('随机基准对比（如果随机选日期，期望命中率）')
print('=' * 90)
fear_pct = fear_cnt / len(d) * 100
greed_pct = greed_cnt / len(d) * 100
print(f'随机选一天恰好是恐惧信号的概率: {fear_pct:.1f}%')
print(f'随机选一天恰好是贪婪信号的概率: {greed_pct:.1f}%')
# ±5日容差下的随机期望
# P(至少1天命中) = 1 - (1-p)^11（11个交易日窗口）
import math
p_fear_5 = 1 - (1 - fear_cnt/len(d))**11
p_greed_5 = 1 - (1 - greed_cnt/len(d))**11
print(f'随机±5日容差下恐惧命中概率: {p_fear_5*100:.1f}%')
print(f'随机±5日容差下贪婪命中概率: {p_greed_5*100:.1f}%')
print()
print(f'实际 vs 随机基准:')
if af_n > 0:
    print(f'  自动恐惧 ±5日命中 {af_5/af_n*100:.1f}% vs 随机 {p_fear_5*100:.1f}%  → {af_5/af_n/p_fear_5:.1f}x 提升')
if ag_n > 0:
    print(f'  自动贪婪 ±5日命中 {ag_5/ag_n*100:.1f}% vs 随机 {p_greed_5*100:.1f}%  → {ag_5/ag_n/p_greed_5:.1f}x 提升')
if h_n > 0:
    avg_hit = h_5 / h_n
    avg_random = (p_fear_5 + p_greed_5) / 2
    print(f'  人工标注 ±5日命中 {avg_hit*100:.1f}% vs 随机 {avg_random*100:.1f}%  → {avg_hit/avg_random:.1f}x 提升')
