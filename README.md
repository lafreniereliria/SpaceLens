# SpaceLens / 建筑空间绩效评价平台

SpaceLens 是一个面向建筑空间使用后评价的本地分析工具。当前项目以 Flask 提供分析 API 和页面路由，以 PyQt6 WebEngine 封装为桌面应用，主要处理平面图、定位、行为、环境、问卷、区域坐标等多源数据，并输出热力图、轨迹、聚类、行为、环境、满意度等指标结果。

本文档记录当前实现情况，方便后续继续开发、功能扩展和 debug。

## 当前实现概览

### 已实现能力

- 桌面端入口：`desktop_app.py`
  - 启动内嵌 Flask 服务。
  - 使用 PyQt6 WebEngine 渲染前端页面。
  - 支持桌面端原生文件选择、保存对话框和打开源文件位置。
  - 默认 Web 服务端口为 `127.0.0.1:18080`，端口占用时会自动寻找空闲端口。

- Web 服务入口：`app.py`
  - 注册页面路由和 `api.analysis` 蓝图。
  - 提供后台管理页 `/admin/db` 和简单密码验证。
  - 直接运行时监听 `127.0.0.1:8080`。

- 分析后端：`api/analysis.py`
  - 单指标 API：支持热力图、轨迹、聚类、使用时长、移动速率、停留时长、人员密度、空间开放程度、拓扑连接关系、轨迹差异、环境、行为、满意度等指标。
  - 一键分析 API：`POST /api/run_all` 立即返回 `session_id`，后台线程逐项计算。
  - 会话 API：`GET /api/session/<sid>` 供结果页轮询。
  - 调试 API：`GET /api/session/<sid>/debug` 返回各指标错误、traceback、文件接收情况。
  - 导出 API：支持项目 ZIP、单指标 ZIP/PNG/XLSX 导出。
  - 结果持久化：计算完成后写入 `~/.spacelens/results/<session_id>/`。

- 本地数据库：`api/db.py`
  - 使用 SQLite 保存项目记录。
  - 默认数据库路径：`~/.spacelens/projects.db`。
  - 可通过环境变量 `SPACELENS_DATA_DIR` 改变数据目录。
  - 支持项目去重、列表、查看、重命名、删除。

- 前端页面：
  - `templates/cover.html`：封面/启动页。
  - `templates/new_project.html`：新建项目和一键上传分析。
  - `templates/index.html`：结果展示、轮询、导出、聚类重算。
  - `templates/history.html`：历史项目查看和恢复。
  - `templates/projects.html`：项目管理。
  - `templates/compare.html`：项目对比。
  - `templates/admin_db.html`：数据库管理页。
  - `static/js/app.js`：旧版/单指标分析页面逻辑，仍保留。

## 快速启动

### 环境要求

- Python 3.9+
- macOS 或 Windows
- 建议使用虚拟环境

### 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 启动桌面端

```bash
python desktop_app.py
```

桌面端是当前推荐运行方式，因为部分功能依赖 PyQt6 注入的本地文件路径和原生保存对话框。

### 启动 Web 服务

```bash
python app.py
```

浏览器访问：

```text
http://127.0.0.1:8080
```

注意：纯 Web 模式下，部分桌面增强能力不可用，例如原生保存对话框、在 Finder/资源管理器中定位源文件等。

## 项目结构

```text
spatial-demo/
├── app.py                         # Flask Web 服务入口
├── desktop_app.py                 # PyQt6 桌面应用入口
├── api/
│   ├── analysis.py                # 分析算法、会话、导出和项目 API
│   └── db.py                      # SQLite 项目数据库
├── templates/                     # Jinja2 页面模板
├── static/
│   ├── css/app.css                # 全局样式
│   └── js/app.js                  # 单指标分析页前端逻辑
├── requirements.txt               # Python 依赖
├── build_windows.spec             # Windows PyInstaller 配置
├── build_macos.spec               # macOS PyInstaller 配置
├── installer.iss                  # Inno Setup 安装包配置
├── test_heatmap_colors.py         # 热力图颜色相关测试/验证脚本
├── gen_demo_data.py               # 示例数据生成脚本
├── generate_color_report.py       # 颜色报告生成脚本
├── GUI/                           # 示例输入数据
├── GUI_评价结果/                  # 示例导出结果
├── 博物馆数据0521/                # 示例数据集
└── 博物馆数据及软件使用问题/       # 历史问题数据与 MATLAB 原型
```

## 核心运行链路

### 桌面端启动链路

1. 运行 `desktop_app.py`。
2. PyQt6 创建主窗口并先显示内置封面 HTML。
3. 后台线程启动 Flask 应用。
4. 桌面端注册：
   - `/api/ready`
   - Qt 原生保存对话框 hook
   - 文件选择路径注入 hook
5. WebEngine 加载本地 Flask 页面。

### 一键分析链路

1. `templates/new_project.html` 收集项目名、建筑类型、文件夹/文件。
2. 前端提交 `POST /api/run_all`。
3. 后端读取上传文件为 bytes，创建内存 session。
4. 后端立即返回 `session_id`。
5. 后台线程 `_bg_compute()` 逐项计算指标。
6. `templates/index.html` 轮询 `GET /api/session/<sid>`。
7. 计算完成后持久化：
   - `~/.spacelens/results/<sid>/images/`
   - `~/.spacelens/results/<sid>/summary.json`
   - `~/.spacelens/results/<sid>/meta.json`
   - `~/.spacelens/projects.db`

### 历史项目恢复链路

1. 历史页读取 `GET /api/projects`。
2. 点击查看时调用 `GET /api/projects/<pid>/view`。
3. 若 session 仍在内存，直接跳转结果页。
4. 若 session 过期，尝试从 `result_folder` 的 `meta.json`、`summary.json` 和 `images/` 恢复。

## 主要页面路由

| 路由 | 模板 | 说明 |
| --- | --- | --- |
| `/` | `cover.html` | 封面页 |
| `/new_project` | `new_project.html` | 新建项目/上传数据 |
| `/results` | `index.html` | 分析结果页，依赖 `?sid=` |
| `/history` | `history.html` | 历史项目 |
| `/projects` | `projects.html` | 项目列表/管理 |
| `/compare` | `compare.html` | 项目对比 |
| `/select_module` | `select_module.html` | 模块选择 |
| `/admin/db` | `admin_db.html` | 数据库管理 |

## 主要 API

### 会话与一键分析

| API | 方法 | 说明 |
| --- | --- | --- |
| `/api/run_all` | POST | 一键计算全部可用指标，返回 `session_id` |
| `/api/session/<sid>` | GET | 获取会话结果和计算状态 |
| `/api/session/<sid>/debug` | GET | 获取调试信息和各指标错误 |
| `/api/session/<sid>/cluster` | POST | 在已有 session 内重算聚类 |

### 项目与导出

| API | 方法 | 说明 |
| --- | --- | --- |
| `/api/save_project/<sid>` | POST | 桌面端保存项目 ZIP |
| `/api/export_project/<sid>` | POST | 浏览器下载项目 ZIP |
| `/api/export_metric/<sid>/<metric_id>` | GET | 下载单指标 ZIP |
| `/api/save_metric/<sid>/<metric_id>/<file_type>` | POST | 桌面端保存单指标文件 |
| `/api/projects/check_duplicate` | POST | 检查重复项目 |
| `/api/projects` | GET | 项目列表 |
| `/api/projects/<pid>` | DELETE | 删除项目 |
| `/api/projects/<pid>/rename` | POST | 重命名项目 |
| `/api/projects/compare` | GET | 项目对比数据 |
| `/api/projects/<pid>/view` | GET | 查看/恢复历史项目 |
| `/api/projects/<pid>/export` | POST | 导出历史项目 |

### 单指标分析

| API | 方法 | 说明 |
| --- | --- | --- |
| `/api/heatmap` | POST | 到访频次热力图 |
| `/api/trajectory` | POST | 轨迹长度/轨迹图 |
| `/api/cluster` | POST | 空间聚类 |
| `/api/usetime` | POST | 使用时长 |
| `/api/speed` | POST | 移动速率 |
| `/api/duration` | POST | 停留时长 |
| `/api/density` | POST | 人员密度 |
| `/api/openness` | POST | 空间开放程度 |
| `/api/topology` | POST | 拓扑连接关系 |
| `/api/difference` | POST | 轨迹差异系数 |
| `/api/environment` | POST | 环境参数 |
| `/api/behavior_count` | POST | 行为发生人次 |
| `/api/behavior_duration` | POST | 行为时长 |
| `/api/behavior_rate` | POST | 行为发生率 |
| `/api/behavior_entropy` | POST | 行为复合度 |
| `/api/utilization` | POST | 功能利用率 |
| `/api/satisfaction` | POST | 整体满意度 |
| `/api/satisfaction_region` | POST | 空间区域满意度 |
| `/api/satisfaction_design` | POST | 设计要素满意度 |

## 数据输入约定

### 平面图

- 文件字段：`layout_img`
- 支持 PNG/JPG 等 Pillow 可读取格式。
- 坐标系需要与定位/行为/环境数据的 `X`、`Y` 对应。
- 黑色墙体区域会被识别为不可通行区域，用于减少热力图渗色。

### 背景遮罩图

- 文件字段：`background_img`
- 可选。
- 黑色区域表示无测量数据，不参与正式热力图上色。

### 定位数据

- 文件字段：`loc_data`
- 支持 CSV / Excel。

常用列：

| 列名 | 说明 |
| --- | --- |
| `X` | 横坐标，必需 |
| `Y` | 纵坐标，必需 |
| `t` | 时间戳/时间序号，时长和速率类指标常用 |
| `UserID` | 人员 ID，轨迹和人员类指标常用 |
| `Region` | 区域编号或区域名，区域统计和拓扑常用 |

### 行为数据

- 文件字段：`behavior_data`
- 常用列包括 `X`、`Y`、`Region`、`UserID`、`Behavior`、`BehaviorNum`、`Duration` 等。
- 不同指标对列要求不同，缺列时该指标会跳过或返回错误。

### 环境数据

- 文件字段：`env_data`
- 常用列包括 `X`、`Y`、`ParameterNum`、`Value`。
- `ParameterNum` 当前通常对应：
  - `1`：温度
  - `2`：湿度
  - `3`：光照
  - `4`：风速
  - `5`：噪声

### 问卷数据

一键分析时分为三类问卷：

| 文件字段 | 说明 |
| --- | --- |
| `ques_data_overall` | 整体满意度 |
| `ques_data_region` | 空间区域满意度 |
| `ques_data_design` | 设计要素满意度 |

常用列包括 `UserID`、`Region`、`Factor`、`Satisfaction` 等，具体取决于指标。

### 区域坐标数据

- 文件字段：`region_data`
- 可选。
- 用于空间开放程度、功能利用率等需要区域面积/边界的指标。

## 结果与持久化

默认数据目录：

```text
~/.spacelens/
├── projects.db
└── results/
    └── <session_id>/
        ├── images/
        ├── summary.json
        └── meta.json
```

自定义数据目录：

```bash
SPACELENS_DATA_DIR=/path/to/data python desktop_app.py
```

项目导出的 ZIP 通常包含：

```text
images/        # 指标结果图片
data/          # 指标数值汇总 Excel
summary.json   # 全量摘要
README.txt     # 导出说明
```

## 管理员页面

访问：

```text
/admin/db
```

默认密码在 `app.py` 中：

```python
ADMIN_PASSWORD = 'spacelens2025'
```

当前管理页主要用于查看数据库项目记录、搜索、导出 CSV、删除记录或清空全部记录。密码校验偏本地工具场景，不应视为生产级鉴权。

## 打包

### Windows

建议在 Windows 环境下执行：

```bash
pip install -r requirements.txt
pyinstaller build_windows.spec
```

输出目录通常为：

```text
dist/SpaceLens/SpaceLens.exe
```

也可以参考：

```bash
./build_windows_docker.sh
```

### macOS

```bash
pip install -r requirements.txt
pyinstaller build_macos.spec
```

## 测试与验证

当前仓库中测试较少，主要是针对热力图颜色/插值的验证脚本：

```bash
python test_heatmap_colors.py
```

常规开发时建议至少做以下检查：

```bash
python -m py_compile app.py desktop_app.py api/analysis.py api/db.py
python app.py
```

然后浏览器访问 `http://127.0.0.1:8080`，用 `GUI/` 或 `博物馆数据0521/` 中的示例数据跑一遍新建项目和导出流程。

## 当前已知状态与待排查点

- 纯 Web 模式下，`app.py` 未直接定义 `/api/ready`；该路由目前由 `desktop_app.py` 启动时动态注册。若直接运行 `python app.py`，前端中轮询 `/api/ready` 的页面可能需要兼容处理或在 `app.py` 中补一个 ready API。
- `static/js/app.js` 是单指标分析页面逻辑，`templates/new_project.html` 和 `templates/index.html` 又实现了一键分析/结果页逻辑。后续若继续开发，建议明确主流程，避免两套前端状态模型继续分叉。
- `api/analysis.py` 已经承担算法、API、会话缓存、导出、恢复、文件系统操作等职责，文件较大。后续适合逐步拆分为：
  - `metrics/`：各指标计算
  - `sessions.py`：内存 session 与恢复
  - `exports.py`：ZIP/Excel/图片导出
  - `paths.py`：桌面端路径解析和数据目录
- session TTL 当前为 1 小时，过期后依赖磁盘结果恢复。调试历史项目时优先确认 `~/.spacelens/results/<sid>/meta.json` 是否存在。
- 数据列名目前偏强约定，很多指标依赖固定列名。后续可增加数据导入预检，提前告诉用户缺哪些列，而不是等指标计算阶段逐个失败。
- 管理员接口当前本地防护较轻，适合桌面单机使用；若未来部署为多人 Web 服务，需要重新设计认证和权限。
- 项目里保留了多个历史报告、示例 zip、MATLAB 原型和构建产物目录。正式发布前建议整理 `.gitignore` 和示例数据策略，减少仓库噪声。

## Debug 建议

### 一键分析没有结果

1. 打开浏览器开发者工具或桌面端日志，确认 `POST /api/run_all` 是否返回 `session_id`。
2. 请求：

```text
GET /api/session/<sid>/debug
```

查看：

- `files_received`：后端是否收到文件。
- `computed`：已成功指标。
- `skipped`：跳过指标。
- `details.<metric>.error`：错误原因。
- `details.<metric>.traceback`：后端 traceback。

### 历史项目打不开

1. 查数据库中的 `result_folder` 是否存在。
2. 检查结果目录是否包含：

```text
meta.json
summary.json
images/
```

3. 调用：

```text
GET /api/projects/<pid>/view
```

看返回是内存 session、磁盘恢复成功，还是 expired。

### 导出失败

- 桌面端优先走 `/api/save_project/<sid>` 或 `/api/save_metric/...`，依赖 Qt 原生保存对话框 hook。
- 浏览器模式可走 `/api/export_project/<sid>` 或 `/api/export_metric/...`。
- 若提示 session 过期，先通过历史项目恢复再导出。

### 图像或热力图异常

- 确认平面图与 `X`、`Y` 坐标系一致。
- 确认坐标是否超出图像尺寸；`run_all` 中有自动归一化逻辑，但单指标 API 的行为可能不同。
- 若热力图被大面积遮挡，检查平面图黑色区域和可选 `background_img` 遮罩。

## 后续开发优先级建议

1. 给 `app.py` 补齐 `/api/ready`，或让前端在纯 Web 模式下不依赖该端点。
2. 增加统一的数据预检 API，提前返回每个指标的可计算性和缺失列。
3. 拆分 `api/analysis.py`，先从导出、session、项目 API 三块开始。
4. 为关键指标添加小型 fixture 数据和自动化测试。
5. 统一一键分析与单指标分析的前端状态管理。
6. 清理构建产物、历史报告和示例数据的版本管理策略。
