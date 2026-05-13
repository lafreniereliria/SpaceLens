"""
生成示例测试数据
运行: python gen_demo_data.py
"""

import numpy as np
import pandas as pd
import os

np.random.seed(42)

# 模拟 10 个用户的定位数据
records = []
for uid in range(1, 11):
    # 每人 50-120 条定位记录
    n = np.random.randint(50, 121)
    # 生成随机游走轨迹（限制在 0-800 x 0-600 范围内）
    x_start = np.random.uniform(50, 750)
    y_start = np.random.uniform(50, 550)
    x = np.cumsum(np.random.randn(n) * 15) + x_start
    y = np.cumsum(np.random.randn(n) * 12) + y_start
    x = np.clip(x, 10, 790)
    y = np.clip(y, 10, 590)
    region = np.random.randint(1, 9, size=n)
    for i in range(n):
        records.append({
            'UserID': uid,
            'X': round(x[i], 2),
            'Y': round(y[i], 2),
            'Region': int(region[i]),
        })

df = pd.DataFrame(records)
out_path = os.path.join(os.path.dirname(__file__), 'demo_loc_data.csv')
df.to_csv(out_path, index=False)
print(f"✅ 已生成示例定位数据: {out_path}")
print(f"   共 {len(df)} 条记录，{df['UserID'].nunique()} 名用户")
