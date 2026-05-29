# 评分模块设计文档（第五章 评分算法）

> 实现位置：`api/analysis.py` 末尾 "评分算法模块" 区段
> 接口：`POST /api/score/<sid>` → 前端页面 `/score?sid=<sid>`
> 单元测试：`tests/unit/test_scoring.py`（29 条用例）

本文档作为算法权威来源，避免后续 Agent 重复去解析 docx 源文档。

---

## 1. 流水线总览

```
[session.results]
   ↓ (每指标 1 个主数值，来自 summary)
[_score_extract_value]
   ↓
[_score_standardize_*]       ← 4 种标准化公式
   ↓ (per_metric_score, 0-100)
[_score_dimension]            ← CV 权重 + 短板惩罚
[_score_subjective]           ← 回归融合（主观维度专用）
   ↓ (dimension scores)
[ahp_weights × dim_score]    ← AHP 综合
   ↓
[total_score, grade]
```

并行计算：`_compute_region_scores` 对每个空间单元跑同样流程，输出区域排行。

---

## 2. 单一指标标准化（→ 0~100）

| 类型 | 公式 | 适用 |
|---|---|---|
| `positive` 正向 | `S = 100 × (x − x_min) / (x_max − x_min)` | 行为人次、行为时长、利用率等"越大越好" |
| `negative` 逆向 | `S = 100 × (x_max − x) / (x_max − x_min)` | 噪声、差异系数、密度上限等"越小越好" |
| `target` 区间型 | `S = 100 × exp(−(x − x_opt)² / (2σ²))` | 温度、湿度、光照、速度、停留时长等"最优值" |
| `likert` 7 级 | `S = (x − 1) / 6 × 100` | 满意度问卷（1=非常不满意；7=非常满意） |

### σ 参数表（目标区间型）

| 指标 | x_opt | σ |
|---|---|---|
| 温度 (℃) | 24 | 2 |
| 相对湿度 (%) | 50 | 10 |
| 照度 (lx) | 300 | 100 |
| 噪声 (dB) | 45 | 10 |
| CO₂ (ppm) | 800 | 200 |
| 移动速率 (m/s) | 0.8 | 0.3 |
| 停留时长 (min) | 3 | 2 |
| 人员密度 (人/㎡) | 0.5 | 0.3 |
| 空间开放程度 | 0.7 | 0.2 |

---

## 3. 维度得分（非主观维度）

```
ω_i  = CV_i / Σ CV_i           # 变异系数权重
P_i  = 1.0    if S_i ≥ 85
       0.9    if 70 ≤ S_i < 85
       0.7    if S_i < 70      # 短板惩罚
S_k  = Σ(ω_i × S_i × P_i)
```

实现：`_score_cv_weights` + `_score_short_board_penalty` + `_score_dimension`

**边界情况**：
- 维度仅 1 个指标：ω=1，直接 `S × P`
- 所有指标得分相同：CV→0，退化为等权

---

## 4. 主观心理感知（subjective 维度专用）

`_score_subjective` 实现：

```
S_overall  = Likert(整体满意度问卷)
S_zone     = Likert(空间单元满意度)
S_element  = Likert(设计要素满意度)

# 回归模型（缺训练数据时使用经验权重）
a = 5.0,  β₁ = 0.55,  β₂ = 0.40
S_predicted = a + β₁·S_zone + β₂·S_element

# 修正融合
α = 0.65
S_subjective = α·S_overall + (1−α)·S_predicted
```

后续如果有人工标注数据，可替换 `a/β1/β2` 为线性回归实际拟合值。

---

## 5. 综合得分

```
S_total = Σ(W_k × S_k)
W_k = AHP 维度权重（默认值，前端可改）
```

### 默认 AHP 权重

| 维度 | 默认权重 |
|---|---|
| `subjective` 主观心理感知 | **0.40** |
| `physical` 物理环境感知 | 0.20 |
| `circulation` 动线感知 | 0.20 |
| `behavior` 行为感知 | 0.20 |

### 分级

| 区间 | 等级 |
|---|---|
| `≥ 85` | 优秀 |
| `70 – 85` | 良好 |
| `60 – 70` | 一般 |
| `< 60` | 存在明显问题 |

---

## 6. 指标 → 维度 + 标准化类型映射

来源：`_SCORE_DIMENSION_MAP` + `_METRIC_SCORE_RULES`

### 物理环境（physical）

| metric_id | label | kind | 参数 / summary 字段 |
|---|---|---|---|
| `environment_p1` | 温度 | target | x_opt=24, σ=2, key=`mean` |
| `environment_p2` | 湿度 | target | x_opt=50, σ=10, key=`mean` |
| `environment_p3` | 光照 | target | x_opt=300, σ=100, key=`mean` |
| `environment_p4` | 风速 | target | x_opt=0.8, σ=0.3, key=`mean` |
| `environment_p5` | 噪声 | negative | key=`mean` |

### 动线感知（circulation）

| metric_id | label | kind | summary 字段优先级 |
|---|---|---|---|
| `heatmap` | 到访频次 | positive | `avg_frequency` / `peak_frequency` |
| `usetime` | 使用时长 | positive | `avg_duration_s` / `total_duration_s` |
| `speed` | 移动速率 | target (0.8, 0.3) | `global_speed_ms` / `avg_speed_ms` |
| `duration` | 停留时长 | target (180s, 120s) | `avg_duration_s` |
| `topology` | 拓扑流量 | positive | `avg_flow` / `total_flow` |
| `difference` | 轨迹差异系数 | negative | `avg_diff_coeff` / `avg_diff` |
| `density` | 人员密度 | target (0.5, 0.3) | `avg_density` / `avg_density_per_sqm` |
| `openness` | 空间开放程度 | target (0.7, 0.2) | `avg_openness` / `global_openness` |
| `trajectory` | 轨迹长度 | positive | `avg_length_m` |

### 行为感知（behavior）

| metric_id | label | kind | summary 字段 |
|---|---|---|---|
| `behavior_count` | 行为人次 | positive | `total_records` |
| `behavior_duration` | 行为时长 | positive | `total_duration_s` |
| `behavior_rate` | 行为发生率 | positive | `region_count`（占位代理） |
| `behavior_entropy` | 行为复合程度 | positive | `avg_reg_entropy` |
| `utilization` | 空间利用率 | positive | `avg_util` / `global_util` |

### 主观心理感知（subjective）

| metric_id | label | kind | summary 字段 |
|---|---|---|---|
| `satisfaction` | 整体满意度 | likert | `avg_score` |
| `satisfaction_region` | 空间单元满意度 | likert | `avg_score` |
| `satisfaction_design` | 设计要素满意度 | likert | `avg_score` |

---

## 7. 空间区域级评分

`_compute_region_scores` 扫描 `results[metric_id]['export_data']` 里
任何包含 `'空间单元'` 或 `'Region'` 列的行，把每个区域当成一个"迷你 session"
再跑一遍 `compute_scores`，输出 `region_scores` 数组（按 total 倒序）。

依赖前提：相关指标的 `export_data` 必须遵循统一 schema：
```python
{
  '<sheet_name>': [
    {'空间单元': '<rid>', '<value_col>': <number>},
    ...
  ]
}
```

不满足 schema 的指标会自动跳过（不报错）。

---

## 8. 前端展示

| 图 / 组件 | 来源字段 |
|---|---|
| 综合得分环形卡片 | `images.image_total` + `score.total_score` |
| 雷达图 | `images.image_radar` |
| 维度柱状图 | `images.image_dim_bar` |
| 指标柱状图 | `images.image_metric_bar` |
| 区域评分柱状图 | `images.image_region_bar` |
| 区域 × 维度热力图 | `images.image_region_heatmap` |
| 维度块（4 个） | `score.dimensions[k].score/weight` |
| 指标贡献明细表 | `score.dimensions[k].breakdown.metrics` |
| 区域排行榜 | `score.region_scores` |

---

## 9. 扩展指南

### 加一个新指标到评分体系

1. 确认指标 id（如 `new_metric`）已在 `_METRIC_NAMES` 注册
2. 在 `_SCORE_DIMENSION_MAP` 对应维度的 `metrics` 列表里加 id
3. 在 `_METRIC_SCORE_RULES` 加规则：
   ```python
   'new_metric': {'kind': 'positive', 'value_keys': ['avg_xxx']},
   ```
4. 跑 `pytest tests/unit/test_scoring.py` + 在桌面端检查 `/score` 页是否出现该指标

### 调整 AHP 默认权重

修改 `_DEFAULT_AHP_WEIGHTS`，权重和不需要严格 = 1（接口会按比例归一化）。

### 改主观回归参数

替换 `_score_subjective` 内的 `a, beta1, beta2`，或将其改为读取拟合好的
sklearn 模型 pickle。

---

## 10. 历史和参考

- 算法源文档：`第五章 评分算法(1).docx`（在仓库根目录但已 gitignore）
- 实现 commit：`76fc1e2`（feat）、`c1f9445`（桌面端路由修复）
- 实现 thread：`vfdjm1oraxrtstbjq1gr`
