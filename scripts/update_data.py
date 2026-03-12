#!/usr/bin/env python3
"""
eIndex 数据更新脚本
通过 akshare 获取A股市场实盘数据，计算情绪指数

数据源：
  - 换手率：新浪财经（沪深指数每日成交额）
  - 融资余额：上交所 + 深交所
  - 涨停家数：东方财富网

用法：
  python update_data.py          # 增量更新（只获取新数据）
  python update_data.py --full   # 全量重建（涨停数据获取较慢）
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_FILE = DATA_DIR / "eindex_data.json"

# ── 流通市值历史锚点（单位：元）──────────────────────────
# 用于计算换手率 = 总成交额 / 流通市值
# 最终取250日分位数会归一化，绝对值的小偏差影响有限
FLOAT_MCAP_ANCHORS = [
    ("2015-01", 32e12), ("2015-06", 58e12), ("2015-09", 38e12), ("2015-12", 40e12),
    ("2016-06", 34e12), ("2016-12", 35e12),
    ("2017-06", 38e12), ("2017-12", 42e12),
    ("2018-06", 35e12), ("2018-12", 30e12),
    ("2019-06", 38e12), ("2019-12", 42e12),
    ("2020-06", 48e12), ("2020-12", 55e12),
    ("2021-06", 62e12), ("2021-12", 65e12),
    ("2022-06", 58e12), ("2022-12", 55e12),
    ("2023-06", 58e12), ("2023-12", 57e12),
    ("2024-06", 54e12), ("2024-09", 55e12), ("2024-10", 72e12), ("2024-12", 75e12),
    ("2025-06", 78e12), ("2025-12", 80e12),
    ("2026-06", 82e12),
]

# 各年份全市场股票总数（近似）
TOTAL_STOCKS = {
    2015: 2800, 2016: 3000, 2017: 3400, 2018: 3600,
    2019: 3800, 2020: 4100, 2021: 4500, 2022: 4900,
    2023: 5200, 2024: 5350, 2025: 5450, 2026: 5500,
}


def ensure_akshare():
    try:
        import akshare
        return akshare
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "akshare", "-q"])
        import akshare
        return akshare


def estimate_float_mcap(date_str):
    """线性插值估算某日的全市场流通市值"""
    ym = date_str[:7]
    if ym <= FLOAT_MCAP_ANCHORS[0][0]:
        return FLOAT_MCAP_ANCHORS[0][1]
    if ym >= FLOAT_MCAP_ANCHORS[-1][0]:
        return FLOAT_MCAP_ANCHORS[-1][1]

    for i in range(len(FLOAT_MCAP_ANCHORS) - 1):
        k0, v0 = FLOAT_MCAP_ANCHORS[i]
        k1, v1 = FLOAT_MCAP_ANCHORS[i + 1]
        if k0 <= ym <= k1:
            d0 = datetime.strptime(k0 + "-15", "%Y-%m-%d")
            d1 = datetime.strptime(k1 + "-15", "%Y-%m-%d")
            dt = datetime.strptime(ym + "-15", "%Y-%m-%d")
            ratio = (dt - d0).days / max((d1 - d0).days, 1)
            return v0 + (v1 - v0) * ratio

    return 70e12


def get_trade_dates(ak, start="2015-01-01"):
    """从上证指数获取真实交易日历（自动排除周末和节假日）"""
    print("获取交易日历...")
    df = ak.stock_zh_index_daily(symbol="sh000001")
    df['date'] = df['date'].astype(str)
    end = datetime.now().strftime("%Y-%m-%d")
    dates = sorted(d for d in df['date'] if start <= d <= end)
    print(f"  交易日: {dates[0]} ~ {dates[-1]}，共 {len(dates)} 天")
    return dates


def get_turnover_data(ak, trade_dates):
    """全市场换手率 = (沪市成交额 + 深市成交额) / 估算流通市值"""
    print("获取全市场成交额（新浪财经）...")
    results = {}

    try:
        df_sh = ak.stock_zh_index_daily(symbol="sh000001")
        df_sh['date'] = df_sh['date'].astype(str)
        sh_vol = dict(zip(df_sh['date'], df_sh['volume']))

        df_sz = ak.stock_zh_index_daily(symbol="sz399001")
        df_sz['date'] = df_sz['date'].astype(str)
        sz_vol = dict(zip(df_sz['date'], df_sz['volume']))

        for dt in trade_dates:
            sh = sh_vol.get(dt, 0) or 0
            sz = sz_vol.get(dt, 0) or 0
            total = float(sh) + float(sz)
            if total > 0:
                mcap = estimate_float_mcap(dt)
                results[dt] = total / mcap

        print(f"  换手率数据: {len(results)} 天")
    except Exception as e:
        print(f"  换手率获取失败: {e}")

    return results


def _parse_date(val):
    """把各种日期格式统一为 YYYY-MM-DD"""
    s = str(val).strip()
    if len(s) >= 10 and s[4] == '-':
        return s[:10]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # pandas Timestamp
    try:
        return val.strftime("%Y-%m-%d")
    except Exception:
        return None


def _find_column(df, candidates):
    """在 DataFrame 中按候选名查找列"""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def get_margin_data(ak):
    """获取沪深两市融资余额占比（上交所 + 深交所）"""
    print("获取融资余额（上交所 + 深交所）...")
    sh_margin = {}
    sz_margin = {}

    # ── 上交所 ──
    try:
        df = ak.stock_margin_sse(start_date="20150101")
        date_col = df.columns[0]  # 第一列通常是日期
        bal_col = _find_column(df, ['融资余额(元)', '融资余额', '融资余额（元）'])
        if bal_col is None:
            bal_col = df.columns[4] if len(df.columns) > 4 else None

        if bal_col:
            for _, row in df.iterrows():
                dt = _parse_date(row[date_col])
                if dt is None:
                    continue
                try:
                    balance = float(row[bal_col])
                    if balance > 0:
                        sh_margin[dt] = balance
                except (ValueError, TypeError):
                    continue

        print(f"  上交所融资: {len(sh_margin)} 天")
    except Exception as e:
        print(f"  上交所融资获取失败: {e}")

    # ── 深交所 ──
    # akshare 深交所融资 API 名称可能随版本变化，逐个尝试
    szse_fetchers = [
        ("stock_margin_szse", {"start_date": "20150101"}),
        ("stock_margin_detail_szse", {}),
    ]

    for func_name, kwargs in szse_fetchers:
        if hasattr(ak, func_name):
            try:
                df = getattr(ak, func_name)(**kwargs)
                date_col = df.columns[0]
                bal_col = _find_column(df, ['融资余额(元)', '融资余额', '融资余额（元）'])
                if bal_col is None:
                    bal_col = df.columns[4] if len(df.columns) > 4 else None

                if bal_col:
                    for _, row in df.iterrows():
                        dt = _parse_date(row[date_col])
                        if dt is None:
                            continue
                        try:
                            balance = float(row[bal_col])
                            if balance > 0:
                                sz_margin[dt] = balance
                        except (ValueError, TypeError):
                            continue

                print(f"  深交所融资: {len(sz_margin)} 天 (via {func_name})")
                break
            except Exception as e:
                print(f"  {func_name} 失败: {e}")

    # ── 合并 ──
    results = {}
    if sh_margin and not sz_margin:
        # 深交所数据不可用，用上交所 × 1.67 估算全市场
        print("  深交所数据不可用，使用上交所 × 1.67 估算全市场")
        for dt, val in sh_margin.items():
            mcap = estimate_float_mcap(dt)
            results[dt] = val * 1.67 / mcap
    else:
        all_dates = sorted(set(list(sh_margin.keys()) + list(sz_margin.keys())))
        for dt in all_dates:
            sh = sh_margin.get(dt, 0)
            sz = sz_margin.get(dt, 0)
            total = sh + sz
            if total > 0:
                mcap = estimate_float_mcap(dt)
                results[dt] = total / mcap

    print(f"  融资占比数据: {len(results)} 天")
    return results


LIMITUP_CACHE = DATA_DIR / "limitup_cache.json"


def _load_limitup_cache():
    """加载涨停数据缓存"""
    if LIMITUP_CACHE.exists():
        with open(LIMITUP_CACHE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_limitup_cache(cache):
    """保存涨停数据缓存"""
    DATA_DIR.mkdir(exist_ok=True)
    with open(LIMITUP_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_limitup_data(ak, trade_dates, max_days=60):
    """获取涨停家数占比（东方财富网）+ 持久化缓存

    stock_zt_pool_em 在东方财富只保留最近约 1 个月的数据，
    因此采用增量缓存策略：
    1. 读取本地缓存 (data/limitup_cache.json)
    2. 仅向 API 请求缓存中缺失的最近日期
    3. 将新获取的数据追加到缓存
    随着每日自动运行，缓存会逐渐积累完整的历史数据。
    """
    cache = _load_limitup_cache()
    print(f"涨停数据缓存: {len(cache)} 天已有")

    # 找出缓存中缺失的最近日期（API 只保留 ~1 个月）
    recent_dates = trade_dates[-max_days:]
    missing = [dt for dt in recent_dates if dt not in cache]

    if not missing:
        print("  涨停缓存已覆盖最近日期，无需请求 API")
    else:
        # 从最新日期向后推，因为 API 只保留最近 ~1 个月
        missing_reversed = list(reversed(missing))
        print(f"  需获取 {len(missing_reversed)} 天 ({missing_reversed[-1]} ~ {missing_reversed[0]})")
        consecutive_empty = 0
        fetched = 0

        for i, dt in enumerate(missing_reversed):
            try:
                df = ak.stock_zt_pool_em(date=dt.replace('-', ''))
                year = int(dt[:4])
                total = TOTAL_STOCKS.get(year, 5300)
                if df is not None and len(df) > 0:
                    count = len(df)
                    cache[dt] = {"count": count, "ratio": count / total}
                    consecutive_empty = 0
                    fetched += 1
                else:
                    consecutive_empty += 1
            except Exception as e:
                consecutive_empty += 1
                if consecutive_empty <= 3:
                    print(f"  {dt}: {e}")

            # 东方财富只保留 ~1 个月，连续空结果说明已超出范围
            if consecutive_empty >= 8:
                print(f"  连续 {consecutive_empty} 天无数据，已达 API 历史上限")
                break

            if (i + 1) % 20 == 0:
                print(f"  进度: {i + 1}/{len(missing_reversed)}")

            time.sleep(0.3)

        _save_limitup_cache(cache)
        print(f"  新获取 {fetched} 天，缓存共 {len(cache)} 天")

    # 转换为 {date: ratio} 格式供后续计算
    results = {}
    for dt in trade_dates:
        if dt in cache:
            entry = cache[dt]
            if isinstance(entry, dict):
                results[dt] = entry["ratio"]
            else:
                results[dt] = float(entry)  # 兼容旧格式

    print(f"  涨停数据可用: {len(results)} 天")
    return results


def compute_percentile(history, current, window=250):
    """计算当前值在最近 window 个值中的分位数（0-100）"""
    if len(history) < 2:
        return 50.0
    recent = history[-window:] if len(history) >= window else history
    rank = sum(1 for v in recent if v <= current)
    return (rank / len(recent)) * 100


def load_existing():
    """加载已有数据"""
    if DATA_FILE.exists():
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def generate_data():
    """主函数：获取实盘数据并计算eIndex"""
    ak = ensure_akshare()

    full_mode = '--full' in sys.argv

    # 加载已有数据
    existing_dates = set()
    if not full_mode:
        old_data = load_existing()
        if old_data:
            existing_dates = {d['date'] for d in old_data.get('data', [])}
            print(f"已有 {len(existing_dates)} 天历史数据")

    # 获取交易日历（来自上证指数真实交易日，自动排除节假日）
    trade_dates = get_trade_dates(ak)

    if not trade_dates:
        print("无交易日数据")
        return

    # 增量模式检查
    if existing_dates and not full_mode:
        new_dates = [d for d in trade_dates if d not in existing_dates]
        if not new_dates:
            print("数据已是最新，无需更新")
            return
        print(f"需要更新: {len(new_dates)} 天 ({new_dates[0]} ~ {new_dates[-1]})")

    # ── 获取三大指标 ──
    turnover_data = get_turnover_data(ak, trade_dates)
    margin_data = get_margin_data(ak)

    # 涨停数据使用持久化缓存，每次只获取缺失的最近日期
    limitup_data = get_limitup_data(ak, trade_dates, max_days=60)

    # ── 计算情绪指数 ──
    print("计算情绪指数...")
    results = []
    t_hist, m_hist, l_hist = [], [], []

    for dt in trade_dates:
        t_val = turnover_data.get(dt)
        m_val = margin_data.get(dt)
        l_val = limitup_data.get(dt)

        if t_val is not None:
            t_hist.append(t_val)
        if m_val is not None:
            m_hist.append(m_val)
        if l_val is not None:
            l_hist.append(l_val)

        # 至少需要一个指标有数据
        if t_val is None and m_val is None and l_val is None:
            continue

        t_pct = compute_percentile(t_hist, t_val) if t_val is not None else None
        m_pct = compute_percentile(m_hist, m_val) if m_val is not None else None
        l_pct = compute_percentile(l_hist, l_val) if l_val is not None else None

        # 有几个指标就用几个的均值（而非缺失时默认50）
        pcts = [p for p in [t_pct, m_pct, l_pct] if p is not None]
        if not pcts:
            continue
        eindex = sum(pcts) / len(pcts)

        results.append({
            "date": dt,
            "eindex": round(eindex, 2),
            "turnover_rate": round(t_val, 6) if t_val is not None else 0,
            "turnover_pct": round(t_pct, 2) if t_pct is not None else 0,
            "margin_ratio": round(m_val, 6) if m_val is not None else 0,
            "margin_pct": round(m_pct, 2) if m_pct is not None else 0,
            "limitup_ratio": round(l_val, 6) if l_val is not None else 0,
            "limitup_pct": round(l_pct, 2) if l_pct is not None else 0,
        })

    # ── 保存 ──
    output = {
        "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "data": results
    }

    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n数据已保存: {DATA_FILE}")
    print(f"共 {len(results)} 条记录")
    if results:
        latest = results[-1]
        sig = "买入" if latest['eindex'] <= 20 else "卖出" if latest['eindex'] >= 80 else "持有"
        print(f"最新: {latest['date']}  eIndex={latest['eindex']}  信号={sig}")


if __name__ == '__main__':
    generate_data()
