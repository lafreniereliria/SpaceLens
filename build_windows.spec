# -*- mode: python ; coding: utf-8 -*-
#
# SpaceLens Windows desktop app packaging config
# Usage (run on Windows):
#   pip install pyinstaller PyQt6 PyQt6-WebEngine
#   pyinstaller build_windows.spec
#
# Output: dist/SpaceLens/SpaceLens.exe  (onedir mode, faster startup)
#

import sys
import os
import glob
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# --------------------------------------------------------------------------- #
#  Locate and bundle python3.11.dll so the package runs on machines
#  that have no Python installation at all.
#
#  Search order:
#    1. Same directory as the Python executable (typical for venv / Actions)
#    2. Windows\System32
#    3. Any path in PATH that contains python*.dll
# --------------------------------------------------------------------------- #
def _find_python_dll():
    dll_name = f'python3{sys.version_info.minor}.dll'      # e.g. python311.dll
    # Also handle the "python3.11.dll" variant (older naming)
    alt_dll   = f'python{sys.version_info.major}.{sys.version_info.minor}.dll'

    candidates = []
    # 1. Next to python.exe
    py_dir = os.path.dirname(sys.executable)
    candidates += glob.glob(os.path.join(py_dir, dll_name))
    candidates += glob.glob(os.path.join(py_dir, alt_dll))
    # 2. Windows\System32 / SysWOW64
    win_sys = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'System32')
    candidates += glob.glob(os.path.join(win_sys, dll_name))
    candidates += glob.glob(os.path.join(win_sys, alt_dll))
    # 3. Every directory on PATH
    for p in os.environ.get('PATH', '').split(os.pathsep):
        candidates += glob.glob(os.path.join(p, dll_name))
        candidates += glob.glob(os.path.join(p, alt_dll))

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


extra_binaries = []

py_dll = _find_python_dll()
if py_dll:
    extra_binaries.append((py_dll, '.'))
    print(f'[spec] Bundling Python DLL: {py_dll}')
else:
    print('[spec] WARNING: python3.11.dll not found — build may not run on clean machines')

# Also bundle vcruntime / MSVCP if they live next to the Python executable
# (GitHub Actions runners have them there after "setup-python")
py_dir = os.path.dirname(sys.executable)
for pat in ('vcruntime140*.dll', 'msvcp140*.dll', 'api-ms-win-crt*.dll'):
    for f in glob.glob(os.path.join(py_dir, pat)):
        extra_binaries.append((f, '.'))
        print(f'[spec] Bundling VC runtime: {f}')

# --------------------------------------------------------------------------- #
#  Collect PyQt6-WebEngine data files (Qt resources, translations, etc.)
# --------------------------------------------------------------------------- #
qt_webengine_datas = collect_data_files('PyQt6.QtWebEngineCore', includes=['**'])
qt_webengine_datas += collect_data_files('PyQt6', includes=['Qt6/resources/**', 'Qt6/translations/**'])

# --------------------------------------------------------------------------- #
#  Analysis
# --------------------------------------------------------------------------- #
a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=extra_binaries,
    datas=[
        # Flask templates and static assets
        ('templates', 'templates'),
        ('static',    'static'),
    ] + qt_webengine_datas,
    hiddenimports=[
        # Flask / Werkzeug dynamic imports
        'flask',
        'werkzeug',
        'werkzeug.routing',
        'werkzeug.middleware.proxy_fix',
        'jinja2',
        'jinja2.ext',
        # Scientific libraries
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
        # api module
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
    console=False,           # no black console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',       # uncomment and supply .ico for a custom icon
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
