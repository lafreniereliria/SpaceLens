# Changelog

本项目变更日志，遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

每个 PR 在 `[Unreleased]` 段落下追加一行，发布时再归档到对应版本号。

---

## [Unreleased]

### Added
- `CONTRIBUTING.md`：AI Agent 协作工作流（任务卡格式、Reviewer Agent prompt、Release checklist）
- `AGENTS.md`：给 AI Agent 看的项目说明书，包含必读历史坑
- `.github/workflows/ci.yml`：CI（compile + ruff + pytest）
- **评分页面体验全面提升**：
  - 顶部导航栏改为与 23 指标页一致的按钮样式（`topnav-mgr-btn`）
  - 左侧边栏加入页面内 TOC 目录（AHP 权重 / 综合得分 / 维度概览 / 维度柱状图 / 指标得分 / 指标贡献明细 / 空间区域评分 / 算法说明），支持点击平滑滚动 + 滚动 spy 高亮
  - 右上角加入「保存项目」按钮，弹出模态可选择导出"23 指标 + 评分"/"仅 23 指标"/"仅评分"三种组合
  - 所有柱状图（维度柱状图、指标得分图、区域评分图、热力图）改为单列全宽显示
- `_build_project_zip` 新增 `include_score`/`score_only`/`ahp_weights` 参数：可在 ZIP 中追加 `score/` 目录（6 张评分图 + score_summary.json）
- `/api/save_project/<sid>`、`/api/export_project/<sid>` 同步支持评分导出参数
- `.github/pull_request_template.md`：PR 自检模板
- `.github/ISSUE_TEMPLATE/`：AI 任务卡 / Bug 报告模板
- `requirements-dev.txt`：开发期依赖（pytest / ruff）
- `tests/` 测试骨架 + `conftest.py` + 关键回归用例（`/` 占位符、`_clean_behavior_df`）
- **评分模块**：新增 `/score` 页面与 `/api/score/<sid>` 后端接口，实现《第五章
  评分算法》全套公式：单一指标标准化（正向 / 逆向 / 目标区间型 / Likert）、
  维度层得分（CV 权重 + 短板惩罚）、主观心理感知得分（回归 + 修正融合）、
  综合绩效得分（AHP 维度权重）。前端展示综合得分卡、雷达图、维度柱状图、
  指标得分图、空间区域排行 + 热力图，并支持调整 AHP 权重实时重算。
  23 指标结果页右上角新增「开始评分」按钮入口（`templates/index.html`）。
- `tests/unit/test_scoring.py`：29 条覆盖标准化 / 惩罚 / 权重 / 维度 / 主观 /
  综合的回归用例。
- `docs/scoring_design.md`：评分算法设计文档，记录公式、指标映射、σ 参数表、
  扩展指南，避免后续 Agent 重复解析 docx 源文档。

### Fixed
- 低分屏（1366×768 等）桌面端窗口溢出：按 `availableGeometry()` 动态调整窗口尺寸，
  并对 WebView 设置 `zoomFactor` 自动缩放内容（`desktop_app.py`）
- 多个图表 X 轴空间单元序号显示：移除 "区域 " 前缀；若有 `region_name_map`
  则用备注名替代序号（`api/analysis.py`）
- **桌面端 `/score` 路由 404**：`desktop_app.py` 自带独立 Flask 实例，加新
  页面路由必须同时改 `app.py` 和 `desktop_app.py::_setup_flask_routes`。已
  在 `AGENTS.md §4.6` 立坑记录。

### Changed
- `.gitignore`：追加大文件 / 临时产物 / Agent 沙箱目录过滤规则
- 环境参数指标移除"各测点 XX 值"散点图，仅保留空间分布热力图
  （`api/analysis.py` `_env_fn` / `/api/environment` / `_METRIC_CHART_TITLES`）

---

## [2.0.0] - 2026-05

### Added
- 桌面端完整工作流：封面、一键分析、历史项目恢复、项目对比
- 环境参数拆分为温度/湿度/光照/风速/噪声独立对比
- 导出 ZIP 包含 `images/`、`data/`、`summary.json`、`README.txt`

### Fixed
- 行为数据 `/` 占位符过滤（`load_df` / `_clean_behavior_df`）
- 热力图黑色区域被错误上色（`_make_heatmap_overlay` coverage_mask 分支）
- 热力图叠加时非背景区域被白色覆盖（混合起点改为 `overlay`）
- session 轮询瘦身，避免大矩阵和重复图片导致前端卡住
