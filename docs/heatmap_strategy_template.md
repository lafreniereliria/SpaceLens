# Heatmap Strategy Template / 热力图实现参考策略

本文档记录当前版本热力图相关实现逻辑，作为后续功能开发和问题修复的参考模板。

稳定参考点：

- Git tag：`v1.0.0`
- 主要实现文件：`api/analysis.py`
- 核心函数：
  - `extract_walkable_mask()`
  - `extract_measurement_mask()`
  - `merge_masks()`
  - `filter_points_in_mask()`
  - `_make_heatmap_overlay()`
  - `_make_rbf_overlay()`

## 一句话原则

事件密度、停留时长、移动速率、行为时长等“点位 + 可选权重”的图，用 `_make_heatmap_overlay()`。

温度、湿度、光照、风速、噪声等“稀疏测点 + 连续数值场”的图，用 `_make_rbf_overlay()`。

不要把 RBF 当成人流密度图，也不要用 KDE 密度图表达连续传感器读数。

## 当前热力图类型

| 类型 | 典型指标 | 数据形态 | 生成函数 | 颜色建议 |
| --- | --- | --- | --- | --- |
| 到访频次 | `heatmap` | `X`, `Y` 事件点 | `_make_heatmap_overlay()` | `plasma` |
| 使用/停留/行为时长 | `usetime`, `duration`, `behavior_duration` | `X`, `Y` + `t` 权重 | `_make_heatmap_overlay(weights=t)` | `jet` |
| 移动速率 | `speed` | `X`, `Y` + 区域均速权重 | `_make_heatmap_overlay(weights=weights)` | `jet` |
| 人员密度/开放程度 | `density`, `openness` | `X`, `Y` 事件点，区域统计另算 | `_make_heatmap_overlay()` | `jet` |
| 环境参数 | `environment_p1` - `environment_p5` | `X`, `Y`, `Value` 测点 | `_make_rbf_overlay()` | `RdYlBu_r` |

## 通用数据预处理

### 1. 加载数据

使用 `load_df(file_storage)`：

- CSV 走 `pd.read_csv()`。
- 其他文件走 `pd.read_excel()`。
- 已知数值列会做 `pd.to_numeric(errors='coerce')`。

常见数值列：

```python
{'X', 'Y', 't', 'BehaviorNum', 'Satisfaction', 'UserNum', 'ParameterNum', 'Value', 'Region'}
```

### 2. 加载平面图

使用 `load_img(file_storage)`：

- 输出 RGB `numpy.ndarray`。
- PNG 透明通道会合成到白底，避免透明图导致灰度/mask 判断异常。

### 3. 坐标归一化

一键分析 `run_all` 内部有 `_normalize_xy(df)`：

- 只有当 `X/Y` 超出图像边界时才触发。
- 将原始坐标线性映射到 `[0, image_width] x [0, image_height]`。
- 坐标已在图像范围内时不改变。

单指标 API 不一定都有同样的归一化逻辑。若出现一键分析正常、单指标异常，优先检查这一点。

## Mask 策略

### walkable mask：墙体/障碍过滤

函数：`extract_walkable_mask(img_arr)`

语义：

- `True`：可走/可上色区域。
- `False`：墙体或障碍。

默认逻辑：

1. RGB 转灰度。
2. 灰度 `< 60` 视为黑色墙体。
3. 墙体向外膨胀 `2px`，给墙边留缓冲。
4. 若可走区域少于全图 5%，降级为全 `True`，避免特殊底图把整张图屏蔽。

使用原则：

- 对 KDE 热力图：在高斯平滑之后乘 `walkable_mask`，抑制热力渗进墙体。
- 对 RBF 环境图：与 `coverage_mask` 合并成 `effective_mask`，把不可用区域置为 `NaN`。
- 对轨迹/聚类散点：可用 `filter_points_in_mask()` 过滤落在墙体上的点。

### coverage mask：测量覆盖范围

函数：`extract_measurement_mask(img_arr)`

语义：

- `True`：允许上色。
- `False`：无测量数据，不应上色。

默认逻辑：

1. RGB 转灰度。
2. 灰度 `> 20` 视为允许上色。
3. 若允许区域少于全图 5%，降级为全 `True`。

来源：

- 前端可选上传 `background_img`。
- `background_img` 黑色区域表示无数据区域。

使用原则：

- 有 `background_img` 时，用它控制正式上色范围。
- 没有 `background_img` 时，一键分析通常传 `None`；部分单指标旧实现会退回 `extract_measurement_mask(img)`。
- 如果发现热力图外围被错误上色或整图被盖色，优先检查 `coverage_mask` 来源。

### mask 合并

函数：`merge_masks(*masks)`

规则：

- 忽略 `None`。
- shape 一致时按逻辑与合并。
- 用于 RBF 的有效区域约束。

## `_make_heatmap_overlay()` 策略

适用：

- 点位密度图。
- 点位加权密度图。
- 权重可为停留时长、使用时长、区域均速、行为时长等。

输入核心参数：

```python
overlay, density = _make_heatmap_overlay(
    img,
    x,
    y,
    weights=None,          # 可选；None 表示每个点权重为 1
    alpha=0.65,
    cmap='jet',
    bandwidth=None,        # None 时自动取 max(min(h, w) * 0.025, 8)
    walkable_mask=walkable,
    coverage_mask=coverage,
)
```

处理流程：

1. 将 `X/Y` 四舍五入并裁剪到图像范围内。
2. 如果有 `coverage_mask`：
   - 在允许上色区域均匀采样一批 0 值点。
   - 原始点和 0 值点一起进入密度栅格。
   - 这样可以形成完整热力场，减少边界断裂。
3. 构建像素级 `density[h, w]`。
4. 对 `density` 做 `gaussian_filter()`。
5. 如果有 `walkable_mask`，平滑后乘 mask，压掉墙体区域。
6. 用 99 分位数归一化，减少极端峰值压缩整体颜色。
7. 输出 RGB overlay 和平滑后的 density。

有 `coverage_mask` 时的叠加策略：

- 只在 `coverage_mask=True` 区域做 alpha 叠加。
- `coverage_mask=False` 区域保留原平面图。

无 `coverage_mask` 时的叠加策略：

- 当前实现是全图固定 alpha 叠加。
- 即使 0 密度区也会显示 colormap 最低颜色，平面图结构线通过半透明保留。

常见调用模板：

```python
img = load_img(img_file)
walkable = extract_walkable_mask(img)
coverage = None
bg_file = request.files.get('background_img')
if bg_file is not None:
    coverage = extract_measurement_mask(load_img(bg_file))

overlay, density = _make_heatmap_overlay(
    img,
    x,
    y,
    weights=weights,       # 到访频次/人员密度可传 None
    alpha=0.65,
    cmap='jet',
    walkable_mask=walkable,
    coverage_mask=coverage,
)
```

## `_make_rbf_overlay()` 策略

适用：

- 稀疏环境测点生成连续标量场。
- 当前用于温度、湿度、光照、风速、噪声。

输入核心参数：

```python
overlay, field, vmin, vmax = _make_rbf_overlay(
    img,
    x,
    y,
    values,
    alpha=0.65,
    cmap='RdYlBu_r',
    walkable_mask=walkable,
    coverage_mask=coverage,
    kernel='linear',
    smoothing=max(np.nanstd(values) * 0.03, 1e-6),
    neighbors=min(max(len(values), 8), 24),
    epsilon=None,
)
```

处理流程：

1. 过滤 `X/Y/values` 中的非有限值。
2. 有效测点少于 3 个时返回 `interp=None`。
3. 用 `RBFInterpolator` 在整张图像网格上插值。
4. RBF 失败时降级为 `griddata(linear)`，再用 `nearest` 填洞。
5. 如果有 `coverage_mask`，在允许区域内对 `NaN` 用 nearest 补值。
6. 合并 `walkable_mask` 和 `coverage_mask`，无效区域置为 `NaN`。
7. 用有效值的 2/98 分位数作为 `vmin/vmax`。
8. 输出 RGB overlay、插值场和色标范围。

当前环境参数配置：

```python
kernel_map = {
    1: 'linear',    # 温度
    2: 'linear',    # 湿度
    3: 'gaussian',  # 光照
    4: 'linear',    # 风速
    5: 'linear',    # 噪声
}

epsilon_map = {
    3: max(min(image_width, image_height) * 0.015, 4.0)
}
```

选择原因：

- 多数环境参数用 `linear` 保持稳定、不过度振荡。
- 光照空间变化可能更局部，当前用 `gaussian` 并指定 `epsilon`。
- `neighbors` 限制在 8 到 24 之间，避免测点多时插值过慢，也避免测点少时局部性过强。

## 色标与数值摘要

### KDE 型热力图

色标常见写法：

```python
sm = plt.cm.ScalarMappable(
    cmap='jet',
    norm=mcolors.Normalize(0, float(density.max()) if float(density.max()) > 0 else 1.0)
)
```

注意：

- overlay 内部使用 99 分位归一化。
- colorbar 用 `density.max()` 或业务权重最大值，二者并不总是严格一致。
- 若需要精确图例，应统一 overlay 归一化和 colorbar norm。

### RBF 型环境图

色标使用 `_make_rbf_overlay()` 返回的 `vmin/vmax`：

```python
sm = plt.cm.ScalarMappable(
    cmap='RdYlBu_r',
    norm=mcolors.Normalize(vmin, vmax)
)
```

这样可以和插值场裁剪范围保持一致。

## 指标接入模板

### 新增事件密度类热力图

```python
df = load_df(data_file)
required = {'X', 'Y'}
if not required.issubset(df.columns):
    return None

df = df.dropna(subset=['X', 'Y'])
df = normalize_xy(df)  # run_all 内部使用；单指标需自行处理

x = df['X'].astype(float).values
y = df['Y'].astype(float).values
weights = None

img = load_img(img_file)
walkable = extract_walkable_mask(img)
coverage = extract_measurement_mask(load_img(bg_file)) if bg_file else None

overlay, density = _make_heatmap_overlay(
    img,
    x,
    y,
    weights=weights,
    alpha=0.65,
    cmap='jet',
    walkable_mask=walkable,
    coverage_mask=coverage,
)
```

### 新增权重密度类热力图

```python
required = {'X', 'Y', 't'}
df = df.dropna(subset=list(required))

x = df['X'].astype(float).values
y = df['Y'].astype(float).values
weights = df['t'].astype(float).values

overlay, density = _make_heatmap_overlay(
    img,
    x,
    y,
    weights=weights,
    alpha=0.65,
    cmap='jet',
    walkable_mask=walkable,
    coverage_mask=coverage,
)
```

### 新增连续测点类热力图

```python
required = {'X', 'Y', 'Value'}
df = df.dropna(subset=list(required))

x = df['X'].astype(float).values
y = df['Y'].astype(float).values
values = df['Value'].astype(float).values

overlay, field, vmin, vmax = _make_rbf_overlay(
    img,
    x,
    y,
    values,
    alpha=0.65,
    cmap='RdYlBu_r',
    walkable_mask=walkable,
    coverage_mask=coverage,
    kernel='linear',
    smoothing=max(float(np.nanstd(values)) * 0.03, 1e-6),
    neighbors=min(max(len(values), 8), 24),
)

if field is None:
    return None
```

## 排错清单

### 热力图完全空白

- 检查 `X/Y` 是否存在且能转成数值。
- 检查 `X/Y` 是否全部为 `NaN`。
- 检查坐标是否远超图像范围，单指标 API 可能没有自动归一化。
- 检查 `coverage_mask` 是否几乎全 False。
- 检查 `walkable_mask` 是否误把底图识别成墙体。

### 热力图覆盖到不该上色的黑区

- 确认是否上传了正确的 `background_img`。
- 确认 `coverage_mask=False` 区域是否真的是黑色，阈值当前为 `20`。
- 检查调用时是否把 `coverage_mask` 传进 `_make_heatmap_overlay()` 或 `_make_rbf_overlay()`。

### 热力图渗入墙体

- 检查平面图墙体是否足够黑，`extract_walkable_mask()` 阈值当前为 `60`。
- 可增大 `dilate_wall_iters`，给墙体更宽缓冲。
- 可适当降低 KDE `bandwidth`，减少跨墙扩散。

### 热力图边界断裂或只在点附近有颜色

- KDE 型：确认有传 `coverage_mask` 时，0 值填充点是否覆盖允许区域。
- RBF 型：确认测点数是否至少 3 个。
- RBF 型：检查是否因为 mask 合并后有效区域太小，导致大面积 `NaN`。

### 颜色对比过强或过弱

- KDE 型：调整 `bandwidth`、`alpha` 或归一化分位数。
- RBF 型：检查 `vmin/vmax` 的 2/98 分位是否受异常值影响。
- 光照等局部变化强的参数，可调整 `epsilon`、`kernel`、`neighbors`。

### 一键分析与单指标结果不一致

优先比较：

- 是否都做了坐标归一化。
- 是否都传入同样的 `coverage_mask`。
- 是否都使用同样的 `walkable_mask`。
- 权重字段是否一致。
- colorbar 的 norm 是否一致。

## 修改热力图代码时的最小验证

1. 用同一组示例数据分别跑一键分析和单指标 API。
2. 至少检查这些指标：
   - `heatmap`
   - `usetime`
   - `speed`
   - `duration`
   - `density`
   - `environment`
   - `behavior_duration`
3. 比较有无 `background_img` 两种情况。
4. 检查墙体边缘、黑色无数据区、测点附近、稀疏区域。
5. 若改动涉及归一化或 mask，打开：

```text
GET /api/session/<sid>/debug
```

确认指标没有隐藏 traceback。

## 建议后续重构方向

- 将 mask 相关函数移到 `api/heatmap_masks.py`。
- 将 `_make_heatmap_overlay()` 和 `_make_rbf_overlay()` 移到 `api/heatmap_rendering.py`。
- 为每类热力图增加小型 fixture，固定输入输出摘要。
- 统一一键分析和单指标 API 的坐标归一化、coverage 默认策略和 colorbar norm。
- 为 `background_img` 增加显式预检，返回允许上色区域占比，方便用户判断遮罩是否正确。
