#!/usr/bin/env python3
"""生成示例数据用于页面展示"""

import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

def generate_sample_data():
    """生成从2015年至今的模拟数据"""
    data = []
    start = datetime(2015, 1, 5)
    
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
        
        # 模拟随机跳过 (节假日)
        if random.random() < 0.03:
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
