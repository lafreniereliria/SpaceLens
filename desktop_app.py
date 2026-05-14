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


def _run_flask(port: int, status_cb=None):
    """
    启动策略：
    - 后台线程预热重型库（与 splash 画面同时进行）
    - 重型库加载完毕后 Flask 才启动并绑定端口
    - _wait_for_flask() 检测到端口可用时，splash 关闭、主窗口打开
    - 整个过程用户看到的是进度条，不是白屏
    """
    import flask as _flask
    import threading as _threading

    # 分阶段加载，驱动进度条平滑推进
    if status_cb:
        status_cb("正在加载数学计算库...")
    try:
        import numpy  # noqa
    except Exception:
        pass

    if status_cb:
        status_cb("正在加载数据分析库...")
    try:
        import pandas  # noqa
    except Exception:
        pass

    if status_cb:
        status_cb("正在加载图形渲染库...")
    try:
        import matplotlib  # noqa
        matplotlib.use('Agg')
    except Exception:
        pass

    if status_cb:
        status_cb("正在注册分析模块...")
    try:
        from api.analysis import analysis_bp
    except Exception as e:
        if status_cb:
            status_cb(f"加载失败: {e}")
        return

    if status_cb:
        status_cb("正在启动服务...")

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
        # 能访问到这里说明 blueprint 已注册，直接返回 ready
        return _flask.jsonify({"ready": True, "error": None})

    flask_app.run(host=FLASK_HOST, port=port, debug=False, use_reloader=False)


def _wait_for_flask(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((FLASK_HOST, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# --------------------------------------------------------------------------- #
#  信号桥（跨线程通信）
# --------------------------------------------------------------------------- #
class _Signal(QObject):
    flask_ready = pyqtSignal(int)
    status_update = pyqtSignal(str)   # 进度文字更新


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
        self._pulse_mode = False    # True = 摆动模式（长耗时阶段）
        self._pulse_base = 0.0      # 摆动中心值
        self._pulse_phase = 0.0     # 摆动相位（0~2π）
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)   # 50ms = 20fps，够流畅

    def enter_pulse(self):
        """进入摆动模式：进度条在当前值附近小幅振荡，避免视觉卡死"""
        self._pulse_mode = True
        self._pulse_base = self._progress_val
        self._pulse_phase = 0.0

    def exit_pulse(self):
        """退出摆动模式，恢复正常趋近"""
        self._pulse_mode = False

    # ── 动画心跳 ──
    def _tick(self):
        import math
        # 1. 进度条
        if self._pulse_mode:
            # 摆动模式：在 base ± 2.5 之间用正弦波振荡
            self._pulse_phase += 0.12   # 每帧推进相位（~0.38Hz，约2.6s一周期）
            offset = 2.5 * math.sin(self._pulse_phase)
            display = self._pulse_base + offset
            self.progress.setValue(int(display))
        else:
            # 正常模式：指数衰减趋近 target
            diff = self._progress_target - self._progress_val
            if diff > 0.05:
                step = max(diff * 0.06, 0.12)
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

        QApplication.processEvents()

    def set_status(self, text: str, target_progress: float = None, pulse: bool = False):
        self.status_lbl.setText(text)
        if target_progress is not None:
            self._progress_target = min(float(target_progress), 92.0)
        if pulse:
            self.enter_pulse()
        else:
            self.exit_pulse()
        QApplication.processEvents()

    def finish_loading(self):
        """加载完成：退出摆动，从当前值平滑冲到 100"""
        self.exit_pulse()
        # 把浮点值同步到真实显示值（摆动期间 _progress_val 没在更新）
        self._progress_val = float(self.progress.value())
        self._progress_target = 100.0
        deadline = time.time() + 0.8
        while self._progress_val < 99.5 and time.time() < deadline:
            self._tick()
            time.sleep(0.03)
        self._timer.stop()
        self._glow.hide()
        self.progress.setValue(100)
        QApplication.processEvents()


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

    bridge = _Signal()
    window_holder = {}

    _STAGE_PROGRESS = {
        "正在加载数学计算库...": (35,  False),
        "正在加载数据分析库...": (55,  False),
        "正在加载图形渲染库...": (72,  False),
        "正在注册分析模块...":   (82,  True),   # 耗时最久，用摆动模式
        "正在启动服务...":       (93,  False),
    }

    def _on_status(text: str):
        """从 Flask 线程回调，更新启动画面状态和目标进度"""
        entry = _STAGE_PROGRESS.get(text)
        if entry:
            target, pulse = entry
            splash.set_status(text, target, pulse=pulse)
        else:
            splash.set_status(text)

    def _on_flask_ready(p: int):
        splash.set_status("加载完成，正在打开界面...", 98)
        splash.finish_loading()
        splash.close()
        win = SpaceLensWindow(p)
        window_holder["win"] = win
        win.show()

    bridge.flask_ready.connect(_on_flask_ready)
    bridge.status_update.connect(_on_status)

    # 在后台线程启动 Flask，通过 signal 回调更新 UI
    port = _find_free_port()

    def _status_cb(text: str):
        bridge.status_update.emit(text)

    flask_thread = threading.Thread(
        target=_run_flask, args=(port, _status_cb), daemon=True
    )
    flask_thread.start()

    def _checker():
        if _wait_for_flask(port, timeout=30.0):
            bridge.flask_ready.emit(port)
        else:
            splash.set_status("⚠ 服务启动超时，请重试")
            QTimer.singleShot(3000, app.quit)

    checker_thread = threading.Thread(target=_checker, daemon=True)
    checker_thread.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
