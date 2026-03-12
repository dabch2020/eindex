#!/usr/bin/env python3
"""生成示例数据用于页面展示"""

import json
import math
import random
from datetime import datetime, timedelta, date
from pathlib import Path

random.seed(42)


def get_cn_holidays():
    """返回A股休市的公共假日集合（2015-2026）"""
    holidays = set()

    # 辅助函数：添加日期范围
    def add_range(y, m_start, d_start, m_end, d_end):
        d = date(y, m_start, d_start)
        end = date(y, m_end, d_end)
        while d <= end:
            holidays.add(d)
            d += timedelta(days=1)

    for y in range(2015, 2027):
        # 元旦 (1月1日，通常放1-3天)
        add_range(y, 1, 1, 1, 1)

        # 春节 (约1月底-2月中，放7天)
        spring_festival = {
            2015: (2, 18, 2, 24), 2016: (2, 7, 2, 13), 2017: (1, 27, 2, 2),
            2018: (2, 15, 2, 21), 2019: (2, 4, 2, 10), 2020: (1, 24, 1, 31),
            2021: (2, 11, 2, 17), 2022: (1, 31, 2, 6), 2023: (1, 21, 1, 27),
            2024: (2, 10, 2, 17), 2025: (1, 28, 2, 4), 2026: (2, 17, 2, 23),
        }
        if y in spring_festival:
            add_range(y, *spring_festival[y])

        # 清明节 (4月4-6日左右，放3天)
        add_range(y, 4, 4, 4, 6)

        # 劳动节 (5月1-5日，放5天)
        add_range(y, 5, 1, 5, 5)

        # 端午节 (约6月中，放3天)
        dragon_boat = {
            2015: (6, 20, 6, 22), 2016: (6, 9, 6, 11), 2017: (5, 28, 5, 30),
            2018: (6, 16, 6, 18), 2019: (6, 7, 6, 9), 2020: (6, 25, 6, 27),
            2021: (6, 12, 6, 14), 2022: (6, 3, 6, 5), 2023: (6, 22, 6, 24),
            2024: (6, 8, 6, 10), 2025: (5, 31, 6, 2), 2026: (6, 19, 6, 21),
        }
        if y in dragon_boat:
            add_range(y, *dragon_boat[y])

        # 中秋节 (约9-10月，放3天)
        mid_autumn = {
            2015: (9, 26, 9, 27), 2016: (9, 15, 9, 17), 2017: (10, 4, 10, 4),
            2018: (9, 22, 9, 24), 2019: (9, 13, 9, 15), 2020: (10, 1, 10, 1),
            2021: (9, 19, 9, 21), 2022: (9, 10, 9, 12), 2023: (9, 29, 9, 29),
            2024: (9, 15, 9, 17), 2025: (10, 6, 10, 8), 2026: (9, 25, 9, 27),
        }
        if y in mid_autumn:
            add_range(y, *mid_autumn[y])

        # 国庆节 (10月1-7日)
        add_range(y, 10, 1, 10, 7)

    return holidays


def generate_sample_data():
    """生成从2015年至今的模拟数据"""
    data = []
    start = datetime(2015, 1, 5)

    # A股公共假日
    cn_holidays = get_cn_holidays()

    # 模拟市场周期
    turnover_base = 0.012  # 1.2%
    margin_base = 0.022    # 2.2%
    limitup_base = 0.008   # 0.8%
    
    turnover_history = []
    margin_history = []
    limitup_history = []
    
    day_count = 0
    current = start
    end = datetime(2026, 3, 12)
    
    while current <= end:
        # 跳过周末
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        
        # 跳过A股公共假日
        if current.date() in cn_holidays:
            current += timedelta(days=1)
            continue
        
        t = day_count / 250.0  # 归一化时间
        
        # 使用正弦函数模拟市场周期
        cycle = math.sin(t * 2 * math.pi * 0.8 + random.gauss(0, 0.1))
        trend = math.sin(t * 2 * math.pi * 0.3) * 0.5
        
        # 换手率
        turnover = turnover_base * (1 + 0.4 * cycle + 0.2 * trend + random.gauss(0, 0.15))
        turnover = max(0.004, min(0.035, turnover))
        turnover_history.append(turnover)
        
        # 融资余额占比
        margin = margin_base * (1 + 0.15 * cycle + 0.1 * trend + random.gauss(0, 0.05))
        margin = max(0.015, min(0.032, margin))
        margin_history.append(margin)
        
        # 涨停家数占比
        limitup = limitup_base * (1 + 0.6 * cycle + 0.3 * trend + random.gauss(0, 0.25))
        limitup = max(0.001, min(0.025, limitup))
        limitup_history.append(limitup)
        
        # 计算分位数
        window = 250
        def percentile(history, val):
            recent = history[-window:] if len(history) >= window else history
            rank = sum(1 for v in recent if v <= val)
            return (rank / len(recent)) * 100
        
        t_pct = percentile(turnover_history, turnover)
        m_pct = percentile(margin_history, margin)
        l_pct = percentile(limitup_history, limitup)
        
        eindex = (t_pct + m_pct + l_pct) / 3
        
        data.append({
            "date": current.strftime('%Y-%m-%d'),
            "eindex": round(eindex, 2),
            "turnover_rate": round(turnover, 6),
            "turnover_pct": round(t_pct, 2),
            "margin_ratio": round(margin, 6),
            "margin_pct": round(m_pct, 2),
            "limitup_ratio": round(limitup, 6),
            "limitup_pct": round(l_pct, 2)
        })
        
        day_count += 1
        current += timedelta(days=1)
    
    output = {
        "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "data": data
    }
    
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    with open(data_dir / "eindex_data.json", 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"生成 {len(data)} 条模拟数据")
    print(f"最新: {data[-1]['date']} eIndex={data[-1]['eindex']}")

if __name__ == '__main__':
    generate_sample_data()
