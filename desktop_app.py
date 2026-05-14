"""
SpaceLens 桌面程序入口
使用 PyQt6 创建原生窗口，内嵌 Flask 服务 + WebEngine 渲染界面
无需打开浏览器，即为独立桌面程序
"""

import sys
import os
import threading
import time
import socket
import math

# --------------------------------------------------------------------------- #
#  PyInstaller 打包后路径修正
# --------------------------------------------------------------------------- #
if getattr(sys, 'frozen', False):
    _BASE_DIR = sys._MEIPASS
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QSplashScreen, QLabel, QProgressBar, QWidget
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PyQt6.QtCore import QUrl, Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QColor, QFont, QPainter, QLinearGradient

# --------------------------------------------------------------------------- #
#  Flask 服务配置
# --------------------------------------------------------------------------- #
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 18080


def _find_free_port() -> int:
    s = socket.socket()
    try:
        s.bind((FLASK_HOST, FLASK_PORT))
        s.close()
        return FLASK_PORT
    except OSError:
        s2 = socket.socket()
        s2.bind((FLASK_HOST, 0))
        port = s2.getsockname()[1]
        s2.close()
        return port


def _warmup_matplotlib():
    """
    预热 matplotlib 字体缓存（最耗时的步骤）。
    在 Flask 线程启动前先跑一次 import，后续调用几乎零延迟。
    """
    import matplotlib
    # 强制触发字体缓存构建，之后再次 import 会命中缓存
    matplotlib.font_manager._fmcache  # access to trigger lazy init
    try:
        matplotlib.font_manager.fontManager  # noqa
    except Exception:
        pass


def _run_flask(port: int, state: dict):
    """
    后台线程：分阶段加载重型库，通过共享 state 字典传递进度，
    不直接调用任何 Qt API，避免跨线程崩溃。
    """
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

    # ── 阶段 4：注册分析模块（拆分为 4 个真实子阶段）──
    _set("正在初始化热力图分析与渲染核心...", 4)
    try:
        import matplotlib.pyplot   # noqa  触发字体缓存（最耗时）
        import matplotlib.colors   # noqa
    except Exception:
        pass

    _set("正在初始化轨迹分析...", 5)
    try:
        import matplotlib.font_manager  # noqa  字体扫描
        from scipy.ndimage import gaussian_filter  # noqa
        from scipy.interpolate import make_interp_spline  # noqa
    except Exception:
        pass

    _set("正在初始化聚类分析...", 6)
    try:
        from scipy.cluster.vq import kmeans2  # noqa  已替换 sklearn，更快
        from PIL import Image  # noqa
    except Exception:
        pass

    _set("正在注册 API 路由...", 7)
    try:
        from api.analysis import analysis_bp
    except Exception as e:
        state['error'] = str(e)
        state['stage'] = -1
        return

    _set("正在启动服务...", 8)

    flask_app = _flask.Flask(
        __name__,
        template_folder=os.path.join(_BASE_DIR, 'templates'),
        static_folder=os.path.join(_BASE_DIR, 'static'),
    )
    flask_app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    flask_app.register_blueprint(analysis_bp, url_prefix='/api')

    @flask_app.route('/')
    def _index():
        return _flask.render_template('index.html')

    @flask_app.route('/api/ready')
    def _api_ready():
        return _flask.jsonify({"ready": True, "error": None})

    flask_app.run(host=FLASK_HOST, port=port, debug=False, use_reloader=False)




# --------------------------------------------------------------------------- #
#  主窗口
# --------------------------------------------------------------------------- #
class SpaceLensWindow(QMainWindow):
    def __init__(self, port: int):
        super().__init__()
        self.port = port
        self._setup_window()
        self._setup_webview()

    def _setup_window(self):
        self.setWindowTitle("SpaceLens · 空间分析系统")
        self.setMinimumSize(1200, 780)
        self.resize(1440, 900)
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - 1440) // 2
        y = (screen.height() - 900) // 2
        self.move(x, y)

    def _setup_webview(self):
        self.webview = QWebEngineView()
        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        page = QWebEnginePage(profile, self.webview)
        self.webview.setPage(page)
        url = QUrl(f"http://{FLASK_HOST}:{self.port}/")
        self.webview.setUrl(url)
        self.setCentralWidget(self.webview)

    def closeEvent(self, event):
        QApplication.quit()
        event.accept()


# --------------------------------------------------------------------------- #
#  启动画面（带进度条 + 动态状态文字）
# --------------------------------------------------------------------------- #
class SplashScreen(QSplashScreen):
    """自定义启动画面，带进度条和状态文字"""

    def __init__(self):
        W, H = 520, 300
        pixmap = QPixmap(W, H)
        pixmap.fill(Qt.GlobalColor.transparent)

        # 渐变背景
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0, QColor("#0f0f23"))
        grad.setColorAt(1, QColor("#1a1a3e"))
        painter.fillRect(0, 0, W, H, grad)

        # 顶部强调线
        painter.setPen(QColor("#7c83fd"))
        painter.drawLine(0, 0, W, 0)
        painter.end()

        super().__init__(pixmap, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(W, H)

        # 标题
        title = QLabel("SpaceLens", self)
        title.setGeometry(0, 60, W, 65)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(36)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #7c83fd; background: transparent;")

        # 副标题
        sub = QLabel("空间分析系统", self)
        sub.setGeometry(0, 132, W, 32)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f2 = QFont()
        f2.setPointSize(14)
        sub.setFont(f2)
        sub.setStyleSheet("color: #9090c0; background: transparent;")

        # 进度条
        self.progress = QProgressBar(self)
        self.progress.setGeometry(40, 210, W - 80, 8)
        self.progress.setRange(0, 100)
        self.progress.setValue(5)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                background: #2a2a4a;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c83fd, stop:1 #a78bfa);
                border-radius: 4px;
            }
        """)

        # 状态文字
        self.status_lbl = QLabel("正在启动...", self)
        self.status_lbl.setGeometry(0, 228, W, 28)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f3 = QFont()
        f3.setPointSize(10)
        self.status_lbl.setFont(f3)
        self.status_lbl.setStyleSheet("color: #5a5a8a; background: transparent;")

        # 版本号
        ver = QLabel("v1.0", self)
        ver.setGeometry(0, H - 26, W, 20)
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f4 = QFont()
        f4.setPointSize(9)
        ver.setFont(f4)
        ver.setStyleSheet("color: #3a3a6a; background: transparent;")

        self.show()
        QApplication.processEvents()

        # ── 流光动画（进度条上方的移动光点）──
        BAR_X, BAR_Y, BAR_W, BAR_H = 40, 210, W - 80, 8
        self._bar_x = BAR_X
        self._bar_w = BAR_W

        self._glow = QWidget(self)
        GLOW_D = 14
        self._glow.setFixedSize(GLOW_D, GLOW_D)
        self._glow.move(BAR_X - GLOW_D // 2, BAR_Y + BAR_H // 2 - GLOW_D // 2)
        self._glow.setStyleSheet("""
            background: radial-gradient(circle, #ffffff, #a78bfa);
            border-radius: 7px;
        """)
        # Qt widget 用 border-radius 实现圆形
        self._glow.setStyleSheet(
            "background-color: #c4b5fd;"
            "border-radius: 7px;"
        )
        self._glow_opacity = 1.0
        self._glow_dir = -0.08   # 透明度变化方向（呼吸效果）

        # ── 进度驱动（指数衰减平滑趋近）──
        self._progress_val = 5.0   # 浮点，累积小步长
        self._progress_target = 30.0
        self._decay = 0.06          # 衰减系数
        self._min_step = 0.08       # 最小步长（保底速度）
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)   # 50ms = 20fps，够流畅

    # ── 动画心跳 ──
    def _tick(self):
        # 进度条：指数衰减 + 保底最小步长
        # 步长 = max(diff * decay,  min_step)
        # decay 控制起步快慢，min_step 防止末段太慢
        diff = self._progress_target - self._progress_val
        if diff > 0.05:
            step = max(diff * self._decay, self._min_step)
            self._progress_val = min(self._progress_val + step, self._progress_target)
        self.progress.setValue(int(self._progress_val))

        # 2. 流光小圆点：跟随进度条前沿位置 + 呼吸透明度
        filled_w = int(self._bar_w * self._progress_val / 100)
        gx = self._bar_x + filled_w - self._glow.width() // 2
        gy = 210 + 4 - self._glow.height() // 2
        self._glow.move(gx, gy)

        # 呼吸效果
        self._glow_opacity += self._glow_dir
        if self._glow_opacity <= 0.3 or self._glow_opacity >= 1.0:
            self._glow_dir *= -1
        alpha = int(self._glow_opacity * 255)
        self._glow.setStyleSheet(
            f"background-color: rgba(196,181,253,{alpha});"
            "border-radius: 7px;"
        )

    def set_status(self, text: str, target_progress: float = None,
                   decay: float = None, min_step: float = None):
        self.status_lbl.setText(text)
        if target_progress is not None:
            self._progress_target = min(float(target_progress), 92.0)
        if decay is not None:
            self._decay = decay
        if min_step is not None:
            self._min_step = min_step
        # 不调用 processEvents，让 Qt 事件循环自然处理

    def finish_loading(self):
        """加载完成：快速冲到 100，用 QTimer 单次回调，不阻塞主线程"""
        self._decay = 0.10
        self._min_step = 0.30   # 尾段快速推进
        self._progress_target = 100.0
        # 不在这里 sleep，让 _tick 继续由 timer 驱动直到完成
        # 由 _on_flask_ready 调用，50ms 后 timer 会继续跑完剩余


# --------------------------------------------------------------------------- #
#  程序入口
# --------------------------------------------------------------------------- #
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("SpaceLens")
    app.setOrganizationName("SpaceLens")

    splash = SplashScreen()
    window_holder = {}

    # 共享状态字典（后台线程写，主线程 QTimer 轮询读）
    # 彻底避免后台线程直接 emit Qt signal，消除跨线程崩溃
    state = {'status': '正在准备...', 'stage': 0, 'error': None}
    port = _find_free_port()

    # 阶段 → (进度目标, 衰减系数, 最小步长/帧)
    # stage 4（热力图/字体缓存）是真正的瓶颈，分配 25→75% 的大区间
    # 其余子阶段（5/6/7）每步只占 ~5%，快速扫过与实际耗时匹配
    _STAGES = {
        0: (10,  0.10,  0.08),
        1: (15,  0.10,  0.08),   # 加载数学计算库
        2: (20,  0.08,  0.08),   # 加载数据分析库
        3: (25,  0.07,  0.08),   # 加载图形渲染库（matplotlib 基础）
        4: (89,  0.012, 0.18),   # 初始化热力图分析（字体缓存，最耗时，大区间慢爬）
        5: (92,  0.08,  0.12),   # 初始化轨迹分析（scipy）
        6: (97,  0.08,  0.12),   # 初始化聚类分析（sklearn）
        7: (98,  0.08,  0.12),   # 注册 API 路由
        8: (99,  0.08,  0.08),   # 启动服务
    }
    _last_stage = [-1]
    _flask_opened = [False]

    def _poll():
        stage = state['stage']
        if stage == -1:
            splash.set_status(f"⚠ {state.get('error', '加载失败')}")
            return
        if stage != _last_stage[0]:
            _last_stage[0] = stage
            target, decay, min_step = _STAGES.get(stage, (93, 0.08, 0.08))
            splash.set_status(state['status'], target, decay=decay, min_step=min_step)
        if not _flask_opened[0] and stage >= 8:
            try:
                with socket.create_connection((FLASK_HOST, port), timeout=0.05):
                    _flask_opened[0] = True
                    _poll_timer.stop()
                    splash.set_status("加载完成，正在打开界面...")
                    splash.finish_loading()
                    def _open_win():
                        splash.close()
                        win = SpaceLensWindow(port)
                        window_holder["win"] = win
                        win.show()
                    QTimer.singleShot(400, _open_win)
            except OSError:
                pass

    _poll_timer = QTimer()
    _poll_timer.timeout.connect(_poll)
    _poll_timer.start(100)

    flask_thread = threading.Thread(
        target=_run_flask, args=(port, state), daemon=True
    )
    flask_thread.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
