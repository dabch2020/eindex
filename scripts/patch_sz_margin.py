#!/usr/bin/env python3
"""
从东方财富 datacenter API 抓取缺失的深市融资余额数据，
存为 data/sz_rz193.json（单位：亿元）。
"""
import json
import sys
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
MARGIN_CACHE = DATA_DIR / "margin_cache.json"
OUTPUT_FILE = DATA_DIR / "sz_rz193.json"

URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def get_missing_dates():
    """从 margin_cache.json 找出缺少 SZ 数据的日期"""
    with open(MARGIN_CACHE, "r", encoding="utf-8") as f:
        cache = json.load(f)
    return sorted(d for d, v in cache.items() if "sz" not in v or v.get("sz", 0) <= 0)


def fetch_eastmoney_sz_margin():
    """
    用 RPTA_WEB_RZRQ_LSSH 接口批量获取深证融资余额。
    SCDM=001 => 深证, RZYE 单位：元
    """
    result = {}
    page = 1
    page_size = 500

    while True:
        params = {
            "reportName": "RPTA_WEB_RZRQ_LSSH",
            "columns": "DIM_DATE,RZYE,SCDM",
            "filter": '(SCDM="001")',
            "pageSize": page_size,
            "pageNumber": page,
            "sortColumns": "DIM_DATE",
            "sortTypes": -1,
            "source": "WEB",
        }
        for attempt in range(3):
            try:
                r = requests.get(URL, params=params, headers=HEADERS, timeout=30)
                data = r.json()
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  请求异常(page={page}), 重试... {e}")
                    time.sleep(3)
                else:
                    print(f"  请求失败(page={page}): {e}")
                    return result

        if not data.get("success") or not data.get("result"):
            print(f"  API 返回失败: {data.get('message', 'unknown')}")
            break

        rows = data["result"].get("data", [])
        if not rows:
            break

        for row in rows:
            dt = row["DIM_DATE"][:10]  # "2025-06-18 00:00:00" -> "2025-06-18"
            rzye = row.get("RZYE")
            if rzye and float(rzye) > 0:
                result[dt] = round(float(rzye) / 1e8, 4)  # 元 → 亿元

        total_pages = data["result"].get("pages", 1)
        print(f"  page {page}/{total_pages}, 累计 {len(result)} 条")

        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)

    return result


def main():
    missing_dates = get_missing_dates()
    print(f"缺失 SZ 数据的日期: {len(missing_dates)} 天")
    if not missing_dates:
        print("无缺失，退出。")
        return

    print("从东方财富 API 获取深市融资余额...")
    all_sz = fetch_eastmoney_sz_margin()
    print(f"  共获取深市数据 {len(all_sz)} 天")

    # 筛选出缺失日期的数据
    filled = {}
    still_missing = []
    for dt in missing_dates:
        if dt in all_sz:
            filled[dt] = all_sz[dt]
        else:
            still_missing.append(dt)

    print(f"  匹配缺失日期: {len(filled)} 天")
    if still_missing:
        print(f"  仍缺失: {len(still_missing)} 天")
        for d in still_missing[:10]:
            print(f"    {d}")
        if len(still_missing) > 10:
            print(f"    ... 共 {len(still_missing)} 天")

    # 保存 sz_rz193.json
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(filled, f, ensure_ascii=False, indent=2)
    print(f"已保存到 {OUTPUT_FILE}（{len(filled)} 天，单位：亿元）")

    # 合并到 margin_cache.json
    with open(MARGIN_CACHE, "r", encoding="utf-8") as f:
        cache = json.load(f)
    merged = 0
    for dt, val in filled.items():
        if dt in cache:
            cache[dt]["sz"] = val
            merged += 1
    with open(MARGIN_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"已合并 {merged} 天到 margin_cache.json")


if __name__ == "__main__":
    main()
