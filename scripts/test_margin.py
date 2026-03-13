#!/usr/bin/env python3
"""
eIndex 融资余额数据测试
按 test_spec.md：
- 读取本地缓存数据库中，深交所和上交所 2025-04-08 ~ 2025-04-10 融资余额绝对值
- 不用 macro 接口
- 单位：万亿，打印
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
MARGIN_CACHE = DATA_DIR / "margin_cache.json"

def main():
    dates = ['2025-04-08', '2025-04-09', '2025-04-10']

    print("=" * 65)
    print("融资余额绝对值（读取本地缓存，单位：万亿）")
    print("=" * 65)

    with open(MARGIN_CACHE, 'r', encoding='utf-8') as f:
        cache = json.load(f)

    print(f"\n缓存文件: {MARGIN_CACHE}")
    print(f"缓存总天数: {len(cache)}")

    print(f"\n{'日期':>12}  {'沪市(万亿)':>12}  {'深市(万亿)':>12}  {'合计(万亿)':>12}")
    print("-" * 65)
    for dt in dates:
        entry = cache.get(dt, {})
        sh = entry.get('sh')  # 缓存单位：亿元
        sz = entry.get('sz')  # 缓存单位：亿元
        sh_t = f"{sh / 10000:.4f}" if sh else "N/A"
        sz_t = f"{sz / 10000:.4f}" if sz else "N/A"
        if sh and sz:
            total_t = f"{(sh + sz) / 10000:.4f}"
        else:
            total_t = "N/A"
        print(f"{dt:>12}  {sh_t:>12}  {sz_t:>12}  {total_t:>12}")
    print("=" * 65)


if __name__ == '__main__':
    main()
