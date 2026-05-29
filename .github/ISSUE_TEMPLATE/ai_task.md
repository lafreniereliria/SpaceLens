---
name: AI 任务卡
about: 给 AI Agent 的开发任务（新指标 / 新模块 / 重构）
title: "[TASK] "
labels: ["type:feat"]
---

## 目标（一句话）
<!-- 例：为 SpaceLens 添加「行为复合度」指标 -->

## 接口契约
- 路由：`POST /api/<name>`
- 输入：
  - layout_img: image/png|jpeg
  - <data_file>: CSV/Excel，必须列 …
  - 表单字段：…
- 输出：
  ```json
  {
    "image": "<base64 png>",
    "image2": "<base64 png>",
    "summary": { "...": "..." }
  }
  ```
- 在 `_bg_compute` 批量路径里**必须注册**

## 数据约定
- 必须列：
- 可选列：
- 占位符处理（`/`、NaN）：参考 `_clean_behavior_df` / `load_df`

## 验收条件（Agent 自检 + Reviewer 核对）
- [ ] `python -m py_compile api/analysis.py` 通过
- [ ] `pytest tests/unit/test_<name>.py` 通过
- [ ] 用 `GUI/` 示例数据跑 run_all，新指标不在 skipped 里
- [ ] 前端 `templates/index.html` + `static/js/app.js` 能显示
- [ ] 导出 ZIP 里能找到这张图
- [ ] `README.md` 数据列说明已更新
- [ ] `AGENTS.md` 如有新坑则记录

## 参考
- 类似实现：`_<existing_metric>_fn`
- 历史坑：

## Owner / Reviewer
- Owner: @
- Reviewer: @
