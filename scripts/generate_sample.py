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

    # A股历史市场阶段 — 每个阶段定义基准倍率
    # (start_date, end_date, turnover_mult, margin_mult, limitup_mult, noise_scale)
    # turnover_mult: 成交额相对基准的倍率
    # margin_mult: 融资余额相对基准的倍率
    # limitup_mult: 涨停数相对基准的倍率
    market_phases = [
        # 2015 H1 大牛市：天量成交、大量涨停、融资爆发
        ("2015-01-05", "2015-06-12", 2.2, 1.5, 2.5, 0.08),
        # 2015 股灾：成交缩量但仍较高、融资强制平仓下降、涨停极少
        ("2015-06-15", "2015-09-30", 1.6, 1.1, 0.3, 0.10),
        # 2015 Q4 弱反弹
        ("2015-10-08", "2015-12-31", 1.1, 0.95, 0.8, 0.08),
        # 2016 熔断后震荡
        ("2016-01-04", "2016-02-29", 0.7, 0.8, 0.3, 0.06),
        # 2016 震荡回升
        ("2016-03-01", "2016-12-30", 0.85, 0.85, 0.7, 0.06),
        # 2017 蓝筹结构牛 — 成交温和、融资平稳、涨停少
        ("2017-01-03", "2017-12-29", 0.75, 0.82, 0.5, 0.05),
        # 2018 贸易战熊市 — 全面低迷
        ("2018-01-02", "2018-12-28", 0.6, 0.7, 0.4, 0.06),
        # 2019 Q1 春季躁动 — 短暂放量
        ("2019-01-02", "2019-04-19", 1.3, 0.9, 1.4, 0.08),
        # 2019 Q2-Q4 回落震荡
        ("2019-04-22", "2019-12-31", 0.8, 0.85, 0.6, 0.05),
        # 2020 Q1 疫情暴跌
        ("2020-01-02", "2020-03-23", 0.9, 0.75, 0.35, 0.10),
        # 2020 Q2-Q3 流动性牛市
        ("2020-03-24", "2020-09-30", 1.5, 1.1, 1.6, 0.08),
        # 2020 Q4 回落
        ("2020-10-08", "2020-12-31", 0.95, 0.95, 0.8, 0.05),
        # 2021 H1 抱团牛末期
        ("2021-01-04", "2021-02-18", 1.4, 1.05, 1.3, 0.08),
        # 2021 抱团瓦解后震荡
        ("2021-02-19", "2021-12-31", 0.9, 0.9, 0.7, 0.06),
        # 2022 全年熊市
        ("2022-01-04", "2022-10-31", 0.65, 0.72, 0.4, 0.06),
        # 2022 Q4 弱反弹
        ("2022-11-01", "2022-12-30", 0.85, 0.78, 0.7, 0.06),
        # 2023 年初反弹后持续低迷
        ("2023-01-03", "2023-02-28", 1.1, 0.85, 1.0, 0.06),
        ("2023-03-01", "2023-12-29", 0.6, 0.7, 0.4, 0.05),
        # 2024 H1 继续低迷
        ("2024-01-02", "2024-09-23", 0.55, 0.65, 0.35, 0.05),
        # 2024 924行情大爆发
        ("2024-09-24", "2024-10-08", 2.8, 1.3, 3.0, 0.05),
        # 2024 Q4 冲高回落
        ("2024-10-09", "2024-12-31", 1.2, 1.0, 1.0, 0.07),
        # 2025 震荡分化
        ("2025-01-02", "2025-12-31", 0.9, 0.88, 0.7, 0.06),
        # 2026 至今
        ("2026-01-02", "2026-12-31", 0.8, 0.82, 0.6, 0.05),
    ]

    def get_phase(dt_str):
        for ps, pe, tm, mm, lm, ns in market_phases:
            if ps <= dt_str <= pe:
                return tm, mm, lm, ns
        return 1.0, 1.0, 1.0, 0.06

    turnover_base = 0.012   # 基准换手率 ~1.2%
    margin_base = 0.022     # 基准融资占比 ~2.2%
    limitup_base = 0.008    # 基准涨停占比 ~0.8%

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

        dt_str = current.strftime('%Y-%m-%d')
        tm, mm, lm, ns = get_phase(dt_str)

        # 各指标独立噪声 + 阶段倍率
        turnover = turnover_base * tm * (1 + random.gauss(0, ns))
        turnover = max(0.003, min(0.040, turnover))
        turnover_history.append(turnover)

        margin = margin_base * mm * (1 + random.gauss(0, ns * 0.5))
        margin = max(0.010, min(0.038, margin))
        margin_history.append(margin)

        limitup = limitup_base * lm * (1 + random.gauss(0, ns * 1.5))
        limitup = max(0.0005, min(0.030, limitup))
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
