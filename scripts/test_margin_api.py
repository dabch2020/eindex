#!/usr/bin/env python3
"""测试 akshare 融资余额 API 数据可用性"""
import akshare as ak
import socket
from datetime import datetime

socket.setdefaulttimeout(15)

test_dates = ['20260318', '20260319', '20260320']

print('=' * 60)
print('测试融资余额数据可用性')
print(f'测试时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
print('=' * 60)

for date_str in test_dates:
    dt = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}'
    print(f'\n--- {dt} ---')

    # 沪市
    try:
        df_sh = ak.stock_margin_detail_sse(date=date_str)
        total_sh = df_sh['融资余额'].astype(float).sum()
        print(f'  沪市融资余额: {total_sh/1e8:.4f} 亿元  ({len(df_sh)} 条记录)')
    except Exception as e:
        print(f'  沪市融资余额: 获取失败 - {e}')

    # 深市
    try:
        df_sz = ak.stock_margin_szse(date=date_str)
        bal_sz = float(df_sz['融资余额'].iloc[0])
        print(f'  深市融资余额: {bal_sz:.4f} 亿元')
    except Exception as e:
        print(f'  深市融资余额: 获取失败 - {e}')

print('\n' + '=' * 60)
print('测试完成')
