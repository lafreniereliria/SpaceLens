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
- `.github/pull_request_template.md`：PR 自检模板
- `.github/ISSUE_TEMPLATE/`：AI 任务卡 / Bug 报告模板
- `requirements-dev.txt`：开发期依赖（pytest / ruff）
- `tests/` 测试骨架 + `conftest.py` + 关键回归用例（`/` 占位符、`_clean_behavior_df`）

### Fixed
- 低分屏（1366×768 等）桌面端窗口溢出：按 `availableGeometry()` 动态调整窗口尺寸，
  并对 WebView 设置 `zoomFactor` 自动缩放内容（`desktop_app.py`）
- 多个图表 X 轴空间单元序号显示：移除 "区域 " 前缀；若有 `region_name_map`
  则用备注名替代序号（`api/analysis.py`）

### Changed
- `.gitignore`：追加大文件 / 临时产物 / Agent 沙箱目录过滤规则

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
