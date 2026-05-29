# SpaceLens — AI Agent 接入说明

> 任何 AI Agent（Cursor / Claude Code / Codeflicker / Copilot 等）在本仓库
> 写代码前，**先读完本文档**。这里写清楚了项目结构、必踩坑、PR 要求。

---

## 1. 项目一句话定位

SpaceLens 是一款本地桌面/Web 双形态的**建筑空间绩效评价平台**：
读取平面图 + 定位/行为/环境/问卷数据，输出可视化图表、统计指标和可导出
的分析结果。技术栈 Flask + matplotlib + PyQt6 WebEngine。

---

## 2. 启动方式

```bash
# 桌面端（推荐，含原生文件对话框）
python desktop_app.py

# 纯 Web 模式
python app.py     # 默认 127.0.0.1:8080

# 测试
pytest -q
```

依赖安装：
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt    # 开发期：pytest / ruff
```

---

## 3. 仓库结构速览

```
app.py                 Flask Web 入口
desktop_app.py         PyQt6 桌面封装 + Flask 后台线程（生产入口）
api/
  ├── analysis.py      所有 /api/* endpoint + 算法 + _bg_compute 批量路径
  └── db.py            历史项目 SQLite（~/.spacelens/projects.db）
templates/             Jinja2 模板（cover/index/new_project/history/compare…）
static/                CSS + JS
tests/                 pytest 测试集（unit/ + integration/）
GUI/                   示例数据集（保持轻量，用于手动回归）
```

---

## 4. ⚠️ 必读：历史已知坑（违反等于引入回归 bug）

下面这些坑都**修过又复发**过，新代码必须规避：

### 4.1 `'/'` 占位符（数值列含字符串）

- `behavior.xlsx` 的 `t` / `BehaviorNum` 列、`environment.xlsx` 的
  `ParameterNum` / `Value` 列，会包含 `'/'`。
- 必须用 `pd.to_numeric(errors='coerce')` 转换 + `dropna()` 过滤。
- 已有 helper：`load_df()` / `_clean_behavior_df()`。**新代码复用，不要再写裸的 `astype(int)`。**

### 4.2 numpy array 不能用 `or` / `and`

```python
# ❌ 错：触发 ValueError: The truth value of an array is ambiguous
mask = _get_coverage_mask() or extract_measurement_mask(img)

# ✅ 对
_cov = _get_coverage_mask()
mask = _cov if _cov is not None else extract_measurement_mask(img)
```

### 4.3 热力图叠加不能用白色覆盖

- `_make_heatmap_overlay` 中：用 `density_norm > 0.01` 阈值判断有效密度，
  混合起点用 **`overlay`（Step1 底色）**，而不是 `img_f`（白底图）。
- `coverage_mask` 分支只在 `fill_mask=True` 区域叠加 alpha，避免黑色外围
  区域被涂色。

### 4.4 新指标必须三处都改

加一个新指标 `/api/<name>`：

1. `api/analysis.py` 加独立 endpoint
2. `_bg_compute` 批量计算路径里**注册一次**（否则一键分析不会算）
3. 返回结构遵守 `{ image, summary, image2?, extras? }`
4. 前端 `templates/index.html` + `static/js/app.js` 加渲染
5. 导出三件套（图片 / Excel / ZIP）都要能找到

### 4.5 桌面端低分屏适配

- `desktop_app.py::MainWindow.__init__` 已按 `availableGeometry()` 动态算
  窗口尺寸 + `webview.setZoomFactor()` 缩放。
- 新增 WebView 或重置 URL 后**必须重新应用 zoom factor**（已用
  `loadFinished.connect` 兜底，照搬即可）。

### 4.6 桌面端和 Web 端是两套 Flask 实例 ⚠️ 重要

- **新增页面路由（`@app.route('/xxx')`）必须改两个文件！**
  - `app.py`：纯 Web 模式 (`python app.py`) 的入口
  - `desktop_app.py::_setup_flask_routes`（约第 660 行）：桌面端的内联 Flask 实例
- API 路由不受影响：两边都执行 `register_blueprint(analysis_bp, url_prefix='/api')`，
  所以 `api/analysis.py` 里 `@analysis_bp.route('/xxx')` 只写一次即可。
- 症状：桌面端访问新页面时报 `The requested URL was not found on the server`，
  但 Web 模式（`python app.py`）能打开 → 大概率是漏了 `desktop_app.py` 那一份。
- 历史案例：thread `vfdjm1oraxrtstbjq1gr` 加 `/score` 时只改了 `app.py`，
  桌面端 404，commit `c1f9445` 补回。

### 4.7 评分模块依赖 summary 字段名约定

- `api/analysis.py` 里 `_METRIC_SCORE_RULES` 通过 `value_keys`（如 `['mean']`,
  `['avg_frequency']`, `['avg_score']`）从每个指标的 `summary` dict 中提取主数值。
- **改某个指标的 `summary` 字段名时**（比如 `avg_score` 改成 `mean_score`），
  必须同步更新 `_METRIC_SCORE_RULES[<metric_id>]['value_keys']`，否则该指标
  在评分页会被"静默跳过"——不报错但维度得分缺它，总分异常。
- 自检：改完后跑 `pytest tests/unit/test_scoring.py`，并访问
  `/score?sid=<sid>` 确认每个指标都出现在"各指标标准化得分"图。
- 指标 → 维度映射 + σ 参数详见 `docs/scoring_design.md`。

---

## 5. 数据列约定

详见 `README.md` "数据准备" 章节。简表：

| 文件 | 必备列 |
|---|---|
| location | `UserID, X, Y` （`Timestamp, t, Region` 可选） |
| behavior | `UserID, X, Y, Region, BehaviorNum, behaviortype, t` |
| environment | `X, Y, ParameterNum, Value` |
| questionnaire | 见 `_satisfaction_*` 实现 |

---

## 6. PR 提交清单（Agent 自检）

提 PR 前 Agent 必须本地跑：

```bash
python -m py_compile app.py desktop_app.py api/analysis.py api/db.py
ruff check .
pytest -q
```

PR 描述里必须有：

- [ ] 关联的 Issue 号（`Closes #N`）
- [ ] 从 Issue 复制的验收 checklist + 完成状态
- [ ] UI 改动附截图
- [ ] 如果是 fix：附**新增的回归测试用例**链接
- [ ] CHANGELOG.md `[Unreleased]` 段已追加一行

---

## 7. 分支命名

```
feat/<short>     新功能 / 新指标 / 新模块
fix/<issue-id>   bug 修复
chore/<short>    配置 / 依赖 / 文档
```

禁止直接 push 到 `main`（纯文档 typo 除外）。

---

## 8. 找上下文的快捷方式

| 想干什么 | 看哪 |
|---|---|
| 加新指标 | `api/analysis.py` 搜 `_beh_entropy_fn` 当模板 |
| 改前端面板 | `templates/index.html` + `static/js/app.js` |
| 改桌面端窗口/进度 | `desktop_app.py::MainWindow` |
| 改导出 | `api/analysis.py` 搜 `export_zip` / `export_excel` |
| 历史项目恢复 | `api/db.py` + `api/analysis.py` 搜 `restore` |
| 评分模块（综合 / 维度 / 主观） | `api/analysis.py` 搜 `compute_scores` + `docs/scoring_design.md` |
| 加新页面路由 | `app.py` **和** `desktop_app.py::_setup_flask_routes` 都要加（见 §4.6）|
| 协作流程 | `CONTRIBUTING.md` |
| 路线图 | `ROADMAP.md` |

---

## 9. 一句话总结给 Agent

> **先读 §4 必读坑，按 §6 自检 checklist 走完，不会出大问题。**
