#!/usr/bin/env python3
"""
eIndex 数据更新脚本
通过 akshare 获取A股市场实盘数据，计算情绪指数

数据源：
  - 换手率：新浪财经（沪深指数每日成交额）
  - 融资余额：上交所 + 深交所
  - 涨停家数：通达信 880006 停板家数 (via mootdx)

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


def get_trade_dates(ak, start="2016-01-26"):
    """从上证指数获取真实交易日历（自动排除周末和节假日）"""
    print("获取交易日历...")
    df = ak.stock_zh_index_daily_em(symbol="sh000001")
    df['date'] = df['date'].astype(str)
    end = datetime.now().strftime("%Y-%m-%d")
    dates = sorted(d for d in df['date'] if start <= d <= end)
    print(f"  交易日: {dates[0]} ~ {dates[-1]}，共 {len(dates)} 天")
    return dates


def get_turnover_data(ak, trade_dates):
    """全市场换手率 = (沪市成交额 + 深市成交额) / 估算流通市值"""
    print("获取全市场成交额（东方财富）...")
    results = {}

    try:
        df_sh = ak.stock_zh_index_daily_em(symbol="sh000001")
        df_sh['date'] = df_sh['date'].astype(str)
        sh_amt = dict(zip(df_sh['date'], df_sh['amount']))

        df_sz = ak.stock_zh_index_daily_em(symbol="sz399001")
        df_sz['date'] = df_sz['date'].astype(str)
        sz_amt = dict(zip(df_sz['date'], df_sz['amount']))

        for dt in trade_dates:
            sh = sh_amt.get(dt, 0) or 0
            sz = sz_amt.get(dt, 0) or 0
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
    """获取沪深两市融资余额占比

    数据源：
    - 主要：macro_china_market_margin_sh/sz（东方财富，2010 至今，每日更新）
    - 备用：stock_margin_sse（上交所，end_date 写死 20230922，仅覆盖到 2023-09）
    """
    print("获取融资余额（沪市 + 深市）...")
    sh_margin = {}
    sz_margin = {}

    # ── 沪市（macro 接口，数据最全） ──
    try:
        df = ak.macro_china_market_margin_sh()
        for _, row in df.iterrows():
            dt = _parse_date(row['日期'])
            if dt is None or dt < '2016-01-26':
                continue
            try:
                balance = float(row['融资余额'])
                if balance > 0:
                    sh_margin[dt] = balance
            except (ValueError, TypeError):
                continue
        print(f"  沪市融资: {len(sh_margin)} 天")
    except Exception as e:
        print(f"  沪市融资获取失败: {e}")
        # 备用：stock_margin_sse（截止 2023-09）
        try:
            df = ak.stock_margin_sse(start_date="20160126")
            bal_col = _find_column(df, ['融资余额(元)', '融资余额', '融资余额（元）'])
            if bal_col is None:
                bal_col = df.columns[4] if len(df.columns) > 4 else None
            if bal_col:
                for _, row in df.iterrows():
                    dt = _parse_date(row[df.columns[0]])
                    if dt is None:
                        continue
                    try:
                        balance = float(row[bal_col])
                        if balance > 0:
                            sh_margin[dt] = balance
                    except (ValueError, TypeError):
                        continue
            print(f"  沪市融资(备用): {len(sh_margin)} 天")
        except Exception as e2:
            print(f"  沪市融资备用也失败: {e2}")

    # ── 深市 ──
    try:
        df = ak.macro_china_market_margin_sz()
        for _, row in df.iterrows():
            dt = _parse_date(row['日期'])
            if dt is None or dt < '2016-01-26':
                continue
            try:
                balance = float(row['融资余额'])
                if balance > 0:
                    sz_margin[dt] = balance
            except (ValueError, TypeError):
                continue
        print(f"  深市融资: {len(sz_margin)} 天")
    except Exception as e:
        print(f"  深市融资获取失败: {e}")

    # ── 合并 ──
    results = {}
    if sh_margin and not sz_margin:
        print("  深市数据不可用，使用沪市 × 1.67 估算全市场")
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


def ensure_mootdx():
    """确保 mootdx 已安装"""
    try:
        from mootdx.quotes import Quotes
        return Quotes
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "mootdx", "-q"])
        from mootdx.quotes import Quotes
        return Quotes


def get_limitup_data(ak, trade_dates, max_days=60):
    """获取涨停家数占比 — 通达信 880006 停板家数 via mootdx

    880006 的 close 列 = 涨停家数，open 列 = 跌停家数。
    mootdx 通过通达信行情协议可获取约 2500 个交易日的历史数据（~2016年起）。
    获取后持久化缓存到 data/limitup_cache.json，避免重复请求。
    """
    import socket
    socket.setdefaulttimeout(10)

    cache = _load_limitup_cache()
    cached_dates = set(cache.keys())
    missing = [dt for dt in trade_dates if dt not in cached_dates]

    print(f"涨停数据缓存: {len(cached_dates)} 天已有, {len(missing)} 天缺失")

    if missing:
        try:
            Quotes = ensure_mootdx()
            client = Quotes.factory(market='std')

            import pandas as pd
            all_data = []
            for start in range(0, 5000, 800):
                data = client.index(symbol='880006', frequency=9, start=start, offset=800)
                if data is None or len(data) == 0:
                    break
                all_data.append(data)
                if len(data) < 800:
                    break

            if all_data:
                combined = pd.concat(all_data)
                combined = combined[~combined.index.duplicated(keep='first')]
                new_count = 0
                for idx, row in combined.iterrows():
                    dt = idx.strftime('%Y-%m-%d')
                    if dt not in cached_dates:
                        count = int(row['close'])
                        year = int(dt[:4])
                        total = TOTAL_STOCKS.get(year, 5300)
                        cache[dt] = {"count": count, "ratio": count / total}
                        new_count += 1

                _save_limitup_cache(cache)
                print(f"  mootdx 880006 新增 {new_count} 天, 缓存共 {len(cache)} 天")
            else:
                print("  mootdx 未获取到数据")
        except Exception as e:
            print(f"  mootdx 获取失败: {e}")

    # 转换为 {date: (ratio, count)} 格式
    results = {}
    for dt in trade_dates:
        if dt in cache:
            entry = cache[dt]
            if isinstance(entry, dict):
                results[dt] = (entry["ratio"], entry["count"])
            else:
                results[dt] = (float(entry), 0)

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

    # 涨停数据使用通达信 880006 + 持久化缓存
    limitup_data = get_limitup_data(ak, trade_dates)

    # ── 计算情绪指数 ──
    print("计算情绪指数...")
    results = []
    t_hist, m_hist, l_hist = [], [], []

    for dt in trade_dates:
        t_val = turnover_data.get(dt)
        m_val = margin_data.get(dt)
        l_entry = limitup_data.get(dt)
        l_val = l_entry[0] if l_entry is not None else None
        l_count = l_entry[1] if l_entry is not None else 0

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
            "limitup_count": l_count,
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
