# -*- mode: python ; coding: utf-8 -*-
#
# SpaceLens macOS 桌面程序打包配置
# 用法（在此项目目录下执行）：
#   source .venv311/bin/activate
#   pyinstaller build_macos.spec
#
# 输出：dist/SpaceLens.app（macOS App Bundle）
#       dist/SpaceLens/SpaceLens（可执行文件）
#

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 收集 PyQt6-WebEngine 所需资源
qt_webengine_datas = collect_data_files('PyQt6.QtWebEngineCore', includes=['**'])
qt_webengine_datas += collect_data_files('PyQt6', includes=['Qt6/resources/**', 'Qt6/translations/**'])

a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # macOS 路径分隔符用冒号
        ('templates', 'templates'),
        ('static',    'static'),
    ] + qt_webengine_datas,
    hiddenimports=[
        'flask',
        'werkzeug',
        'werkzeug.routing',
        'jinja2',
        'jinja2.ext',
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
        'matplotlib',
        'matplotlib.backends.backend_agg',
        'PIL',
        'openpyxl',
        'api',
        'api.analysis',
    ] + collect_submodules('scipy.cluster'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_test', 'pytest'],
    noarchive=False,
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
    upx=False,          # macOS 上 upx 常有兼容问题，关闭
    console=False,      # 不显示终端窗口
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='SpaceLens',
)

# macOS App Bundle
app = BUNDLE(
    coll,
    name='SpaceLens.app',
    bundle_identifier='com.spacelens.app',
    info_plist={
        'CFBundleDisplayName': 'SpaceLens',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
    },
)
