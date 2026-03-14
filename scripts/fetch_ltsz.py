#!/usr/bin/env python3
"""
从上交所和深交所官网获取每日股票流通市值，存入 data/ltsz_cache.json。

数据源：
  - 上交所: https://www.sse.com.cn/market/view/
    API: query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_SJ_SCGM_C
    字段: result[0].NEGO_VALUE（股票流通市值，亿元）
  - 深交所: https://www.szse.cn/market/index.html
    API: www.szse.cn/api/report/ShowReport/data?CATALOGID=1803
    字段: zbmc="股票流通市值（亿元）" → brsz

用法：
  python3 scripts/fetch_ltsz.py              # 补齐缺失日期（增量）
  python3 scripts/fetch_ltsz.py --recent     # 只抓最近5个交易日
  python3 scripts/fetch_ltsz.py --date 2026-03-13  # 抓单日
"""
import json
import sys
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "ltsz_cache.json"
EINDEX_DATA = DATA_DIR / "eindex_data.json"

# ── 请求配置 ──────────────────────────────────────────────
SSE_URL = "https://query.sse.com.cn/commonQuery.do"
SSE_HEADERS = {
    "Referer": "https://www.sse.com.cn/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

SZSE_URL = "https://www.szse.cn/api/report/ShowReport/data"
SZSE_HEADERS = {
    "Referer": "https://www.szse.cn/market/overview/index.html",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

REQUEST_DELAY = 1.5  # 秒，避免被限流


def _load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def _get_trading_dates():
    """从 eindex_data.json 获取所有交易日列表"""
    with open(EINDEX_DATA, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [r["date"] for r in data["data"]]


def _parse_number(s):
    """解析可能带逗号的数字字符串，如 '631,017.07' → 631017.07"""
    if not s or s == "-":
        return None
    return float(s.replace(",", ""))


def fetch_sse(date_str, retries=2):
    """
    获取上交所某日股票流通市值（亿元）。
    date_str: 'YYYY-MM-DD' 格式
    """
    trade_date = date_str.replace("-", "")
    params = {
        "sqlId": "COMMON_SSE_SJ_SCGM_C",
        "isPagination": "false",
        "TRADE_DATE": trade_date,
    }
    for attempt in range(retries + 1):
        try:
            r = requests.get(SSE_URL, params=params, headers=SSE_HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            results = data.get("result", [])
            if not results:
                return None
            # 第一行是"股票"汇总，NEGO_VALUE 为流通市值
            nego = results[0].get("NEGO_VALUE")
            return _parse_number(nego)
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
            else:
                print(f"    SSE {date_str} 失败: {e}")
                return None


def fetch_szse(date_str, retries=2):
    """
    获取深交所某日股票流通市值（亿元）。
    date_str: 'YYYY-MM-DD' 格式
    """
    params = {
        "SHOWTYPE": "JSON",
        "CATALOGID": "1803",
        "TABKEY": "tab1",
        "txtQueryDate": date_str,
    }
    for attempt in range(retries + 1):
        try:
            r = requests.get(SZSE_URL, params=params, headers=SZSE_HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            if not data or not data[0].get("data"):
                return None
            for row in data[0]["data"]:
                if "流通市值" in row.get("zbmc", ""):
                    return _parse_number(row["brsz"])
            return None
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
            else:
                print(f"    SZSE {date_str} 失败: {e}")
                return None


def fetch_date(date_str):
    """获取单日的沪深流通市值，返回 (sh, sz) 或部分 None。
    SSE API 无 2018 年以前数据，跳过以节省时间。"""
    if date_str >= "2018-01-01":
        sh = fetch_sse(date_str)
        time.sleep(REQUEST_DELAY)
    else:
        sh = None
    sz = fetch_szse(date_str)
    return sh, sz


def run(dates_to_fetch):
    """批量抓取并保存到缓存"""
    cache = _load_cache()
    total = len(dates_to_fetch)
    added = 0
    failed = []

    for i, dt in enumerate(dates_to_fetch):
        print(f"  [{i+1}/{total}] {dt} ...", end="", flush=True)
        sh, sz = fetch_date(dt)

        if sh is not None or sz is not None:
            entry = {}
            if sh is not None:
                entry["sh"] = round(sh, 2)
            if sz is not None:
                entry["sz"] = round(sz, 2)
            cache[dt] = entry
            added += 1
            sh_s = f"{sh:.2f}" if sh else "N/A"
            sz_s = f"{sz:.2f}" if sz else "N/A"
            print(f" sh={sh_s} sz={sz_s}")
        else:
            failed.append(dt)
            print(" 无数据")

        # 每50条保存一次，防止中断丢失
        if added > 0 and added % 50 == 0:
            _save_cache(cache)
            print(f"  -- 已保存 {added} 条 --")

        if i < total - 1:
            time.sleep(REQUEST_DELAY)

    _save_cache(cache)

    print(f"\n完成: 新增 {added} 条, 失败 {len(failed)} 条, 缓存总计 {len(cache)} 条")
    if failed:
        print(f"失败日期: {', '.join(failed[:20])}")
        if len(failed) > 20:
            print(f"  ... 共 {len(failed)} 条")


def main():
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            dt = sys.argv[idx + 1]
            print(f"抓取单日: {dt}")
            run([dt])
        else:
            print("用法: --date YYYY-MM-DD")
        return

    all_dates = _get_trading_dates()
    cache = _load_cache()

    if "--recent" in sys.argv:
        # 最近5个交易日
        recent = all_dates[-5:]
        missing = [d for d in recent if d not in cache]
        if not missing:
            print(f"最近5个交易日已全部缓存")
            return
        print(f"抓取最近缺失: {len(missing)} 天")
        run(missing)
    else:
        # 增量：补齐所有缺失日期
        missing = [d for d in all_dates if d not in cache]
        if not missing:
            print(f"所有 {len(all_dates)} 个交易日已全部缓存")
            return
        print(f"共 {len(all_dates)} 个交易日, 已缓存 {len(cache)}, 待抓取 {len(missing)}")
        est_min = len(missing) * REQUEST_DELAY * 2 / 60
        print(f"预计耗时约 {est_min:.0f} 分钟 (每日2次请求, 间隔{REQUEST_DELAY}s)")
        run(missing)


if __name__ == "__main__":
    main()
