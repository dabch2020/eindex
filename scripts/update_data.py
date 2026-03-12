#!/usr/bin/env python3
"""
eIndex 数据更新脚本
使用 akshare 获取A股市场数据，计算情绪指数
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


def install_akshare():
    """确保 akshare 已安装"""
    try:
        import akshare
        return akshare
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "akshare", "-q"])
        import akshare
        return akshare


def get_market_data(ak, start_date, end_date):
    """获取市场数据"""
    print("获取沪深两市成交额与流通市值...")

    # 获取上证指数日线 (用于日期参考)
    df_sh = ak.stock_zh_index_daily(symbol="sh000001")
    df_sh = df_sh[(df_sh['date'] >= start_date) & (df_sh['date'] <= end_date)]

    # 获取沪深两市每日成交额
    # 使用A股市场总貌数据
    try:
        df_market = ak.stock_szse_summary(date=end_date.replace("-", ""))
    except Exception:
        pass

    return df_sh


def get_turnover_data(ak, trade_dates):
    """获取换手率相关数据 - 全市场成交额与流通市值"""
    print("计算全市场换手率...")
    results = {}

    try:
        # 上证指数成交额
        df_sh = ak.stock_zh_index_daily(symbol="sh000001")
        df_sh['date'] = df_sh['date'].astype(str)
        sh_volume = dict(zip(df_sh['date'], df_sh['volume']))

        # 深证成指成交额
        df_sz = ak.stock_zh_index_daily(symbol="sz399001")
        df_sz['date'] = df_sz['date'].astype(str)
        sz_volume = dict(zip(df_sz['date'], df_sz['volume']))

        for dt in trade_dates:
            dt_str = dt if isinstance(dt, str) else dt.strftime('%Y-%m-%d')
            sh_vol = sh_volume.get(dt_str, 0)
            sz_vol = sz_volume.get(dt_str, 0)
            total_vol = sh_vol + sz_vol
            # 近似流通市值 (使用经验比例约 80万亿)
            float_mcap = 80e12
            if total_vol > 0:
                results[dt_str] = total_vol / float_mcap
    except Exception as e:
        print(f"获取换手率数据出错: {e}")

    return results


def get_margin_data(ak, trade_dates):
    """获取融资余额数据"""
    print("获取融资余额...")
    results = {}

    try:
        df_margin = ak.stock_margin_sse(start_date="20240101")
        df_margin['信用交易日期'] = df_margin['信用交易日期'].astype(str)
        for _, row in df_margin.iterrows():
            dt = row['信用交易日期']
            if len(dt) == 8:
                dt = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
            margin_balance = row.get('融资余额(元)', 0)
            if margin_balance and margin_balance > 0:
                float_mcap = 80e12
                results[dt] = margin_balance / float_mcap
    except Exception as e:
        print(f"获取融资数据出错: {e}")

    return results


def get_limitup_data(ak, trade_dates):
    """获取涨停股票数量"""
    print("获取涨停数据...")
    results = {}

    total_stocks = 5300  # 近似全市场股票数

    for dt_str in trade_dates[-60:]:  # 只获取最近60天避免频率限制
        try:
            dt_clean = dt_str.replace('-', '')
            df = ak.stock_zt_pool_em(date=dt_clean)
            if df is not None and len(df) > 0:
                results[dt_str] = len(df) / total_stocks
        except Exception:
            pass

    return results


def compute_percentile(values, current, window=250):
    """计算分位数"""
    if len(values) < 2:
        return 50.0
    recent = values[-window:] if len(values) >= window else values
    rank = sum(1 for v in recent if v <= current)
    return (rank / len(recent)) * 100


def generate_data():
    """主函数：获取数据并计算eIndex"""
    ak = install_akshare()

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=500)).strftime('%Y-%m-%d')

    # 获取交易日历
    print("获取交易日历...")
    df_cal = ak.stock_zh_index_daily(symbol="sh000001")
    df_cal['date'] = df_cal['date'].astype(str)
    trade_dates = sorted([d for d in df_cal['date'].tolist()
                         if start_date <= d <= end_date])

    if not trade_dates:
        print("无交易日数据")
        return

    print(f"交易日范围: {trade_dates[0]} ~ {trade_dates[-1]}, 共 {len(trade_dates)} 天")

    # 获取三大指标
    turnover_data = get_turnover_data(ak, trade_dates)
    margin_data = get_margin_data(ak, trade_dates)
    limitup_data = get_limitup_data(ak, trade_dates)

    # 计算情绪指数
    print("计算情绪指数...")
    results = []
    turnover_history = []
    margin_history = []
    limitup_history = []

    for dt in trade_dates:
        t_val = turnover_data.get(dt)
        m_val = margin_data.get(dt)
        l_val = limitup_data.get(dt)

        if t_val is not None:
            turnover_history.append(t_val)
        if m_val is not None:
            margin_history.append(m_val)
        if l_val is not None:
            limitup_history.append(l_val)

        if t_val is None and m_val is None and l_val is None:
            continue

        t_pct = compute_percentile(turnover_history, t_val) if t_val else 50
        m_pct = compute_percentile(margin_history, m_val) if m_val else 50
        l_pct = compute_percentile(limitup_history, l_val) if l_val else 50

        eindex = (t_pct + m_pct + l_pct) / 3

        results.append({
            "date": dt,
            "eindex": round(eindex, 2),
            "turnover_rate": round(t_val, 6) if t_val else 0,
            "turnover_pct": round(t_pct, 2),
            "margin_ratio": round(m_val, 6) if m_val else 0,
            "margin_pct": round(m_pct, 2),
            "limitup_ratio": round(l_val, 6) if l_val else 0,
            "limitup_pct": round(l_pct, 2)
        })

    # 保存数据
    output = {
        "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "data": results
    }

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / "eindex_data.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"数据已保存: {output_file}")
    print(f"共 {len(results)} 条记录")
    if results:
        latest = results[-1]
        print(f"最新情绪指数: {latest['eindex']} ({latest['date']})")


if __name__ == '__main__':
    generate_data()
