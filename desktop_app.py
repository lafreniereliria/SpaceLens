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
    QApplication, QMainWindow, QSplashScreen, QLabel, QProgressBar
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
    """在后台线程中启动 Flask，禁用 debug 和 reloader"""
    if status_cb:
        status_cb("正在加载数学计算库...")
    import flask as _flask
    import numpy  # noqa - 提前 import 让后续调用更快

    if status_cb:
        status_cb("正在加载数据分析库...")
    import pandas  # noqa

    if status_cb:
        status_cb("正在加载图形渲染库...")
    from api.analysis import analysis_bp  # 内部会 import matplotlib / sklearn

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

        # 进度条动画 timer（假进度，视觉反馈）
        self._progress_val = 5
        self._progress_target = 30
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick_progress)
        self._timer.start(80)

    def _tick_progress(self):
        if self._progress_val < self._progress_target:
            self._progress_val += 1
            self.progress.setValue(self._progress_val)
            QApplication.processEvents()

    def set_status(self, text: str, target_progress: int = None):
        self.status_lbl.setText(text)
        if target_progress is not None:
            self._progress_target = min(target_progress, 95)
        QApplication.processEvents()

    def finish_loading(self):
        self._timer.stop()
        # 快速填满进度条
        for v in range(self._progress_val, 101, 3):
            self.progress.setValue(v)
            QApplication.processEvents()
            time.sleep(0.01)


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

    def _on_status(text: str):
        """从 Flask 线程回调，更新启动画面状态"""
        # 根据状态文字推断进度
        progress_map = {
            "正在加载数学计算库...": 25,
            "正在加载数据分析库...": 50,
            "正在加载图形渲染库...": 75,
            "正在启动服务...": 88,
        }
        target = progress_map.get(text, None)
        splash.set_status(text, target)

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
