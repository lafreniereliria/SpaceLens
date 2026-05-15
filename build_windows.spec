# -*- mode: python ; coding: utf-8 -*-
#
# SpaceLens Windows 桌面程序打包配置
# 用法（在 Windows 上执行）：
#   pip install pyinstaller PyQt6 PyQt6-WebEngine
#   pyinstaller build_windows.spec
#
# 输出：dist/SpaceLens/SpaceLens.exe（onedir 模式，启动更快）
#

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# --------------------------------------------------------------------------- #
#  收集 PyQt6-WebEngine 所需的资源文件（QtWebEngine 依赖很多二进制资源）
# --------------------------------------------------------------------------- #
qt_webengine_datas = collect_data_files('PyQt6.QtWebEngineCore', includes=['**'])
qt_webengine_datas += collect_data_files('PyQt6', includes=['Qt6/resources/**', 'Qt6/translations/**'])

# --------------------------------------------------------------------------- #
#  Analysis（依赖分析）
# --------------------------------------------------------------------------- #
a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Flask 模板和静态资源
        ('templates', 'templates'),
        ('static',    'static'),
        # 额外数据（可选，如演示数据）
        # ('demo_loc_data.csv', '.'),
    ] + qt_webengine_datas,
    hiddenimports=[
        # Flask / Werkzeug 动态导入
        'flask',
        'werkzeug',
        'werkzeug.routing',
        'werkzeug.middleware.proxy_fix',
        'jinja2',
        'jinja2.ext',
        # 科学计算库
        'numpy',
        'pandas',
        'pandas._libs.tslibs.timedeltas',
        'pandas._libs.tslibs.np_datetime',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.hashtable',
        'scipy',
        'scipy.ndimage',
        'scipy.interpolate',
        'scipy.cluster',
        'scipy.cluster.vq',
        'scipy.spatial.transform._rotation_groups',
        # matplotlib
        'matplotlib',
        'matplotlib.backends.backend_agg',
        'PIL',
        'openpyxl',
        # api 模块
        'api',
        'api.analysis',
    ] + collect_submodules('scipy.cluster'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'test', '_test',
        'xmlrunner', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SpaceLens',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # 不显示黑色命令行窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',       # 取消注释并提供 .ico 文件可设置程序图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SpaceLens',
)
