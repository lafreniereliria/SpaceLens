# Test fixtures

放置小型示例数据，专供 pytest 使用。**保持轻量（每个 ≤ 100 KB）**，
不要把 `GUI/` 下的真实数据集复制进来。

建议的命名：
- `tiny_location.csv` — 几十行定位数据
- `tiny_behavior.csv` — 几十行行为数据（含 `/` 占位符以验证回归）
- `tiny_environment.csv` — 几十行环境数据
- `tiny_layout.png` — 200×200 的简单平面图
