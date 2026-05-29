# SpaceLens 协同开发指南（AI Agent 版）

适用：两个人都用 AI Agent 写代码，人工只在「立目标、批方向、点合并」这三类
关键节点介入。其它环节交给 Agent。

> 目标：让两个 Agent 在同一仓库并行干活，**不撞车、不回退、不需要人逐行 review**。

---

## 1. 核心理念

**人 = 产品经理 + 架构师 + 质检员**
**Agent = 工程师**

人只做三件事：

1. **写清楚一句话需求**（喂给 Agent 的 prompt）
2. **拍板接口契约和验收条件**（给 Agent 划红线）
3. **看绿灯合并 PR**（CI 通过 + 关键截图过目）

其它（写代码、写测试、写文档、debug）全部 Agent 做。

---

## 2. 任务分配（按"文件领地"切，避免两个 Agent 抢同一行）

| 领地 | 负责人 | 主要文件 |
|---|---|---|
| **后端 / 指标** | A | `api/analysis.py`、`api/db.py`、`tests/` |
| **前端 / 桌面** | B | `templates/*`、`static/*`、`desktop_app.py` |
| **共享区**（README/ROADMAP/CHANGELOG/requirements） | 谁动谁负责，PR 里 ping 对方 |

**铁律**：两人的 Agent 不要同时改同一个文件。要改对方领地的文件，先在群里说一声、或开 issue。

### 当前工作映射

- **2 个新指标**：A 主导（后端 + 测试），B 收尾（前端渲染 + 导出）
- **2 个大模块**：各拿 1 个当 Owner，对方 review
- **Debug**：谁先看到、能复现，谁就开 fix 分支

---

## 3. 简化版 Git 流程（一图流）

```
main  ────────────────●──────────●──────────●────►
                       ▲          ▲          ▲
                       │ merge    │ merge    │ merge
                  feat/metric-x  feat/module-y  fix/zip-bug
                  (A 的 agent)   (B 的 agent)   (任意 agent)
```

- 只有 `main` + 短分支两种。
- 分支名：`feat/xxx`、`fix/xxx`、`chore/xxx`。
- **不要长期分支**，一个 PR ≤ 2 天合入。
- 直接 push main 只允许：纯文档 typo、CHANGELOG 更新。

---

## 4. AI 友好的任务卡格式

每个 Issue 直接当成"给 Agent 的 prompt"来写。模板：

```markdown
## 目标（一句话）
为 SpaceLens 添加「行为复合度」指标。

## 接口契约
- 路由：POST /api/behavior_compose
- 输入：layout_img + behavior data (CSV/Excel，必须列 X/Y/Region/BehaviorNum)
- 输出：{ image: base64, image2?: base64, summary: { region_compose: [...] } }
- 在 _bg_compute 批量路径里也要注册

## 数据约定
- BehaviorNum 含 '/' 占位符要先过滤（参考 _clean_behavior_df）
- Region 缺失则返回 400

## 验收条件（Agent 自检 / CI 检查）
- [ ] python -m py_compile api/analysis.py 通过
- [ ] pytest tests/unit/test_behavior_compose.py 通过
- [ ] 用 GUI/ 示例数据跑 run_all，新指标不在 skipped 里
- [ ] 前端 templates/index.html + static/js/app.js 能显示
- [ ] 导出 ZIP 里能找到这张图
- [ ] README 数据列说明已更新

## 参考
- 类似指标：_beh_entropy_fn（thread ca5crs7lz4arwo73ljac）
- 历史坑：'/' 占位符（thread viihn96cq0fkzl786zpc）
```

**核心**：验收条件写成 checklist，Agent 自己能逐条核对。**这一条做好，人工 review 工作量 → 0。**

---

## 5. 简化版工作流（5 步）

```
①  人：开 Issue（按 §4 模板写）
②  Agent A 在分支上开发 + 自测 + push
③  CI 自动跑（compile + ruff + pytest）
④  Agent B 用 AI review（给它 PR diff，让它对照验收条件逐条勾）
⑤  人：看 CI 绿 + Reviewer Agent 出的 review 报告，点 Merge
```

人在第 ① 步和第 ⑤ 步介入，单次大约 1–3 分钟。

### Agent Review 的标准 prompt

把 PR diff 喂给对方的 Agent，prompt 模板：

```
你是 Code Reviewer。请对照下面的「验收条件」逐条核对这份 PR diff：
1. 列出每条 checklist 的 PASS/FAIL/UNCERTAIN
2. FAIL 的要给出具体行号和修复建议
3. 检查是否引入了历史坑（'/' 占位符、numpy or 运算、热力图黑色上色）
4. 检查是否破坏了现有 endpoint 的响应结构
最后输出一个 ✅/⚠️/❌ 总评。
```

---

## 6. 仓库一次性配置（10 分钟搞定）

人工干一次，以后躺平。

### 6.1 GitHub 设置

进入仓库 Settings：

1. **Branches → Add rule for `main`**
   - ☑ Require a pull request before merging
   - ☑ Require status checks to pass before merging（勾选 CI 任务）
   - ☑ Require linear history
   - ❌ 不要勾"Require approvals"（两人 + Agent 模式下太重，靠 CI 把关）
2. **Collaborators → Add `<同伴 GitHub>` 为 Write**
3. **Actions → Enable**

### 6.2 仓库内必备文件

```
.github/
├── workflows/ci.yml          # 见 §7
├── pull_request_template.md  # 见 §5
└── ISSUE_TEMPLATE/
    └── ai_task.md            # 见 §4 模板
.gitignore                    # 追加 §6.3 规则
CONTRIBUTING.md               # 本文件
CHANGELOG.md                  # Keep a Changelog 格式
requirements-dev.txt          # pytest + ruff
AGENTS.md                     # 给 Agent 看的项目上下文（见 §8）
```

### 6.3 .gitignore 追加

当前仓库混入了 zip / docx / 大 PNG，建议追加：

```gitignore
~/.spacelens/
.spacelens/
*.zip
*.docx
*.xlsx
test_*_output.png
*_REPORT.md
.coverage
.pytest_cache/
```

然后一次性清理引用（不动 history）：

```bash
git rm --cached GUI_评价结果.zip GUI_评价结果1.zip "博物馆数据0521(1).zip" \
                "建筑空间绩效评价平台软件说明0507.docx" "软件名称修改0527.xlsx"
git commit -m "chore: stop tracking large binary artifacts"
```

---

## 7. CI（唯一的人工质检替身）

`.github/workflows/ci.yml`：

```yaml
name: CI
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: pip
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Compile
        run: python -m py_compile app.py desktop_app.py api/analysis.py api/db.py
      - name: Lint
        run: ruff check .
      - name: Test
        run: pytest -q
```

**CI 红 = 不准合**。这是两个 Agent 互相把关的唯一硬门槛。

### 必备测试集（一次性建立，以后 Agent 自己往里加）

```
tests/
├── conftest.py
├── fixtures/
│   ├── tiny_location.csv
│   ├── tiny_behavior.xlsx
│   └── tiny_layout.png
├── unit/
│   ├── test_load_df.py           # '/' 占位符回归
│   ├── test_clean_behavior.py    # BehaviorNum 字符串回归
│   └── test_metric_<name>.py     # 新指标必备
└── integration/
    ├── test_api_run_all.py       # 一键分析回归
    └── test_export_zip.py        # 导出回归
```

**每个 fix PR 必须带一个新的回归用例**——这是治"bug 反复出现"的唯一办法（历史上 `/` 占位符、numpy or、热力图黑色都修过又复发）。

---

## 8. AGENTS.md（给 Agent 看的"项目说明书"）

在仓库根建一个 `AGENTS.md`（Cursor / Claude Code / Codeflicker 都会优先读取），让任何新 Agent 接手都能 5 分钟上手：

```markdown
# SpaceLens — AI Agent 接入说明

## 启动
- 桌面端：python desktop_app.py
- Web：python app.py
- 测试：pytest -q

## 改代码前必读
- api/analysis.py 是核心，包含所有 endpoint + 算法 + _bg_compute 批量路径
- 加新指标必须同时改：endpoint + _bg_compute 注册 + 导出 + 前端 + 测试
- 数据列约定见 README.md

## 已知坑（必须规避）
1. '/' 占位符：load_df / _clean_behavior_df 已用 pd.to_numeric(errors='coerce') 处理，新代码要复用
2. numpy array 不能用 `or`：用 `x if x is not None else y` 替代
3. 热力图叠加：用 density_norm > 0.01 阈值，混合起点用 overlay（见 _make_heatmap_overlay）
4. 桌面端低分屏：window 尺寸已按 availableGeometry 动态算 + webview.setZoomFactor

## PR 必做
- 跑 pytest -q
- 用 GUI/ 示例数据手动验一次
- 更新 CHANGELOG.md 的 [Unreleased]
- UI 改动附截图
```

---

## 9. 沟通节奏（极简版）

- **IM 群**：开 PR 时丢个链接 + 一句话说明；CI 红了 @对方
- **不开会**，靠 Issue / PR 留痕
- **设计大模块**：先让 Agent 出一份 1 页 design doc 放 `docs/design/<name>.md`，两人各让 Agent 看一遍 → 在 PR 里互评 → 人拍板 → 进入开发
- **复盘**：每周五让 Agent 跑一遍 `git log --since="1 week ago" --oneline` + CHANGELOG diff，自动生成周报

---

## 10. Commit / PR 格式（Agent 自带的能力即可）

- Commit：`feat(metrics): xxx` / `fix(export): xxx` / `chore: xxx`
- PR 标题 = 主 commit 标题
- PR 描述模板（写到 `.github/pull_request_template.md`）：

```markdown
## 关联 Issue
Closes #

## 验收 checklist（从 Issue 复制）
- [ ] ...

## Agent Review 结果
<!-- 把对方 Agent 的 review 总结贴这里 -->

## 截图（UI 改动必填）
```

---

## 11. 人工兜底（必须，但少）

只有这些时刻人必须出手：

| 场景 | 谁 | 做什么 |
|---|---|---|
| 立新需求 | 提出方 | 按 §4 写 Issue |
| Agent 卡死 / 反复修不对 | 任意一人 | 接管该分支，手动调试或换思路 |
| Merge PR | PR 提交者 | 看 CI 绿 + Reviewer Agent 报告 ✅，点 Squash Merge |
| 发布 release | 共同 | 走 §12 release checklist，打 tag |
| 架构级分歧 | 共同 | 30 分钟 IM 讨论 / 视频，写进 design doc |

---

## 12. Release Checklist（每次打 tag 前 5 分钟）

直接复制到 release PR 描述：

- [ ] CHANGELOG.md `[Unreleased]` 已转为版本号
- [ ] CI 全绿
- [ ] 桌面端在 1366×768 屏正常启动（截图）
- [ ] GUI/ 示例数据一键分析全部完成（截图）
- [ ] 历史项目恢复 + 项目对比能用
- [ ] git tag vX.Y.Z && git push --tags

---

## 13. 一句话总结

> **人写 Issue + 点 Merge，Agent 写代码 + 写测试 + 互相 review，CI 是唯一硬门槛。**
>
> 这套流程下，两个人 + 两个 Agent ≈ 4 人份产出，每天人工时间 < 30 分钟。
