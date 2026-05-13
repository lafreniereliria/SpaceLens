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
#  打包后资源文件在 sys._MEIPASS 下，需要将其加入 sys.path 以便 import app / api
# --------------------------------------------------------------------------- #
if getattr(sys, 'frozen', False):
    # 打包后运行：资源根目录
    _BASE_DIR = sys._MEIPASS
else:
    # 开发模式：脚本所在目录
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 确保 app.py / api/ 能被找到
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from PyQt6.QtWidgets import QApplication, QMainWindow, QSplashScreen, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PyQt6.QtCore import QUrl, Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QPixmap, QColor, QFont

# --------------------------------------------------------------------------- #
#  Flask 服务配置
# --------------------------------------------------------------------------- #
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 18080   # 用非常用端口，避免冲突


def _find_free_port() -> int:
    """如果默认端口被占用，自动找一个可用端口"""
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


def _run_flask(port: int):
    """在后台线程中启动 Flask，禁用 debug 和 reloader"""
    import flask as _flask
    from api.analysis import analysis_bp

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


def _wait_for_flask(port: int, timeout: float = 10.0) -> bool:
    """轮询等待 Flask 就绪"""
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
    flask_ready = pyqtSignal(int)   # 携带端口号


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
        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - 1440) // 2
        y = (screen.height() - 900) // 2
        self.move(x, y)
        # 可选：设置任务栏图标（如果有 icon.ico 放在同目录）
        # self.setWindowIcon(QIcon("icon.ico"))

    def _setup_webview(self):
        self.webview = QWebEngineView()

        # 允许本地文件访问（上传 CSV 等需要）
        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)

        page = QWebEnginePage(profile, self.webview)
        self.webview.setPage(page)

        url = QUrl(f"http://{FLASK_HOST}:{self.port}/")
        self.webview.setUrl(url)
        self.setCentralWidget(self.webview)

    def closeEvent(self, event):
        # 关闭窗口时直接退出整个进程（包括后台 Flask 线程）
        QApplication.quit()
        event.accept()


# --------------------------------------------------------------------------- #
#  启动画面
# --------------------------------------------------------------------------- #
def _make_splash() -> QSplashScreen:
    """创建简洁的启动画面"""
    pixmap = QPixmap(480, 280)
    pixmap.fill(QColor("#1a1a2e"))

    splash = QSplashScreen(pixmap, Qt.WindowType.WindowStaysOnTopHint)

    # 标题
    title = QLabel("SpaceLens", splash)
    title.setGeometry(0, 80, 480, 60)
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    font = QFont("Arial", 32, QFont.Weight.Bold)
    title.setFont(font)
    title.setStyleSheet("color: #7c83fd; background: transparent;")

    # 副标题
    sub = QLabel("空间分析系统", splash)
    sub.setGeometry(0, 150, 480, 36)
    sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sub.setFont(QFont("Arial", 14))
    sub.setStyleSheet("color: #a0a0c0; background: transparent;")

    # 加载提示
    hint = QLabel("正在初始化，请稍候...", splash)
    hint.setGeometry(0, 230, 480, 30)
    hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hint.setFont(QFont("Arial", 10))
    hint.setStyleSheet("color: #606080; background: transparent;")

    splash.show()
    QApplication.processEvents()
    return splash


# --------------------------------------------------------------------------- #
#  程序入口
# --------------------------------------------------------------------------- #
def main():
    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("SpaceLens")
    app.setOrganizationName("SpaceLens")

    # 启动画面
    splash = _make_splash()

    # 在后台线程启动 Flask
    port = _find_free_port()
    flask_thread = threading.Thread(target=_run_flask, args=(port,), daemon=True)
    flask_thread.start()

    # 等待 Flask 就绪（最多 15 秒）
    bridge = _Signal()
    window_holder = {}

    def _on_flask_ready(p: int):
        splash.close()
        win = SpaceLensWindow(p)
        window_holder["win"] = win
        win.show()

    bridge.flask_ready.connect(_on_flask_ready)

    def _checker():
        if _wait_for_flask(port, timeout=15.0):
            bridge.flask_ready.emit(port)
        else:
            # 超时：显示错误并退出
            splash.showMessage(
                "⚠ 服务启动超时，请检查依赖是否完整安装",
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                QColor("#ff6b6b"),
            )
            QTimer.singleShot(3000, app.quit)

    checker_thread = threading.Thread(target=_checker, daemon=True)
    checker_thread.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
