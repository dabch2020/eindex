#!/usr/bin/env python3
"""
快速并发版 ltsz 补全脚本。
使用线程池并发抓取 SZSE 和 SSE 数据，大幅加速。
SZSE 和 SSE 是不同站点，可以同时请求。
同一站点保持适当间隔防止限流。
"""
import json
import time
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "ltsz_cache.json"
EINDEX_DATA = DATA_DIR / "eindex_data.json"

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

cache_lock = Lock()
save_counter = 0


def _load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def _parse_number(s):
    if not s or s == "-":
        return None
    return float(s.replace(",", ""))


def fetch_sse(date_str, retries=2):
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
            nego = results[0].get("NEGO_VALUE")
            return _parse_number(nego)
        except Exception:
            if attempt < retries:
                time.sleep(2)
    return None


def fetch_szse(date_str, retries=2):
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
        except Exception:
            if attempt < retries:
                time.sleep(2)
    return None


def fetch_szse_batch(dates, cache, delay=0.6):
    """串行抓取一批 SZSE 数据（同站点需串行）"""
    global save_counter
    results = {}
    for i, dt in enumerate(dates):
        sz = fetch_szse(dt)
        if sz is not None:
            results[dt] = sz
            with cache_lock:
                if dt not in cache:
                    cache[dt] = {}
                cache[dt]["sz"] = round(sz, 2)
                save_counter += 1
                if save_counter % 100 == 0:
                    _save_cache(cache)
                    print(f"  [SZSE] 已保存 {save_counter} 条", flush=True)
        if i < len(dates) - 1:
            time.sleep(delay)
    return results


def fetch_sse_batch(dates, cache, delay=0.8):
    """串行抓取一批 SSE 数据（同站点需串行）"""
    global save_counter
    results = {}
    for i, dt in enumerate(dates):
        sh = fetch_sse(dt)
        if sh is not None:
            results[dt] = sh
            with cache_lock:
                if dt not in cache:
                    cache[dt] = {}
                cache[dt]["sh"] = round(sh, 2)
                save_counter += 1
                if save_counter % 100 == 0:
                    _save_cache(cache)
                    print(f"  [SSE] 已保存 {save_counter} 条", flush=True)
        if i < len(dates) - 1:
            time.sleep(delay)
    return results


def main():
    cache = _load_cache()

    with open(EINDEX_DATA, "r", encoding="utf-8") as f:
        all_dates = [r["date"] for r in json.load(f)["data"]]

    # 找缺失日期
    missing_sz = [d for d in all_dates if d not in cache or "sz" not in cache[d]]
    missing_sh = [d for d in all_dates if d >= "2018-01-01" and (d not in cache or "sh" not in cache[d])]

    print(f"总交易日: {len(all_dates)}")
    print(f"缺 SZSE: {len(missing_sz)}")
    print(f"缺 SSE (2018+): {len(missing_sh)}")

    if not missing_sz and not missing_sh:
        print("已全部缓存！")
        return

    # SZSE 和 SSE 同时抓取（不同站点可并行）
    # 各自内部串行（同站点需串行避免限流）
    global save_counter
    save_counter = 0

    print(f"\n开始并发抓取: SZSE {len(missing_sz)} 天 + SSE {len(missing_sh)} 天")
    est_sec = max(len(missing_sz) * 0.6, len(missing_sh) * 0.8)
    print(f"预计耗时约 {est_sec/60:.0f} 分钟")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        if missing_sz:
            futures.append(executor.submit(fetch_szse_batch, missing_sz, cache, 0.6))
        if missing_sh:
            futures.append(executor.submit(fetch_sse_batch, missing_sh, cache, 0.8))

        for f in as_completed(futures):
            try:
                result = f.result()
                print(f"  线程完成: 获取 {len(result)} 条")
            except Exception as e:
                print(f"  线程异常: {e}")

    _save_cache(cache)
    print(f"\n完成！缓存总计 {len(cache)} 条")

    # 统计
    has_both = sum(1 for v in cache.values() if v.get("sh", 0) > 0 and v.get("sz", 0) > 0)
    sz_only = sum(1 for v in cache.values() if v.get("sh", 0) == 0 and v.get("sz", 0) > 0)
    print(f"  SH+SZ 完整: {has_both}")
    print(f"  仅 SZ: {sz_only}")


if __name__ == "__main__":
    main()
