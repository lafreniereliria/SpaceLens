# 空间分析系统 Demo · SpaceLens

## 快速启动（开发模式）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 生成演示数据（可选）
python gen_demo_data.py

# 3. 启动 Web 服务（浏览器模式）
python app.py
```

访问 http://127.0.0.1:8080

---

## 🖥 桌面独立程序模式（推荐）

无需打开浏览器，直接以原生窗口运行，体验类似 Photoshop。

### 直接运行（开发调试）

```bash
pip install -r requirements.txt   # 含 PyQt6 和 PyQt6-WebEngine
python desktop_app.py
```

### 打包为 Windows exe（在 Windows 机器上执行）

```bash
pip install pyinstaller
pip install -r requirements.txt

pyinstaller build_windows.spec
```

打包完成后，`dist/SpaceLens/SpaceLens.exe` 即为可分发的独立程序。  
将整个 `dist/SpaceLens/` 文件夹压缩发送给用户，解压后双击 `SpaceLens.exe` 即可。

> **注意**：必须在 Windows 环境下打包才能生成 Windows exe。  
> 打包后文件夹约 300–500 MB（含 QtWebEngine 引擎）。

---

## 功能说明

| 功能 | 对应原版 | 需要数据 |
|------|---------|---------|
| 到访频次热力图 | A1 | 平面图 + 定位数据（X, Y） |
| 人员轨迹分析 | A10 | 平面图 + 定位数据（X, Y, UserID） |
| 空间聚类分析 | A5 | 平面图 + 定位数据（X, Y） |

## 数据格式

定位数据 CSV/Excel 必须包含以下列：

```
UserID, X, Y, Region（可选）
```

平面图支持 PNG/JPG，建议分辨率 800×600 以上。
