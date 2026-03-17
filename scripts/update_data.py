#!/usr/bin/env python3
"""
eIndex 数据更新脚本
通过 akshare 获取A股市场实盘数据，计算情绪指数

数据源：
  - 换手率：新浪财经（沪深指数每日成交额）
  - 融资余额：上交所 + 深交所
  - 涨停家数：通达信 880006 停板家数 (via mootdx)
  - 市场方向：通达信 880008 全A等权指数 N 日收益率

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
DATA_JS_FILE = DATA_DIR / "eindex_data.js"
INDEX_HTML = Path(__file__).parent.parent / "index.html"
LOG_FILE = Path(__file__).parent.parent / "log.md"
LTSZ_CACHE_FILE = DATA_DIR / "ltsz_cache.json"
TURNOVER_CACHE = DATA_DIR / "turn_rate_cache.json"
CJE_CACHE = DATA_DIR / "cje_cache.json"
RETURN_CACHE = DATA_DIR / "return_cache.json"  # 880008 收益率缓存

# 市场方向因子使用的收益率回望天数
RETURN_LOOKBACK = 3

# 分位数计算滚动窗口（交易日数）
PERCENTILE_WINDOW = 120

# 恐惧/贪婪信号的分位数阈值（基于滚动窗口内 eIndex 的百分位）
FEAR_PERCENTILE = 15
GREED_PERCENTILE = 84

# 各因子权重（加权平均替代等权）
W_CJE = 0.20       # 成交额
W_MARGIN = 0.05    # 融资余额（信号区分度最弱，降权）
W_LIMITUP = 0.30   # 涨停家数
W_RETURN = 0.35    # 市场方向（880008收益率）

# 各年份全市场股票总数（近似）
TOTAL_STOCKS = {
    2015: 2800, 2016: 3000, 2017: 3400, 2018: 3600,
    2019: 3800, 2020: 4100, 2021: 4500, 2022: 4900,
    2023: 5200, 2024: 5350, 2025: 5450, 2026: 5500,
}


# ── 流通市值缓存（单位：亿元）──────────────────────────
_ltsz_cache = None
_sh_sz_ratio = None  # SH/SZ 比值，用于估算 2018 前的 SH 数据

def _load_ltsz_cache():
    """加载 ltsz_cache.json，返回 {date: {sh, sz}} 字典"""
    global _ltsz_cache
    if _ltsz_cache is None:
        if LTSZ_CACHE_FILE.exists():
            with open(LTSZ_CACHE_FILE, 'r', encoding='utf-8') as f:
                _ltsz_cache = json.load(f)
        else:
            _ltsz_cache = {}
    return _ltsz_cache


def _get_sh_sz_ratio():
    """从缓存中计算 2018 年最早期的 SH/SZ 流通市值比值，用于估算 2018 前的 SH。"""
    global _sh_sz_ratio
    if _sh_sz_ratio is not None:
        return _sh_sz_ratio
    cache = _load_ltsz_cache()
    # 取 2018 年初有完整数据的最早 20 个交易日的 SH/SZ 比值的中位数
    ratios = []
    for dt in sorted(cache.keys()):
        entry = cache[dt]
        sh = entry.get('sh', 0)
        sz = entry.get('sz', 0)
        if sh > 0 and sz > 0 and dt >= '2018-01-01':
            ratios.append(sh / sz)
            if len(ratios) >= 20:
                break
    if ratios:
        ratios.sort()
        _sh_sz_ratio = ratios[len(ratios) // 2]  # 中位数
    else:
        _sh_sz_ratio = 1.85  # 历史近似值（沪市≈65%，深市≈35%）
    return _sh_sz_ratio


def get_float_mcap(date_str):
    """获取某日全市场流通市值（亿元）。
    优先使用 ltsz_cache.json 真实数据；
    若仅有 SZ 数据（2018 前 SSE 无数据），按 SH/SZ 比值估算 SH。"""
    cache = _load_ltsz_cache()
    entry = cache.get(date_str)
    if not entry:
        return None
    sh = entry.get('sh', 0)
    sz = entry.get('sz', 0)
    if sh > 0 and sz > 0:
        return sh + sz
    if sz > 0 and sh == 0:
        ratio = _get_sh_sz_ratio()
        return sz * (1 + ratio)  # total = sz + sz * ratio
    if sh > 0 and sz == 0:
        return None  # 不应该出现此情况
    return None


def ensure_akshare():
    try:
        import akshare
        return akshare
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "akshare", "-q"])
        import akshare
        return akshare


def get_trade_dates(ak=None, start="2016-01-26"):
    """获取真实交易日历（自动排除周末和节假日）
    优先从本地缓存推导（turn_rate_cache / limitup_cache 的 keys），
    仅当本地无缓存时才调用 akshare API。"""
    print("获取交易日历...")
    end = datetime.now().strftime("%Y-%m-%d")

    # 优先从本地缓存推导交易日历
    cache_dates = set()
    tc = _load_turnover_cache()
    if tc:
        cache_dates.update(tc.keys())
    lc_path = DATA_DIR / "limitup_cache.json"
    if lc_path.exists():
        with open(lc_path, 'r', encoding='utf-8') as f:
            lc = json.load(f)
        cache_dates.update(lc.keys())

    if cache_dates:
        dates = sorted(d for d in cache_dates if start <= d <= end)
        if dates:
            print(f"  交易日(缓存): {dates[0]} ~ {dates[-1]}，共 {len(dates)} 天")
            return dates

    # 回退：调用 akshare API
    if ak is None:
        ak = ensure_akshare()
    df = ak.stock_zh_index_daily_em(symbol="sh000001")
    df['date'] = df['date'].astype(str)
    dates = sorted(d for d in df['date'] if start <= d <= end)
    print(f"  交易日(API): {dates[0]} ~ {dates[-1]}，共 {len(dates)} 天")
    return dates


def _load_turnover_cache():
    """加载换手率缓存"""
    if TURNOVER_CACHE.exists():
        with open(TURNOVER_CACHE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_turnover_cache(cache):
    """保存换手率缓存"""
    DATA_DIR.mkdir(exist_ok=True)
    with open(TURNOVER_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _load_cje_cache():
    """加载成交额缓存（亿元）"""
    if CJE_CACHE.exists():
        with open(CJE_CACHE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_cje_cache(cache):
    """保存成交额缓存（亿元）"""
    DATA_DIR.mkdir(exist_ok=True)
    with open(CJE_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _load_return_cache():
    """加载 880008 收益率缓存"""
    if RETURN_CACHE.exists():
        with open(RETURN_CACHE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_return_cache(cache):
    """保存 880008 收益率缓存"""
    DATA_DIR.mkdir(exist_ok=True)
    with open(RETURN_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_market_return(trade_dates, lookback=RETURN_LOOKBACK):
    """获取 880008 全A等权指数 N 日收益率作为市场方向因子。
    返回 {date: return_rate}，正值=上涨，负值=下跌。"""
    import socket
    socket.setdefaulttimeout(10)

    cache = _load_return_cache()
    cached_dates = set(cache.keys())
    missing = [dt for dt in trade_dates if dt not in cached_dates]

    print(f"市场方向（880008 {lookback}日收益率）: 缓存 {len(cached_dates)} 天, 缺失 {len(missing)} 天")

    if missing:
        try:
            Quotes = ensure_mootdx()
            client = Quotes.factory(market='std')
            import pandas as pd

            all_data = []
            for start in range(0, 5000, 800):
                data = client.index(symbol='880008', frequency=9, start=start, offset=800) # type: ignore
                if data is None or len(data) == 0:
                    break
                all_data.append(data)
                if len(data) < 800:
                    break
                time.sleep(0.5)

            if all_data:
                combined = pd.concat(all_data)
                combined = combined[~combined.index.duplicated(keep='first')]
                combined = combined.sort_index()
                closes = {idx.strftime('%Y-%m-%d'): float(row['close'])
                          for idx, row in combined.iterrows()}
                sorted_dates = sorted(closes.keys())

                new_count = 0
                for i, dt in enumerate(sorted_dates):
                    if dt in cached_dates:
                        continue
                    if i < lookback:
                        continue
                    prev_dt = sorted_dates[i - lookback]
                    prev_close = closes[prev_dt]
                    cur_close = closes[dt]
                    if prev_close > 0:
                        ret = (cur_close - prev_close) / prev_close
                        cache[dt] = round(ret, 6)
                        new_count += 1

                _save_return_cache(cache)
                print(f"  880008 收益率新增 {new_count} 天, 缓存共 {len(cache)} 天")
        except Exception as e:
            print(f"  880008 收益率获取失败: {e}")

    results = {dt: cache[dt] for dt in trade_dates if dt in cache}
    print(f"  市场方向数据: {len(results)} 天")
    return results


def get_turnover_data(ak, trade_dates):
    """全市场换手率 = (沪市成交额 + 深市成交额) / 流通市值"""
    print("获取全市场成交额（东方财富）...")

    cache = _load_turnover_cache()
    cje = _load_cje_cache()
    cached_dates = set(cache.keys())
    missing = [dt for dt in trade_dates if dt not in cached_dates]
    print(f"  缓存: {len(cached_dates)} 天已有, {len(missing)} 天缺失")

    if missing:
        missing_mcap = 0
        try:
            df_sh = ak.stock_zh_index_daily_em(symbol="sh000001")
            df_sh['date'] = df_sh['date'].astype(str)
            sh_amt = dict(zip(df_sh['date'], df_sh['amount']))

            time.sleep(1)

            df_sz = ak.stock_zh_index_daily_em(symbol="sz399001")
            df_sz['date'] = df_sz['date'].astype(str)
            sz_amt = dict(zip(df_sz['date'], df_sz['amount']))

            new_count = 0
            for dt in missing:
                sh = sh_amt.get(dt, 0) or 0
                sz = sz_amt.get(dt, 0) or 0
                total = float(sh) + float(sz)  # 元
                if total > 0:
                    sh_yi = round(float(sh) / 1e8, 4)
                    sz_yi = round(float(sz) / 1e8, 4)
                    mcap_yi = get_float_mcap(dt)  # 亿元
                    if mcap_yi and mcap_yi > 0:
                        rate = total / (mcap_yi * 1e8)  # 元 / 元
                        cache[dt] = {"sh_amount": sh_yi,
                                     "sz_amount": sz_yi,
                                     "turnover_rate": round(rate, 8)}
                        cje[dt] = {"sh": sh_yi, "sz": sz_yi}
                        new_count += 1
                    else:
                        missing_mcap += 1

            _save_turnover_cache(cache)
            _save_cje_cache(cje)
            print(f"  新增 {new_count} 天, 缓存共 {len(cache)} 天")
            if missing_mcap:
                print(f"  ⚠ {missing_mcap} 天缺少流通市值数据，请运行 fetch_ltsz.py 补齐")
        except Exception as e:
            print(f"  换手率获取失败: {e}")

    results = {}
    for dt in trade_dates:
        if dt in cache:
            entry = cache[dt]
            if isinstance(entry, dict):
                results[dt] = entry["turnover_rate"]
            else:
                results[dt] = float(entry)

    print(f"  换手率数据: {len(results)} 天")
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


def get_margin_data(ak, trade_dates):
    """获取沪深两市融资余额占比（缓存优先）

    数据流程：
    1. 加载本地 margin_cache.json（单位统一为亿元）
    2. 仅对 trade_dates 中缺失的日期，用交易所逐日接口获取
    3. 保存缓存，计算 ratio
    """
    print("获取融资余额（沪市 + 深市）...")

    cache = _load_margin_cache()
    sh_margin = {dt: v['sh'] for dt, v in cache.items() if 'sh' in v and v['sh'] > 0}
    sz_margin = {dt: v['sz'] for dt, v in cache.items() if 'sz' in v and v['sz'] > 0}
    print(f"  缓存: 沪市 {len(sh_margin)} 天, 深市 {len(sz_margin)} 天")

    # ── 仅对缺失日期逐日获取 ──
    missing_sh = [dt for dt in trade_dates if dt not in sh_margin]
    missing_sz = [dt for dt in trade_dates if dt not in sz_margin]
    need_fetch = sorted(set(missing_sh + missing_sz))
    print(f"  缺失: 沪市 {len(missing_sh)} 天, 深市 {len(missing_sz)} 天")

    if need_fetch:
        filled_sh = 0
        filled_sz = 0
        for dt in need_fetch:
            date_str = dt.replace('-', '')

            # 沪市：stock_margin_detail_sse（返回元，逐券汇总 → 亿元）
            if dt not in sh_margin:
                for attempt in range(3):
                    try:
                        df_day = ak.stock_margin_detail_sse(date=date_str)
                        total = df_day['融资余额'].astype(float).sum()
                        if total > 0:
                            sh_margin[dt] = total / 1e8
                            filled_sh += 1
                        break
                    except Exception:
                        if attempt < 2:
                            time.sleep(5)

            time.sleep(1)

            # 深市：stock_margin_szse（返回亿元）
            if dt not in sz_margin:
                for attempt in range(3):
                    try:
                        df_day = ak.stock_margin_szse(date=date_str)
                        bal = float(df_day['融资余额'].iloc[0])
                        if bal > 0:
                            sz_margin[dt] = bal
                            filled_sz += 1
                        break
                    except Exception:
                        if attempt < 2:
                            time.sleep(5)

            # 增量保存
            if (filled_sh + filled_sz) > 0 and (filled_sh + filled_sz) % 20 == 0:
                for d in set(list(sh_margin.keys()) + list(sz_margin.keys())):
                    if d not in cache:
                        cache[d] = {}
                    if d in sh_margin:
                        cache[d]['sh'] = round(sh_margin[d], 4)
                    if d in sz_margin:
                        cache[d]['sz'] = round(sz_margin[d], 4)
                _save_margin_cache(cache)
                print(f"    已获取... 沪市+{filled_sh} 深市+{filled_sz}")

            time.sleep(1)  # 每日查询间隔

        # 保存缓存
        for d in set(list(sh_margin.keys()) + list(sz_margin.keys())):
            if d not in cache:
                cache[d] = {}
            if d in sh_margin:
                cache[d]['sh'] = round(sh_margin[d], 4)
            if d in sz_margin:
                cache[d]['sz'] = round(sz_margin[d], 4)
        _save_margin_cache(cache)
        print(f"  补漏完成: 沪市+{filled_sh}, 深市+{filled_sz}, 缓存共 {len(cache)} 天")

    # ── 合并计算 ratio（仅使用当天有完整沪深数据的日期） ──
    results = {}
    margin_gaps = []
    all_dates = sorted(set(list(sh_margin.keys()) + list(sz_margin.keys())))

    for dt in all_dates:
        sh = sh_margin.get(dt)
        sz = sz_margin.get(dt)

        if sh is None and sz is None:
            margin_gaps.append((dt, "沪市+深市"))
            continue
        if sh is None:
            margin_gaps.append((dt, "沪市"))
            continue
        if sz is None:
            margin_gaps.append((dt, "深市"))
            continue

        total_yi = sh + sz  # 亿元
        if total_yi > 0:
            mcap_yi = get_float_mcap(dt)  # 亿元
            if mcap_yi and mcap_yi > 0:
                results[dt] = (total_yi / mcap_yi, round(sh, 4), round(sz, 4))  # (ratio, sh亿, sz亿)

    if margin_gaps:
        _append_margin_gaps_to_log(margin_gaps)

    print(f"  融资占比数据: {len(results)} 天")
    return results


def _append_margin_gaps_to_log(gaps):
    """将融资余额缺失记录追加到 log.md"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [f"\n### 融资余额数据缺失记录（{now}）\n\n"]
    lines.append(f"共 {len(gaps)} 天存在缺失，已用前值填充：\n\n")
    lines.append("| 日期 | 缺失市场 |\n")
    lines.append("|------|----------|\n")
    for dt, side in gaps:
        lines.append(f"| {dt} | {side} |\n")

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"  缺失记录已写入 log.md（{len(gaps)} 条）")


def _invalidate_recent_caches(dates):
    """清除指定日期的所有缓存，强制重新获取。
    换手率/成交额缓存：仅清除 0 值条目（正常数据不会变，且重算需要 ltsz_cache）。
    融资余额/涨停缓存：全部清除（强制重新获取）。"""

    # 换手率缓存：仅清除 0 值条目
    tc = _load_turnover_cache()
    tc_changed = False
    for dt in dates:
        if dt in tc:
            entry = tc[dt]
            if isinstance(entry, dict) and entry.get('turnover_rate', 0) == 0:
                del tc[dt]
                tc_changed = True
    if tc_changed:
        _save_turnover_cache(tc)

    # 成交额缓存：仅清除 0 值条目
    cje = _load_cje_cache()
    cje_changed = False
    for dt in dates:
        if dt in cje:
            entry = cje[dt]
            if isinstance(entry, dict) and entry.get('sh', 0) == 0 and entry.get('sz', 0) == 0:
                del cje[dt]
                cje_changed = True
    if cje_changed:
        _save_cje_cache(cje)

    # 融资余额缓存：清除全部（或 0 值条目）
    if MARGIN_CACHE.exists():
        with open(MARGIN_CACHE, 'r', encoding='utf-8') as f:
            mc = json.load(f)
        mc_changed = False
        for dt in dates:
            if dt in mc:
                del mc[dt]
                mc_changed = True
        if mc_changed:
            with open(MARGIN_CACHE, 'w', encoding='utf-8') as f:
                json.dump(mc, f, ensure_ascii=False, indent=2)

    # 涨停缓存
    lc = _load_limitup_cache()
    lc_changed = False
    for dt in dates:
        if dt in lc:
            del lc[dt]
            lc_changed = True
    if lc_changed:
        _save_limitup_cache(lc)

    print(f"  已清除 {len(dates)} 天缓存，准备重新获取")


MARGIN_CACHE = DATA_DIR / "margin_cache.json"


def _load_margin_cache():
    """加载融资余额缓存（亿元）"""
    if MARGIN_CACHE.exists():
        with open(MARGIN_CACHE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_margin_cache(cache):
    """保存融资余额缓存（亿元）"""
    DATA_DIR.mkdir(exist_ok=True)
    with open(MARGIN_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


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
            # 只缺少几天时，仅取最近一小批数据（刷新模式）
            if len(missing) <= 10:
                data = client.index(symbol='880006', frequency=9, start=0, offset=20) # type: ignore
                if data is not None and len(data) > 0:
                    all_data.append(data)
            else:
                for start in range(0, 5000, 800):
                    data = client.index(symbol='880006', frequency=9, start=start, offset=800) # type: ignore
                    if data is None or len(data) == 0:
                        break
                    all_data.append(data)
                    if len(data) < 800:
                        break
                    time.sleep(1)

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


def compute_percentile(history, current, window=PERCENTILE_WINDOW):
    """计算当前值在最近 window 个值中的分位数（0-100）"""
    if len(history) < 2:
        return 50.0
    recent = history[-window:] if len(history) >= window else history
    rank = sum(1 for v in recent if v <= current)
    return (rank / len(recent)) * 100


def compute_dynamic_thresholds(eindex_hist, window=PERCENTILE_WINDOW):
    """基于滚动窗口内 eIndex 历史值，计算恐惧/贪婪动态阈值。
    返回 (fear_threshold, greed_threshold)。"""
    if len(eindex_hist) < 2:
        return (FEAR_PERCENTILE, GREED_PERCENTILE)
    recent = eindex_hist[-window:] if len(eindex_hist) >= window else eindex_hist
    s = sorted(recent)
    n = len(s)
    fear_idx = max(0, int(n * FEAR_PERCENTILE / 100) - 1)
    greed_idx = min(n - 1, int(n * GREED_PERCENTILE / 100))
    return (round(s[fear_idx], 2), round(s[greed_idx], 2))


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

    # ── 获取四大指标 ──
    turnover_data = get_turnover_data(ak, trade_dates)
    margin_data = get_margin_data(ak, trade_dates)

    # 涨停数据使用通达信 880006 + 持久化缓存
    limitup_data = get_limitup_data(ak, trade_dates)

    # 市场方向因子（880008 N日收益率）
    return_data = get_market_return(trade_dates)

    # 成交额数据（亿元）
    cje_cache = _load_cje_cache()

    # ── 计算情绪指数 ──
    print("计算情绪指数...")
    results = []
    t_hist, m_hist, l_hist, cje_hist, ret_hist = [], [], [], [], []

    for dt in trade_dates:
        t_val = turnover_data.get(dt)
        m_entry = margin_data.get(dt)
        m_val = m_entry[0] if m_entry is not None else None
        m_sh = m_entry[1] if m_entry is not None else 0
        m_sz = m_entry[2] if m_entry is not None else 0
        l_entry = limitup_data.get(dt)
        l_val = l_entry[0] if l_entry is not None else None
        l_count = l_entry[1] if l_entry is not None else 0
        ret_val = return_data.get(dt)

        cje_entry = cje_cache.get(dt)
        cje_val = round(cje_entry['sh'] + cje_entry['sz'], 4) if cje_entry else None

        if t_val is not None:
            t_hist.append(t_val)
        if m_val is not None:
            m_hist.append(m_val)
        if l_val is not None:
            l_hist.append(l_val)
        if cje_val is not None and cje_val > 0:
            cje_hist.append(cje_val)
        if ret_val is not None:
            ret_hist.append(ret_val)

        # 至少需要一个指标有数据
        if cje_val is None and m_val is None and l_val is None:
            continue

        t_pct = compute_percentile(t_hist, t_val) if t_val is not None else None
        m_pct = compute_percentile(m_hist, m_val) if m_val is not None else None
        l_pct = compute_percentile(l_hist, l_val) if l_val is not None else None
        cje_pct = compute_percentile(cje_hist, cje_val) if (cje_val is not None and cje_val > 0) else None
        ret_pct = compute_percentile(ret_hist, ret_val) if ret_val is not None else None

        # 四大核心指标加权平均
        parts, weights = [], []
        if cje_pct is not None:
            parts.append(cje_pct * W_CJE); weights.append(W_CJE)
        if m_pct is not None:
            parts.append(m_pct * W_MARGIN); weights.append(W_MARGIN)
        if l_pct is not None:
            parts.append(l_pct * W_LIMITUP); weights.append(W_LIMITUP)
        if ret_pct is not None:
            parts.append(ret_pct * W_RETURN); weights.append(W_RETURN)
        if not weights:
            continue
        eindex = sum(parts) / sum(weights)

        # 动态阈值：基于滚动窗口内已有 eIndex 的分位数
        eindex_hist = [r['eindex'] for r in results]
        fear_th, greed_th = compute_dynamic_thresholds(eindex_hist)

        results.append({
            "date": dt,
            "eindex": round(eindex, 2),
            "fear_threshold": fear_th,
            "greed_threshold": greed_th,
            "turnover_rate": round(t_val, 6) if t_val is not None else 0,
            "turnover_pct": round(t_pct, 2) if t_pct is not None else 0,
            "margin_ratio": round(m_val, 6) if m_val is not None else 0,
            "margin_pct": round(m_pct, 2) if m_pct is not None else 0,
            "margin_sh": round(m_sh, 2),
            "margin_sz": round(m_sz, 2),
            "limitup_count": l_count,
            "limitup_ratio": round(l_val, 6) if l_val is not None else 0,
            "limitup_pct": round(l_pct, 2) if l_pct is not None else 0,
            "cje_amount": round(cje_val, 2) if cje_val is not None else 0,
            "cje_pct": round(cje_pct, 2) if cje_pct is not None else 0,
        })

    # ── 保存 ──
    output = {
        "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "data": results
    }

    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    _save_js_version(output)

    print(f"\n数据已保存: {DATA_FILE}")
    print(f"共 {len(results)} 条记录")
    if results:
        latest = results[-1]
        sig = "恐惧" if latest['eindex'] <= latest.get('fear_threshold', FEAR_PERCENTILE) else "贪婪" if latest['eindex'] >= latest.get('greed_threshold', GREED_PERCENTILE) else "中性"
        print(f"最新: {latest['date']}  eIndex={latest['eindex']}  信号={sig}  恐惧线={latest.get('fear_threshold', '?')}  贪婪线={latest.get('greed_threshold', '?')}")


def _fill_missing_with_zero(dates, turnover_data, margin_data, limitup_data):
    """刷新模式下，获取不到的数据仅在内存中补 0（用于本次计算），
    不写入缓存文件，以便下次运行时自动重新获取。返回警告列表。"""
    warnings = []

    # 换手率（仅内存补 0，不写缓存）
    for dt in dates:
        if dt not in turnover_data:
            turnover_data[dt] = 0
            warnings.append(f"{dt} 换手率数据缺失")
            print(f"  ⚠ {dt} 换手率获取失败，本次按 0 计算（不写入缓存，下次将重试）")

    # 融资余额（仅内存补 0，不写缓存）
    mc = _load_margin_cache()
    for dt in dates:
        if dt not in margin_data:
            margin_data[dt] = (0, 0, 0)
            entry = mc.get(dt, {})
            has_sh = entry.get('sh', 0) > 0
            has_sz = entry.get('sz', 0) > 0
            if not has_sh and not has_sz:
                missing_side = "上交所+深交所"
            elif not has_sh:
                missing_side = "上交所"
            else:
                missing_side = "深交所"
            warnings.append(f"{dt} 融资余额数据缺失（{missing_side}）")
            print(f"  ⚠ {dt} 融资余额获取失败（{missing_side}），本次按 0 计算（不写入缓存，下次将重试）")

    # 涨停（仅内存补 0，不写缓存）
    for dt in dates:
        if dt not in limitup_data:
            limitup_data[dt] = (0, 0)
            warnings.append(f"{dt} 涨停数据缺失")
            print(f"  ⚠ {dt} 涨停数据获取失败，本次按 0 计算（不写入缓存，下次将重试）")

    return warnings


def generate_data_recent(n_days=2):
    """增量更新最近 n_days 个交易日的数据（由刷新按钮触发）"""
    ak = ensure_akshare()

    old_data = load_existing()
    if not old_data or not old_data.get('data'):
        print("无已有数据，请先执行 --full 全量更新")
        return

    existing = old_data['data']
    existing_by_date = {d['date']: d for d in existing}

    # 获取交易日历
    trade_dates = get_trade_dates(ak)
    recent_dates = trade_dates[-n_days:]
    print(f"增量更新最近 {n_days} 个交易日: {recent_dates[0]} ~ {recent_dates[-1]}")

    # 强制清除最近几天的缓存，确保重新获取
    _invalidate_recent_caches(recent_dates)

    # 获取四大指标（仅重新获取 recent_dates）
    turnover_data = get_turnover_data(ak, recent_dates)
    margin_data = get_margin_data(ak, recent_dates)
    limitup_data = get_limitup_data(ak, recent_dates)

    # 市场方向因子（880008 N日收益率）— 需要全部交易日来计算
    return_data = get_market_return(trade_dates)

    # 刷新模式：获取不到的数据按 0 存入缓存
    warnings = _fill_missing_with_zero(recent_dates, turnover_data, margin_data, limitup_data)

    # 成交额数据（亿元）
    cje_cache = _load_cje_cache()

    # 从已有数据重建历史分位序列（用于计算分位数）
    t_hist = [d['turnover_rate'] for d in existing if d['turnover_rate'] > 0 and d['date'] < recent_dates[0]]
    m_hist = [d['margin_ratio'] for d in existing if d['margin_ratio'] > 0 and d['date'] < recent_dates[0]]
    l_hist = [d['limitup_ratio'] for d in existing if d['limitup_ratio'] > 0 and d['date'] < recent_dates[0]]
    cje_hist = [d.get('cje_amount', 0) for d in existing if d.get('cje_amount', 0) > 0 and d['date'] < recent_dates[0]]
    # 880008 收益率历史：从 return_data 中取 recent_dates 之前的数据
    ret_hist = [return_data[dt] for dt in sorted(return_data.keys()) if dt < recent_dates[0]]

    updated = 0
    for dt in recent_dates:
        t_val = turnover_data.get(dt)
        m_entry = margin_data.get(dt)
        m_val = m_entry[0] if m_entry is not None else None
        m_sh = m_entry[1] if m_entry is not None else 0
        m_sz = m_entry[2] if m_entry is not None else 0
        l_entry = limitup_data.get(dt)
        l_val = l_entry[0] if l_entry is not None else None
        l_count = l_entry[1] if l_entry is not None else 0
        ret_val = return_data.get(dt)

        cje_entry = cje_cache.get(dt)
        cje_val = round(cje_entry['sh'] + cje_entry['sz'], 4) if cje_entry else None

        if t_val is not None:
            t_hist.append(t_val)
        if m_val is not None:
            m_hist.append(m_val)
        if l_val is not None:
            l_hist.append(l_val)
        if cje_val is not None and cje_val > 0:
            cje_hist.append(cje_val)
        if ret_val is not None:
            ret_hist.append(ret_val)

        if cje_val is None and m_val is None and l_val is None:
            continue

        t_pct = compute_percentile(t_hist, t_val) if t_val is not None else None
        m_pct = compute_percentile(m_hist, m_val) if m_val is not None else None
        l_pct = compute_percentile(l_hist, l_val) if l_val is not None else None
        cje_pct = compute_percentile(cje_hist, cje_val) if (cje_val is not None and cje_val > 0) else None
        ret_pct = compute_percentile(ret_hist, ret_val) if ret_val is not None else None

        # 四大核心指标加权平均
        parts, weights = [], []
        if cje_pct is not None:
            parts.append(cje_pct * W_CJE); weights.append(W_CJE)
        if m_pct is not None:
            parts.append(m_pct * W_MARGIN); weights.append(W_MARGIN)
        if l_pct is not None:
            parts.append(l_pct * W_LIMITUP); weights.append(W_LIMITUP)
        if ret_pct is not None:
            parts.append(ret_pct * W_RETURN); weights.append(W_RETURN)
        if not weights:
            continue
        eindex = sum(parts) / sum(weights)

        # 动态阈值：使用 existing_by_date（含本次已更新的记录）
        eindex_hist_for_th = [existing_by_date[d]['eindex'] for d in sorted(existing_by_date) if d < dt and existing_by_date[d]['eindex'] > 0]
        fear_th, greed_th = compute_dynamic_thresholds(eindex_hist_for_th)

        existing_by_date[dt] = {
            "date": dt,
            "eindex": round(eindex, 2),
            "fear_threshold": fear_th,
            "greed_threshold": greed_th,
            "turnover_rate": round(t_val, 6) if t_val is not None else 0,
            "turnover_pct": round(t_pct, 2) if t_pct is not None else 0,
            "margin_ratio": round(m_val, 6) if m_val is not None else 0,
            "margin_pct": round(m_pct, 2) if m_pct is not None else 0,
            "margin_sh": round(m_sh, 2),
            "margin_sz": round(m_sz, 2),
            "limitup_count": l_count,
            "limitup_ratio": round(l_val, 6) if l_val is not None else 0,
            "limitup_pct": round(l_pct, 2) if l_pct is not None else 0,
            "cje_amount": round(cje_val, 2) if cje_val is not None else 0,
            "cje_pct": round(cje_pct, 2) if cje_pct is not None else 0,
        }
        updated += 1

    merged = sorted(existing_by_date.values(), key=lambda x: x['date'])

    # 补填旧记录中可能缺失的 fear_threshold / greed_threshold
    eindex_hist_backfill = []
    for d in merged:
        if 'fear_threshold' not in d or 'greed_threshold' not in d:
            fear_th, greed_th = compute_dynamic_thresholds(eindex_hist_backfill)
            d['fear_threshold'] = fear_th
            d['greed_threshold'] = greed_th
        eindex_hist_backfill.append(d['eindex'])

    output = {
        "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "warnings": warnings,
        "data": merged
    }

    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    _save_js_version(output)

    print(f"\n增量更新完成: 更新/新增 {updated} 天，总计 {len(merged)} 条")
    if merged:
        latest = merged[-1]
        sig = "恐惧" if latest['eindex'] <= latest.get('fear_threshold', FEAR_PERCENTILE) else "贪婪" if latest['eindex'] >= latest.get('greed_threshold', GREED_PERCENTILE) else "中性"
        print(f"最新: {latest['date']}  eIndex={latest['eindex']}  信号={sig}  恐惧线={latest.get('fear_threshold', '?')}  贪婪线={latest.get('greed_threshold', '?')}")


def _save_js_version(output):
    """同时保存 JS 版本，供本地 file:// 打开时使用"""
    js_content = 'window.__EINDEX_DATA__ = ' + json.dumps(output, ensure_ascii=False) + ';\n'
    with open(DATA_JS_FILE, 'w', encoding='utf-8') as f:
        f.write(js_content)


def _bump_version():
    """自动更新 index.html 中的版本号（格式 vYYYY-MM-DD-NNN）"""
    import re
    if not INDEX_HTML.exists():
        return
    html = INDEX_HTML.read_text(encoding='utf-8')
    today = datetime.now().strftime('%Y-%m-%d')
    m = re.search(r'v(\d{4}-\d{2}-\d{2})-(\d{3})', html)
    if m and m.group(1) == today:
        seq = int(m.group(2)) + 1
    else:
        seq = 1
    new_ver = f'v{today}-{seq:03d}'
    html_new = re.sub(r'v\d{4}-\d{2}-\d{2}-\d{3}', new_ver, html)
    INDEX_HTML.write_text(html_new, encoding='utf-8')
    print(f"版本号已更新: {new_ver}")


if __name__ == '__main__':
    if '--bump-version' in sys.argv:
        _bump_version()
    elif '--recent' in sys.argv:
        generate_data_recent()
    else:
        generate_data()
