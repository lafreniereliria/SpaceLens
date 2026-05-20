"""
建筑空间绩效评价平台 桌面程序入口
使用 PyQt6 创建原生窗口，内嵌 Flask 服务 + WebEngine 渲染界面
封面界面通过 setHtml() 立即显示，无需等待 Flask 启动
"""

import sys
import os
import threading
import time
import socket

# --------------------------------------------------------------------------- #
#  PyInstaller 打包后路径修正
# --------------------------------------------------------------------------- #
if getattr(sys, 'frozen', False):
    _BASE_DIR = sys._MEIPASS
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PyQt6.QtCore import QUrl, Qt, QTimer
from PyQt6.QtGui import QFont

# --------------------------------------------------------------------------- #
#  Flask 服务配置
# --------------------------------------------------------------------------- #
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 18080

APP_NAME = "建筑空间绩效评价平台"
APP_NAME_EN = "Building Space Performance Evaluation Platform"

def _find_free_port() -> int:
    # 用 with 语句确保 socket 在任何情况下都会被关闭（包括意外异常）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((FLASK_HOST, FLASK_PORT))
            return FLASK_PORT
        except OSError:
            pass
    # 让 OS 分配一个空闲端口
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
        s2.bind((FLASK_HOST, 0))
        return s2.getsockname()[1]


# --------------------------------------------------------------------------- #
#  封面 HTML（内嵌，不依赖 Flask，可立即显示）
# --------------------------------------------------------------------------- #
def _build_cover_html() -> str:
    """生成封面 HTML 字符串，通过 setHtml() 立即渲染"""
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>建筑空间绩效评价平台</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    height: 100vh;
    display: flex;
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f4f7fb;
    color: #1a2035;
    overflow: hidden;
  }

  /* ── 左侧装饰区 ── */
  .cover-left {
    width: 55%;
    background: linear-gradient(135deg, #0a1628 0%, #0e2a52 40%, #0a4a8c 80%, #0ea5e9 100%);
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 60px 56px;
    overflow: hidden;
  }

  .cover-left::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at 20% 80%, rgba(14,165,233,0.25) 0%, transparent 50%),
      radial-gradient(circle at 80% 20%, rgba(56,189,248,0.15) 0%, transparent 45%);
  }

  .grid-deco {
    position: absolute;
    inset: 0;
    opacity: 0.08;
    background-image:
      linear-gradient(rgba(255,255,255,0.6) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,0.6) 1px, transparent 1px);
    background-size: 60px 60px;
  }

  .hex-deco {
    position: absolute;
    bottom: -40px;
    right: -40px;
    width: 320px;
    height: 320px;
    opacity: 0.06;
  }

  .cover-left-content { position: relative; z-index: 1; }

  .cover-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(14,165,233,0.2);
    border: 1px solid rgba(14,165,233,0.4);
    color: #7dd3fc;
    font-size: 12px;
    letter-spacing: 2px;
    padding: 6px 14px;
    border-radius: 20px;
    margin-bottom: 32px;
  }

  .cover-badge-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #38bdf8;
    animation: pulse 2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
  }

  .cover-title-en {
    font-size: 13px;
    letter-spacing: 3px;
    color: rgba(125,211,252,0.7);
    text-transform: uppercase;
    margin-bottom: 16px;
  }

  .cover-title-zh {
    font-size: 36px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.3;
    margin-bottom: 24px;
    letter-spacing: 2px;
  }

  .cover-title-zh em {
    font-style: normal;
    color: #38bdf8;
  }

  .cover-desc {
    font-size: 14px;
    color: rgba(186,230,255,0.65);
    line-height: 1.8;
    max-width: 380px;
  }

  .tag-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 36px;
  }

  .tag {
    font-size: 11px;
    padding: 4px 12px;
    border-radius: 12px;
    border: 1px solid rgba(56,189,248,0.3);
    color: rgba(186,230,255,0.8);
    background: rgba(14,165,233,0.1);
  }

  .cover-version {
    position: absolute;
    bottom: 28px;
    left: 56px;
    font-size: 12px;
    color: rgba(186,230,255,0.4);
    z-index: 1;
  }

  /* ── 右侧操作区 ── */
  .cover-right {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 48px 56px;
  }

  .logo-icon {
    width: 72px;
    height: 72px;
    background: linear-gradient(135deg, #0ea5e9, #0284c7);
    border-radius: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 8px 24px rgba(14,165,233,0.35);
    margin-bottom: 24px;
  }

  .logo-icon svg { width: 38px; height: 38px; color: #ffffff; }

  .right-title {
    font-size: 22px;
    font-weight: 700;
    color: #0f172a;
    text-align: center;
    margin-bottom: 8px;
    letter-spacing: 1px;
  }

  .right-subtitle {
    font-size: 13px;
    color: #64748b;
    text-align: center;
    margin-bottom: 40px;
  }

  .btn-primary {
    width: 100%;
    max-width: 320px;
    padding: 16px 32px;
    background: linear-gradient(135deg, #0ea5e9, #0284c7);
    color: #fff;
    border: none;
    border-radius: 12px;
    font-size: 16px;
    font-weight: 600;
    letter-spacing: 2px;
    cursor: pointer;
    box-shadow: 0 6px 20px rgba(14,165,233,0.4);
    transition: all 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    margin-bottom: 16px;
  }

  .btn-primary:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 10px 28px rgba(14,165,233,0.5);
    background: linear-gradient(135deg, #38bdf8, #0ea5e9);
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-row {
    display: flex;
    gap: 12px;
    width: 100%;
    max-width: 320px;
    margin-bottom: 12px;
  }

  .btn-secondary {
    flex: 1;
    padding: 12px 16px;
    background: #ffffff;
    color: #334155;
    border: 1.5px solid #e2e8f0;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.18s;
    text-align: center;
    line-height: 1.4;
  }

  .btn-secondary:hover { border-color: #0ea5e9; color: #0ea5e9; background: #f0f9ff; }

  /* 进度条 */
  .loading-bar { width: 100%; max-width: 320px; margin-top: 28px; }

  .loading-label {
    font-size: 11px;
    color: #94a3b8;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
  }

  .loading-track {
    height: 4px;
    background: #e2e8f0;
    border-radius: 2px;
    overflow: hidden;
  }

  .loading-fill {
    height: 100%;
    background: linear-gradient(90deg, #0ea5e9, #38bdf8);
    border-radius: 2px;
    width: 0%;
    transition: width 0.4s ease;
  }

  /* 面板 */
  .panel-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(15,23,42,0.5);
    z-index: 100;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(4px);
  }

  .panel-overlay.active { display: flex; }

  .panel-box {
    background: #ffffff;
    border-radius: 16px;
    width: 560px;
    max-width: 90vw;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 24px 60px rgba(0,0,0,0.18);
    overflow: hidden;
  }

  .panel-header {
    padding: 20px 24px;
    border-bottom: 1px solid #f1f5f9;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .panel-header h3 { font-size: 16px; font-weight: 600; color: #0f172a; }

  .panel-close {
    width: 32px; height: 32px;
    border-radius: 8px;
    border: none;
    background: #f1f5f9;
    color: #64748b;
    font-size: 18px;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.15s;
  }

  .panel-close:hover { background: #e2e8f0; color: #1e293b; }
  .panel-body { padding: 24px; overflow-y: auto; flex: 1; }

  .tree-item {
    padding: 8px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    color: #334155;
    display: flex;
    align-items: center;
    gap: 8px;
    transition: background 0.15s;
  }

  .tree-item:hover { background: #f0f9ff; color: #0ea5e9; }
  .tree-item.level1 { font-weight: 600; color: #0f172a; margin-top: 4px; }
  .tree-item.level2 { padding-left: 28px; color: #475569; }
  .tree-item.level3 { padding-left: 48px; color: #64748b; font-size: 13px; }
  .tree-arrow { font-size: 10px; color: #94a3b8; transition: transform 0.2s; }
  .tree-arrow.open { transform: rotate(90deg); }
  .tree-children { display: none; }
  .tree-children.open { display: block; }

  .info-row {
    display: flex;
    align-items: flex-start;
    gap: 16px;
    padding: 16px 0;
    border-bottom: 1px solid #f1f5f9;
  }

  .info-row:last-child { border-bottom: none; }
  .info-label { width: 80px; font-size: 12px; color: #94a3b8; flex-shrink: 0; padding-top: 2px; }
  .info-value { font-size: 14px; color: #334155; line-height: 1.6; }

  .version-tag {
    display: inline-block;
    padding: 2px 10px;
    background: #f0f9ff;
    color: #0ea5e9;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid #bae6fd;
  }
</style>
</head>
<body>

<div class="cover-left">
  <div class="grid-deco"></div>
  <svg class="hex-deco" viewBox="0 0 200 200" fill="none">
    <polygon points="100,10 185,55 185,145 100,190 15,145 15,55" stroke="white" stroke-width="2" fill="none"/>
    <polygon points="100,35 165,72 165,128 100,165 35,128 35,72" stroke="white" stroke-width="1.5" fill="none"/>
    <polygon points="100,60 145,85 145,115 100,140 55,115 55,85" stroke="white" stroke-width="1" fill="none"/>
  </svg>
  <div class="cover-left-content">
    <div class="cover-badge">
      <div class="cover-badge-dot"></div>
      INTELLIGENT EVALUATION PLATFORM
    </div>
    <div class="cover-title-en">Building Space Performance Assessment</div>
    <div class="cover-title-zh">建筑空间绩效<br><em>评价平台</em></div>
    <p class="cover-desc">
      基于多源空间行为数据，综合分析建筑空间使用绩效，
      支持热力图、轨迹分析、聚类分析等多维度评价方法，
      为建筑设计与优化提供数据驱动的决策支持。
    </p>
    <div class="tag-row">
      <span class="tag">到访频次分析</span>
      <span class="tag">轨迹分析</span>
      <span class="tag">空间聚类</span>
      <span class="tag">使用时长</span>
      <span class="tag">密度分析</span>
      <span class="tag">移动速率</span>
    </div>
  </div>
  <div class="cover-version">v1.0.0 · 2025</div>
</div>

<div class="cover-right">
  <div class="logo-icon">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <polygon points="12,2 22,8.5 22,15.5 12,22 2,15.5 2,8.5"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  </div>
  <div class="right-title">建筑空间绩效评价平台</div>
  <div class="right-subtitle">Building Space Performance Evaluation Platform</div>

  <button class="btn-primary" id="btn-start" disabled onclick="startEvaluation()">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
      <polygon points="5,3 19,12 5,21"/>
    </svg>
    开始使用
  </button>

  <div class="btn-row">
    <button class="btn-secondary" onclick="showPanel('intro')">工具介绍</button>
    <button class="btn-secondary" onclick="showPanel('team')">开发人员</button>
    <button class="btn-secondary" onclick="showPanel('version')">版本信息</button>
  </div>

  <div class="loading-bar">
    <div class="loading-label">
      <span id="loading-text">正在初始化系统...</span>
      <span id="loading-pct">0%</span>
    </div>
    <div class="loading-track">
      <div class="loading-fill" id="loading-fill"></div>
    </div>
  </div>
</div>

<!-- 工具介绍面板 -->
<div class="panel-overlay" id="panel-intro">
  <div class="panel-box">
    <div class="panel-header">
      <h3>工具介绍</h3>
      <button class="panel-close" onclick="closePanel('intro')">×</button>
    </div>
    <div class="panel-body">
      <div class="tree-item level1" onclick="toggleTree(this)"><span class="tree-arrow">▶</span> 软件概述</div>
      <div class="tree-children">
        <div class="tree-item level2" onclick="toggleTree(this)"><span class="tree-arrow">▶</span> 开发背景</div>
        <div class="tree-children">
          <div class="tree-item level3">· 空间使用效率评估需求</div>
          <div class="tree-item level3">· 多源数据融合研究</div>
        </div>
        <div class="tree-item level2">· 研究目标与意义</div>
      </div>
      <div class="tree-item level1" onclick="toggleTree(this)"><span class="tree-arrow">▶</span> 功能模块</div>
      <div class="tree-children">
        <div class="tree-item level2">· 建筑空间使用绩效评价</div>
        <div class="tree-item level2">· 空间服务点布局与评价</div>
        <div class="tree-item level2">· 空间句法与性能耦合评价</div>
      </div>
      <div class="tree-item level1" onclick="toggleTree(this)"><span class="tree-arrow">▶</span> 指标体系</div>
      <div class="tree-children">
        <div class="tree-item level2">· 动线指标（轨迹长度 / 移动速率）</div>
        <div class="tree-item level2">· 行为指标（行为人次 / 发生率）</div>
        <div class="tree-item level2">· 物理环境指标（温湿度 / 光照 / 噪声）</div>
        <div class="tree-item level2">· 主观感知指标（满意度）</div>
      </div>
      <div class="tree-item level1" onclick="toggleTree(this)"><span class="tree-arrow">▶</span> 使用流程</div>
      <div class="tree-children">
        <div class="tree-item level2">· 导入空间图像</div>
        <div class="tree-item level2">· 导入多源数据</div>
        <div class="tree-item level2">· 选择分析模块</div>
        <div class="tree-item level2">· 查看可视化结果</div>
        <div class="tree-item level2">· 导出分析报告</div>
      </div>
    </div>
  </div>
</div>

<!-- 开发人员面板 -->
<div class="panel-overlay" id="panel-team">
  <div class="panel-box">
    <div class="panel-header">
      <h3>开发人员</h3>
      <button class="panel-close" onclick="closePanel('team')">×</button>
    </div>
    <div class="panel-body">
      <div class="info-row"><div class="info-label">单位</div><div class="info-value">同济大学建筑与城市规划学院</div></div>
      <div class="info-row"><div class="info-label">研究团队</div><div class="info-value">建筑空间绩效评价研究组</div></div>
      <div class="info-row"><div class="info-label">指导教师</div><div class="info-value">待补充</div></div>
      <div class="info-row"><div class="info-label">开发成员</div><div class="info-value">待补充</div></div>
      <div class="info-row"><div class="info-label">联系邮箱</div><div class="info-value">待补充</div></div>
    </div>
  </div>
</div>

<!-- 版本信息面板 -->
<div class="panel-overlay" id="panel-version">
  <div class="panel-box">
    <div class="panel-header">
      <h3>版本信息</h3>
      <button class="panel-close" onclick="closePanel('version')">×</button>
    </div>
    <div class="panel-body">
      <div class="info-row"><div class="info-label">当前版本</div><div class="info-value"><span class="version-tag">v1.0.0</span></div></div>
      <div class="info-row"><div class="info-label">更新时间</div><div class="info-value">2025 年 5 月</div></div>
      <div class="info-row"><div class="info-label">技术栈</div><div class="info-value">Python · Flask · PyQt6 · NumPy · SciPy · Matplotlib</div></div>
      <div class="info-row">
        <div class="info-label">更新内容</div>
        <div class="info-value">· 热力图、轨迹分析、聚类分析模块<br>· 多主题配色支持<br>· 双平台（macOS / Windows）打包支持</div>
      </div>
    </div>
  </div>
</div>

<script>
// ── 由 Python 调用的接口，推送进度 ──
var _flaskPort = null;

function setProgress(pct, text) {
  document.getElementById('loading-fill').style.width = pct + '%';
  document.getElementById('loading-pct').textContent = Math.round(pct) + '%';
  if (text) document.getElementById('loading-text').textContent = text;
}

function setReady(port) {
  _flaskPort = port;
  setProgress(100, '系统就绪，可以开始使用');
  document.getElementById('btn-start').disabled = false;
}

function startEvaluation() {
  if (_flaskPort) {
    window.location.href = 'http://127.0.0.1:' + _flaskPort + '/select_module';
  }
}

// ── 面板控制 ──
function showPanel(id) { document.getElementById('panel-' + id).classList.add('active'); }
function closePanel(id) { document.getElementById('panel-' + id).classList.remove('active'); }

document.querySelectorAll('.panel-overlay').forEach(function(el) {
  el.addEventListener('click', function(e) { if (e.target === el) el.classList.remove('active'); });
});

function toggleTree(el) {
  var arrow = el.querySelector('.tree-arrow');
  var children = el.nextElementSibling;
  if (!children || !children.classList.contains('tree-children')) return;
  var isOpen = children.classList.toggle('open');
  if (arrow) arrow.classList.toggle('open', isOpen);
}
</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
#  Flask 后台线程
# --------------------------------------------------------------------------- #
def _run_flask(port: int, state: dict):
    try:
        _run_flask_impl(port, state)
    except Exception as e:
        import traceback
        state['error'] = f"Fatal: {e}\n{traceback.format_exc()}"
        state['stage'] = -1


def _run_flask_impl(port: int, state: dict):
    import flask as _flask

    def _set(text, stage):
        state['status'] = text
        state['stage'] = stage

    _set("正在加载数学计算库...", 1)
    try:
        import numpy  # noqa
    except Exception:
        pass

    _set("正在加载数据分析库...", 2)
    try:
        import pandas  # noqa
    except Exception:
        pass

    _set("正在加载图形渲染库...", 3)
    try:
        import matplotlib  # noqa
        matplotlib.use('Agg')
    except Exception:
        pass

    _set("正在初始化热力图分析...", 4)
    try:
        import matplotlib.pyplot   # noqa
        import matplotlib.colors   # noqa
    except Exception:
        pass

    _set("正在初始化轨迹分析...", 5)
    try:
        import matplotlib.font_manager  # noqa
        from scipy.ndimage import gaussian_filter  # noqa
        from scipy.interpolate import make_interp_spline  # noqa
    except Exception:
        pass

    _set("正在初始化聚类分析...", 6)
    try:
        from scipy.cluster.vq import kmeans2  # noqa
        from PIL import Image  # noqa
    except Exception:
        pass

    _set("正在注册 API 路由...", 7)
    try:
        from api.analysis import analysis_bp, register_save_dialog_hook
    except Exception as e:
        state['error'] = str(e)
        state['stage'] = -1
        return

    # ── 注册 Qt 原生文件保存对话框钩子 ──
    # Flask 线程不能直接调用 Qt，用 queue 桥接到主线程
    import queue as _queue
    _dialog_req  = _queue.Queue()   # Flask 线程发请求
    _dialog_resp = _queue.Queue()   # Qt 主线程回应结果

    def _qt_save_dialog(title, default_filename, file_filter=None):
        """Flask 线程调用：把请求放入队列，阻塞等待 Qt 主线程处理"""
        _dialog_req.put((title, default_filename, file_filter))
        return _dialog_resp.get()   # 阻塞直到 Qt 线程返回路径（或 None）

    register_save_dialog_hook(_qt_save_dialog)
    # 把两个队列存入 state，供 MainWindow 轮询
    state['_dialog_req']  = _dialog_req
    state['_dialog_resp'] = _dialog_resp

    _set("正在启动服务...", 8)

    flask_app = _flask.Flask(
        __name__,
        template_folder=os.path.join(_BASE_DIR, 'templates'),
        static_folder=os.path.join(_BASE_DIR, 'static'),
    )
    flask_app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    flask_app.register_blueprint(analysis_bp, url_prefix='/api')

    @flask_app.route('/')
    def _cover():
        return _flask.render_template('cover.html')

    @flask_app.route('/results')
    def _index():
        return _flask.render_template('index.html')

    @flask_app.route('/projects')
    def _projects():
        return _flask.render_template('projects.html')

    @flask_app.route('/select_module')
    def _select_module():
        return _flask.render_template('select_module.html')

    @flask_app.route('/new_project')
    def _new_project():
        return _flask.render_template('new_project.html')

    @flask_app.route('/history')
    def _history():
        return _flask.render_template('history.html')

    @flask_app.route('/compare')
    def _compare():
        return _flask.render_template('compare.html')

    @flask_app.route('/api/ready')
    def _api_ready():
        return _flask.jsonify({"ready": True, "error": None})

    @flask_app.route('/api/shutdown', methods=['POST'])
    def _api_shutdown():
        """供桌面主进程在退出时调用，通知 Werkzeug 停止服务"""
        func = _flask.request.environ.get('werkzeug.server.shutdown')
        if func:
            func()
        return _flask.jsonify({"ok": True})

    flask_app.run(host=FLASK_HOST, port=port, debug=False, use_reloader=False)


# --------------------------------------------------------------------------- #
#  主窗口（封面用 setHtml 立即显示，就绪后 setUrl 跳转主界面）
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self, port: int, state: dict):
        super().__init__()
        self.port = port
        self.state = state
        self._flask_ready = False

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1200, 780)
        self.resize(1440, 900)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - 1440) // 2, (screen.height() - 900) // 2)

        # WebView
        self.webview = QWebEngineView()
        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        page = QWebEnginePage(profile, self.webview)
        self.webview.setPage(page)
        self.setCentralWidget(self.webview)

        # 立即加载封面（不依赖 Flask）
        self.webview.setHtml(
            _build_cover_html(),
            QUrl("about:blank")   # baseUrl 设 about:blank，封面内所有资源都内嵌
        )

        # 阶段 → (进度目标%)
        self._STAGES = {
            0: (5,   "正在初始化系统..."),
            1: (12,  "正在加载数学计算库..."),
            2: (18,  "正在加载数据分析库..."),
            3: (24,  "正在加载图形渲染库..."),
            4: (72,  "正在初始化热力图分析..."),
            5: (80,  "正在初始化轨迹分析..."),
            6: (87,  "正在初始化聚类分析..."),
            7: (93,  "正在注册 API 路由..."),
            8: (97,  "正在启动服务..."),
        }
        self._last_stage = -1
        self._smooth_pct = 5.0    # 平滑进度值

        # 轮询定时器（加载进度）
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(80)

        # 文件对话框请求轮询定时器
        self._dialog_timer = QTimer(self)
        self._dialog_timer.timeout.connect(self._check_dialog_request)
        self._dialog_timer.start(100)

    def _js(self, code: str):
        """安全地向 WebView 推送 JS"""
        self.webview.page().runJavaScript(code)

    def _poll(self):
        stage = self.state['stage']

        # 错误处理
        if stage == -1:
            err = self.state.get('error', '加载失败')
            self._js(f"setProgress(0, '⚠ {err.splitlines()[0][:50]}')")
            self._poll_timer.stop()
            return

        # 更新进度（平滑趋近目标值）
        if stage in self._STAGES:
            target_pct, status_text = self._STAGES[stage]

            # 阶段切换时立即更新文字
            if stage != self._last_stage:
                self._last_stage = stage
                self._js(f"setProgress({int(self._smooth_pct)}, '{status_text}')")

            # 平滑推进
            if self._smooth_pct < target_pct:
                diff = target_pct - self._smooth_pct
                # stage 4 最慢（decay 小），其余较快
                decay = 0.012 if stage == 4 else 0.06
                min_step = 0.18 if stage == 4 else 0.15
                self._smooth_pct += max(diff * decay, min_step)
                self._smooth_pct = min(self._smooth_pct, target_pct)
                self._js(f"setProgress({self._smooth_pct:.1f})")

        # Flask 就绪检测
        if not self._flask_ready and stage >= 8:
            try:
                with socket.create_connection((FLASK_HOST, self.port), timeout=0.05):
                    self._flask_ready = True
                    self._poll_timer.stop()
                    # 平滑冲到 100% 再解锁按钮
                    self._finish_timer_count = 0
                    self._finish_timer = QTimer(self)
                    self._finish_timer.timeout.connect(self._finish_anim)
                    self._finish_timer.start(40)
            except OSError:
                pass

    def _finish_anim(self):
        """100% 完成动画，约 800ms"""
        self._finish_timer_count += 1
        pct = min(97 + self._finish_timer_count * 1.5, 100)
        self._js(f"setProgress({pct:.1f})")
        if pct >= 100:
            self._finish_timer.stop()
            self._js(f"setReady({self.port})")

    def _check_dialog_request(self):
        """Qt 主线程：检查是否有 Flask 线程发来的文件保存对话框请求"""
        import queue as _queue
        req_q  = self.state.get('_dialog_req')
        resp_q = self.state.get('_dialog_resp')
        if req_q is None or resp_q is None:
            return
        try:
            item = req_q.get_nowait()
        except _queue.Empty:
            return

        # 兼容旧的二元组和新的三元组
        if len(item) == 3:
            title, default_filename, file_filter = item
        else:
            title, default_filename = item
            file_filter = None

        # 根据文件类型选择合适的过滤器
        if file_filter is None:
            if default_filename.endswith('.png'):
                file_filter = 'PNG 图片 (*.png);;所有文件 (*)'
            elif default_filename.endswith('.xlsx'):
                file_filter = 'Excel 文件 (*.xlsx);;所有文件 (*)'
            else:
                file_filter = 'ZIP 压缩包 (*.zip);;所有文件 (*)'

        # 在 Qt 主线程弹出原生保存对话框
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            default_filename,
            file_filter,
        )
        # 把结果（字符串或空串）传回 Flask 线程
        resp_q.put(save_path if save_path else None)

    def closeEvent(self, event):
        # 1. 停止轮询定时器，避免关闭过程中再触发 JS 调用
        if hasattr(self, '_poll_timer') and self._poll_timer.isActive():
            self._poll_timer.stop()
        if hasattr(self, '_dialog_timer') and self._dialog_timer.isActive():
            self._dialog_timer.stop()
        if hasattr(self, '_finish_timer') and self._finish_timer.isActive():
            self._finish_timer.stop()

        # 2. 让 WebView 先加载空白页，通知 Chromium 子进程释放资源
        #    这一步对 Windows 上 QtWebEngineProcess.exe 孤儿进程至关重要
        try:
            self.webview.setUrl(QUrl("about:blank"))
            self.webview.page().deleteLater()
        except Exception:
            pass

        # 3. 退出 Qt 事件循环 → main() 中 sys.exit(app.exec()) 返回
        QApplication.quit()
        event.accept()


# --------------------------------------------------------------------------- #
#  程序入口
# --------------------------------------------------------------------------- #
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)

    port = _find_free_port()
    state = {'status': '正在准备...', 'stage': 0, 'error': None}

    # 启动 Flask 后台线程
    flask_thread = threading.Thread(
        target=_run_flask, args=(port, state), daemon=True
    )
    flask_thread.start()

    # 立即打开主窗口（封面通过 setHtml 即时渲染，无需等 Flask）
    win = MainWindow(port, state)
    win.show()

    exit_code = app.exec()

    # app.exec() 返回后（窗口已关闭），主动通知 Flask/Werkzeug 停止
    # Flask 线程是 daemon，进程退出时会被强杀，但主动关闭可立即释放端口（Windows 尤其重要）
    try:
        import urllib.request as _ur
        _ur.urlopen(
            _ur.Request(f'http://{FLASK_HOST}:{port}/api/shutdown', data=b''),
            timeout=0.5
        )
    except Exception:
        pass  # Flask 可能还没启动完，或已经停了，忽略错误

    sys.exit(exit_code)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
