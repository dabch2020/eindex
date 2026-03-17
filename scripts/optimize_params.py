#!/usr/bin/env python3
"""
参数优化脚本：以人工标注的恐惧/贪婪日期为主要基准，
辅以 880008 全A等权指数局部极值，网格搜索最优参数组合。

评分逻辑：
  - 人工标注日期权重 = 3（主导），880008 自动检测日期权重 = 1（辅助）
  - 对 PERCENTILE_WINDOW / FEAR_PERCENTILE / GREED_PERCENTILE 做网格搜索
  - 综合得分 = 加权恐惧命中率 + 加权贪婪命中率 - 噪音惩罚

用法：
  python scripts/optimize_params.py
  python scripts/optimize_params.py --tolerance 5   # 前后5个交易日内算命中（默认3）
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"


def fetch_880008():
    """获取 880008 全A等权指数历史日线数据"""
    from mootdx.quotes import Quotes
    import socket
    socket.setdefaulttimeout(10)

    client = Quotes.factory(market='std')
    all_data = []
    for start in range(0, 5000, 800):
        data = client.index(symbol='880008', frequency=9, start=start, offset=800) # type: ignore
        if data is None or len(data) == 0:
            break
        all_data.append(data)
        if len(data) < 800:
            break
        time.sleep(0.5)

    if not all_data:
        raise RuntimeError("无法获取 880008 数据")

    combined = pd.concat(all_data)
    combined = combined[~combined.index.duplicated(keep='first')]
    combined = combined.sort_index()

    # 转为简单的 date -> close 字典
    result = {}
    for idx, row in combined.iterrows():
        dt = idx.strftime('%Y-%m-%d')
        result[dt] = float(row['close'])
    return result


def find_peaks_and_troughs(prices, peak_window=30):
    """找出局部高点（贪婪日）和局部低点（恐惧日）。
    peak_window: 在前后各 peak_window 个交易日内是最高/最低的，才算极值点。"""
    dates = sorted(prices.keys())
    values = [prices[d] for d in dates]
    n = len(values)

    greed_dates = []  # 局部高点
    fear_dates = []   # 局部低点

    for i in range(peak_window, n - peak_window):
        window = values[i - peak_window: i + peak_window + 1]
        v = values[i]
        if v == max(window):
            greed_dates.append(dates[i])
        if v == min(window):
            fear_dates.append(dates[i])

    return fear_dates, greed_dates


def load_raw_indicators():
    """从缓存文件加载原始指标数据（不依赖 eindex_data.json 中的参数）"""
    # 成交额
    cje_path = DATA_DIR / "cje_cache.json"
    cje = {}
    if cje_path.exists():
        with open(cje_path) as f:
            raw = json.load(f)
        for dt, v in raw.items():
            total = v.get('sh', 0) + v.get('sz', 0)
            if total > 0:
                cje[dt] = total

    # 融资余额
    margin_path = DATA_DIR / "margin_cache.json"
    ltsz_path = DATA_DIR / "ltsz_cache.json"
    margin_ratio = {}
    if margin_path.exists() and ltsz_path.exists():
        with open(margin_path) as f:
            mc = json.load(f)
        with open(ltsz_path) as f:
            lc = json.load(f)

        # 计算 SH/SZ 比值用于估算
        ratios = []
        for dt in sorted(lc.keys()):
            e = lc[dt]
            if e.get('sh', 0) > 0 and e.get('sz', 0) > 0 and dt >= '2018-01-01':
                ratios.append(e['sh'] / e['sz'])
                if len(ratios) >= 20:
                    break
        sh_sz_ratio = sorted(ratios)[len(ratios)//2] if ratios else 1.85

        for dt, v in mc.items():
            sh = v.get('sh', 0)
            sz = v.get('sz', 0)
            if sh > 0 and sz > 0:
                total_margin = sh + sz
            else:
                continue
            # 流通市值
            le = lc.get(dt)
            if not le:
                continue
            lsh = le.get('sh', 0)
            lsz = le.get('sz', 0)
            if lsh > 0 and lsz > 0:
                mcap = lsh + lsz
            elif lsz > 0:
                mcap = lsz * (1 + sh_sz_ratio)
            else:
                continue
            if mcap > 0:
                margin_ratio[dt] = total_margin / mcap

    # 涨停
    limitup_path = DATA_DIR / "limitup_cache.json"
    limitup = {}
    if limitup_path.exists():
        with open(limitup_path) as f:
            raw = json.load(f)
        for dt, v in raw.items():
            if isinstance(v, dict):
                limitup[dt] = v.get('ratio', 0)
            else:
                limitup[dt] = float(v)

    return cje, margin_ratio, limitup


def load_880008_returns(lookback=3):
    """加载 880008 收益率缓存，或从 880008 价格数据计算 N 日收益率"""
    return_cache_path = DATA_DIR / "return_cache.json"
    if return_cache_path.exists():
        with open(return_cache_path) as f:
            return json.load(f)

    # 如果没有缓存，从 880008 价格计算
    prices = fetch_880008()
    sorted_dates = sorted(prices.keys())
    returns = {}
    for i, dt in enumerate(sorted_dates):
        if i < lookback:
            continue
        prev_dt = sorted_dates[i - lookback]
        prev_close = prices[prev_dt]
        cur_close = prices[dt]
        if prev_close > 0:
            returns[dt] = round((cur_close - prev_close) / prev_close, 6)
    return returns


def simulate_eindex(trade_dates, cje, margin_ratio, limitup, window, returns=None):
    """用指定 window 重新计算每天的 eIndex（模拟 compute_percentile）"""

    def pct(history, current, w):
        if len(history) < 2:
            return 50.0
        recent = history[-w:] if len(history) >= w else history
        rank = sum(1 for v in recent if v <= current)
        return (rank / len(recent)) * 100

    cje_hist, m_hist, l_hist, ret_hist = [], [], [], []
    results = {}  # date -> eindex

    for dt in trade_dates:
        c_val = cje.get(dt)
        m_val = margin_ratio.get(dt)
        l_val = limitup.get(dt)
        r_val = returns.get(dt) if returns else None

        if c_val is not None and c_val > 0:
            cje_hist.append(c_val)
        if m_val is not None:
            m_hist.append(m_val)
        if l_val is not None and l_val > 0:
            l_hist.append(l_val)
        if r_val is not None:
            ret_hist.append(r_val)

        if c_val is None and m_val is None and l_val is None:
            continue

        pcts = []
        if c_val is not None and c_val > 0:
            pcts.append(pct(cje_hist, c_val, window))
        if m_val is not None:
            pcts.append(pct(m_hist, m_val, window))
        if l_val is not None and l_val > 0:
            pcts.append(pct(l_hist, l_val, window))
        if r_val is not None:
            pcts.append(pct(ret_hist, r_val, window))

        if not pcts:
            continue
        results[dt] = sum(pcts) / len(pcts)

    return results


def compute_thresholds_for_date(eindex_history, window, fear_pct, greed_pct):
    """给定 eIndex 历史序列，计算当天的动态阈值"""
    if len(eindex_history) < 2:
        return fear_pct, greed_pct
    recent = eindex_history[-window:] if len(eindex_history) >= window else eindex_history
    s = sorted(recent)
    n = len(s)
    fi = max(0, int(n * fear_pct / 100) - 1)
    gi = min(n - 1, int(n * greed_pct / 100))
    return s[fi], s[gi]


# ── 人工标注的恐惧/贪婪日期（权重最高） ──
HUMAN_FEAR_DATES = [
    "2022-04-27", "2022-10-31", "2023-06-26", "2023-10-23",
    "2024-02-05", "2024-09-18", "2025-04-09", "2025-06-23",
]
HUMAN_GREED_DATES = [
    "2022-01-04", "2022-07-04", "2023-01-30", "2023-07-31",
    "2024-05-10", "2024-10-08", "2025-05-14", "2025-10-09",
]

HUMAN_WEIGHT = 3  # 人工标注权重
AUTO_WEIGHT = 1   # 880008 自动检测权重


def _check_hits(target_dates, signal_type, signal, date_to_idx, trade_dates, tolerance):
    """检查 target_dates 中有多少在 ±tolerance 内产生了 signal_type 信号"""
    hits = 0
    total = 0
    for fd in target_dates:
        if fd not in date_to_idx:
            continue
        total += 1
        fi = date_to_idx[fd]
        for offset in range(-tolerance, tolerance + 1):
            j = fi + offset
            if 0 <= j < len(trade_dates):
                if signal.get(trade_dates[j]) == signal_type:
                    hits += 1
                    break
    return hits, total


def evaluate_params(trade_dates, eindex_by_date,
                    human_fear, human_greed,
                    auto_fear_set, auto_greed_set,
                    window, fear_pct, greed_pct, tolerance=3):
    """评估一组参数的得分（人工标注 3x 权重 + 880008 自动检测 1x 权重）。"""
    eindex_hist = []
    signal = {}

    for dt in trade_dates:
        ei = eindex_by_date.get(dt)
        if ei is None:
            continue
        fear_th, greed_th = compute_thresholds_for_date(eindex_hist, window, fear_pct, greed_pct)
        if ei <= fear_th:
            signal[dt] = 'fear'
        elif ei >= greed_th:
            signal[dt] = 'greed'
        else:
            signal[dt] = 'neutral'
        eindex_hist.append(ei)

    date_to_idx = {d: i for i, d in enumerate(trade_dates)}

    # 人工标注命中率
    h_fear_hits, h_fear_total = _check_hits(human_fear, 'fear', signal, date_to_idx, trade_dates, tolerance)
    h_greed_hits, h_greed_total = _check_hits(human_greed, 'greed', signal, date_to_idx, trade_dates, tolerance)

    # 880008 自动检测命中率
    a_fear_hits, a_fear_total = _check_hits(auto_fear_set, 'fear', signal, date_to_idx, trade_dates, tolerance)
    a_greed_hits, a_greed_total = _check_hits(auto_greed_set, 'greed', signal, date_to_idx, trade_dates, tolerance)

    # 加权命中率
    fear_numer = HUMAN_WEIGHT * h_fear_hits + AUTO_WEIGHT * a_fear_hits
    fear_denom = HUMAN_WEIGHT * h_fear_total + AUTO_WEIGHT * a_fear_total
    greed_numer = HUMAN_WEIGHT * h_greed_hits + AUTO_WEIGHT * a_greed_hits
    greed_denom = HUMAN_WEIGHT * h_greed_total + AUTO_WEIGHT * a_greed_total

    fear_rate = fear_numer / fear_denom if fear_denom > 0 else 0
    greed_rate = greed_numer / greed_denom if greed_denom > 0 else 0

    # 人工标注单独命中率（用于输出）
    h_fear_rate = h_fear_hits / h_fear_total if h_fear_total > 0 else 0
    h_greed_rate = h_greed_hits / h_greed_total if h_greed_total > 0 else 0

    # 噪音惩罚
    fear_signals = sum(1 for v in signal.values() if v == 'fear')
    greed_signals = sum(1 for v in signal.values() if v == 'greed')
    total_days = len(signal)
    noise_ratio = (fear_signals + greed_signals) / total_days if total_days > 0 else 1

    score = fear_rate + greed_rate
    if noise_ratio > 0.3:
        score *= (0.3 / noise_ratio)

    return (score, fear_rate, greed_rate,
            h_fear_rate, h_greed_rate,
            fear_signals, greed_signals)


def _snap_to_trade_date(target, trade_dates, max_delta=5):
    """将目标日期对齐到最近的交易日（±max_delta 天内）"""
    if target in trade_dates:
        return target
    # 向前后各搜索
    td_set = set(trade_dates)
    for delta in range(1, max_delta + 1):
        from datetime import datetime, timedelta
        dt = datetime.strptime(target, '%Y-%m-%d')
        for sign in [-1, 1]:
            candidate = (dt + timedelta(days=sign * delta)).strftime('%Y-%m-%d')
            if candidate in td_set:
                return candidate
    return None


def main():
    tolerance = 3
    for i, arg in enumerate(sys.argv):
        if arg == '--tolerance' and i + 1 < len(sys.argv):
            tolerance = int(sys.argv[i + 1])

    peak_window = 30

    print("=" * 70)
    print("eIndex 参数优化器（人工标注 + 880008 辅助）")
    print(f"人工标注权重: {HUMAN_WEIGHT}x，880008 自动检测权重: {AUTO_WEIGHT}x")
    print(f"容差: ±{tolerance} 个交易日")
    print("=" * 70)

    # 1. 人工标注
    print(f"\n[1/5] 人工标注日期:")
    print(f"  恐惧日: {len(HUMAN_FEAR_DATES)} 个 → {HUMAN_FEAR_DATES}")
    print(f"  贪婪日: {len(HUMAN_GREED_DATES)} 个 → {HUMAN_GREED_DATES}")

    # 2. 获取 880008
    print("\n[2/5] 获取 880008 历史数据...")
    prices = fetch_880008()
    print(f"  共 {len(prices)} 个交易日")

    # 3. 找极值点
    print(f"\n[3/5] 检测 880008 局部极值 (窗口={peak_window})...")
    auto_fear_dates, auto_greed_dates = find_peaks_and_troughs(prices, peak_window)
    # 排除与人工标注重叠的（避免双重计分）
    human_fear_set = set(HUMAN_FEAR_DATES)
    human_greed_set = set(HUMAN_GREED_DATES)
    auto_fear_dates = [d for d in auto_fear_dates if d not in human_fear_set]
    auto_greed_dates = [d for d in auto_greed_dates if d not in human_greed_set]
    print(f"  自动恐惧日（去重后）: {len(auto_fear_dates)} 个")
    print(f"  自动贪婪日（去重后）: {len(auto_greed_dates)} 个")

    # 4. 加载原始指标
    print("\n[4/5] 加载原始指标数据...")
    cje, margin_ratio, limitup = load_raw_indicators()
    all_dates = sorted(set(list(cje.keys()) + list(margin_ratio.keys()) + list(limitup.keys())))
    trade_dates = [d for d in all_dates if d >= '2016-06-01']
    print(f"  有效交易日: {len(trade_dates)} 天 ({trade_dates[0]} ~ {trade_dates[-1]})")

    # 加载 880008 收益率（用作第4个指标）
    lookbacks = [3, 5, 10, 20]
    returns_by_lb = {}
    for lb in lookbacks:
        returns_by_lb[lb] = load_880008_returns(lb)
    print(f"  880008 收益率已加载: lookbacks={lookbacks}")

    # 对齐人工标注日期到交易日
    human_fear_snapped = []
    for d in HUMAN_FEAR_DATES:
        s = _snap_to_trade_date(d, trade_dates)
        if s:
            human_fear_snapped.append(s)
            if s != d:
                print(f"  恐惧日 {d} → 对齐到交易日 {s}")
    human_greed_snapped = []
    for d in HUMAN_GREED_DATES:
        s = _snap_to_trade_date(d, trade_dates)
        if s:
            human_greed_snapped.append(s)
            if s != d:
                print(f"  贪婪日 {d} → 对齐到交易日 {s}")

    print(f"  有效人工恐惧日: {len(human_fear_snapped)}, 有效人工贪婪日: {len(human_greed_snapped)}")

    # 5. 网格搜索
    print("\n[5/5] 网格搜索最优参数...")
    windows = [60, 80, 100, 120, 150, 180, 200, 250, 300]
    fear_pcts = [5, 8, 10, 12, 15, 18, 20, 25]
    greed_pcts = [78, 80, 82, 85, 88, 90, 92, 95]

    total_combos = len(lookbacks) * len(windows) * len(fear_pcts) * len(greed_pcts)
    print(f"  参数空间: {len(lookbacks)} × {len(windows)} × {len(fear_pcts)} × {len(greed_pcts)} = {total_combos} 组")

    # 预计算各 (lookback, window) 下的 eIndex
    eindex_cache = {}
    for lb in lookbacks:
        for w in windows:
            eindex_cache[(lb, w)] = simulate_eindex(trade_dates, cje, margin_ratio, limitup, w, returns=returns_by_lb[lb])

    results = []
    done = 0
    for lb in lookbacks:
        for w in windows:
            eindex_by_date = eindex_cache[(lb, w)]
            for fp in fear_pcts:
                for gp in greed_pcts:
                    if fp >= gp:
                        continue
                    (score, fr, gr,
                     hfr, hgr,
                     fs, gs) = evaluate_params(
                        trade_dates, eindex_by_date,
                        human_fear_snapped, human_greed_snapped,
                        set(auto_fear_dates), set(auto_greed_dates),
                        w, fp, gp, tolerance
                    )
                    results.append({
                        'lookback': lb,
                        'window': w, 'fear_pct': fp, 'greed_pct': gp,
                        'score': score, 'fear_rate': fr, 'greed_rate': gr,
                        'h_fear_rate': hfr, 'h_greed_rate': hgr,
                        'fear_signals': fs, 'greed_signals': gs,
                    })
                    done += 1
                    if done % 200 == 0:
                        print(f"    {done}/{total_combos}...", end='\r')

    results.sort(key=lambda x: -x['score'])

    print(f"\n\n{'='*110}")
    print(f"Top 20 参数组合 (容差 ±{tolerance} 天, 人工权重 {HUMAN_WEIGHT}x)")
    print(f"{'='*110}")
    print(f"{'排名':>4} | {'LB':>3} | {'WIN':>4} | {'FEAR':>4} | {'GREED':>5} | {'得分':>6} | "
          f"{'综合恐惧':>8} | {'综合贪婪':>8} | {'人工恐惧':>8} | {'人工贪婪':>8} | "
          f"{'恐惧信号':>6} | {'贪婪信号':>6}")
    print("-" * 110)
    for i, r in enumerate(results[:20]):
        print(f"{i+1:4d} | {r['lookback']:3d} | {r['window']:4d} | {r['fear_pct']:4d} | {r['greed_pct']:5d} | "
              f"{r['score']:6.3f} | {r['fear_rate']:7.1%} | {r['greed_rate']:7.1%} | "
              f"{r['h_fear_rate']:7.1%} | {r['h_greed_rate']:7.1%} | "
              f"{r['fear_signals']:6d} | {r['greed_signals']:6d}")

    best = results[0]
    print(f"\n★ 推荐参数:")
    print(f"  RETURN_LOOKBACK   = {best['lookback']}")
    print(f"  PERCENTILE_WINDOW = {best['window']}")
    print(f"  FEAR_PERCENTILE   = {best['fear_pct']}")
    print(f"  GREED_PERCENTILE  = {best['greed_pct']}")
    print(f"  综合得分: {best['score']:.3f}")
    print(f"  加权命中: 恐惧 {best['fear_rate']:.1%}, 贪婪 {best['greed_rate']:.1%}")
    print(f"  人工命中: 恐惧 {best['h_fear_rate']:.1%}, 贪婪 {best['h_greed_rate']:.1%}")
    print(f"  信号数量: 恐惧 {best['fear_signals']}, 贪婪 {best['greed_signals']}")

    # 显示最优参数下，每个人工标注日期的 eIndex 值和信号
    print(f"\n\n{'='*70}")
    print(f"最优参数下各人工标注日期的 eIndex 详情")
    print(f"{'='*70}")
    best_eindex = eindex_cache[(best['lookback'], best['window'])]
    eindex_hist = []
    signal_map = {}
    threshold_map = {}
    for dt in trade_dates:
        ei = best_eindex.get(dt)
        if ei is None:
            continue
        ft, gt = compute_thresholds_for_date(eindex_hist, best['window'], best['fear_pct'], best['greed_pct'])
        if ei <= ft:
            signal_map[dt] = '恐惧'
        elif ei >= gt:
            signal_map[dt] = '贪婪'
        else:
            signal_map[dt] = '中性'
        threshold_map[dt] = (ft, gt)
        eindex_hist.append(ei)

    print(f"\n  恐惧标注日:")
    for d in human_fear_snapped:
        ei = best_eindex.get(d, '?')
        sig = signal_map.get(d, '?')
        th = threshold_map.get(d, ('?', '?'))
        mark = '✓' if sig == '恐惧' else '✗'
        print(f"    {mark} {d}  eIndex={ei:.1f}  信号={sig}  恐惧线={th[0]:.1f}  贪婪线={th[1]:.1f}")

    print(f"\n  贪婪标注日:")
    for d in human_greed_snapped:
        ei = best_eindex.get(d, '?')
        sig = signal_map.get(d, '?')
        th = threshold_map.get(d, ('?', '?'))
        mark = '✓' if sig == '贪婪' else '✗'
        print(f"    {mark} {d}  eIndex={ei:.1f}  信号={sig}  恐惧线={th[0]:.1f}  贪婪线={th[1]:.1f}")


if __name__ == '__main__':
    main()
