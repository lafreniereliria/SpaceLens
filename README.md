# SpaceLens · 建筑空间绩效评价平台

> 基于多源空间行为数据，综合评价建筑空间使用绩效的桌面分析工具。  
> 支持热力图、轨迹分析、聚类分析等多维度评价方法，为建筑设计与优化提供数据驱动的决策支持。

---

## ✨ 功能模块

| 模块 | 指标代码 | 所需数据 | 说明 |
|------|---------|---------|------|
| 到访频次热力图 | A1 | 平面图 + 定位数据（X, Y） | 生成空间使用频率热力图，可视化高频区域 |
| 人员轨迹分析 | A10 | 平面图 + 定位数据（X, Y, UserID） | 绘制个人动线，统计路径长度与速率 |
| 空间聚类分析 | A5 | 平面图 + 定位数据（X, Y） | K-Means 聚类，识别空间使用模式 |
| 使用时长分析 | — | 定位数据（含时间戳） | 统计各区域驻留时间分布 |
| 物理环境指标 | — | 环境传感器数据 | 温湿度、光照、噪声等环境绩效 |
| 主观感知评价 | — | 问卷数据 | 满意度等用户主观感知指标 |

---

## 🚀 快速启动

### 环境要求

- Python 3.9+
- macOS / Windows 均支持

### 安装与运行

```bash
# 1. 克隆仓库
git clone https://github.com/lafreniereliria/SpaceLens.git
cd SpaceLens

# 2. 安装依赖（含桌面端 PyQt6）
pip install -r requirements.txt

# 3. 启动桌面程序（推荐）
python desktop_app.py

# 或：仅启动 Web 服务（浏览器访问）
python app.py
# 访问 http://127.0.0.1:18080
```

---

## 🖥 桌面独立程序

程序以原生窗口运行，无需打开浏览器，体验类似本地应用程序。

### 打包为 Windows 可执行文件

> ⚠️ 必须在 **Windows 环境**下执行打包命令

```bash
pip install pyinstaller
pip install -r requirements.txt

pyinstaller build_windows.spec
```

打包完成后，`dist/SpaceLens/SpaceLens.exe` 即为可分发的独立程序。  
将整个 `dist/SpaceLens/` 文件夹压缩发送给用户，解压后双击 `SpaceLens.exe` 即可运行。

> 打包后文件夹约 300–500 MB（含 Qt WebEngine 引擎）。

---

## 📂 输入数据格式

### 定位数据（CSV / Excel）

| 列名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `X` | 数值 | ✅ | 横坐标（像素） |
| `Y` | 数值 | ✅ | 纵坐标（像素） |
| `UserID` | 字符串 | 轨迹分析必填 | 人员唯一标识 |
| `Region` | 字符串 | 可选 | 区域标签，用于分区统计 |

示例：

```csv
UserID,X,Y,Region
U001,120,340,大厅
U001,135,355,大厅
U002,280,190,走廊
```

### 平面图

- 格式：PNG / JPG
- 建议分辨率：800 × 600 px 以上
- 坐标系与定位数据的像素坐标对应

### 其他数据文件

| 文件 | 说明 |
|------|------|
| `behavior.xlsx` | 行为观察记录（行为类型、发生时间、位置） |
| `environment.xlsx` | 物理环境传感器数据（温度、湿度、光照、噪声） |
| `questionnaire.xlsx` | 主观问卷数据（满意度等评分） |
| `region_coordinates.xlsx` | 功能区域边界坐标 |

---

## 🗂 项目结构

```
SpaceLens/
├── app.py                  # Flask Web 服务入口
├── desktop_app.py          # PyQt6 桌面程序入口
├── build_windows.spec      # PyInstaller 打包配置
├── requirements.txt        # Python 依赖
├── api/
│   ├── analysis.py         # 分析算法 + API 端点
│   └── db.py               # SQLite 项目数据库
├── templates/              # Jinja2 HTML 模板
│   ├── cover.html          # 封面页
│   ├── projects.html       # 项目管理页
│   ├── new_project.html    # 新建项目 / 数据导入页
│   ├── index.html          # 结果展示页
│   ├── history.html        # 历史项目页
│   ├── compare.html        # 项目对比页
│   └── admin_db.html       # 数据库管理页（需密码）
└── static/
    ├── css/app.css         # 全局样式
    └── js/                 # 前端逻辑
```

---

## 🔧 技术栈

| 层次 | 技术 |
|------|------|
| 后端框架 | Python · Flask 3.0 |
| 桌面容器 | PyQt6 · QtWebEngine |
| 数据分析 | NumPy · Pandas · SciPy · scikit-learn |
| 可视化 | Matplotlib (Agg 后端) · Pillow |
| 数据存储 | SQLite（项目元数据） |
| 前端 | 原生 HTML / CSS / JS（无框架） |

---

## 🔑 数据库管理

访问 `/admin/db` 可进入数据库管理页面（需输入管理员密码）。

默认密码在 `app.py` 和 `desktop_app.py` 中的 `ADMIN_PASSWORD` 常量配置：

```python
ADMIN_PASSWORD = 'spacelens2025'
```

管理页面功能：查看所有项目记录、搜索筛选、查看源文件路径、导出 CSV、删除单条或清空全部。

---

## 📋 开发说明

### 兼容性

- Python 版本：3.9+（类型注解使用注释风格，兼容 3.9）
- 操作系统：macOS、Windows（已处理路径分隔符兼容）
- 在 Windows 上用 `explorer /select,"..."` 打开文件所在目录

### 本地开发

```bash
# 仅 Web 模式（无需 PyQt6）
pip install flask numpy pandas matplotlib scikit-learn scipy pillow openpyxl

python app.py
```

### 贡献

欢迎提交 Issue 和 Pull Request。
