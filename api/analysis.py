"""
空间分析后端 API
三个核心功能：到访频次热力图、人员轨迹、空间聚类
"""

import io
import json
import base64
import re
import numpy as np
import pandas as pd
from flask import Blueprint, request, jsonify
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.font_manager as _fm

# ── 桌面端原生文件对话框钩子 ──────────────────────────────
# desktop_app.py 启动时会注册此钩子，使 Flask 线程可安全触发 Qt 对话框
# 签名: (title, default_filename) -> str | None
_native_save_dialog_hook = None

def register_save_dialog_hook(fn):
    """由 desktop_app.py 调用，注册 Qt 原生保存对话框回调"""
    global _native_save_dialog_hook
    _native_save_dialog_hook = fn

# ── 桌面端文件选择路径钩子 ────────────────────────────────
# Qt 的 chooseFiles() 覆写后将 {basename -> abs_path} 存入此 dict
# Flask 线程读取时加锁，避免竞争（写入频率极低，读多写少）
import threading as _file_paths_lock_mod
_file_paths_lock = _file_paths_lock_mod.Lock()
_file_abs_paths: dict = {}   # {filename_basename: absolute_path}

def _register_chosen_paths(paths):
    # type: (list) -> None
    """由 desktop_app.py 的 chooseFiles() 调用，注册本次文件选择的绝对路径。"""
    import os as _os
    with _file_paths_lock:
        for p in paths:
            if not p:
                continue
            # 文件名 basename → 绝对路径
            _file_abs_paths[_os.path.basename(p)] = p
            # 如果 p 本身是目录，也用目录名注册（供文件夹选择模式使用）
            if _os.path.isdir(p):
                _file_abs_paths[_os.path.basename(_os.path.normpath(p))] = p

def _resolve_abs_path(basename_or_rel):
    # type: (str) -> str
    """
    将上传时的文件名（或 webkitRelativePath 末段）解析为绝对路径。
    优先从 Qt 注入的路径表中查找，找不到返回 None。
    """
    import os as _os
    # 统一用 os.path.basename 处理（兼容 Windows 反斜杠）
    fname = _os.path.basename(_os.path.normpath(basename_or_rel))
    with _file_paths_lock:
        return _file_abs_paths.get(fname)
# ──────────────────────────────────────────────────────────

# matplotlib 3.9+ 移除了 cm.get_cmap()，统一用此兼容函数
def _get_cmap(name, n=None):
    """兼容 matplotlib 3.7+ 的 colormap 获取方式"""
    try:
        cmap = matplotlib.colormaps[name]
    except AttributeError:
        # matplotlib < 3.5 fallback
        cmap = _get_cmap(name)
    if n is not None:
        cmap = cmap.resampled(n)
    return cmap

def _trajectory_line_width(track_count):
    """Scale trajectory stroke width down as more user paths are drawn."""
    n = max(int(track_count or 1), 1)
    return max(0.65, min(2.2, 4.8 / np.sqrt(n)))

# ─── 主题配色 ───
def _theme(t='dark'):
    if t == 'light':
        return dict(
            fig_bg='#f7f8fc', ax_bg='#ffffff', ax_bg2='#f0f2f8',
            spine='#d4d8ea', tick='#5a5f7a', text='#1a1d2e',
            subtext='#5a5f7a', legend_bg='#f7f8fc', legend_edge='#d4d8ea',
            grid='#e4e7f2', bar_label='#444', cbar_tick='#5a5f7a',
            bar_edge='#ffffff', accent='#6244e5',
        )
    return dict(
        fig_bg='#0f1117', ax_bg='#0f1117', ax_bg2='#161b27',
        spine='#2d2d3d', tick='#8b8fa8', text='#e0e0e0',
        subtext='#8b8fa8', legend_bg='#1a1f2e', legend_edge='#2d2d3d',
        grid='#2d2d3d', bar_label='#c0c0d0', cbar_tick='#8b8fa8',
        bar_edge='#0f1117', accent='#7c5cfc',
    )

# ─── 中文字体自动选取 ───
def _pick_cjk_font():
    available = {f.name for f in _fm.fontManager.ttflist}
    for name in ('Hiragino Sans GB', 'PingFang SC', 'STHeiti', 'Heiti TC',
                 'Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'Arial Unicode MS'):
        if name in available:
            return name
    return None

_CJK_FONT = _pick_cjk_font()
if _CJK_FONT:
    matplotlib.rcParams['font.family'] = 'sans-serif'
    matplotlib.rcParams['font.sans-serif'] = [_CJK_FONT] + matplotlib.rcParams['font.sans-serif']
    matplotlib.rcParams['axes.unicode_minus'] = False
from matplotlib.patches import FancyArrowPatch
from scipy.cluster.vq import kmeans2 as _kmeans2
from scipy.ndimage import gaussian_filter, binary_erosion, binary_dilation
from scipy.interpolate import RBFInterpolator
from PIL import Image

analysis_bp = Blueprint('analysis', __name__)

SCALE = 18.06  # px / meter
USAGE_SECONDS_PER_RECORD = 10  # 使用时长：每条定位记录代表该人员在该坐标停留 10 秒


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def fig_to_base64(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _make_fig(th, ncols=2, w=14, h=6):
    """Create themed figure with ncols subplots."""
    fig, axes = plt.subplots(1, ncols, figsize=(w, h))
    fig.patch.set_facecolor(th['fig_bg'])
    return fig, axes

def dark_fig(w=9, h=7):
    th = _theme('dark')
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(th['fig_bg'])
    ax.set_facecolor(th['ax_bg'])
    for spine in ax.spines.values():
        spine.set_edgecolor(th['spine'])
    ax.tick_params(colors=th['tick'], labelsize=9)
    ax.xaxis.label.set_color(th['subtext'])
    ax.yaxis.label.set_color(th['subtext'])
    ax.title.set_color(th['text'])
    return fig, ax


def load_df(file_storage):
    fname = file_storage.filename.lower()
    if fname.endswith('.csv'):
        df = pd.read_csv(file_storage)
    else:
        df = pd.read_excel(file_storage)

    # 对已知数值列做容错转换：'/'、空字符串等占位符 → NaN，再强制转为数值类型
    _numeric_cols = {'X', 'Y', 't', 'BehaviorNum', 'Satisfaction', 'UserNum', 'ParameterNum', 'Value', 'Region'}
    for col in _numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def load_img(file_storage):
    """加载平面图，正确处理 PNG 透明通道（合并到白色背景）"""
    pil_img = Image.open(file_storage)
    if pil_img.mode == 'RGBA':
        bg = Image.new('RGB', pil_img.size, (255, 255, 255))
        bg.paste(pil_img, mask=pil_img.split()[3])   # 用 alpha 通道作为 mask
        return np.array(bg)
    if pil_img.mode == 'LA':
        bg = Image.new('RGB', pil_img.size, (255, 255, 255))
        bg.paste(pil_img.convert('RGBA'), mask=pil_img.split()[1])
        return np.array(bg)
    if pil_img.mode == 'P':
        pil_img = pil_img.convert('RGBA')
        bg = Image.new('RGB', pil_img.size, (255, 255, 255))
        bg.paste(pil_img, mask=pil_img.split()[3])
        return np.array(bg)
    return np.array(pil_img.convert('RGB'))


def extract_walkable_mask(img_arr: np.ndarray,
                          black_threshold: int = 60,
                          erode_iters: int = 0,
                          dilate_wall_iters: int = 2) -> np.ndarray:
    """
    从平面图中提取可行走区域 mask（True = 可通行，False = 墙/障碍物）。

    算法：
    1. 将 RGB 转为灰度
    2. 亮度 < black_threshold 的像素视为黑色墙体 → mask = False
    3. 形态学膨胀墙体 dilate_wall_iters 次，让墙体向外扩一圈缓冲区，
       避免热力色紧贴墙边渗漏
    4. 若结果 mask 全为 False（纯黑图/特殊图），降级为全 True（不过滤）

    参数：
        black_threshold   灰度阈值，低于此值视为黑色墙体（0-255，默认 60）
        erode_iters       对可走区域做形态学腐蚀次数，去除孤立小白点（默认 0）
        dilate_wall_iters 墙体向外膨胀的次数（默认 2px 缓冲区）

    返回：bool 数组，shape (H, W)
    """
    # 灰度化
    gray = np.dot(img_arr[..., :3], [0.299, 0.587, 0.114]).astype(np.uint8)
    walkable = gray >= black_threshold          # True = 可走，False = 墙

    # 对墙体区域做膨胀，给墙边缘留缓冲
    if dilate_wall_iters > 0:
        wall = ~walkable
        wall_dilated = binary_dilation(wall, iterations=dilate_wall_iters)
        walkable = ~wall_dilated

    # 对可走区域做腐蚀，去除孤立噪点
    if erode_iters > 0:
        walkable = binary_erosion(walkable, iterations=erode_iters)

    # 降级保护：若 mask 几乎全为 False，说明平面图背景很暗，不做过滤
    if walkable.sum() < walkable.size * 0.05:
        return np.ones(img_arr.shape[:2], dtype=bool)

    return walkable


def extract_measurement_mask(img_arr: np.ndarray,
                             black_threshold: int = 20,
                             erode_iters: int = 0,
                             dilate_black_iters: int = 0) -> np.ndarray:
    """从专门的背景遮罩图中提取“允许上色区域”。

    约定：背景图中的黑色区域表示没有测量数据，不应涂色；
    非黑区域表示允许绘制正式热力图。
    返回 True = 允许上色，False = 不上色。
    """
    gray = np.dot(img_arr[..., :3], [0.299, 0.587, 0.114]).astype(np.uint8)
    allowed = gray > black_threshold

    if dilate_black_iters > 0:
        black = ~allowed
        black = binary_dilation(black, iterations=dilate_black_iters)
        allowed = ~black

    if erode_iters > 0:
        allowed = binary_erosion(allowed, iterations=erode_iters)

    if allowed.sum() < allowed.size * 0.05:
        return np.ones(img_arr.shape[:2], dtype=bool)
    return allowed


def merge_masks(*masks):
    """合并多个 bool mask，None 会被忽略。"""
    valid = [m.astype(bool) for m in masks if m is not None]
    if not valid:
        return None
    out = valid[0].copy()
    for m in valid[1:]:
        if m.shape == out.shape:
            out &= m
    return out


def filter_points_in_mask(x: np.ndarray, y: np.ndarray,
                          mask: np.ndarray,
                          return_mask: bool = False):
    """
    过滤掉落在不可走区域（mask=False）的数据点。

    参数：
        x, y         像素坐标数组（float）
        mask         walkable_mask，shape (H, W)
        return_mask  若 True，额外返回布尔索引 valid_idx

    返回：(x_valid, y_valid) 或 (x_valid, y_valid, valid_bool)
    """
    h, w = mask.shape
    xi = np.clip(np.round(x).astype(int), 0, w - 1)
    yi = np.clip(np.round(y).astype(int), 0, h - 1)
    valid = mask[yi, xi]
    if return_mask:
        return x[valid], y[valid], valid
    return x[valid], y[valid]


def summarize_frequency_grid(density: np.ndarray) -> dict:
    """基于热力图原始平滑密度值生成到访频次摘要。"""
    peak = float(np.nanmax(density)) if density.size else 0.0
    if not np.isfinite(peak) or peak <= 0:
        return {
            'peak_frequency': 0,
            'min_frequency': 0,
            'avg_frequency': 0,
            'covered_area_pct': 0,
        }

    active = density[np.isfinite(density) & (density > peak * 0.05)]
    if active.size == 0:
        active = density[np.isfinite(density) & (density > 0)]
    if active.size == 0:
        active = np.array([0.0])

    def _fmt(v):
        v = float(v)
        return round(v, 2) if v < 10 else int(round(v))

    return {
        'peak_frequency': _fmt(peak),
        'min_frequency': _fmt(float(np.nanmin(active))),
        'avg_frequency': _fmt(float(np.nanmean(active))),
        'covered_area_pct': round(float(active.size) / float(density.size) * 100, 1),
    }


def prepare_visit_frequency_values(df: pd.DataFrame):
    """生成到访频次热力图使用的实际频次值和统计摘要。

    优先按 Region 统计实际到访记录数；若没有 Region，则退化为按像素坐标统计重复点位。
    返回：(x, y, frequency_values_per_point, summary_stats)
    """
    if 'Region' in df.columns:
        counts = df.groupby('Region').size()
        freq_values = df['Region'].map(counts).astype(float).values
        stat_values = counts.astype(float).values
        stats_scope = 'region'
    else:
        rounded_xy = list(zip(
            np.round(df['X'].astype(float)).astype(int),
            np.round(df['Y'].astype(float)).astype(int),
        ))
        counts = pd.Series(rounded_xy).value_counts()
        freq_values = np.array([counts[p] for p in rounded_xy], dtype=float)
        stat_values = counts.astype(float).values
        stats_scope = 'point'

    def _fmt(v):
        v = float(v)
        return round(v, 2) if not float(v).is_integer() else int(v)

    stats = {
        'frequency_scope': stats_scope,
        'peak_frequency': _fmt(np.max(stat_values)) if len(stat_values) else 0,
        'min_frequency': _fmt(np.min(stat_values)) if len(stat_values) else 0,
        'avg_frequency': round(float(np.mean(stat_values)), 2) if len(stat_values) else 0,
    }
    if 'Region' in df.columns:
        field_df = df.assign(_freq=freq_values).groupby('Region', as_index=False).agg({
            'X': 'mean',
            'Y': 'mean',
            '_freq': 'first',
        })
        return (
            field_df['X'].astype(float).values,
            field_df['Y'].astype(float).values,
            field_df['_freq'].astype(float).values,
            stats,
        )
    return (
        df['X'].astype(float).values,
        df['Y'].astype(float).values,
        freq_values,
        stats,
    )


def make_visit_frequency_overlay(img, df, walkable_mask=None, coverage_mask=None):
    """按实际到访频次生成热力图叠加层。

    统计口径优先使用 Region 实际记录数；渲染口径始终使用真实定位点的
    局部频次，避免把区域总数压到区域均值点后产生虚假热点。
    """
    _, _, _, freq_stats = prepare_visit_frequency_values(df)
    x = df['X'].astype(float).values
    y = df['Y'].astype(float).values
    overlay, field = _make_heatmap_overlay(
        img,
        x,
        y,
        alpha=0.70,
        cmap='plasma',
        walkable_mask=walkable_mask,
        coverage_mask=coverage_mask,
        norm_percentile=None,
        scale_to_kernel_area=True,
    )
    vmax = float(np.nanmax(field)) if field is not None and np.isfinite(np.nanmax(field)) else 1.0

    return overlay, field, 0.0, max(vmax, 1.0), freq_stats


# ─────────────────────────────────────────────
# 功能 1：到访频次热力图
# ─────────────────────────────────────────────

@analysis_bp.route('/heatmap', methods=['POST'])
def heatmap():
    try:
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        required = {'X', 'Y'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'定位数据缺少列: {required - set(df.columns)}'}), 400

        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        region_name_map = _parse_region_name_map(request.form.get('region_name_map', ''))

        img = load_img(img_file)

        # 提取可行走区域 mask，屏蔽黑色墙体
        walkable = extract_walkable_mask(img)
        coverage_mask = None
        bgmask_file = request.files.get('background_img')
        if bgmask_file is not None:
            try:
                coverage_mask = extract_measurement_mask(load_img(bgmask_file))
            except Exception:
                coverage_mask = None

        # 按实际到访频次绘制：有 Region 时使用区域总到访次数，而非归一化密度值
        overlay, freq_field, vmin, vmax, freq_stats = make_visit_frequency_overlay(
            img, df, walkable_mask=walkable, coverage_mask=coverage_mask
        )

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('到访频次热力图', color=th['text'], fontsize=13, pad=10)

        sm = plt.cm.ScalarMappable(cmap='plasma', norm=mcolors.Normalize(vmin, vmax if vmax > vmin else vmin + 1.0))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('到访频次', color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)

        if 'Region' in df.columns:
            region_cnt = df.groupby('Region').size().reset_index(name='count')
            _bar_common(ax1, _region_labels(region_cnt['Region'], region_name_map), region_cnt['count'],
                        color=th['accent'], xlabel='空间单元', ylabel='到访人次', th=th)
            ax1.set_title('各空间单元到访频次', color=th['text'], fontsize=13)
        else:
            ax1.text(0.5, 0.5, '无区域数据\n(需要 Region 列)',
                     ha='center', va='center', color=th['subtext'], fontsize=11,
                     transform=ax1.transAxes)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'unique_users': int(df['UserID'].nunique()) if 'UserID' in df.columns else '-',
            **freq_stats,
        }
        return jsonify({'image': img_b64, 'summary': summary})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# 内存会话缓存
# ─────────────────────────────────────────────
import uuid, time as _time, threading as _threading
from werkzeug.datastructures import FileStorage
from io import BytesIO

_sessions: dict = {}          # sid → {'results': {...}, 'ts': float, 'type': str}
_sess_lock = _threading.Lock()
_SESSION_TTL = 3600           # 1 小时 TTL

_INPUT_SLOTS = {
    'img':      ('_raw_img_b', '_img_n', 'layout_img_path'),
    'loc':      ('_loc_b', '_loc_n', 'loc_data_path'),
    'beh':      ('_beh_b', '_beh_n', 'behavior_data_path'),
    'env':      ('_env_b', '_env_n', 'env_data_path'),
    'ques1':    ('_ques1_b', '_ques1_n', 'ques_data_overall_path'),
    'ques2':    ('_ques2_b', '_ques2_n', 'ques_data_region_path'),
    'ques3':    ('_ques3_b', '_ques3_n', 'ques_data_design_path'),
    'region':   ('_region_b', '_region_n', 'region_data_path'),
    'bgmask':   ('_bgmask_b', '_bgmask_n', 'background_img_path'),
}

_METRICS_BY_INPUT_SLOT = {
    'img': {'heatmap', 'usetime', 'speed', 'duration', 'cluster', 'density',
            'openness', 'difference', 'trajectory', 'behavior_count', 'behavior_duration',
            'environment_p1', 'environment_p2', 'environment_p3', 'environment_p4', 'environment_p5'},
    'loc': {'heatmap', 'usetime', 'speed', 'duration', 'cluster', 'density',
            'openness', 'topology', 'difference', 'trajectory'},
    'beh': {'behavior_count', 'behavior_duration', 'behavior_rate', 'behavior_entropy', 'utilization'},
    'env': {'environment_p1', 'environment_p2', 'environment_p3', 'environment_p4', 'environment_p5'},
    'ques1': {'satisfaction'},
    'ques2': {'satisfaction_region'},
    'ques3': {'satisfaction_design'},
    'region': {'openness', 'utilization'},
    'bgmask': {'heatmap', 'usetime', 'speed', 'duration', 'density', 'openness', 'behavior_duration'},
}

def _prune_sessions():
    """清理超时会话（每次写入前调用）"""
    now = _time.time()
    expired = [k for k, v in _sessions.items() if now - v['ts'] > _SESSION_TTL]
    for k in expired:
        del _sessions[k]


def _clone_file(fs: FileStorage):
    """将 FileStorage 读入 BytesIO，支持多次重用"""
    data = fs.read()
    fs.seek(0)
    return data


def _read_source_path(path):
    """Read a previously selected local source file when the user keeps it during recompute."""
    if not path:
        return None
    try:
        import os as _os
        candidates = [path]
        if not _os.path.isabs(path):
            candidates.append(_os.path.join(_BASE_DIR if '_BASE_DIR' in globals() else _os.getcwd(), path))
            candidates.append(_os.path.join(_os.getcwd(), path))
        real_path = next((p for p in candidates if p and _os.path.isfile(p)), None)
        if not real_path:
            return None
        with open(real_path, 'rb') as f:
            return f.read()
    except Exception:
        return None


def _safe_input_filename(slot, filename):
    name = filename or f'{slot}.bin'
    name = str(name).replace('\\', '/').split('/')[-1]
    name = re.sub(r'[^A-Za-z0-9._\-\u4e00-\u9fff]+', '_', name).strip('._')
    return f'{slot}__{name or "input.bin"}'


def _metrics_for_changed_slots(changed_slots):
    metrics = set()
    for slot in changed_slots or []:
        metrics.update(_METRICS_BY_INPUT_SLOT.get(slot, set()))
    return metrics


def _parse_json_list(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _make_fs(data: bytes, filename: str) -> FileStorage:
    """从 bytes 重建 FileStorage"""
    return FileStorage(stream=BytesIO(data), filename=filename)


def _parse_region_name_map(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            return {}
        out = {}
        for k, v in data.items():
            key = str(k).strip()
            val = str(v).strip() if v is not None else ''
            if key and val:
                out[key] = val
        return out
    except Exception:
        return {}


def _region_key(region_id):
    try:
        f = float(region_id)
        if f.is_integer():
            return str(int(f))
    except Exception:
        pass
    return str(region_id)


def _region_label(region_id, region_name_map=None, prefix='区域 '):
    key = _region_key(region_id)
    if region_name_map and key in region_name_map:
        return region_name_map[key]
    return f'{prefix}{key}'


def _region_labels(region_ids, region_name_map=None, prefix='区域 '):
    return [_region_label(r, region_name_map, prefix=prefix) for r in region_ids]


def _default_collection_date():
    return _time.strftime('%Y-%m-%d', _time.localtime())


def _compute_cluster_result(loc_fs, img_fs, k, th, normalize_xy_fn=None, walkable_mask=None):
    """公共聚类计算逻辑，供 run_all 与 session 内重算复用。"""
    if loc_fs is None or img_fs is None:
        return None

    df = load_df(loc_fs)
    if not {'X', 'Y'}.issubset(df.columns):
        return None
    if normalize_xy_fn is not None:
        df = normalize_xy_fn(df)

    img = load_img(img_fs)

    x = df['X'].astype(float).values
    y = df['Y'].astype(float).values

    if walkable_mask is None:
        try:
            walkable_mask = extract_walkable_mask(img)
        except Exception:
            walkable_mask = None

    if walkable_mask is not None:
        x, y = filter_points_in_mask(x, y, walkable_mask)

    if len(x) < 2 or len(y) < 2:
        return None

    data_xy = np.column_stack([x, y])
    k = max(2, min(int(k), len(data_xy) - 1))

    centers, labels = _kmeans2(
        data_xy.astype(float), k,
        iter=10, minit='points', missing='warn', seed=42
    )
    inertia = float(sum(
        ((data_xy[labels == i] - c) ** 2).sum()
        for i, c in enumerate(centers)
    ))

    palette = _get_cmap('tab10', k)
    fig0 = plt.figure(figsize=(9, 6))
    fig0.patch.set_facecolor(th['fig_bg'])
    ax0 = fig0.add_subplot(111)

    ax0.set_facecolor('white')
    ax0.imshow(img, alpha=0.35)
    ax0.axis('off')
    for ci in range(k):
        mask = labels == ci
        ax0.scatter(x[mask], y[mask], s=12, color=palette(ci),
                    alpha=0.7, label=f'簇 {ci+1}')
    ax0.scatter(centers[:, 0], centers[:, 1], s=160, c='white',
                marker='*', zorder=10, edgecolors='#ffcc00', linewidths=1)
    for i, (cx, cy) in enumerate(centers):
        ax0.annotate(f'C{i+1}', (cx, cy),
                     xytext=(6, 6), textcoords='offset points',
                     color='#ffcc00', fontsize=9, fontweight='bold')
    ax0.set_title(f'空间聚类分析 (k={k})', color=th['text'], fontsize=13, pad=10)
    ax0.legend(loc='upper right', fontsize=8, ncol=2,
               facecolor=th['legend_bg'], edgecolor=th['legend_edge'], labelcolor=th['tick'])
    plt.tight_layout(pad=2)
    img_b64 = fig_to_base64(fig0)
    plt.close(fig0)

    fig1 = plt.figure(figsize=(9, 6))
    fig1.patch.set_facecolor(th['fig_bg'])
    ax1 = fig1.add_subplot(111)
    _styled_axes(ax1, th)
    cluster_sizes = [int(np.sum(labels == ci)) for ci in range(k)]
    cluster_labels = [f'簇 {ci+1}' for ci in range(k)]
    colors_bar = [palette(ci) for ci in range(k)]
    bars = ax1.bar(cluster_labels, cluster_sizes, color=colors_bar,
                   alpha=0.85, width=0.55, edgecolor=th['bar_edge'], linewidth=0.5)
    for bar in bars:
        ax1.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 0.5,
                 str(int(bar.get_height())),
                 ha='center', va='bottom', color=th['bar_label'], fontsize=9)
    ax1.set_ylabel('点位数量', color=th['subtext'], fontsize=10)
    ax1.set_title('各聚类点位分布', color=th['text'], fontsize=13)
    ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
    ax1.set_axisbelow(True)
    plt.tight_layout(pad=2)
    img2_b64 = fig_to_base64(fig1)
    plt.close(fig1)

    clusters_info = []
    for ci in range(k):
        mask = labels == ci
        clusters_info.append({
            'id': ci + 1,
            'size': int(mask.sum()),
            'center_x': round(float(centers[ci, 0]), 2),
            'center_y': round(float(centers[ci, 1]), 2),
            'pct': round(float(mask.sum() / len(labels) * 100), 2),
        })

    summary = {
        'k': k,
        'total_points': int(len(x)),
        'inertia': round(inertia, 2),
        'clusters': clusters_info,
    }
    return {'image': img_b64, 'image2': img2_b64, 'summary': summary}


# ─────────────────────────────────────────────
# /api/run_all  —  一键计算所有指标（立即返回 sid，后台线程计算）
# ─────────────────────────────────────────────

def _bg_compute(sid, img_b, img_n, loc_b, loc_n, beh_b, beh_n,
                env_b, env_n, ques1_b, ques1_n, ques2_b, ques2_n, ques3_b, ques3_n,
                region_b, region_n, bgmask_b, bgmask_n, th, region_name_map=None, only_metrics=None):
    """后台线程：逐个计算指标，每算完一个就更新会话缓存"""
    region_name_map = region_name_map or {}
    only_metrics = set(only_metrics or [])

    def mk(b, n):
        return _make_fs(b, n) if b else None

    # ── 一次性提取可行走区域 mask（后续所有指标共享）──
    _walkable = None  # 延迟初始化，第一次用到 img_b 时计算
    def _get_walkable():
        nonlocal _walkable
        if _walkable is None and img_b:
            try:
                _walkable = extract_walkable_mask(load_img(mk(img_b, img_n)))
            except Exception:
                _walkable = None
        return _walkable

    # ── 可选的正式热力图覆盖遮罩（background.png 的黑色区域不涂色）──
    _coverage = None
    def _get_coverage_mask():
        nonlocal _coverage
        if _coverage is None:
            try:
                if bgmask_b:
                    _coverage = extract_measurement_mask(load_img(mk(bgmask_b, bgmask_n)))
                else:
                    _coverage = None
            except Exception:
                _coverage = None
        return _coverage

    # ── 坐标归一化：将 X/Y 线性缩放到图像像素范围 ──
    # 处理数据坐标系原点与平面图不对齐、或尺度不一致的情况
    # 仅当 X/Y 超出图像边界时才触发，坐标已在范围内的数据不做任何变换
    _img_wh = None   # (W, H) 缓存，避免重复解码
    def _get_img_size():
        nonlocal _img_wh
        if _img_wh is None and img_b:
            try:
                arr = load_img(mk(img_b, img_n))
                _img_wh = (arr.shape[1], arr.shape[0])  # (W, H)
            except Exception:
                _img_wh = (0, 0)
        return _img_wh

    def _normalize_xy(df):
        """
        当数据坐标超出图像范围时，自动做平移+缩放将 X/Y 映射到 [0, W] × [0, H]。
        坐标已在图像范围内的数据原样返回（不影响已对齐的建筑数据）。
        """
        if 'X' not in df.columns or 'Y' not in df.columns:
            return df
        wh = _get_img_size()
        if not wh or wh[0] == 0 or wh[1] == 0:
            return df
        img_w, img_h = wh
        x = df['X'].astype(float)
        y = df['Y'].astype(float)
        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()
        # 只有当坐标超出图像边界时才做归一化
        needs_norm = (x_min < 0 or x_max > img_w or y_min < 0 or y_max > img_h)
        if not needs_norm:
            return df
        df = df.copy()
        x_span = x_max - x_min
        y_span = y_max - y_min
        df['X'] = (x - x_min) / x_span * img_w if x_span > 0 else x - x_min
        df['Y'] = (y - y_min) / y_span * img_h if y_span > 0 else y - y_min
        return df

    def _update(name, result):
        """将单个指标结果写入会话缓存"""
        with _sess_lock:
            sess = _sessions.get(sid)
            if sess is None:
                return
            sess['results'][name] = result
            if name in sess.get('computed', []):
                sess['computed'].remove(name)
            if name in sess.get('skipped', []):
                sess['skipped'].remove(name)
            if result is not None and not result.get('error'):
                sess['computed'].append(name)
            else:
                # 记录跳过原因到 result
                if result is None:
                    sess['results'][name] = {'error': '数据不足，跳过（缺少必要文件或列）'}
                sess['skipped'].append(name)

    def _run_metric(name, fn):
        if only_metrics and name not in only_metrics:
            return
        try:
            r = fn()
            _update(name, r)
        except Exception as exc:
            import traceback
            _update(name, {'error': str(exc), 'traceback': traceback.format_exc()})

    # ── A1 到访频次热力图 ──
    def _heatmap():
        if not loc_b or not img_b:
            return None
        df = load_df(mk(loc_b, loc_n))
        if not {'X', 'Y'}.issubset(df.columns):
            return None
        df = _normalize_xy(df)
        img = load_img(mk(img_b, img_n))
        walkable = _get_walkable()
        overlay, freq_field, vmin, vmax, freq_stats = make_visit_frequency_overlay(
            img, df, walkable_mask=walkable, coverage_mask=_get_coverage_mask()
        )
        fig0, ax0 = plt.subplots(figsize=(9, 6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('到访频次热力图', color=th['text'], fontsize=13, pad=10)
        sm = plt.cm.ScalarMappable(cmap='plasma', norm=mcolors.Normalize(vmin, vmax if vmax > vmin else vmin + 1.0))
        sm.set_array([]); cbar = fig0.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('到访频次', color=th['subtext'], fontsize=9)
        plt.tight_layout(pad=2); img_b64 = fig_to_base64(fig0); plt.close(fig0)
        img2_b64 = None
        if 'Region' in df.columns:
            fig1, ax1 = plt.subplots(figsize=(9, 6)); fig1.patch.set_facecolor(th['fig_bg'])
            _styled_axes(ax1, th)
            rc = df.groupby('Region').size().reset_index(name='count')
            _bar_common(ax1, _region_labels(rc['Region'], region_name_map), rc['count'], color=th['accent'], xlabel='空间单元', ylabel='到访人次', th=th)
            ax1.set_title('各空间单元到访频次', color=th['text'], fontsize=13)
            plt.tight_layout(pad=2); img2_b64 = fig_to_base64(fig1); plt.close(fig1)
        return {'image': img_b64, 'image2': img2_b64, 'summary': {
            'total_records': int(len(df)),
            'unique_users': int(df['UserID'].nunique()) if 'UserID' in df.columns else '-',
            **freq_stats,
        }}
    _run_metric('heatmap', _heatmap)

    # ── A2 使用时长 ──
    def _usetime():
        if not loc_b or not img_b: return None
        df = load_df(mk(loc_b, loc_n))
        if not {'X','Y','Region'}.issubset(df.columns): return None
        df = df.dropna(subset=['X','Y','Region'])
        if len(df) == 0: return None
        df = _normalize_xy(df)
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        weights=np.full(len(df), USAGE_SECONDS_PER_RECORD, dtype=float)
        regions=df['Region'].astype(int).values
        img=load_img(mk(img_b, img_n))
        reg_ids=np.sort(np.unique(regions))
        reg_dur=np.array([weights[regions==r].sum() for r in reg_ids])
        overlay,fg=_make_heatmap_overlay(img,x,y,weights=weights,alpha=0.65,cmap='jet',
                                          walkable_mask=_get_walkable(),
                                          coverage_mask=_get_coverage_mask(),
                                          scale_to_kernel_area=True)
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('空间使用时长热力图',color=th['text'],fontsize=13,pad=10)
        sm=plt.cm.ScalarMappable(cmap='jet',norm=mcolors.Normalize(0,float(fg.max()) if float(fg.max()) > 0 else 1.0))
        sm.set_array([]); cbar=fig0.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8)
        cbar.set_label('停留时长 (s)',color=th['subtext'],fontsize=9)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        _bar_common(ax1,_region_labels(reg_ids, region_name_map),reg_dur,color='#00c9a7',xlabel='空间单元',ylabel='时长 (s)',th=th)
        ax1.set_title('各空间单元使用时长',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_records':int(len(df)),'seconds_per_record':USAGE_SECONDS_PER_RECORD,'total_duration_s':round(float(weights.sum()),2),'avg_duration_s':round(float(reg_dur.mean()),2),'max_duration_s':round(float(reg_dur.max()),2),'min_duration_s':round(float(reg_dur.min()),2),'region_count':int(len(reg_ids)),'peak_region':int(reg_ids[np.argmax(reg_dur)])}}
    _run_metric('usetime', _usetime)

    # ── A3 移动速率 ──
    def _speed():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','t','UserID'}.issubset(df.columns): return None
        df = df.dropna(subset=['X','Y','Region','t','UserID'])
        if len(df) == 0: return None
        df = _normalize_xy(df)
        img=load_img(mk(img_b,img_n))
        x_all=df['X'].astype(float).values; y_all=df['Y'].astype(float).values
        t_all=df['t'].astype(float).values; regions_all=df['Region'].astype(int).values
        user_ids=df['UserID'].values; reg_ids=np.sort(np.unique(regions_all))
        reg_dwell=np.array([t_all[regions_all==r].sum() for r in reg_ids])
        reg_length=np.zeros(len(reg_ids))
        for uid in np.unique(user_ids):
            mask=user_ids==uid; ux,uy,ur=x_all[mask],y_all[mask],regions_all[mask]
            if len(ux)<2: continue
            for i in range(len(ux)-1):
                seg=np.sqrt((ux[i+1]-ux[i])**2+(uy[i+1]-uy[i])**2)/SCALE
                for ri in [ur[i],ur[i+1]]:
                    if ri in reg_ids:
                        idx=np.where(reg_ids==ri)[0][0]; reg_length[idx]+=seg*0.5
        with np.errstate(divide='ignore',invalid='ignore'):
            mean_speed=np.where(reg_dwell>0,reg_length/reg_dwell,0)
        weights=np.array([mean_speed[np.where(reg_ids==r)[0][0]] if r in reg_ids else 0 for r in regions_all])
        overlay,speed_grid=_make_heatmap_overlay(img,x_all,y_all,weights=weights,alpha=0.65,cmap='jet',
                                         walkable_mask=_get_walkable(),
                                         coverage_mask=_get_coverage_mask())
        global_speed=reg_length.sum()/reg_dwell.sum() if reg_dwell.sum()>0 else 0
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('空间移动速率热力图 (m/s)',color=th['text'],fontsize=13,pad=10)
        sm=plt.cm.ScalarMappable(cmap='jet',norm=mcolors.Normalize(0,float(speed_grid.max()) if float(speed_grid.max()) > 0 else 1.0))
        sm.set_array([]); cbar=fig0.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8)
        cbar.set_label('移动速率强度',color=th['subtext'],fontsize=9)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        _bar_common(ax1,_region_labels(reg_ids, region_name_map),mean_speed,color='#f5a623',xlabel='空间单元',ylabel='速率 (m/s)',th=th,
                    show_mean=True,color_above='#f5a623',color_below='#00c9a7')
        ax1.set_title('各空间单元平均移动速率',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_records':int(len(df)),'global_speed_ms':round(float(global_speed),2),'avg_speed_ms':round(float(mean_speed.mean()),2),'max_speed_ms':round(float(mean_speed.max()),2),'min_speed_ms':round(float(mean_speed.min()),2),'peak_speed_region':int(reg_ids[np.argmax(mean_speed)]),'region_count':int(len(reg_ids))}}
    _run_metric('speed', _speed)

    # ── A4 停留时长 ──
    def _duration():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','t'}.issubset(df.columns): return None
        df = df.dropna(subset=['X','Y','Region','t'])
        if len(df) == 0: return None
        df = _normalize_xy(df)
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        t=df['t'].astype(float).values; regions=df['Region'].astype(int).values
        img=load_img(mk(img_b,img_n))
        reg_ids=np.sort(np.unique(regions))
        reg_dwell=np.array([t[regions==r].sum() for r in reg_ids])
        overlay,fg=_make_heatmap_overlay(img,x,y,weights=t,alpha=0.65,cmap='jet',
                                          walkable_mask=_get_walkable(),
                                          coverage_mask=_get_coverage_mask())
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('空间停留时长热力图 (s)',color=th['text'],fontsize=13,pad=10)
        sm=plt.cm.ScalarMappable(cmap='jet',norm=mcolors.Normalize(0,float(t.max())))
        sm.set_array([]); cbar=fig0.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8); cbar.set_label('停留时长 (s)',color=th['subtext'],fontsize=9)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        _bar_common(ax1,_region_labels(reg_ids, region_name_map),reg_dwell,color=th['accent'],xlabel='空间单元',ylabel='时长 (s)',th=th)
        ax1.set_title('各空间单元停留时长',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_records':int(len(df)),'total_dwell_s':round(float(t.sum()),2),'avg_dwell_s':round(float(reg_dwell.mean()),2),'max_dwell_s':round(float(reg_dwell.max()),2),'min_dwell_s':round(float(reg_dwell.min()),2),'peak_region':int(reg_ids[np.argmax(reg_dwell)])}}
    _run_metric('duration', _duration)

    # ── A5 空间聚类 (trajectory cluster) ──
    def _cluster():
        if not loc_b or not img_b: return None
        return _compute_cluster_result(
            mk(loc_b, loc_n),
            mk(img_b, img_n),
            5,
            th,
            normalize_xy_fn=_normalize_xy,
            walkable_mask=_get_walkable(),
        )
    _run_metric('cluster', _cluster)

    # ── A6 人员密度 ──
    def _density_fn():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','UserID'}.issubset(df.columns): return None
        df = _normalize_xy(df)
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        regions=df['Region'].astype(int).values; img=load_img(mk(img_b,img_n))
        reg_ids=np.sort(np.unique(regions))
        reg_uu=np.array([df[df['Region']==r]['UserID'].nunique() for r in reg_ids])
        overlay,density_grid=_make_heatmap_overlay(img,x,y,alpha=0.65,cmap='jet',walkable_mask=_get_walkable(),
                                                    coverage_mask=_get_coverage_mask())
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('人员分布热力图',color=th['text'],fontsize=13,pad=10)
        sm=plt.cm.ScalarMappable(cmap='jet',norm=mcolors.Normalize(0,float(density_grid.max()) if float(density_grid.max()) > 0 else 1.0))
        sm.set_array([]); cbar=fig0.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8)
        cbar.set_label('人员分布密度',color=th['subtext'],fontsize=9)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        _bar_common(ax1,_region_labels(reg_ids, region_name_map),reg_uu,color='#00c9a7',xlabel='空间单元',ylabel='独立人员数',th=th)
        ax1.set_title('各空间单元独立人员数',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_records':int(len(df)),'unique_users':int(df['UserID'].nunique()),'avg_density':round(float(reg_uu.mean()),2),'max_density':round(float(reg_uu.max()),2),'min_density':round(float(reg_uu.min()),2),'region_count':int(len(reg_ids)),'peak_region':int(reg_ids[np.argmax(reg_uu)])}}
    _run_metric('density', _density_fn)

    # ── A7 空间开放程度 ──
    def _openness_fn():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','UserID'}.issubset(df.columns): return None
        df = _normalize_xy(df)
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        regions=df['Region'].astype(int).values; img=load_img(mk(img_b,img_n))
        reg_ids=np.sort(np.unique(regions))
        reg_uu=np.array([df[df['Region']==r]['UserID'].nunique() for r in reg_ids],dtype=float)
        if region_b:
            rdf=load_df(mk(region_b,region_n)); areas={}
            for rid in rdf['Region'].unique():
                pts=rdf[rdf['Region']==rid][['X','Y']].values
                if len(pts)>=3:
                    pts_c=np.vstack([pts,pts[0]]); a=0.5*abs(np.sum(pts_c[:-1,0]*pts_c[1:,1]-pts_c[1:,0]*pts_c[:-1,1])); areas[rid]=a/(SCALE**2)
                else: areas[rid]=1.0
            reg_areas=np.array([areas.get(r,1.0) for r in reg_ids])
        else:
            reg_areas=np.ones(len(reg_ids))
        with np.errstate(divide='ignore',invalid='ignore'):
            openness_val=np.where(reg_areas>0,reg_uu/reg_areas,0)
        global_open=df['UserID'].nunique()/reg_areas.sum() if reg_areas.sum()>0 else 0
        overlay,open_grid=_make_heatmap_overlay(img,x,y,alpha=0.65,cmap='jet',walkable_mask=_get_walkable(),
                                                 coverage_mask=_get_coverage_mask())
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('空间开放程度热力图',color=th['text'],fontsize=13,pad=10)
        sm=plt.cm.ScalarMappable(cmap='jet',norm=mcolors.Normalize(0,float(open_grid.max()) if float(open_grid.max()) > 0 else 1.0))
        sm.set_array([]); cbar=fig0.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8)
        cbar.set_label('空间开放程度强度',color=th['subtext'],fontsize=9)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        _bar_common(ax1,_region_labels(reg_ids, region_name_map),openness_val,color='#f5a623',xlabel='空间单元',ylabel='人/㎡',th=th)
        ax1.axhline(global_open,color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'整体 {global_open:.2f}')
        _legend_upper_right(ax1, th)
        ax1.set_title('各空间单元开放程度 (人/㎡)',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'unique_users':int(df['UserID'].nunique()),'global_openness':round(float(global_open),2),'avg_openness':round(float(openness_val.mean()),2),'max_openness':round(float(openness_val.max()),2),'min_openness':round(float(openness_val.min()),2),'peak_region':int(reg_ids[np.argmax(openness_val)]),'region_count':int(len(reg_ids))}}
    _run_metric('openness', _openness_fn)

    # ── A8 拓扑连接关系 ──
    def _topology_fn():
        if not loc_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','UserID'}.issubset(df.columns): return None
        df = _normalize_xy(df)
        regions=df['Region'].astype(int).values; user_ids=df['UserID'].values
        reg_ids=np.sort(np.unique(regions[regions>0])); n=len(reg_ids)
        if n<2: return None
        rid2idx={r:i for i,r in enumerate(reg_ids)}
        trans=np.zeros((n,n),dtype=int)
        for uid in np.unique(user_ids):
            mask=user_ids==uid; ur=regions[mask]
            for i in range(len(ur)-1):
                fr,to=ur[i],ur[i+1]
                if fr!=to and fr in rid2idx and to in rid2idx: trans[rid2idx[fr],rid2idx[to]]+=1
        # ── 子图1：转移矩阵（左下角=低编号，右上角=高编号） ──
        # trans[i,j] = 从 reg_ids[i] 到 reg_ids[j] 的转移次数
        # imshow 默认 origin='upper'（行0在顶部），要让左下角是 (1,1) 需要垂直翻转显示
        trans_display = trans[::-1, :]   # 翻转行顺序用于显示，数据本身不变
        ytick_labels  = reg_ids[::-1]    # Y 轴刻度对应翻转后的行

        # ── 图1：转移矩阵热图 ──
        fig0,ax0=plt.subplots(figsize=(9,8)); fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0,th)
        im=ax0.imshow(trans_display,cmap='YlOrRd',aspect='auto',origin='upper')
        ax0.set_xticks(range(n)); ax0.set_xticklabels(_region_labels(reg_ids, region_name_map, prefix=''),fontsize=8,rotation=30,ha='right')
        ax0.set_yticks(range(n)); ax0.set_yticklabels(_region_labels(ytick_labels, region_name_map, prefix=''),fontsize=8)
        ax0.set_xlabel('目标空间单元',color=th['subtext'],fontsize=10); ax0.set_ylabel('出发空间单元',color=th['subtext'],fontsize=10)
        ax0.set_title('区域人员转移矩阵',color=th['text'],fontsize=13,pad=10)
        vmax_val = trans.max() if trans.max()>0 else 1
        # 对角线（left-bottom→right-top）：display 中的"自环"格，di+j==n-1 即真实对角 ri==j
        for di in range(n):           # di: 显示行（0=顶部=最大编号）
            ri = n-1-di               # ri: 数据行索引（trans 中的真实行）
            for j in range(n):
                if ri == j:   # 对角格（从出发区域到自身）→ 填灰色
                    ax0.add_patch(plt.Rectangle((j-0.5, di-0.5), 1, 1,
                                                facecolor='#808080', edgecolor='none', zorder=2))
                    ax0.text(j, di, '—', ha='center', va='center',
                             fontsize=9, color='white', zorder=3)
                    continue
                v = trans[ri, j]
                if v>0:
                    ax0.text(j, di, str(int(v)), ha='center', va='center',
                             fontsize=7, fontweight='bold',
                             color='white' if v >= vmax_val*0.6 else 'black')
        cbar=fig0.colorbar(im,ax=ax0,fraction=0.04,pad=0.02); cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)

        # ── 图2：入流/出流柱状图 ──
        in_deg=trans.sum(axis=0); out_deg=trans.sum(axis=1)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        bw=0.35; xs=np.arange(n)
        bars_in=ax1.bar(xs-bw/2,in_deg,width=bw,color=th['accent'],alpha=0.85,label='入流')
        bars_out=ax1.bar(xs+bw/2,out_deg,width=bw,color='#00c9a7',alpha=0.85,label='出流')
        for bar in bars_in:
            h=bar.get_height()
            if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.02,str(int(h)),ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        for bar in bars_out:
            h=bar.get_height()
            if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.02,str(int(h)),ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(xs); ax1.set_xticklabels(_region_labels(reg_ids, region_name_map, prefix=''),fontsize=8,rotation=30,ha='right')
        ax1.set_xlabel('空间单元',color=th['subtext'],fontsize=10); ax1.set_ylabel('流量',color=th['subtext'],fontsize=10)
        ax1.set_title('各空间单元人员流入/流出量',color=th['text'],fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)

        # ── 图3：拓扑网络图 ──
        fig2,ax2=plt.subplots(figsize=(9,8)); fig2.patch.set_facecolor(th['fig_bg'])
        ax2.set_facecolor(th['fig_bg']); ax2.set_aspect('equal')
        ax2.set_title('区域拓扑网络图',color=th['text'],fontsize=13,pad=10)
        ax2.axis('off')
        # 计算各区域质心
        df_tmp = df[df['Region'].astype(int).isin(reg_ids)].copy()
        cx = np.array([df_tmp[df_tmp['Region'].astype(int)==r]['X'].astype(float).mean() for r in reg_ids])
        cy = np.array([df_tmp[df_tmp['Region'].astype(int)==r]['Y'].astype(float).mean() for r in reg_ids])
        # 归一化坐标到 [0.05, 0.95] 用于绘图
        def _norm01(arr):
            lo,hi=arr.min(),arr.max()
            return (arr-lo)/(hi-lo+1e-9)*0.85+0.05
        nx_pos=_norm01(cx); ny_pos=1.0-_norm01(cy)  # Y 反转（图像坐标→数学坐标）
        # 绘制有向边
        max_t   = trans.max() if trans.max()>0 else 1
        for i in range(n):
            for j in range(n):
                if i==j: continue
                w=trans[i,j]
                if w==0: continue
                lw=0.5+3.5*(w/max_t)
                alpha=0.25+0.65*(w/max_t)
                x0,y0=nx_pos[i],ny_pos[i]; x1,y1=nx_pos[j],ny_pos[j]
                # 箭头稍微弯曲（同向对边错开）
                rad=0.15 if trans[j,i]>0 else 0.0
                ax2.annotate('',xy=(x1,y1),xytext=(x0,y0),
                    xycoords='axes fraction',textcoords='axes fraction',
                    arrowprops=dict(arrowstyle='-|>',color='#4facfe',lw=lw,
                                   alpha=alpha,connectionstyle=f'arc3,rad={rad}'),
                    annotation_clip=False)
        # 节点大小 ∝ 总流量（入+出）
        total_flow=in_deg+out_deg; max_flow=total_flow.max() if total_flow.max()>0 else 1
        node_r=np.clip(0.025+0.040*(total_flow/max_flow),0.02,0.07)
        cmap_n=_get_cmap('plasma')
        node_colors=[cmap_n(0.2+0.7*(total_flow[i]/max_flow)) for i in range(n)]
        for i in range(n):
            circ=plt.Circle((nx_pos[i],ny_pos[i]),node_r[i],
                            transform=ax2.transAxes,color=node_colors[i],
                            ec='white',lw=1.2,zorder=5,clip_on=False)
            ax2.add_patch(circ)
            label = _region_label(reg_ids[i], region_name_map, prefix='')
            flow_label = f'{int(total_flow[i])}人'
            ax2.text(nx_pos[i],ny_pos[i],f'{label}\n{flow_label}',
                     ha='center',va='center',fontsize=8,fontweight='bold',
                     color='white',transform=ax2.transAxes,zorder=6,linespacing=1.05)
        ax2.set_xlim(0,1); ax2.set_ylim(0,1)
        plt.tight_layout(pad=2); img3_b64=fig_to_base64(fig2); plt.close(fig2)

        return {'image':img_b64,'image2':img2_b64,'image3':img3_b64,
                'summary':{'region_count':n,'total_transitions':int(trans.sum()),
                           'avg_in_flow':round(float(in_deg.mean()),2),'max_in_flow':int(in_deg.max()),'min_in_flow':int(in_deg.min()),
                           'avg_out_flow':round(float(out_deg.mean()),2),'max_out_flow':int(out_deg.max()),'min_out_flow':int(out_deg.min())}}
    _run_metric('topology', _topology_fn)

    # ── A9 轨迹差异系数 ──
    def _difference_fn():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','UserID','Region'}.issubset(df.columns): return None
        df = _normalize_xy(df)
        img=load_img(mk(img_b,img_n))
        user_ids=df['UserID'].values; per_ids=np.unique(user_ids)
        reg_ids=np.sort(np.unique(df['Region'].astype(int).values))
        per_lengths={}
        for uid in per_ids:
            ud=df[df['UserID']==uid]; ux,uy=ud['X'].astype(float).values,ud['Y'].astype(float).values
            per_lengths[uid]=float(np.sum(np.sqrt(np.diff(ux)**2+np.diff(uy)**2)))/SCALE if len(ux)>1 else 0.0
        lengths=np.array([per_lengths[u] for u in per_ids])
        avg_len=lengths[lengths>0].mean() if (lengths>0).any() else 1
        diff_coeff_per=lengths/avg_len
        reg_len_sums={}; reg_len_counts={}
        for uid in per_ids:
            ud=df[df['UserID']==uid]; ux=ud['X'].astype(float).values; uy=ud['Y'].astype(float).values; ur=ud['Region'].astype(int).values
            for i in range(len(ux)-1):
                seg=np.sqrt((ux[i+1]-ux[i])**2+(uy[i+1]-uy[i])**2)/SCALE
                for r in [ur[i],ur[i+1]]:
                    reg_len_sums[r]=reg_len_sums.get(r,0.0)+seg*0.5; reg_len_counts[r]=reg_len_counts.get(r,0)+1
        reg_means=np.array([reg_len_sums.get(r,0)/max(reg_len_counts.get(r,1),1) for r in reg_ids])
        global_mean=reg_means[reg_means>0].mean() if (reg_means>0).any() else 1
        diff_coeff_reg=reg_means/global_mean
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0,th)
        bars0=ax0.bar([str(u) for u in per_ids],diff_coeff_per,
                     color=[th['accent'] if v >= 1.0 else '#00c9a7' for v in diff_coeff_per],
                     alpha=0.85,width=0.6)
        for bar in bars0:
            h=bar.get_height()
            ax0.text(bar.get_x()+bar.get_width()/2,h+h*0.01,f'{h:.2f}',ha='center',va='bottom',color=th['bar_label'],fontsize=8)
        ax0.axhline(1.0,color='#ff5e5e',linestyle='--',linewidth=1.5,label='基准线(=1)')
        ax0.set_xlabel('人员编号',color=th['subtext'],fontsize=10); ax0.set_ylabel('差异系数',color=th['subtext'],fontsize=10)
        ax0.set_title('人员轨迹长度差异系数',color=th['text'],fontsize=13,pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        _set_sparse_xticks(ax0, per_ids)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        bars1=ax1.bar([str(r) for r in reg_ids],diff_coeff_reg,
                     color=['#f5a623' if v >= 1.0 else '#00c9a7' for v in diff_coeff_reg],
                     alpha=0.85,width=0.6)
        for bar in bars1:
            h=bar.get_height()
            ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.01,f'{h:.2f}',ha='center',va='bottom',color=th['bar_label'],fontsize=8)
        ax1.axhline(1.0,color='#ff5e5e',linestyle='--',linewidth=1.5,label='基准线(=1)')
        ax1.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax1.set_ylabel('差异系数',color=th['subtext'],fontsize=10)
        ax1.set_title('区域流线长度差异系数',color=th['text'],fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_users':int(len(per_ids)),'avg_length_m':round(float(avg_len),1),'max_diff_user':str(per_ids[np.argmax(diff_coeff_per)]),'region_count':int(len(reg_ids))}}
    _run_metric('difference', _difference_fn)

    # ── 人员轨迹 (trajectory) ──
    def _trajectory_fn():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','UserID'}.issubset(df.columns): return None
        df = _normalize_xy(df)
        img=load_img(mk(img_b,img_n))
        walkable=_get_walkable()
        user_ids=df['UserID'].unique(); palette=_get_cmap('tab20',len(user_ids)); total_lengths={}
        line_width = _trajectory_line_width(len(user_ids))
        _ih, _iw = img.shape[:2]
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(img,alpha=0.4); ax0.axis('off')
        ax0.set_xlim(0, _iw); ax0.set_ylim(_ih, 0)
        for idx,uid in enumerate(user_ids):
            ud=df[df['UserID']==uid].reset_index(drop=True)
            x_arr=ud['X'].values; y_arr=ud['Y'].values; color=palette(idx)
            if walkable is not None:
                x_arr,y_arr=filter_points_in_mask(x_arr,y_arr,walkable)
            if len(x_arr)<2: continue
            if len(x_arr)>3:
                from scipy.interpolate import make_interp_spline
                t_arr=np.linspace(0,1,len(x_arr)); t_new=np.linspace(0,1,min(500,len(x_arr)*10))
                try:
                    sx=make_interp_spline(t_arr,x_arr,k=min(3,len(x_arr)-1)); sy=make_interp_spline(t_arr,y_arr,k=min(3,len(x_arr)-1))
                    x_s=sx(t_new); y_s=sy(t_new)
                except: x_s,y_s=x_arr,y_arr
            else: x_s,y_s=x_arr,y_arr
            ax0.plot(x_s,y_s,color=color,lw=line_width,alpha=0.85)
            dx=np.diff(x_arr); dy=np.diff(y_arr); total_lengths[uid]=float(np.sum(np.sqrt(dx**2+dy**2))/SCALE)
        ax0.set_title('人员移动轨迹',color=th['text'],fontsize=13,pad=10)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        if not total_lengths:
            return None
        lens_arr=np.array(list(total_lengths.values()), dtype=float)
        hist_min=float(np.min(lens_arr)); hist_max=float(np.max(lens_arr))
        if np.isclose(hist_min, hist_max):
            hist_min -= 0.5
            hist_max += 0.5
        bin_edges=np.linspace(hist_min, hist_max, 11)
        counts, edges=np.histogram(lens_arr, bins=bin_edges)
        labels=[]
        for i in range(len(edges)-1):
            left=edges[i]; right=edges[i+1]
            labels.append(f'{left:.1f}-{right:.1f}')
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        xs=np.arange(len(counts))
        bars=ax1.bar(xs, counts, color='#00c9a7', alpha=0.85, width=0.8)
        for bar in bars:
            h=bar.get_height()
            if h>0:
                ax1.text(bar.get_x()+bar.get_width()/2, h+0.1, f'{int(h)}', ha='center', va='bottom', color=th['bar_label'], fontsize=8)
        ax1.set_xticks(xs)
        ax1.set_xticklabels(labels, fontsize=8, rotation=25, ha='right')
        ax1.set_xlabel('轨迹长度分桶 (m)',color=th['subtext'],fontsize=10)
        ax1.set_ylabel('用户数',color=th['subtext'],fontsize=10)
        ax1.set_title('人员轨迹长度分布（10桶）',color=th['text'],fontsize=13)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_users':len(user_ids),'avg_length_m':round(float(np.mean(list(total_lengths.values()))),1),'max_length_m':round(max(total_lengths.values()),1),'min_length_m':round(min(total_lengths.values()),1)}}
    _run_metric('trajectory', _trajectory_fn)

    # ── B5 环境参数 (每类参数分别计算) ──
    def _env_fn(param_num):
        def _inner():
            if not env_b or not img_b: return None
            df=load_df(mk(env_b,env_n))
            if not {'X','Y','ParameterNum','Value'}.issubset(df.columns): return None
            param_labels={1:'温度(°C)',2:'湿度(%)',3:'光照(lux)',4:'风速(m/s)',5:'噪声(dB)'}
            label=param_labels.get(param_num,f'参数{param_num}')
            sub=df[df['ParameterNum']==param_num].copy()
            sub = sub.dropna(subset=['X', 'Y', 'Value'])
            if sub.empty: return {'no_data': True, 'label': label}
            ex=sub['X'].astype(float).values; ey=sub['Y'].astype(float).values; vals=sub['Value'].astype(float).values
            img=load_img(mk(img_b,img_n)); h_img,w_img=img.shape[:2]
            walkable = _get_walkable()
            kernel_map = {1: 'linear', 2: 'linear', 3: 'gaussian', 4: 'linear', 5: 'linear'}
            epsilon_map = {3: max(min(w_img, h_img) * 0.015, 4.0)}
            overlay, interp, vmin, vmax = _make_rbf_overlay(
                img, ex, ey, vals,
                alpha=0.65,
                cmap='RdYlBu_r',
                walkable_mask=walkable,
                coverage_mask=_get_coverage_mask(),
                kernel=kernel_map.get(param_num, 'linear'),
                smoothing=max(float(np.nanstd(vals)) * 0.03, 1e-6),
                neighbors=min(max(len(vals), 8), 24),
                epsilon=epsilon_map.get(param_num),
            )
            if interp is None:
                return {'no_data': True, 'label': label}
            # 图1：热力图
            fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
            ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
            ax0.scatter(ex, ey, c='white', s=24, zorder=5, edgecolors='#ffcc00', linewidths=0.8)
            ax0.set_title(f'{label} 空间分布',color=th['text'],fontsize=13,pad=10)
            sm=plt.cm.ScalarMappable(cmap='RdYlBu_r',norm=mcolors.Normalize(vmin,vmax))
            sm.set_array([]); cbar=fig0.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
            cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8); cbar.set_label(label,color=th['subtext'],fontsize=9)
            plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
            # 图2：测点散点图
            fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
            _styled_axes(ax1,th)
            ax1.scatter(range(len(vals)),vals,color=th['accent'],s=40,alpha=0.85,zorder=3)
            for xi,vi in enumerate(vals):
                ax1.annotate(f'{vi:.2f}',(xi,vi),xytext=(0,6),textcoords='offset points',ha='center',va='bottom',color=th['bar_label'],fontsize=7)
            ax1.axhline(float(vals.mean()),color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'均值 {vals.mean():.2f}')
            ax1.set_xlabel('测点编号',color=th['subtext'],fontsize=10); ax1.set_ylabel(label,color=th['subtext'],fontsize=10)
            ax1.set_title(f'各测点{label}值',color=th['text'],fontsize=13)
            _legend_upper_right(ax1, th)
            ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
            plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
            return {'image':img_b64,'image2':img2_b64,'summary':{'param':label,'num_points':int(len(vals)),'mean':round(float(vals.mean()),2),'max':round(float(vals.max()),2),'min':round(float(vals.min()),2)}}
        return _inner

    for pn in range(1, 6):
        _run_metric(f'environment_p{pn}', _env_fn(pn))

    # ── C1-C4 行为指标 ──
    def _beh_count():
        if not beh_b or not img_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'X','Y','BehaviorNum','Region'}.issubset(df.columns): return None
        df = df.dropna(subset=['X','Y','BehaviorNum','Region'])
        df = _clean_behavior_df(df, require_t=False)
        if len(df) == 0: return None
        df = _normalize_xy(df)
        img=load_img(mk(img_b,img_n))
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        beh_nums=df['BehaviorNum'].astype(int).values; regions=df['Region'].astype(int).values
        beh_labels_map=df.groupby('BehaviorNum')['behaviortype'].first().to_dict() if 'behaviortype' in df.columns else {b:f'行为{b}' for b in np.unique(beh_nums)}
        uniq_beh=np.sort(np.unique(beh_nums)); uniq_reg=np.sort(np.unique(regions))
        beh_labels=[str(beh_labels_map.get(b,b)) for b in uniq_beh]
        count_matrix=np.zeros((len(uniq_reg),len(uniq_beh)),dtype=int)
        for i,r in enumerate(uniq_reg):
            for j,b in enumerate(uniq_beh): count_matrix[i,j]=int(((regions==r)&(beh_nums==b)).sum())
        palette=_get_cmap('tab10',len(uniq_beh))
        _ih, _iw = img.shape[:2]
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(img,alpha=0.5)
        ax0.set_xlim(0, _iw); ax0.set_ylim(_ih, 0)
        for j,b in enumerate(uniq_beh):
            mask=beh_nums==b; ax0.scatter(x[mask],y[mask],s=18,color=palette(j),alpha=0.75,label=beh_labels[j],zorder=3)
        ax0.axis('off'); ax0.set_title('各行为发生分布',color=th['text'],fontsize=13,pad=10)
        ax0.legend(loc='upper right',fontsize=7,ncol=2,facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'])
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        bw=0.7/len(uniq_beh); xs=np.arange(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            bars_c=ax1.bar(xs+j*bw-0.35+bw/2,count_matrix[:,j],width=bw,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bar in bars_c:
                h=bar.get_height()
                if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.02,str(int(h)),ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(xs); ax1.set_xticklabels(_region_labels(uniq_reg, region_name_map, prefix=''),fontsize=8,rotation=30,ha='right')
        ax1.set_xlabel('空间单元',color=th['subtext'],fontsize=10); ax1.set_ylabel('人次',color=th['subtext'],fontsize=10)
        ax1.set_title('各空间单元行为发生人次',color=th['text'],fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_records':int(len(df)),'behavior_types':len(uniq_beh),'region_count':int(len(uniq_reg)),'behaviors':beh_labels}}
    _run_metric('behavior_count', _beh_count)

    def _beh_dur():
        if not beh_b or not img_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'X','Y','BehaviorNum','Region','t'}.issubset(df.columns): return None
        df = df.dropna(subset=['X','Y','BehaviorNum','Region','t'])
        df = _clean_behavior_df(df, require_t=True)
        if len(df) == 0: return None
        df = _normalize_xy(df)
        img=load_img(mk(img_b,img_n))
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        beh_nums=df['BehaviorNum'].astype(int).values; regions=df['Region'].astype(int).values; t=df['t'].astype(float).values
        beh_labels_map=df.groupby('BehaviorNum')['behaviortype'].first().to_dict() if 'behaviortype' in df.columns else {b:f'行为{b}' for b in np.unique(beh_nums)}
        uniq_beh=np.sort(np.unique(beh_nums)); uniq_reg=np.sort(np.unique(regions)); beh_labels=[str(beh_labels_map.get(b,b)) for b in uniq_beh]
        dur_matrix=np.zeros((len(uniq_reg),len(uniq_beh)))
        for i,r in enumerate(uniq_reg):
            for j,b in enumerate(uniq_beh): dur_matrix[i,j]=t[(regions==r)&(beh_nums==b)].sum()
        palette=_get_cmap('tab10',len(uniq_beh))
        _cov = _get_coverage_mask()
        overlay,beh_grid=_make_heatmap_overlay(img,x,y,weights=t,alpha=0.65,cmap='jet',
            walkable_mask=_get_walkable(), coverage_mask=_cov if _cov is not None else extract_measurement_mask(img))
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off'); ax0.set_title('行为时长热力图 (s)',color=th['text'],fontsize=13,pad=10)
        sm=plt.cm.ScalarMappable(cmap='jet',norm=mcolors.Normalize(0,float(beh_grid.max()) if float(beh_grid.max()) > 0 else 1.0))
        sm.set_array([]); cbar=fig0.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8)
        cbar.set_label('行为时长强度',color=th['subtext'],fontsize=9)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        bw=0.7/len(uniq_beh); xs=np.arange(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            bars_d=ax1.bar(xs+j*bw-0.35+bw/2,dur_matrix[:,j],width=bw,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bar in bars_d:
                h=bar.get_height()
                if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.02,f'{h:.0f}',ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(xs); ax1.set_xticklabels(_region_labels(uniq_reg, region_name_map, prefix=''),fontsize=8,rotation=30,ha='right')
        ax1.set_xlabel('空间单元',color=th['subtext'],fontsize=10); ax1.set_ylabel('时长 (s)',color=th['subtext'],fontsize=10)
        ax1.set_title('各空间单元行为时长',color=th['text'],fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_records':int(len(df)),'total_duration_s':int(t.sum()),'behavior_types':len(uniq_beh),'behaviors':beh_labels}}
    _run_metric('behavior_duration', _beh_dur)

    def _beh_rate():
        if not beh_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'BehaviorNum','Region','t'}.issubset(df.columns): return None
        df = df.dropna(subset=['BehaviorNum','Region','t'])
        df = _clean_behavior_df(df, require_t=True)
        if len(df) == 0: return None
        beh_nums=df['BehaviorNum'].astype(int).values; regions=df['Region'].astype(int).values; t=df['t'].astype(float).values
        beh_labels_map=df.groupby('BehaviorNum')['behaviortype'].first().to_dict() if 'behaviortype' in df.columns else {b:f'行为{b}' for b in np.unique(beh_nums)}
        uniq_beh=np.sort(np.unique(beh_nums)); uniq_reg=np.sort(np.unique(regions)); beh_labels=[str(beh_labels_map.get(b,b)) for b in uniq_beh]
        rate_matrix=np.zeros((len(uniq_reg),len(uniq_beh)))
        for i,r in enumerate(uniq_reg):
            r_mask=regions==r; total_t=t[r_mask].sum()
            for j,b in enumerate(uniq_beh): rate_matrix[i,j]=t[r_mask&(beh_nums==b)].sum()/total_t if total_t>0 else 0
        palette=_get_cmap('tab10',len(uniq_beh))
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0,th); bottom=np.zeros(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            seg_bars=ax0.bar(_region_labels(uniq_reg, region_name_map, prefix=''),rate_matrix[:,j],bottom=bottom,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bi,bar in enumerate(seg_bars):
                h=rate_matrix[bi,j]
                if h>0.02: ax0.text(bar.get_x()+bar.get_width()/2,bottom[bi]+h/2,f'{h:.1%}',ha='center',va='center',color='white',fontsize=7,fontweight='bold')
            bottom+=rate_matrix[:,j]
        ax0.set_xlabel('空间单元',color=th['subtext'],fontsize=10); ax0.set_ylabel('发生率',color=th['subtext'],fontsize=10)
        ax0.set_title('各空间单元行为发生率 (堆叠)',color=th['text'],fontsize=13,pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        bw=0.7/len(uniq_beh); xs=np.arange(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            bars_r=ax1.bar(xs+j*bw-0.35+bw/2,rate_matrix[:,j],width=bw,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bar in bars_r:
                h=bar.get_height()
                if h>0.01: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.04,f'{h:.1%}',ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(xs); ax1.set_xticklabels(_region_labels(uniq_reg, region_name_map, prefix=''),fontsize=8,rotation=30,ha='right')
        ax1.set_xlabel('空间单元',color=th['subtext'],fontsize=10); ax1.set_ylabel('发生率',color=th['subtext'],fontsize=10)
        ax1.set_title('各空间单元行为发生率 (分组)',color=th['text'],fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'total_records':int(len(df)),'behavior_types':len(uniq_beh),'behaviors':beh_labels,'region_count':int(len(uniq_reg))}}
    _run_metric('behavior_rate', _beh_rate)

    def _beh_entropy():
        if not beh_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'BehaviorNum','Region','t'}.issubset(df.columns): return None
        df = df.dropna(subset=['BehaviorNum','Region','t'])
        df = _clean_behavior_df(df, require_t=True)
        if len(df) == 0: return None
        beh_nums=df['BehaviorNum'].astype(int).values; regions=df['Region'].astype(int).values; t=df['t'].astype(float).values
        uniq_beh=np.sort(np.unique(beh_nums)); uniq_reg=np.sort(np.unique(regions))
        def entropy(probs): probs=probs[probs>0]; return float(-np.sum(probs*np.log2(probs))) if len(probs) else 0.0
        reg_entropy=[]
        for r in uniq_reg:
            r_mask=regions==r; total_t=t[r_mask].sum()
            probs=np.array([t[r_mask&(beh_nums==b)].sum()/total_t if total_t>0 else 0 for b in uniq_beh]); reg_entropy.append(entropy(probs))
        user_ids_col=df['UserID'].values if 'UserID' in df.columns else np.arange(len(df))
        uniq_users=np.unique(user_ids_col); user_entropy=[]
        for u in uniq_users:
            u_mask=user_ids_col==u; total_t=t[u_mask].sum()
            probs=np.array([t[u_mask&(beh_nums==b)].sum()/total_t if total_t>0 else 0 for b in uniq_beh]); user_entropy.append(entropy(probs))
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0,th)
        _bar_common(ax0,_region_labels(uniq_reg, region_name_map),reg_entropy,color=th['accent'],xlabel='空间单元',ylabel='行为熵值 (bits)',th=th)
        ax0.set_title('各空间单元行为复合度',color=th['text'],fontsize=13,pad=10)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        _bar_common(ax1,uniq_users,user_entropy,color='#00c9a7',ylabel='行为熵值 (bits)',th=th)
        _set_sparse_xticks(ax1, uniq_users)
        ax1.set_title('各使用者行为复合度',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'region_count':int(len(uniq_reg)),'user_count':int(len(uniq_users)),'avg_reg_entropy':round(float(np.mean(reg_entropy)),2),'max_reg_entropy':round(float(np.max(reg_entropy)),2),'min_reg_entropy':round(float(np.min(reg_entropy)),2),'behavior_types':int(len(uniq_beh))}}
    _run_metric('behavior_entropy', _beh_entropy)

    # ── C5 功能利用率 ──
    def _util():
        if not beh_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'BehaviorNum','Region','t'}.issubset(df.columns): return None
        df = df.dropna(subset=['BehaviorNum','Region','t'])
        df = _clean_behavior_df(df, require_t=True)
        if len(df) == 0: return None
        beh_nums=df['BehaviorNum'].astype(int).values; regions=df['Region'].astype(int).values; t=df['t'].astype(float).values
        beh_labels_map=df.groupby('BehaviorNum')['behaviortype'].first().to_dict() if 'behaviortype' in df.columns else {b:f'行为{b}' for b in np.unique(beh_nums)}
        uniq_beh=np.sort(np.unique(beh_nums)); uniq_reg=np.sort(np.unique(regions)); beh_labels=[str(beh_labels_map.get(b,b)) for b in uniq_beh]
        dur_matrix=np.zeros((len(uniq_reg),len(uniq_beh)))
        for i,r in enumerate(uniq_reg):
            for j,b in enumerate(uniq_beh): dur_matrix[i,j]=t[(regions==r)&(beh_nums==b)].sum()
        if region_b:
            rdf=load_df(mk(region_b,region_n)); areas={}
            for rid in rdf['Region'].unique():
                pts=rdf[rdf['Region']==rid][['X','Y']].values
                if len(pts)>=3:
                    pts_c=np.vstack([pts,pts[0]]); a=0.5*abs(np.sum(pts_c[:-1,0]*pts_c[1:,1]-pts_c[1:,0]*pts_c[:-1,1])); areas[rid]=a/(SCALE**2)
                else: areas[rid]=1.0
            reg_areas=np.array([areas.get(r,1.0) for r in uniq_reg])
        else:
            reg_areas=np.ones(len(uniq_reg))
        util_matrix=dur_matrix/reg_areas[:,np.newaxis]
        total_util=util_matrix.sum(axis=1)
        with np.errstate(divide='ignore', invalid='ignore'):
            util_share_matrix=np.divide(
                util_matrix,
                total_util[:,np.newaxis],
                out=np.zeros_like(util_matrix),
                where=total_util[:,np.newaxis]>0,
            )
        palette=_get_cmap('tab10',len(uniq_beh))
        fig0,ax0=plt.subplots(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0,th); bottom=np.zeros(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            seg_bars=ax0.bar(_region_labels(uniq_reg, region_name_map, prefix=''),util_share_matrix[:,j],bottom=bottom,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bi,bar in enumerate(seg_bars):
                h=util_share_matrix[bi,j]
                if h>0.02: ax0.text(bar.get_x()+bar.get_width()/2,bottom[bi]+h/2,f'{h:.1%}',ha='center',va='center',color='white',fontsize=7,fontweight='bold')
            bottom+=util_share_matrix[:,j]
        ax0.set_xlabel('空间单元',color=th['subtext'],fontsize=10); ax0.set_ylabel('占比',color=th['subtext'],fontsize=10)
        ax0.set_title('各空间单元功能利用率占比 (堆叠)',color=th['text'],fontsize=13,pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1,ax1=plt.subplots(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        _bar_common(ax1,_region_labels(uniq_reg, region_name_map),total_util,color='#f5a623',xlabel='空间单元',ylabel='s/㎡',th=th)
        global_util=dur_matrix.sum()/reg_areas.sum() if reg_areas.sum()>0 else 0
        ax1.axhline(global_util,color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'全局均值 {global_util:.2f}')
        _legend_upper_right(ax1, th)
        ax1.set_title('各空间单元总功能利用率',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'region_count':int(len(uniq_reg)),'behavior_types':int(len(uniq_beh)),'global_util':round(float(global_util),2),'avg_util':round(float(total_util.mean()),2),'max_util':round(float(total_util.max()),2),'min_util':round(float(total_util.min()),2),'behaviors':beh_labels}}
    _run_metric('utilization', _util)

    # ── D3 整体满意度 ──
    def _satisfaction_fn():
        if not ques1_b: return None
        df=load_df(mk(ques1_b,ques1_n))
        score_col = 'Satisfaction' if 'Satisfaction' in df.columns else 'Satisfaction1'
        if not {'UserNum', score_col}.issubset(df.columns): return None
        user_ids=df['UserNum'].values; scores=df[score_col].astype(float).values; avg_score=float(scores.mean())
        # 仅生成右侧分布直方图（左侧个人评分改为前端Canvas交互图）
        fig,ax1=plt.subplots(1,1,figsize=(7,6)); fig.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1,th)
        bins=[0,60,70,80,90,100]; counts,_=np.histogram(scores,bins=bins)
        bars_h=ax1.bar(['<60','60-70','70-80','80-90','90-100'],counts,color='#a78bfa',alpha=0.85,width=0.6)
        for bar in bars_h:
            h=bar.get_height()
            if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+0.2,str(int(h)),ha='center',va='bottom',color=th['bar_label'],fontsize=9)
        ax1.set_xlabel('分数段',color=th['subtext'],fontsize=10); ax1.set_ylabel('人数',color=th['subtext'],fontsize=10)
        ax1.set_title('满意度分布',color=th['text'],fontsize=13)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        ax1.axhline(avg_score, color='#ff5e5e', linestyle='--', linewidth=1.5, label=f'均值 {avg_score:.2f}')
        _legend_upper_right(ax1, th)
        plt.tight_layout(pad=2); img_dist_b64=fig_to_base64(fig); plt.close(fig)
        bar_data=[[str(uid),float(s)] for uid,s in zip(user_ids,scores)]
        return {'image':img_dist_b64,'image_dist':img_dist_b64,'bar_data':bar_data,'avg_score':round(avg_score,1),'summary':{'total_users':int(len(df)),'avg_score':round(avg_score,1),'max_score':int(scores.max()),'min_score':int(scores.min())}}
    _run_metric('satisfaction', _satisfaction_fn)

    # ── D4 空间区域满意度 ──
    def _sat_region():
        if not ques2_b: return None
        df=load_df(mk(ques2_b,ques2_n))
        if 'UserNum' not in df.columns: return None
        region_cols = [c for c in df.columns if c != 'UserNum']
        if not region_cols: return None
        avg_vals=df[region_cols].apply(pd.to_numeric, errors='coerce').mean().values
        reg_ids=[]
        for c in region_cols:
            try: reg_ids.append(int(str(c).replace('Satisfaction','')))
            except: reg_ids.append(str(c))
        avg_score=float(avg_vals.mean())
        reg_labels = _region_labels(reg_ids, region_name_map, prefix='')
        fig0=plt.figure(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0=fig0.add_subplot(111); _styled_axes(ax0,th)
        colors=['#7c5cfc' if v>=avg_score else '#00c9a7' for v in avg_vals]
        bars_r=ax0.bar(reg_labels,avg_vals,color=colors,alpha=0.85,width=0.6)
        for bar in bars_r:
            h=bar.get_height()
            ax0.text(bar.get_x()+bar.get_width()/2,h+1,f'{h:.2f}',ha='center',va='bottom',color=th['bar_label'],fontsize=8)
        ax0.axhline(avg_score,color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'均值 {avg_score:.2f}')
        ax0.set_xlabel('空间单元',color=th['subtext'],fontsize=10); ax0.set_ylabel('满意度均值',color=th['subtext'],fontsize=10)
        ax0.set_title('各空间单元满意度',color=th['text'],fontsize=13,pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1=plt.figure(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        ax1=fig1.add_subplot(111,polar=True); ax1.set_facecolor(th['ax_bg2'])
        theta=np.linspace(0,2*np.pi,len(reg_ids),endpoint=False)
        vals_r=np.append(avg_vals,avg_vals[0]); theta_r=np.append(theta,theta[0])
        ax1.plot(theta_r,vals_r,color=th['accent'],linewidth=2); ax1.fill(theta_r,vals_r,color=th['accent'],alpha=0.2)
        for i,(th_i,val) in enumerate(zip(theta,avg_vals)):
            ax1.annotate(f'{val:.2f}',(th_i,val),xytext=(0,6),textcoords='offset points',ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(theta); ax1.set_xticklabels(reg_labels,color=th['subtext'],fontsize=8)
        ax1.tick_params(colors=th['cbar_tick']); ax1.set_title('区域满意度雷达',color=th['text'],fontsize=13,pad=15)
        ax1.spines['polar'].set_color('#2d2d3d'); ax1.grid(color=th['grid'],linewidth=0.5)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'region_count':int(len(reg_ids)),'avg_score':round(avg_score,2),'max_score':round(float(np.max(avg_vals)),2),'min_score':round(float(np.min(avg_vals)),2),'best_region':str(reg_ids[int(np.argmax(avg_vals))]),'worst_region':str(reg_ids[int(np.argmin(avg_vals))])}}
    _run_metric('satisfaction_region', _sat_region)

    # ── D5 设计要素满意度 ──
    def _sat_design():
        if not ques3_b: return None
        df=load_df(mk(ques3_b,ques3_n))
        if 'UserNum' not in df.columns: return None
        design_cols = [c for c in df.columns if c != 'UserNum']
        if not design_cols: return None
        avg_vals=df[design_cols].apply(pd.to_numeric, errors='coerce').mean().values
        factor_ids=[str(c).replace('设计要素', '') for c in design_cols]
        avg_score=float(avg_vals.mean())
        fig0=plt.figure(figsize=(9,6)); fig0.patch.set_facecolor(th['fig_bg'])
        ax0=fig0.add_subplot(111); _styled_axes(ax0,th)
        colors=['#7c5cfc' if v>=avg_score else '#00c9a7' for v in avg_vals]
        bars_f=ax0.bar([str(r) for r in factor_ids],avg_vals,color=colors,alpha=0.85,width=0.6)
        for bar in bars_f:
            h=bar.get_height()
            ax0.text(bar.get_x()+bar.get_width()/2,h+1,f'{h:.2f}',ha='center',va='bottom',color=th['bar_label'],fontsize=8)
        ax0.axhline(avg_score,color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'均值 {avg_score:.2f}')
        ax0.set_xlabel('设计要素编号',color=th['subtext'],fontsize=10); ax0.set_ylabel('满意度均值',color=th['subtext'],fontsize=10)
        ax0.set_title('各设计要素满意度',color=th['text'],fontsize=13,pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig0); plt.close(fig0)
        fig1=plt.figure(figsize=(9,6)); fig1.patch.set_facecolor(th['fig_bg'])
        ax1=fig1.add_subplot(111,polar=True); ax1.set_facecolor(th['ax_bg2'])
        theta=np.linspace(0,2*np.pi,len(factor_ids),endpoint=False)
        vals_r=np.append(avg_vals,avg_vals[0]); theta_r=np.append(theta,theta[0])
        ax1.plot(theta_r,vals_r,color=th['accent'],linewidth=2); ax1.fill(theta_r,vals_r,color=th['accent'],alpha=0.2)
        ax1.set_xticks(theta); ax1.set_xticklabels([str(r) for r in factor_ids],color=th['subtext'],fontsize=8)
        ax1.tick_params(colors=th['cbar_tick']); ax1.set_title('设计要素满意度雷达',color=th['text'],fontsize=13,pad=15)
        ax1.spines['polar'].set_color('#2d2d3d'); ax1.grid(color=th['grid'],linewidth=0.5)
        plt.tight_layout(pad=2); img2_b64=fig_to_base64(fig1); plt.close(fig1)
        return {'image':img_b64,'image2':img2_b64,'summary':{'factor_count':int(len(factor_ids)),'avg_score':round(avg_score,2),'max_score':round(float(np.max(avg_vals)),2),'min_score':round(float(np.min(avg_vals)),2),'best_factor':str(factor_ids[int(np.argmax(avg_vals))]),'worst_factor':str(factor_ids[int(np.argmin(avg_vals))])}}
    _run_metric('satisfaction_design', _sat_design)

    # ── 全部完成，标记 status + 存入数据库 ──
    with _sess_lock:
        sess = _sessions.get(sid)
        if sess is not None:
            sess['status'] = 'done'
            _save_project_to_db(sid, sess)


def _save_project_to_db(sid, sess):
    # type: (str, dict) -> None
    """将会话结果写入本地数据库，并把结果持久化到磁盘文件夹（在后台线程调用，已持锁）"""
    try:
        from api.db import save_project as _db_save
        floorplan_b64  = _make_thumbnail(sess)
        result_folder  = _persist_results_to_disk(sid, sess)
        project_id = _db_save(
            name          = sess.get('project_name') or sess.get('folder') or '未命名项目',
            building_type = sess.get('type', ''),
            input_folder  = sess.get('folder_abs') or sess.get('folder', ''),  # 优先绝对路径
            session_id    = sid,
            computed      = sess.get('computed', []),
            skipped       = sess.get('skipped',  []),
            floorplan_b64 = floorplan_b64,
            files_md5     = sess.get('_files_md5'),
            result_folder = result_folder,
            source_files  = sess.get('source_files'),  # 绝对路径表，供历史项目点击打开
            floor_info    = sess.get('floor_info', '0'),
            collection_date = sess.get('collection_date', ''),
        )
        sess['project_id'] = project_id
    except Exception:
        pass  # 数据库写失败不影响主流程


def _persist_results_to_disk(sid, sess):
    # type: (str, dict) -> object
    """
    将会话中所有已计算指标的图片和摘要持久化到磁盘。
    目录结构：~/.spacelens/results/<sid>/
      images/<指标英文名>.png
      summary.json
      meta.json          ← building_type / project_name / computed / skipped
    返回保存目录的绝对路径，失败返回 None。
    """
    try:
        import os as _os
        from pathlib import Path as _Path

        base_dir = _os.environ.get('SPACELENS_DATA_DIR', '') or str(_Path.home() / '.spacelens')
        result_dir = _os.path.join(base_dir, 'results', sid)
        _os.makedirs(_os.path.join(result_dir, 'images'), exist_ok=True)
        _os.makedirs(_os.path.join(result_dir, 'inputs'), exist_ok=True)

        results  = sess.get('results',  {})
        computed = sess.get('computed', [])
        source_file_copies = {}
        for slot, (bytes_key, name_key, _path_field) in _INPUT_SLOTS.items():
            data = sess.get(bytes_key)
            if not data:
                continue
            copy_name = _safe_input_filename(slot, sess.get(name_key))
            copy_path = _os.path.join(result_dir, 'inputs', copy_name)
            try:
                with open(copy_path, 'wb') as f:
                    f.write(data)
                source_file_copies[slot] = copy_path
            except Exception:
                pass

        all_summary = {}
        for metric_id in computed:
            data = results.get(metric_id)
            if not data:
                continue
            # 保存图片
            if data.get('image'):
                img_path = _os.path.join(result_dir, 'images', f'{metric_id}.png')
                with open(img_path, 'wb') as f:
                    f.write(base64.b64decode(data['image']))
            # 收集摘要
            if data.get('summary'):
                all_summary[metric_id] = data['summary']

        # 写 summary.json
        with open(_os.path.join(result_dir, 'summary.json'), 'w', encoding='utf-8') as f:
            _json.dump(all_summary, f, ensure_ascii=False, indent=2)

        # 写 meta.json（存储 session 元信息，恢复时用）
        meta = {
            'sid':           sid,
            'project_name':  sess.get('project_name', ''),
            'building_type': sess.get('type', ''),
            'folder_name':   sess.get('folder', ''),
            'folder_abs':    sess.get('folder_abs', ''),   # 绝对路径
            'floor_info':    sess.get('floor_info', '0'),
            'collection_date': sess.get('collection_date', ''),
            'computed':      computed,
            'skipped':       sess.get('skipped', []),
            'theme':         sess.get('theme', 'light'),
            'accent':        sess.get('accent', '#0ea5e9'),
            'source_files':  sess.get('source_files', {}),  # 绝对路径，用于"数据来源"点击打开
            'source_file_copies': source_file_copies,
            'region_name_map': sess.get('region_name_map', {}),
        }
        with open(_os.path.join(result_dir, 'meta.json'), 'w', encoding='utf-8') as f:
            _json.dump(meta, f, ensure_ascii=False, indent=2)

        return result_dir
    except Exception:
        return None


def _make_thumbnail(sess, max_size=200):
    # type: (dict, int) -> object
    """从会话中取平面图，生成缩略图 base64"""
    try:
        # 优先取已存储的原始图片字节
        img_bytes = sess.get('_raw_img_b')
        if not img_bytes:
            return None
        from PIL import Image as _PIL_Image
        img = _PIL_Image.open(io.BytesIO(img_bytes)).convert('RGB')
        img.thumbnail((max_size, max_size), _PIL_Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=75)
        buf.seek(0)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.read()).decode()
    except Exception:
        return None


@analysis_bp.route('/run_all', methods=['POST'])
def run_all():
    """
    接收：layout_img, loc_data, behavior_data, env_data,
    ques_data_overall, ques_data_region, ques_data_design, region_data (optional)
    立即返回 { session_id }，后台线程异步计算各指标并写入缓存。
    """
    try:
        # 读取文件为 bytes（FileStorage 只能读一次，请求结束后就无效）
        def _read(key):
            f = request.files.get(key)
            if f is None:
                return None, None
            return _clone_file(f), f.filename

        img_b, img_n       = _read('layout_img')
        loc_b, loc_n       = _read('loc_data')
        beh_b, beh_n       = _read('behavior_data')
        env_b, env_n       = _read('env_data')
        ques1_b, ques1_n   = _read('ques_data_overall')
        ques2_b, ques2_n   = _read('ques_data_region')
        ques3_b, ques3_n   = _read('ques_data_design')
        region_b, region_n = _read('region_data')
        bgmask_b, bgmask_n = _read('background_img')
        source_project_id = request.form.get('source_project_id', '').strip()
        changed_slots = [str(s) for s in _parse_json_list(request.form.get('changed_slots', '[]')) if str(s) in _INPUT_SLOTS]
        only_metrics = _metrics_for_changed_slots(changed_slots) if changed_slots else set()
        previous_sess = None
        if source_project_id:
            try:
                from api.db import get_project as _get_project
                proj_prev = _get_project(int(source_project_id))
                if proj_prev:
                    prev_sid = proj_prev.get('session_id')
                    with _sess_lock:
                        previous_sess = _sessions.get(prev_sid)
                    if previous_sess is None and proj_prev.get('result_folder'):
                        previous_sess = _restore_session_from_disk(prev_sid, proj_prev.get('result_folder'))
                        if previous_sess:
                            with _sess_lock:
                                _sessions[prev_sid] = previous_sess
            except Exception:
                previous_sess = None

        # 读取前端传来的源文件路径（用于结果页「数据来源」点击打开）
        img_path    = request.form.get('layout_img_path',    img_n    or '')
        loc_path    = request.form.get('loc_data_path',      loc_n    or '')
        beh_path    = request.form.get('behavior_data_path', beh_n    or '')
        env_path    = request.form.get('env_data_path',           env_n    or '')
        ques1_path  = request.form.get('ques_data_overall_path',  ques1_n  or '')
        ques2_path  = request.form.get('ques_data_region_path',   ques2_n  or '')
        ques3_path  = request.form.get('ques_data_design_path',   ques3_n  or '')
        region_path = request.form.get('region_data_path',        region_n or '')
        bgmask_path = request.form.get('background_img_path',      bgmask_n or '')

        # 桌面端：尝试解析为绝对路径（Qt chooseFiles 已注入）
        def _best_path(raw, filename):
            abs_p = _resolve_abs_path(filename or raw)
            return abs_p if abs_p else (raw or filename or '')

        img_path    = _best_path(img_path,    img_n)
        loc_path    = _best_path(loc_path,    loc_n)
        beh_path    = _best_path(beh_path,    beh_n)
        env_path    = _best_path(env_path,    env_n)
        ques1_path  = _best_path(ques1_path,  ques1_n)
        ques2_path  = _best_path(ques2_path,  ques2_n)
        ques3_path  = _best_path(ques3_path,  ques3_n)
        region_path = _best_path(region_path, region_n)
        bgmask_path = _best_path(bgmask_path, bgmask_n)

        def _fill_from_source(data, name, path, slot):
            if data:
                return data, name
            restored = _read_source_path(path)
            if not restored:
                if previous_sess:
                    bytes_key, name_key, _path_field = _INPUT_SLOTS[slot]
                    restored = previous_sess.get(bytes_key)
                    if restored:
                        return restored, name or previous_sess.get(name_key)
                    copy_path = previous_sess.get('source_file_copies', {}).get(slot)
                    restored = _read_source_path(copy_path)
                    if restored:
                        import os as _os_copy
                        return restored, name or _os_copy.path.basename(copy_path)
                return data, name
            import os as _os_src
            return restored, name or _os_src.path.basename(path)

        img_b, img_n       = _fill_from_source(img_b, img_n, img_path, 'img')
        loc_b, loc_n       = _fill_from_source(loc_b, loc_n, loc_path, 'loc')
        beh_b, beh_n       = _fill_from_source(beh_b, beh_n, beh_path, 'beh')
        env_b, env_n       = _fill_from_source(env_b, env_n, env_path, 'env')
        ques1_b, ques1_n   = _fill_from_source(ques1_b, ques1_n, ques1_path, 'ques1')
        ques2_b, ques2_n   = _fill_from_source(ques2_b, ques2_n, ques2_path, 'ques2')
        ques3_b, ques3_n   = _fill_from_source(ques3_b, ques3_n, ques3_path, 'ques3')
        region_b, region_n = _fill_from_source(region_b, region_n, region_path, 'region')
        bgmask_b, bgmask_n = _fill_from_source(bgmask_b, bgmask_n, bgmask_path, 'bgmask')

        # 从已解析的绝对路径推导文件夹绝对路径
        # 先直接查路径表里是否有文件夹名的记录（文件夹选择时注入的）
        import os as _os_r
        _abs_folder = None
        _folder_name_hint = request.form.get('folder_name', '')
        if _folder_name_hint:
            with _file_paths_lock:
                _abs_folder = _file_abs_paths.get(_folder_name_hint)

        def _abs_folder_from_sources(*paths):
            for p in paths:
                if p and _os_r.path.isabs(p) and _os_r.path.exists(p):
                    return _os_r.path.dirname(p)
            return None

        if not _abs_folder:
            _abs_folder = _abs_folder_from_sources(
                img_path, loc_path, beh_path, env_path, ques1_path, ques2_path, ques3_path, region_path, bgmask_path
            )

        # 计算各文件 MD5，用于去重
        import hashlib as _hashlib
        def _md5(b): return _hashlib.md5(b).hexdigest() if b else None
        files_md5 = {
            'img':    _md5(img_b),
            'loc':    _md5(loc_b),
            'beh':    _md5(beh_b),
            'env':    _md5(env_b),
            'ques1':  _md5(ques1_b),
            'ques2':  _md5(ques2_b),
            'ques3':  _md5(ques3_b),
            'region': _md5(region_b),
            'bgmask': _md5(bgmask_b),
        }

        building_type = request.form.get('building_type', 'unknown')
        folder_name   = request.form.get('folder_name',   '')
        project_name  = request.form.get('project_name',  '')
        floor_info    = (request.form.get('floor_info', '0') or '0').strip() or '0'
        collection_date = (request.form.get('collection_date', '') or '').strip() or _default_collection_date()
        theme_name    = request.form.get('theme', 'dark')
        accent_param  = request.form.get('accent', '')
        region_name_map = _parse_region_name_map(request.form.get('region_name_map', ''))

        th = _theme(theme_name)
        if accent_param:
            th['accent'] = accent_param

        # 立即创建会话（status = 'running'）
        sid = str(uuid.uuid4())
        initial_results = {}
        initial_computed = []
        initial_skipped = []
        if previous_sess and only_metrics:
            initial_results = {
                k: v for k, v in previous_sess.get('results', {}).items()
                if k not in only_metrics
            }
            initial_computed = [
                k for k in previous_sess.get('computed', [])
                if k not in only_metrics
            ]
            initial_skipped = [
                k for k in previous_sess.get('skipped', [])
                if k not in only_metrics
            ]
        with _sess_lock:
            _prune_sessions()
            _sessions[sid] = {
                'results':  initial_results,
                'computed': initial_computed,
                'skipped':  initial_skipped,
                'type':     building_type,
                'folder':   folder_name,
                'folder_abs': _abs_folder or '',   # 绝对路径（用于数据库展示）
                'project_name': project_name or folder_name or '未命名项目',
                'floor_info': floor_info,
                'collection_date': collection_date,
                'ts':       _time.time(),
                'status':   'running',
                '_raw_img_b': img_b,     # 保留原图用于生成缩略图
                '_img_b': img_b,
                '_img_n': img_n,
                '_loc_b': loc_b,
                '_loc_n': loc_n,
                '_beh_b': beh_b,
                '_beh_n': beh_n,
                '_env_b': env_b,
                '_env_n': env_n,
                '_ques1_b': ques1_b,
                '_ques1_n': ques1_n,
                '_ques2_b': ques2_b,
                '_ques2_n': ques2_n,
                '_ques3_b': ques3_b,
                '_ques3_n': ques3_n,
                '_region_b': region_b,
                '_region_n': region_n,
                '_bgmask_b': bgmask_b,
                '_bgmask_n': bgmask_n,
                '_files_md5': files_md5, # 各文件 MD5，用于去重
                'source_files': {        # 各源文件名/相对路径（用于结果页展示）
                    'img':    img_path    or None,
                    'loc':    loc_path    or None,
                    'beh':    beh_path    or None,
                    'env':    env_path    or None,
                    'ques1':  ques1_path  or None,
                    'ques2':  ques2_path  or None,
                    'ques3':  ques3_path  or None,
                    'region': region_path or None,
                    'bgmask': bgmask_path or None,
                },
                'region_name_map': region_name_map,
                '_debug_img_b': img_b[:4] if img_b else None,
                '_debug_loc_b': loc_b[:4] if loc_b else None,
                '_debug_beh_b': beh_b[:4] if beh_b else None,
                '_debug_env_b': env_b[:4] if env_b else None,
                '_debug_ques1_b': ques1_b[:4] if ques1_b else None,
                '_debug_ques2_b': ques2_b[:4] if ques2_b else None,
                '_debug_ques3_b': ques3_b[:4] if ques3_b else None,
                '_debug_files': {
                    'img': (img_n, len(img_b) if img_b else 0),
                    'loc': (loc_n, len(loc_b) if loc_b else 0),
                    'beh': (beh_n, len(beh_b) if beh_b else 0),
                    'env': (env_n, len(env_b) if env_b else 0),
                    'ques1': (ques1_n, len(ques1_b) if ques1_b else 0),
                    'ques2': (ques2_n, len(ques2_b) if ques2_b else 0),
                    'ques3': (ques3_n, len(ques3_b) if ques3_b else 0),
                    'region': (region_n, len(region_b) if region_b else 0),
                    'bgmask': (bgmask_n, len(bgmask_b) if bgmask_b else 0),
                },
            }

        # 启动后台线程
        t = _threading.Thread(
            target=_bg_compute,
            args=(sid, img_b, img_n, loc_b, loc_n, beh_b, beh_n,
                  env_b, env_n, ques1_b, ques1_n, ques2_b, ques2_n, ques3_b, ques3_n,
                  region_b, region_n, bgmask_b, bgmask_n, th, region_name_map, only_metrics),
            daemon=True,
        )
        t.start()

        # 立即返回 session_id，前端跳转结果页后轮询
        return jsonify({'session_id': sid})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# /api/session/<sid>  —  读取会话缓存
# ─────────────────────────────────────────────
@analysis_bp.route('/session/<sid>/debug', methods=['GET'])
def debug_session(sid):
    """开发调试：返回每个指标的错误详情"""
    with _sess_lock:
        sess = _sessions.get(sid)
    if sess is None:
        return jsonify({'error': '会话不存在'}), 404
    details = {}
    for k, v in sess.get('results', {}).items():
        if isinstance(v, dict):
            details[k] = {
                'has_image': bool(v.get('image')),
                'error': v.get('error', ''),
                'traceback': v.get('traceback', ''),
            }
        else:
            details[k] = {'value': str(v)}
    return jsonify({
        'status': sess.get('status'),
        'computed': sess.get('computed'),
        'skipped': sess.get('skipped'),
        'files_received': sess.get('_debug_files', {}),
        'details': details,
    })


@analysis_bp.route('/session/<sid>', methods=['GET'])
def get_session(sid):
    with _sess_lock:
        sess = _sessions.get(sid)
    if sess is None:
        return jsonify({'error': '会话不存在或已过期'}), 404
    return jsonify({
        'session_id':    sid,
        'building_type': sess['type'],
        'folder_name':   sess.get('folder', ''),
        'project_name':  sess.get('project_name', ''),
        'project_id':    sess.get('project_id'),
        'floor_info':    sess.get('floor_info', '0'),
        'collection_date': sess.get('collection_date', ''),
        'computed':      sess.get('computed', []),
        'skipped':       sess.get('skipped',  []),
        'results':       sess.get('results',  {}),
        'status':        sess.get('status', 'running'),
        'source_files':  sess.get('source_files', {}),
        'region_name_map': sess.get('region_name_map', {}),
        'debug_errors':  {k: v.get('error','') for k, v in sess.get('results', {}).items() if isinstance(v, dict) and v.get('error')},
    })


@analysis_bp.route('/session/<sid>/cluster', methods=['POST'])
def recompute_session_cluster(sid):
    try:
        with _sess_lock:
            sess = _sessions.get(sid)
        if sess is None:
            return jsonify({'error': '会话不存在或已过期'}), 404

        loc_b = sess.get('_loc_b')
        loc_n = sess.get('_loc_n')
        img_b = sess.get('_img_b')
        img_n = sess.get('_img_n')
        if not loc_b or not img_b:
            return jsonify({'error': '当前会话缺少定位数据或平面图，无法重算空间聚类'}), 400

        try:
            k = int(request.json.get('k') if request.is_json else request.form.get('k', 5))
        except Exception:
            k = 5

        theme_name = request.json.get('theme', 'dark') if request.is_json else request.form.get('theme', 'dark')
        accent_param = request.json.get('accent', '') if request.is_json else request.form.get('accent', '')
        th = _theme(theme_name)
        if accent_param:
            th['accent'] = accent_param

        def _normalize_xy_session(df):
            try:
                arr = load_img(_make_fs(img_b, img_n))
                img_w, img_h = arr.shape[1], arr.shape[0]
            except Exception:
                return df
            if 'X' not in df.columns or 'Y' not in df.columns or len(df) == 0:
                return df
            x = pd.to_numeric(df['X'], errors='coerce').astype(float)
            y = pd.to_numeric(df['Y'], errors='coerce').astype(float)
            valid = np.isfinite(x) & np.isfinite(y)
            if not valid.any():
                return df
            xmin, xmax = float(np.nanmin(x[valid])), float(np.nanmax(x[valid]))
            ymin, ymax = float(np.nanmin(y[valid])), float(np.nanmax(y[valid]))
            need = (xmin < 0) or (ymin < 0) or (xmax > img_w) or (ymax > img_h)
            if not need:
                return df
            out = df.copy()
            if xmax > xmin:
                out.loc[valid, 'X'] = (x[valid] - xmin) / (xmax - xmin) * max(img_w - 1, 1)
            if ymax > ymin:
                out.loc[valid, 'Y'] = (y[valid] - ymin) / (ymax - ymin) * max(img_h - 1, 1)
            return out

        walkable_mask = None
        try:
            walkable_mask = extract_walkable_mask(load_img(_make_fs(img_b, img_n)))
        except Exception:
            walkable_mask = None

        result = _compute_cluster_result(
            _make_fs(loc_b, loc_n),
            _make_fs(img_b, img_n),
            k,
            th,
            normalize_xy_fn=_normalize_xy_session,
            walkable_mask=walkable_mask,
        )
        if result is None:
            return jsonify({'error': '数据不足，无法计算当前 K 值下的空间聚类'}), 400

        with _sess_lock:
            sess = _sessions.get(sid)
            if sess is None:
                return jsonify({'error': '会话不存在或已过期'}), 404
            sess['results']['cluster'] = result
            if 'cluster' not in sess['computed']:
                sess['computed'].append('cluster')
            if 'cluster' in sess['skipped']:
                sess['skipped'].remove('cluster')
            sess['ts'] = _time.time()

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@analysis_bp.route('/open_source/<sid>/<key>', methods=['POST'])
def open_source(sid, key):
    """
    桌面端专用：在资源管理器/Finder 中打开（或高亮）指定源文件。
    key: img | loc | beh | env | ques1 | ques2 | ques3 | region
    """
    import subprocess as _sub
    import sys as _sys
    import os as _os
    try:
        with _sess_lock:
            sess = _sessions.get(sid)
        if sess is None:
            return jsonify({'error': '会话不存在或已过期'}), 404

        source_files = sess.get('source_files', {})
        stored_path = source_files.get(key)
        if not stored_path:
            return jsonify({'error': '未记录该文件路径'}), 404

        # stored_path 可能是绝对路径（桌面端 Qt 注入）或仅文件名/相对路径
        abs_path = None

        # 1. 直接是绝对路径
        if _os.path.isabs(stored_path) and _os.path.exists(stored_path):
            abs_path = stored_path

        # 2. 再尝试用文件名从 Qt 路径表中查找（以防 run_all 时未注入）
        if abs_path is None:
            abs_path = _resolve_abs_path(stored_path)

        # 3. 相对路径拼凑（仅作兜底）
        if abs_path is None and ('/' in stored_path or '\\' in stored_path):
            home = _os.path.expanduser('~')
            for base in [home,
                         _os.path.join(home, 'Desktop'), _os.path.join(home, 'Documents'),
                         _os.path.join(home, 'Downloads'), _os.path.join(home, '桌面'),
                         _os.path.join(home, '文档'), _os.path.join(home, '下载')]:
                p = _os.path.join(base, stored_path)
                if _os.path.exists(p):
                    abs_path = p
                    break

        if abs_path is None:
            fname = _os.path.basename(stored_path.replace('\\', '/'))
            return jsonify({'warning': f'文件已上传处理，但无法定位原始路径。文件名：{fname}'}), 200

        # 在系统文件管理器中高亮该文件
        platform = _sys.platform
        if platform == 'darwin':
            _sub.Popen(['open', '-R', abs_path])
        elif platform == 'win32':
            # explorer /select, 需要整个命令作为单个字符串，否则含空格路径会出错
            _sub.Popen('explorer /select,"' + abs_path.replace('/', '\\') + '"', shell=True)
        else:
            _sub.Popen(['xdg-open', _os.path.dirname(abs_path)])

        return jsonify({'success': True, 'path': abs_path})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# /api/export_project/<sid>  —  导出项目结果（ZIP）
# ─────────────────────────────────────────────
import zipfile as _zipfile
import os as _os
import json as _json

# 指标中文名映射
_METRIC_NAMES = {
    'heatmap':             '到访频次热力图',
    'usetime':             '使用时长',
    'speed':               '移动速率',
    'duration':            '停留时长',
    'cluster':             '空间聚类',
    'density':             '人员密度',
    'openness':            '空间开放程度',
    'topology':            '拓扑连接关系',
    'difference':          '轨迹差异系数',
    'trajectory':          '轨迹长度',
    'environment_p1':      '环境参数_温度',
    'environment_p2':      '环境参数_湿度',
    'environment_p3':      '环境参数_光照',
    'environment_p4':      '环境参数_风速',
    'environment_p5':      '环境参数_噪声',
    'behavior_count':      '行为人次',
    'behavior_duration':   '行为时长',
    'behavior_rate':       '行为发生率',
    'behavior_entropy':    '行为复合度',
    'utilization':         '功能利用率',
    'satisfaction':        '整体满意度',
    'satisfaction_region': '空间满意度',
    'satisfaction_design': '设计要素满意度',
}

# 每个指标各子图的标题（用于保存文件名）
_METRIC_CHART_TITLES = {
    'heatmap':             ['到访频次热力图', '各空间单元到访频次'],
    'usetime':             ['空间使用时长热力图', '各空间单元使用时长'],
    'speed':               ['空间移动速率热力图', '各空间单元平均移动速率'],
    'duration':            ['空间停留时长热力图', '各空间单元停留时长'],
    'cluster':             ['空间聚类分析', '各聚类点位分布'],
    'density':             ['人员分布热力图', '各空间单元独立人员数'],
    'openness':            ['空间开放程度热力图', '各空间单元开放程度'],
    'topology':            ['区域人员转移矩阵', '各空间单元人员流入流出量', '区域拓扑网络图'],
    'difference':          ['人员轨迹长度差异系数', '区域流线长度差异系数'],
    'trajectory':          ['人员移动轨迹', '人员轨迹长度'],
    'environment_p1':      ['温度空间分布', '各测点温度值'],
    'environment_p2':      ['湿度空间分布', '各测点湿度值'],
    'environment_p3':      ['光照空间分布', '各测点光照值'],
    'environment_p4':      ['风速空间分布', '各测点风速值'],
    'environment_p5':      ['噪声空间分布', '各测点噪声值'],
    'behavior_count':      ['各行为发生分布', '各空间单元行为发生人次'],
    'behavior_duration':   ['行为时长热力图', '各空间单元行为时长'],
    'behavior_rate':       ['各空间单元行为发生率_堆叠', '各空间单元行为发生率_分组'],
    'behavior_entropy':    ['各空间单元行为复合度', '各使用者行为复合度'],
    'utilization':         ['各空间单元功能利用率占比_堆叠', '各空间单元总功能利用率'],
    'satisfaction':        ['整体满意度'],
    'satisfaction_region': ['各空间单元满意度'],
    'satisfaction_design': ['各设计要素满意度'],
}


def _build_project_zip(sid, sel_metrics, folder_name):
    """
    通用：将会话结果打包成 ZIP bytes。
    返回 (zip_bytes, safe_folder_name, error_str)
    """
    with _sess_lock:
        sess = _sessions.get(sid)
    if sess is None:
        return None, None, '会话不存在或已过期'

    safe_folder = ''.join(c if c not in r'\/:*?"<>|' else '_' for c in (folder_name or 'SpaceLens项目'))
    if not safe_folder:
        safe_folder = 'SpaceLens项目'

    results  = sess.get('results', {})
    computed = sess.get('computed', [])
    to_export = computed[:] if sel_metrics is None else [m for m in sel_metrics if m in computed]
    if not to_export:
        return None, safe_folder, '没有可导出的计算结果'

    buf = io.BytesIO()
    with _zipfile.ZipFile(buf, 'w', _zipfile.ZIP_DEFLATED) as zf:
        all_summary = {}
        for metric_id in to_export:
            data = results.get(metric_id)
            if not data:
                continue
            cn_name = _METRIC_NAMES.get(metric_id, metric_id)
            if data.get('image'):
                zf.writestr(f'images/{cn_name}.png', base64.b64decode(data['image']))
            summary = data.get('summary')
            if summary:
                all_summary[cn_name] = summary
                _write_summary_xlsx(zf, metric_id, cn_name, summary)

        zf.writestr('summary.json', _json.dumps(all_summary, ensure_ascii=False, indent=2))
        building_type = sess.get('type', '')
        readme = (
            f'项目名称：{folder_name}\n'
            f'建筑类型：{building_type}\n'
            f'导出指标数：{len(to_export)}\n'
            f'导出时间：{_time.strftime("%Y-%m-%d %H:%M:%S")}\n'
            '\n各子文件夹说明：\n'
            '  images/  — 指标结果图片（PNG）\n'
            '  data/    — 指标数值汇总（Excel）\n'
            '  summary.json — 全量数值摘要\n'
        )
        zf.writestr('README.txt', readme.encode('utf-8'))

    buf.seek(0)
    return buf.read(), safe_folder, None


@analysis_bp.route('/save_project/<sid>', methods=['POST'])
def save_project(sid):
    """
    桌面端专用：弹出原生文件保存对话框，将 ZIP 写到用户选择的路径。
    POST body JSON: { "metrics": [...], "folder_name": "..." }
    成功返回: { "success": true, "path": "..." }
    取消返回: { "cancelled": true }
    失败返回: { "error": "..." }
    """
    try:
        body        = request.get_json(silent=True) or {}
        sel_metrics = body.get('metrics', None)
        folder_name = body.get('folder_name', '') or 'SpaceLens项目'

        zip_bytes, safe_folder, err = _build_project_zip(sid, sel_metrics, folder_name)
        if err:
            return jsonify({'error': err}), 400

        zip_filename = f'{safe_folder}_评价结果.zip'

        # ── 1. 优先使用 Qt 原生对话框（桌面端） ──
        if _native_save_dialog_hook is not None:
            save_path = _native_save_dialog_hook('选择保存路径', zip_filename)
        else:
            # ── 2. 尝试 tkinter ──
            try:
                import tkinter as _tk
                import tkinter.filedialog as _fd
                root = _tk.Tk()
                root.withdraw()
                root.lift()
                root.attributes('-topmost', True)
                save_path = _fd.asksaveasfilename(
                    parent=root,
                    title='选择保存路径',
                    defaultextension='.zip',
                    initialfile=zip_filename,
                    filetypes=[('ZIP 压缩包', '*.zip'), ('所有文件', '*.*')],
                )
                root.destroy()
            except Exception:
                return jsonify({'error': '无法打开文件对话框（非桌面环境）'}), 500

        if not save_path:
            return jsonify({'cancelled': True})

        with open(save_path, 'wb') as f:
            f.write(zip_bytes)

        return jsonify({'success': True, 'path': save_path})

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'detail': traceback.format_exc()}), 500


@analysis_bp.route('/export_project/<sid>', methods=['POST'])
def export_project(sid):
    """原始 blob 下载端点（浏览器环境保留）"""
    try:
        body        = request.get_json(silent=True) or {}
        sel_metrics = body.get('metrics', None)
        folder_name = body.get('folder_name', '') or 'SpaceLens项目'

        zip_bytes, safe_folder, err = _build_project_zip(sid, sel_metrics, folder_name)
        if err:
            status = 404 if '不存在' in err else 400
            return jsonify({'error': err}), status

        from flask import send_file
        buf = io.BytesIO(zip_bytes)
        return send_file(
            buf,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{safe_folder}_评价结果.zip',
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# /api/export_metric/<sid>/<metric_id>  —  单指标导出
# ─────────────────────────────────────────────

@analysis_bp.route('/export_metric/<sid>/<metric_id>', methods=['GET'])
def export_metric(sid, metric_id):
    """
    单指标导出：返回包含图片（PNG）和数值（Excel）的 ZIP 文件。
    支持 satisfaction 特殊处理（image_dist + bar_data）。
    """
    try:
        with _sess_lock:
            sess = _sessions.get(sid)
        if sess is None:
            return jsonify({'error': '会话不存在或已过期'}), 404

        results = sess.get('results', {})
        computed = sess.get('computed', [])

        # environment → 导出所有可用的 environment_pX 子结果
        actual_id = metric_id
        if metric_id == 'environment':
            env_ids = [f'environment_p{n}' for n in range(1, 6) if f'environment_p{n}' in computed]
            if not env_ids:
                return jsonify({'error': '环境参数尚未计算或无结果'}), 400
            cn_name_zip = '环境参数'
            folder_name = sess.get('folder', '') or 'SpaceLens'
            safe_folder = ''.join(c if c not in r'\/:*?"<>|' else '_' for c in folder_name)
            buf = io.BytesIO()
            with _zipfile.ZipFile(buf, 'w', _zipfile.ZIP_DEFLATED) as zf:
                for eid in env_ids:
                    edata = results.get(eid)
                    if not edata:
                        continue
                    ecn = _METRIC_NAMES.get(eid, eid)
                    img_b64 = edata.get('image')
                    if img_b64:
                        zf.writestr(f'{ecn}.png', base64.b64decode(img_b64))
                    summary = edata.get('summary')
                    if summary:
                        _write_summary_xlsx(zf, eid, ecn, summary)
            buf.seek(0)
            from flask import send_file as _send
            return _send(buf, mimetype='application/zip', as_attachment=True,
                         download_name=f'{safe_folder}_{cn_name_zip}.zip')

        data = results.get(actual_id)
        if not data:
            return jsonify({'error': f'指标 {metric_id} 尚未计算或无结果'}), 400

        cn_name = _METRIC_NAMES.get(actual_id, actual_id)
        folder_name = sess.get('folder', '') or 'SpaceLens'
        safe_folder = ''.join(c if c not in r'\/:*?"<>|' else '_' for c in folder_name)

        buf = io.BytesIO()
        with _zipfile.ZipFile(buf, 'w', _zipfile.ZIP_DEFLATED) as zf:
            # 图片：优先 image，其次 image_dist（satisfaction 专用）
            img_b64 = data.get('image') or data.get('image_dist')
            if img_b64:
                zf.writestr(f'{cn_name}.png', base64.b64decode(img_b64))

            # satisfaction bar_data → 写入 Excel
            bar_data = data.get('bar_data')
            if bar_data and actual_id == 'satisfaction':
                try:
                    wb_buf = io.BytesIO()
                    with pd.ExcelWriter(wb_buf, engine='openpyxl') as writer:
                        pd.DataFrame(bar_data, columns=['人员编号', '满意度得分']).to_excel(
                            writer, sheet_name='个人评分', index=False)
                        summary = data.get('summary')
                        if summary:
                            scalar_rows = [{'指标': k, '数值': v}
                                           for k, v in summary.items() if not isinstance(v, list)]
                            pd.DataFrame(scalar_rows).to_excel(
                                writer, sheet_name='摘要', index=False)
                    wb_buf.seek(0)
                    zf.writestr(f'{cn_name}.xlsx', wb_buf.read())
                except Exception:
                    pass
            else:
                summary = data.get('summary')
                if summary:
                    _write_summary_xlsx(zf, actual_id, cn_name, summary)

        buf.seek(0)
        from flask import send_file as _send
        return _send(
            buf,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{safe_folder}_{cn_name}.zip',
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@analysis_bp.route('/save_metric/<sid>/<metric_id>/<file_type>', methods=['POST'])
def save_metric(sid, metric_id, file_type):
    """
    桌面端专用：弹出原生保存对话框，保存单指标文件。
    file_type: 'img' | 'xlsx' | 'zip'
      - img:  保存单张 PNG 图片
      - xlsx: 保存单个 Excel 文件（仅数值，无图片）
      - zip:  保存 ZIP 压缩包（图片 + Excel 打包）
    成功返回: { "success": true, "path": "..." }
    取消返回: { "cancelled": true }
    """
    try:
        with _sess_lock:
            sess = _sessions.get(sid)
        if sess is None:
            return jsonify({'error': '会话不存在或已过期'}), 404

        results     = sess.get('results', {})
        computed    = sess.get('computed', [])
        folder_name = sess.get('folder', '') or 'SpaceLens'
        safe_folder = ''.join(c if c not in r'\/:*?"<>|' else '_' for c in folder_name)
        cn_name_map = _METRIC_NAMES  # shorthand

        def _open_dialog(title, default_name, ext, filetypes):
            # 构造 Qt 格式的文件过滤字符串（如 'PNG 图片 (*.png);;所有文件 (*)'）
            qt_filter = ';;'.join(
                f'{label} ({pattern})' for label, pattern in filetypes
            )
            if _native_save_dialog_hook is not None:
                return _native_save_dialog_hook(title, default_name, qt_filter)
            try:
                import tkinter as _tk
                import tkinter.filedialog as _fd
                root = _tk.Tk(); root.withdraw(); root.lift()
                root.attributes('-topmost', True)
                path = _fd.asksaveasfilename(
                    parent=root, title=title,
                    defaultextension=ext, initialfile=default_name,
                    filetypes=filetypes,
                )
                root.destroy()
                return path
            except Exception:
                return None

        # ── 辅助：构建单指标 Excel bytes ──
        def _build_xlsx_bytes(mid, data):
            wb_buf = io.BytesIO()
            with pd.ExcelWriter(wb_buf, engine='openpyxl') as writer:
                # satisfaction 特殊：写个人评分 sheet
                bar_data = data.get('bar_data')
                if bar_data and mid == 'satisfaction':
                    pd.DataFrame(bar_data, columns=['人员编号', '满意度得分']).to_excel(
                        writer, sheet_name='个人评分', index=False)
                summary = data.get('summary')
                if summary:
                    scalar_rows = [{'指标': k, '数值': v}
                                   for k, v in summary.items() if not isinstance(v, list)]
                    if scalar_rows:
                        pd.DataFrame(scalar_rows).to_excel(writer, sheet_name='摘要', index=False)
                    for fk, fv in summary.items():
                        if isinstance(fv, list) and fv:
                            first = fv[0]
                            if isinstance(first, dict):
                                pd.DataFrame(fv).to_excel(writer, sheet_name=fk[:31], index=False)
                            else:
                                pd.DataFrame({fk: fv}).to_excel(writer, sheet_name=fk[:31], index=False)
            wb_buf.seek(0)
            return wb_buf.read()

        # ── 辅助：获取图片 b64 列表 ──
        def _get_img_b64_list(mid, actual):
            """返回 [(chart_title, b64), ...] 用于多图保存，chart_title 用于文件名"""
            if mid == 'satisfaction':
                b64 = results.get('satisfaction', {}).get('image_dist')
                return [('整体满意度', b64)] if b64 else []
            data = results.get(actual, {})
            chart_titles = _METRIC_CHART_TITLES.get(actual, [])
            imgs = []
            for idx, key in enumerate(['image', 'image2', 'image3']):
                b64 = data.get(key)
                if b64:
                    title = chart_titles[idx] if idx < len(chart_titles) else f'{_METRIC_NAMES.get(actual, actual)}_{idx+1}'
                    imgs.append((title, b64))
            return imgs

        # ════════════════════════════════════
        # file_type == 'img'  →  保存图片（多图时直接保存所有）
        # ════════════════════════════════════
        if file_type == 'img':
            actual_id = metric_id
            if metric_id == 'environment':
                pn = request.args.get('pn', '1')
                actual_id = f'environment_p{pn}'
            cn_name = cn_name_map.get(actual_id, actual_id)
            img_list = _get_img_b64_list(metric_id, actual_id)
            if not img_list:
                return jsonify({'error': '暂无图片数据'}), 400

            if len(img_list) == 1:
                # 单图：弹一次对话框，文件名即图表标题
                chart_title = img_list[0][0]
                default_name = f'{safe_folder}_{chart_title}.png'
                save_path = _open_dialog('保存图片', default_name, '.png',
                                         [('PNG 图片', '*.png'), ('所有文件', '*.*')])
                if save_path is None:
                    return jsonify({'error': '无法打开文件对话框'}), 500
                if not save_path:
                    return jsonify({'cancelled': True})
                with open(save_path, 'wb') as f:
                    f.write(base64.b64decode(img_list[0][1]))
                return jsonify({'success': True, 'path': save_path})
            else:
                # 多图：选保存目录，各图用自己的标题命名
                import os as _os_dialog
                first_title = img_list[0][0]
                default_name = f'{safe_folder}_{first_title}.png'
                save_path = _open_dialog(f'选择保存位置（共{len(img_list)}张，将按图表名称保存）',
                                         default_name, '.png',
                                         [('PNG 图片', '*.png'), ('所有文件', '*.*')])
                if save_path is None:
                    return jsonify({'error': '无法打开文件对话框'}), 500
                if not save_path:
                    return jsonify({'cancelled': True})
                save_dir = _os_dialog.path.dirname(save_path)
                saved_paths = []
                for chart_title, b64 in img_list:
                    safe_title = ''.join(c if c not in r'\/:*?"<>|' else '_' for c in chart_title)
                    p = _os_dialog.path.join(save_dir, f'{safe_folder}_{safe_title}.png')
                    with open(p, 'wb') as f:
                        f.write(base64.b64decode(b64))
                    saved_paths.append(p)
                return jsonify({'success': True, 'path': saved_paths[0], 'all_paths': saved_paths})

        # ════════════════════════════════════
        # file_type == 'xlsx'  →  保存单个 Excel
        # ════════════════════════════════════
        elif file_type == 'xlsx':
            if metric_id == 'environment':
                # 多参数：合并到一个 workbook，每个参数一个 sheet
                env_ids = [f'environment_p{n}' for n in range(1, 6)
                           if f'environment_p{n}' in computed]
                if not env_ids:
                    return jsonify({'error': '环境参数尚未计算'}), 400
                wb_buf = io.BytesIO()
                with pd.ExcelWriter(wb_buf, engine='openpyxl') as writer:
                    for eid in env_ids:
                        edata = results.get(eid, {})
                        ecn = cn_name_map.get(eid, eid)
                        summary = edata.get('summary', {})
                        if summary:
                            scalar_rows = [{'指标': k, '数值': v}
                                           for k, v in summary.items() if not isinstance(v, list)]
                            if scalar_rows:
                                pd.DataFrame(scalar_rows).to_excel(
                                    writer, sheet_name=ecn[:31], index=False)
                wb_buf.seek(0)
                xlsx_bytes = wb_buf.read()
                default_name = f'{safe_folder}_环境参数.xlsx'
            else:
                data = results.get(metric_id, {})
                if not data:
                    return jsonify({'error': '暂无数据'}), 400
                xlsx_bytes = _build_xlsx_bytes(metric_id, data)
                cn_name = cn_name_map.get(metric_id, metric_id)
                default_name = f'{safe_folder}_{cn_name}.xlsx'

            save_path = _open_dialog('保存 Excel', default_name, '.xlsx',
                                     [('Excel 文件', '*.xlsx'), ('所有文件', '*.*')])
            if save_path is None:
                return jsonify({'error': '无法打开文件对话框'}), 500
            if not save_path:
                return jsonify({'cancelled': True})
            with open(save_path, 'wb') as f:
                f.write(xlsx_bytes)
            return jsonify({'success': True, 'path': save_path})

        # ════════════════════════════════════
        # file_type == 'zip'  →  图片 + Excel 打包
        # ════════════════════════════════════
        elif file_type == 'zip':
            if metric_id == 'environment':
                env_ids = [f'environment_p{n}' for n in range(1, 6)
                           if f'environment_p{n}' in computed]
                if not env_ids:
                    return jsonify({'error': '环境参数尚未计算'}), 400
                buf = io.BytesIO()
                with _zipfile.ZipFile(buf, 'w', _zipfile.ZIP_DEFLATED) as zf:
                    for eid in env_ids:
                        edata = results.get(eid, {})
                        ecn = cn_name_map.get(eid, eid)
                        if edata.get('image'):
                            zf.writestr(f'{ecn}.png', base64.b64decode(edata['image']))
                        if edata.get('summary'):
                            _write_summary_xlsx(zf, eid, ecn, edata['summary'])
                buf.seek(0); zip_bytes = buf.read()
                default_name = f'{safe_folder}_环境参数.zip'
            else:
                data = results.get(metric_id, {})
                if not data:
                    return jsonify({'error': '暂无数据'}), 400
                cn_name = cn_name_map.get(metric_id, metric_id)
                buf = io.BytesIO()
                with _zipfile.ZipFile(buf, 'w', _zipfile.ZIP_DEFLATED) as zf:
                    # 图片
                    if metric_id == 'satisfaction':
                        img_b64 = data.get('image_dist')
                        if img_b64:
                            zf.writestr('满意度分布.png', base64.b64decode(img_b64))
                    else:
                        img_b64 = data.get('image')
                        if img_b64:
                            zf.writestr(f'{cn_name}.png', base64.b64decode(img_b64))
                    # Excel
                    xlsx_bytes = _build_xlsx_bytes(metric_id, data)
                    if xlsx_bytes:
                        zf.writestr(f'{cn_name}.xlsx', xlsx_bytes)
                buf.seek(0); zip_bytes = buf.read()
                default_name = f'{safe_folder}_{cn_name}.zip'

            save_path = _open_dialog('保存 ZIP', default_name, '.zip',
                                     [('ZIP 压缩包', '*.zip'), ('所有文件', '*.*')])
            if save_path is None:
                return jsonify({'error': '无法打开文件对话框'}), 500
            if not save_path:
                return jsonify({'cancelled': True})
            with open(save_path, 'wb') as f:
                f.write(zip_bytes)
            return jsonify({'success': True, 'path': save_path})

        else:
            return jsonify({'error': f'未知文件类型: {file_type}'}), 400

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'detail': traceback.format_exc()}), 500


def _write_summary_xlsx(zf, metric_id, cn_name, summary):
    """将一个指标的 summary dict 写入 ZIP 内的 data/<cn_name>.xlsx"""
    try:
        # 将 summary 中的列表字段（如 clusters、behaviors）展开为独立 sheet
        wb_buf = io.BytesIO()
        with pd.ExcelWriter(wb_buf, engine='openpyxl') as writer:
            # Sheet1: 主摘要（标量值）
            scalar_rows = []
            list_fields = {}
            for k, v in summary.items():
                if isinstance(v, list):
                    list_fields[k] = v
                else:
                    scalar_rows.append({'指标': k, '数值': v})

            if scalar_rows:
                pd.DataFrame(scalar_rows).to_excel(
                    writer, sheet_name='摘要', index=False)
            else:
                pd.DataFrame([{'说明': '无标量摘要'}]).to_excel(
                    writer, sheet_name='摘要', index=False)

            # 如有列表字段（如 clusters 详情），展开为额外 sheet
            for field_name, field_val in list_fields.items():
                if field_val and isinstance(field_val[0], dict):
                    pd.DataFrame(field_val).to_excel(
                        writer, sheet_name=field_name[:31], index=False)
                else:
                    pd.DataFrame({field_name: field_val}).to_excel(
                        writer, sheet_name=field_name[:31], index=False)

        wb_buf.seek(0)
        zf.writestr(f'data/{cn_name}.xlsx', wb_buf.read())
    except Exception:
        pass  # 单个 xlsx 写失败不影响整体 ZIP


# ─────────────────────────────────────────────
# 历史项目 API
# ─────────────────────────────────────────────

@analysis_bp.route('/projects/check_duplicate', methods=['POST'])
def api_check_duplicate():
    """
    检查即将创建的项目是否与历史记录重复。
    接受 multipart/form-data：building_type + 核心文件（img/loc/beh/env/ques1/ques2/ques3）。
    后端统一用 MD5 计算哈希，与数据库中存储的 MD5 进行比对。
    region 文件不参与去重（可选辅助文件）。
    返回:
      { duplicate: false }                          —— 未找到
      { duplicate: true, project: {id, name, ...} } —— 找到匹配记录
    """
    try:
        import hashlib as _hashlib
        import json as _j
        import sqlite3 as _sqlite3
        from api.db import _dedup_key, DB_PATH, _lock

        building_type = request.form.get('building_type', '').strip()
        floor_info = (request.form.get('floor_info', '0') or '0').strip() or '0'
        collection_date = (request.form.get('collection_date', '') or '').strip() or _default_collection_date()
        if not building_type:
            return jsonify({'duplicate': False})

        # 只对核心文件计算 MD5，与 run_all 保存时的键名完全一致
        def _md5(f):
            if f is None:
                return None
            b = f.read()
            f.seek(0)
            return _hashlib.md5(b).hexdigest() if b else None

        files_md5 = {
            'img':  _md5(request.files.get('img')),
            'loc':  _md5(request.files.get('loc')),
            'beh':  _md5(request.files.get('beh')),
            'env':  _md5(request.files.get('env')),
            'ques1': _md5(request.files.get('ques1')),
            'ques2': _md5(request.files.get('ques2')),
            'ques3': _md5(request.files.get('ques3')),
        }
        # 过滤掉 None 值后再计算 dedup_key
        files_md5_nonempty = {k: v for k, v in files_md5.items() if v}

        dedup_key = _dedup_key(files_md5_nonempty, building_type, floor_info, collection_date)
        if not dedup_key:
            return jsonify({'duplicate': False})

        # 在数据库中查找相同 dedup_key
        with _lock:
            conn = _sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.row_factory = _sqlite3.Row
            try:
                rows = conn.execute(
                    'SELECT * FROM projects WHERE building_type = ? AND floor_info = ? AND collection_date = ? AND files_md5 IS NOT NULL',
                    (building_type, floor_info, collection_date)
                ).fetchall()
                for row in rows:
                    try:
                        stored_md5_full = _j.loads(row['files_md5'] or '{}')
                    except Exception:
                        stored_md5_full = {}
                    # 只取核心键参与比对（忽略 region）
                    stored_md5_core = {k: v for k, v in stored_md5_full.items()
                                       if k in ('img', 'loc', 'beh', 'env', 'ques1', 'ques2', 'ques3') and v}
                    if _dedup_key(stored_md5_core, row['building_type'], row['floor_info'], row['collection_date']) == dedup_key:
                        p = dict(row)
                        p['computed'] = _j.loads(p.get('computed') or '[]')
                        p['skipped']  = _j.loads(p.get('skipped')  or '[]')
                        p.pop('files_md5', None)
                        return jsonify({'duplicate': True, 'project': p})
            finally:
                conn.close()

        return jsonify({'duplicate': False})
    except Exception as e:
        return jsonify({'duplicate': False, 'error': str(e)})

@analysis_bp.route('/projects', methods=['GET'])
def api_list_projects():
    """返回所有历史项目（不含 results 详情，只含基础信息+缩略图）"""
    try:
        from api.db import list_projects as _list
        projects = _list()
        # 每个记录只返回必要字段（不含完整 results 内容）
        result = []
        for p in projects:
            result.append({
                'id':            p['id'],
                'name':          p['name'],
                'building_type': p['building_type'],
                'input_folder':  p['input_folder'],
                'floor_info':    p.get('floor_info', '0'),
                'collection_date': p.get('collection_date', ''),
                'session_id':    p['session_id'],
                'computed':      p['computed'],
                'skipped':       p['skipped'],
                'floorplan_b64': p['floorplan_b64'],
                'created_at':    p['created_at'],
            })
        return jsonify({'projects': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@analysis_bp.route('/projects/<int:pid>', methods=['DELETE'])
def api_delete_project(pid):
    """删除历史项目记录"""
    try:
        from api.db import delete_project as _delete
        ok = _delete(pid)
        if ok:
            return jsonify({'success': True})
        return jsonify({'error': '记录不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@analysis_bp.route('/projects/<int:pid>/rename', methods=['POST'])
def api_rename_project(pid):
    """重命名历史项目"""
    try:
        from api.db import update_project_name as _rename
        body = request.get_json(silent=True) or {}
        name = (body.get('name') or '').strip()
        if not name:
            return jsonify({'error': '名称不能为空'}), 400
        ok = _rename(pid, name)
        if ok:
            return jsonify({'success': True})
        return jsonify({'error': '记录不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@analysis_bp.route('/projects/compare', methods=['GET'])
def api_compare_projects():
    """
    对比两个历史项目的结果数据。
    GET /api/projects/compare?pids=1,2
    返回:
      {
        projects: [
          { id, name, building_type, session_id, status('done'|'expired'),
            computed, skipped, results },
          { ... }
        ]
      }
    """
    try:
        from api.db import get_project as _get
        pids_raw = request.args.get('pids', '')
        pids = []
        for p in pids_raw.split(','):
            p = p.strip()
            if p.isdigit():
                pids.append(int(p))
        if len(pids) != 2:
            return jsonify({'error': '请传入恰好 2 个项目 ID，例如 ?pids=1,2'}), 400

        out = []
        for pid in pids:
            proj = _get(pid)
            if proj is None:
                return jsonify({'error': f'项目 {pid} 不存在'}), 404

            sid = proj['session_id']
            # 1. session 在内存
            with _sess_lock:
                sess = _sessions.get(sid)

            if sess is not None and sess.get('status') == 'done':
                out.append({
                    'id':            pid,
                    'name':          proj['name'],
                    'building_type': proj['building_type'],
                    'session_id':    sid,
                    'status':        'done',
                    'computed':      sess.get('computed', []),
                    'skipped':       sess.get('skipped',  []),
                    'results':       sess.get('results',  {}),
                })
                continue

            # 2. 磁盘恢复
            disk_folder = proj.get('result_folder', '') or ''
            if disk_folder:
                restored = _restore_session_from_disk(sid, disk_folder)
                if restored:
                    with _sess_lock:
                        _sessions[sid] = restored
                    out.append({
                        'id':            pid,
                        'name':          proj['name'],
                        'building_type': proj['building_type'],
                        'session_id':    sid,
                        'status':        'done',
                        'computed':      restored.get('computed', []),
                        'skipped':       restored.get('skipped',  []),
                        'results':       restored.get('results',  {}),
                    })
                    continue

            # 3. 过期
            out.append({
                'id':            pid,
                'name':          proj['name'],
                'building_type': proj['building_type'],
                'session_id':    sid,
                'status':        'expired',
                'computed':      proj.get('computed', []),
                'skipped':       proj.get('skipped',  []),
                'results':       {},
            })

        return jsonify({'projects': out})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@analysis_bp.route('/projects/<int:pid>/view', methods=['GET'])
def api_view_project(pid):
    """
    查看历史项目：
    1. 若 session 仍在内存 -- 直接用
    2. 否则尝试从 result_folder（磁盘）恢复 session
    3. 也可通过 ?result_folder=<path> 手动指定文件夹
    4. 都不行 -- 返回 expired
    """
    try:
        from api.db import get_project as _get, save_project as _db_save
        proj = _get(pid)
        if proj is None:
            return jsonify({'error': '项目不存在'}), 404

        sid = proj['session_id']

        # ── 1. session 仍在内存 ──
        with _sess_lock:
            sess = _sessions.get(sid)
            if sess is not None:
                sess['project_id'] = pid

        if sess is not None and sess.get('status') == 'done':
            return jsonify({
                'session_id':    sid,
                'building_type': sess.get('type', ''),
                'folder_name':   sess.get('folder', ''),
                'project_name':  sess.get('project_name', proj['name']),
                'project_id':    pid,
                'floor_info':    sess.get('floor_info', proj.get('floor_info', '0')),
                'collection_date': sess.get('collection_date', proj.get('collection_date', '')),
                'computed':      sess.get('computed', []),
                'skipped':       sess.get('skipped',  []),
                'results':       sess.get('results',  {}),
                'source_files':  sess.get('source_files', {}),
                'region_name_map': sess.get('region_name_map', {}),
                'status':        'done',
                'from_db':       False,
            })

        # ── 2. 尝试从磁盘恢复（优先使用 DB 记录的 result_folder，可被 query 参数覆盖）──
        manual_folder = request.args.get('result_folder', '').strip()
        disk_folder   = manual_folder or proj.get('result_folder', '') or ''

        if disk_folder:
            restored = _restore_session_from_disk(sid, disk_folder)
            if restored:
                restored['project_id'] = pid
                # 写回内存 session
                with _sess_lock:
                    _sessions[sid] = restored
                # 如果是手动指定的路径，顺便更新 DB 里的 result_folder
                if manual_folder and manual_folder != proj.get('result_folder'):
                    try:
                        _db_save(
                            name          = proj['name'],
                            building_type = proj['building_type'],
                            input_folder  = proj['input_folder'],
                            session_id    = sid,
                            computed      = restored.get('computed', []),
                            skipped       = restored.get('skipped',  []),
                            files_md5     = proj.get('files_md5'),
                            result_folder = manual_folder,
                            source_files  = proj.get('source_files'),
                            floor_info    = proj.get('floor_info', '0'),
                            collection_date = proj.get('collection_date', ''),
                        )
                    except Exception:
                        pass
                return jsonify({
                    'session_id':    sid,
                    'building_type': restored.get('type', ''),
                    'folder_name':   restored.get('folder', ''),
                    'project_name':  restored.get('project_name', proj['name']),
                    'project_id':    pid,
                    'floor_info':    restored.get('floor_info', proj.get('floor_info', '0')),
                    'collection_date': restored.get('collection_date', proj.get('collection_date', '')),
                    'computed':      restored.get('computed', []),
                    'skipped':       restored.get('skipped',  []),
                    'results':       restored.get('results',  {}),
                    'source_files':  restored.get('source_files', {}),
                    'region_name_map': restored.get('region_name_map', {}),
                    'status':        'done',
                    'from_db':       True,
                    'restored_from': disk_folder,
                })

        # ── 3. Session 已过期且无法从磁盘恢复 ──
        return jsonify({
            'session_id':    sid,
            'building_type': proj['building_type'],
            'folder_name':   proj['input_folder'],
            'project_name':  proj['name'],
            'project_id':    pid,
            'floor_info':    proj.get('floor_info', '0'),
            'collection_date': proj.get('collection_date', ''),
            'computed':      proj['computed'],
            'skipped':       proj['skipped'],
            'results':       {},
            'source_files':  proj.get('source_files') or {},
            'region_name_map': {},
            'status':        'expired',
            'from_db':       True,
            'result_folder': proj.get('result_folder', ''),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _restore_session_from_disk(sid, result_folder):
    # type: (str, str) -> object
    """
    从磁盘结果文件夹恢复 session dict。
    文件夹结构：
      meta.json          ← 元信息（project_name / building_type / computed / skipped …）
      images/<metric>.png
      summary.json       ← {metric_id: summary_dict}
    返回 session dict（已含 results），失败返回 None。
    """
    try:
        import os as _os
        meta_path    = _os.path.join(result_folder, 'meta.json')
        summary_path = _os.path.join(result_folder, 'summary.json')
        images_dir   = _os.path.join(result_folder, 'images')

        if not _os.path.isfile(meta_path):
            return None

        with open(meta_path, encoding='utf-8') as f:
            meta = _json.load(f)

        summary_all = {}
        if _os.path.isfile(summary_path):
            with open(summary_path, encoding='utf-8') as f:
                summary_all = _json.load(f)

        computed = meta.get('computed', [])
        results  = {}
        for metric_id in computed:
            img_path = _os.path.join(images_dir, f'{metric_id}.png')
            img_b64  = None
            if _os.path.isfile(img_path):
                with open(img_path, 'rb') as f:
                    img_b64 = base64.b64encode(f.read()).decode()   # 纯 base64，不带 data: 前缀
            results[metric_id] = {
                'image':   img_b64,
                'summary': summary_all.get(metric_id, {}),
            }

        source_files_meta = meta.get('source_files', {})
        source_file_copies = meta.get('source_file_copies', {})

        # 把历史绝对路径重新注入路径表，确保 open_source 可以查到
        if source_files_meta or source_file_copies:
            import os as _os_r
            with _file_paths_lock:
                for _p in list(source_files_meta.values()) + list(source_file_copies.values()):
                    if _p and _os_r.path.isabs(_p):
                        _file_abs_paths[_os_r.path.basename(_p)] = _p

        restored_inputs = {}
        for slot, copy_path in source_file_copies.items():
            if not copy_path:
                continue
            try:
                with open(copy_path, 'rb') as f:
                    restored_inputs[slot] = f.read()
            except Exception:
                pass

        sess = {
            'status':        'done',
            'ts':            _time.time(),
            'project_name':  meta.get('project_name', ''),
            'type':          meta.get('building_type', ''),
            'folder':        meta.get('folder_name', ''),
            'folder_abs':    meta.get('folder_abs', ''),   # 恢复绝对路径
            'floor_info':    meta.get('floor_info', '0'),
            'collection_date': meta.get('collection_date', ''),
            'computed':      computed,
            'skipped':       meta.get('skipped', []),
            'theme':         meta.get('theme', 'light'),
            'accent':        meta.get('accent', '#0ea5e9'),
            'results':       results,
            'source_files':  source_files_meta,  # 恢复绝对路径，供"数据来源"点击打开
            'source_file_copies': source_file_copies,
            'region_name_map': meta.get('region_name_map', {}),
        }
        for slot, (bytes_key, name_key, _path_field) in _INPUT_SLOTS.items():
            if slot in restored_inputs:
                sess[bytes_key] = restored_inputs[slot]
                sess[name_key] = _safe_input_filename(slot, source_file_copies.get(slot, '')).split('__', 1)[-1]
        if sess.get('_raw_img_b') and not sess.get('_img_b'):
            sess['_img_b'] = sess.get('_raw_img_b')
        return sess
    except Exception:
        return None


@analysis_bp.route('/projects/<int:pid>/export', methods=['POST'])
def api_export_project_by_id(pid):
    """
    历史项目另存为：从数据库获取 session_id，调用 save_project 接口。
    若 session 已过期，返回 { "expired": true }
    """
    try:
        from api.db import get_project as _get
        proj = _get(pid)
        if proj is None:
            return jsonify({'error': '项目不存在'}), 404

        sid = proj['session_id']

        # 检查 session 是否存活
        with _sess_lock:
            sess = _sessions.get(sid)

        if sess is None or sess.get('status') != 'done':
            return jsonify({'expired': True,
                            'message': '该项目的计算结果已过期，请重新计算后再导出'})

        # 复用 save_project 端点逻辑
        body = request.get_json(silent=True) or {}
        body.setdefault('folder_name', proj['name'])
        request._cached_json = (body, True)  # patch for nested call

        zip_bytes, safe_folder, err = _build_project_zip(
            sid,
            body.get('metrics', None),
            body.get('folder_name', proj['name'])
        )
        if err:
            return jsonify({'error': err}), 400

        zip_filename = f'{safe_folder}_评价结果.zip'

        if _native_save_dialog_hook is not None:
            save_path = _native_save_dialog_hook('另存为', zip_filename)
        else:
            try:
                import tkinter as _tk
                import tkinter.filedialog as _fd
                root = _tk.Tk(); root.withdraw(); root.lift()
                root.attributes('-topmost', True)
                save_path = _fd.asksaveasfilename(
                    parent=root, title='另存为',
                    defaultextension='.zip', initialfile=zip_filename,
                    filetypes=[('ZIP 压缩包', '*.zip'), ('所有文件', '*.*')],
                )
                root.destroy()
            except Exception:
                return jsonify({'error': '无法打开文件对话框'}), 500

        if not save_path:
            return jsonify({'cancelled': True})

        with open(save_path, 'wb') as f:
            f.write(zip_bytes)

        return jsonify({'success': True, 'path': save_path})

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'detail': traceback.format_exc()}), 500


# ─────────────────────────────────────────────
# 功能 2：人员轨迹
# ─────────────────────────────────────────────

@analysis_bp.route('/trajectory', methods=['POST'])
def trajectory():
    try:
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        if not {'X', 'Y', 'UserID'}.issubset(df.columns):
            return jsonify({'error': '定位数据需要 X, Y, UserID 列'}), 400

        img = load_img(img_file)

        # 提取可行走区域 mask
        walkable = extract_walkable_mask(img)

        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        # 左：轨迹叠加图
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(img, alpha=0.4)
        ax0.axis('off')

        user_ids = df['UserID'].unique()
        palette = _get_cmap('tab20', len(user_ids))
        line_width = _trajectory_line_width(len(user_ids))
        total_lengths = {}

        for idx, uid in enumerate(user_ids):
            ud = df[df['UserID'] == uid].reset_index(drop=True)
            x_arr = ud['X'].values
            y_arr = ud['Y'].values
            color = palette(idx)

            # 过滤落在黑色区域（不可达）的数据点
            x_arr, y_arr = filter_points_in_mask(x_arr, y_arr, walkable)
            if len(x_arr) < 2:
                continue

            # 样条平滑
            if len(x_arr) > 3:
                from scipy.interpolate import make_interp_spline
                t_arr = np.linspace(0, 1, len(x_arr))
                t_new = np.linspace(0, 1, min(500, len(x_arr) * 10))
                try:
                    spl_x = make_interp_spline(t_arr, x_arr, k=min(3, len(x_arr)-1))
                    spl_y = make_interp_spline(t_arr, y_arr, k=min(3, len(x_arr)-1))
                    x_s = spl_x(t_new)
                    y_s = spl_y(t_new)
                except Exception:
                    x_s, y_s = x_arr, y_arr
            else:
                x_s, y_s = x_arr, y_arr

            ax0.plot(x_s, y_s, color=color, lw=line_width, alpha=0.85)

            # 轨迹长度（米）
            dx = np.diff(x_arr); dy = np.diff(y_arr)
            total_lengths[uid] = float(np.sum(np.sqrt(dx**2 + dy**2)) / SCALE)

        ax0.set_title('人员移动轨迹', color=th['text'], fontsize=13, pad=10)

        # 右：轨迹长度分桶分布（10 桶）
        ax1 = axes[1]
        _styled_axes(ax1, th)

        lens_arr = np.array(list(total_lengths.values()), dtype=float)
        hist_min = float(np.min(lens_arr))
        hist_max = float(np.max(lens_arr))
        if np.isclose(hist_min, hist_max):
            hist_min -= 0.5
            hist_max += 0.5
        bin_edges = np.linspace(hist_min, hist_max, 11)
        counts, edges = np.histogram(lens_arr, bins=bin_edges)
        labels_bins = []
        for i in range(len(edges) - 1):
            labels_bins.append(f'{edges[i]:.1f}-{edges[i+1]:.1f}')

        xs = np.arange(len(counts))
        bars = ax1.bar(xs, counts, color='#00c9a7', alpha=0.85, width=0.8)
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax1.text(bar.get_x() + bar.get_width() / 2, h + 0.1,
                         f'{int(h)}', ha='center', va='bottom', color=th['bar_label'], fontsize=8)
        ax1.set_xticks(xs)
        ax1.set_xticklabels(labels_bins, fontsize=8, rotation=25, ha='right')
        ax1.set_xlabel('轨迹长度分桶 (m)', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('用户数', color=th['subtext'], fontsize=10)
        ax1.set_title('人员轨迹长度分布（10桶）', color=th['text'], fontsize=13)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_users': len(user_ids),
            'avg_length_m': round(float(np.mean(list(total_lengths.values()))), 1),
            'max_length_m': round(max(total_lengths.values()), 1),
            'min_length_m': round(min(total_lengths.values()), 1),
        }
        return jsonify({'image': img_b64, 'summary': summary})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# 功能 3：空间聚类
# ─────────────────────────────────────────────

@analysis_bp.route('/cluster', methods=['POST'])
def cluster():
    try:
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        k = int(request.form.get('k', 5))
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        if not {'X', 'Y'}.issubset(df.columns):
            return jsonify({'error': '定位数据需要 X, Y 列'}), 400

        img = load_img(img_file)

        # 提取可行走区域 mask，过滤掉落在黑色区域的点
        walkable = extract_walkable_mask(img)

        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values

        # 过滤不可走区域的点，再做聚类
        x, y = filter_points_in_mask(x, y, walkable)
        data_xy = np.column_stack([x, y])

        k = max(2, min(k, len(data_xy) - 1))
        # 用 scipy.cluster.vq.kmeans2 替代 sklearn.KMeans
        # 优势：scipy 已作为依赖加载，无额外 import 开销；sklearn 在 PyInstaller bundle
        # 中需要解压大量 Cython .so，是启动最慢的单步（占约 35%）
        centers, labels = _kmeans2(
            data_xy.astype(float), k,
            iter=10, minit='points', missing='warn', seed=42
        )
        # 计算 inertia（簇内平方和，等价于 sklearn 的 km.inertia_）
        inertia = float(sum(
            ((data_xy[labels == i] - c) ** 2).sum()
            for i, c in enumerate(centers)
        ))

        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param

        fig0, ax0 = plt.subplots(figsize=(9, 6))
        fig0.patch.set_facecolor(th['fig_bg'])

        # 左：聚类散点叠加图
        ax0.set_facecolor('white')
        ax0.imshow(img, alpha=0.35)
        ax0.axis('off')

        palette = _get_cmap('tab10', k)
        for ci in range(k):
            mask = labels == ci
            ax0.scatter(x[mask], y[mask], s=12, color=palette(ci),
                        alpha=0.7, label=f'簇 {ci+1}')

        # 聚类中心标记
        ax0.scatter(centers[:, 0], centers[:, 1], s=160, c='white',
                    marker='*', zorder=10, edgecolors='#ffcc00', linewidths=1)
        for i, (cx, cy) in enumerate(centers):
            ax0.annotate(f'C{i+1}', (cx, cy),
                         xytext=(6, 6), textcoords='offset points',
                         color='#ffcc00', fontsize=9, fontweight='bold')

        ax0.set_title(f'空间聚类分析 (k={k})', color=th['text'], fontsize=13, pad=10)
        ax0.legend(loc='upper right', fontsize=8, ncol=2,
                   facecolor=th['legend_bg'], edgecolor=th['legend_edge'], labelcolor=th['tick'])
        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig0)
        plt.close(fig0)

        # 右：各簇人数 & 中心坐标
        fig1, ax1 = plt.subplots(figsize=(9, 6))
        fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1, th)

        cluster_sizes = [int(np.sum(labels == ci)) for ci in range(k)]
        cluster_labels = [f'簇 {ci+1}' for ci in range(k)]
        colors_bar = [palette(ci) for ci in range(k)]

        bars = ax1.bar(cluster_labels, cluster_sizes, color=colors_bar,
                       alpha=0.85, width=0.55, edgecolor=th['bar_edge'], linewidth=0.5)
        for bar in bars:
            ax1.text(bar.get_x() + bar.get_width() / 2,
                     bar.get_height() + 0.5,
                     str(int(bar.get_height())),
                     ha='center', va='bottom', color=th['bar_label'], fontsize=9)

        ax1.set_ylabel('点位数量', color=th['subtext'], fontsize=10)
        ax1.set_title('各聚类点位分布', color=th['text'], fontsize=13)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img2_b64 = fig_to_base64(fig1)
        plt.close(fig1)

        # 簇信息
        clusters_info = []
        for ci in range(k):
            mask = labels == ci
            clusters_info.append({
                'id': ci + 1,
                'size': int(mask.sum()),
                'center_x': round(float(centers[ci, 0]), 1),
                'center_y': round(float(centers[ci, 1]), 1),
                'pct': round(float(mask.sum() / len(labels) * 100), 1),
            })

        summary = {
            'k': k,
            'total_points': len(x),
            'inertia': round(inertia, 1),
            'clusters': clusters_info,
        }
        return jsonify({'image': img_b64, 'image2': img2_b64, 'summary': summary})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# 共用工具：热力图叠加生成
# ─────────────────────────────────────────────

def _make_heatmap_overlay(img_arr, x, y, weights=None, alpha=0.70, cmap='jet',
                          bandwidth=None, theme='dark', walkable_mask=None, coverage_mask=None,
                          norm_percentile=99, scale_to_kernel_area=False):
    """KDE 像素级高斯密度热力图叠加，返回 (overlay RGB float[0,1], density_2d)

    walkable_mask : bool 数组 (H,W)，False = 平面图自动识别的墙体，
                   仅用于高斯平滑后抑制密度渗入墙体，不影响整体填色范围。
    coverage_mask : bool 数组 (H,W)，False = background.png 黑色区域（禁止上色）。
                   提供后采用"填充0值点"策略：
                   在 coverage_mask=True 区域均匀撒0值点，确保整个区域都有数据，
                   高斯平滑后实现完整热力场，无明显边界。
    norm_percentile : 默认用正值区 99 分位数压制极端峰值；传 None 时用原始最大值，
                   适合到访频次这类需要图例和渲染都对应原始数值的图。
    scale_to_kernel_area : 将高斯平滑后的密度乘以 2πσ²，恢复到近似原始计数/权重尺度。
                   到访频次使用 True，避免图例出现很小的小数密度值。
    未提供 coverage_mask 时：仅 density>0 处做 alpha 叠加（原有行为）。
    """
    h, w = img_arr.shape[:2]

    xi = np.clip(np.round(x).astype(int), 0, w - 1)
    yi = np.clip(np.round(y).astype(int), 0, h - 1)

    # ── 有 coverage_mask：在非background区域填充0值点 ──────────────────────
    if coverage_mask is not None:
        fill_mask = coverage_mask.astype(bool)

        # 估算填充点间隔（约为数据点平均间距的1.5倍）
        if len(xi) > 0:
            data_area = np.sum(fill_mask)
            avg_spacing = int(np.sqrt(data_area / max(len(xi), 1)))
            fill_spacing = max(int(avg_spacing * 1.5), 10)
        else:
            fill_spacing = 20

        # 在 coverage_mask=True 区域均匀撒0值点
        fill_y, fill_x = np.where(fill_mask)
        sample_indices = np.arange(0, len(fill_x), fill_spacing)
        fill_x_sampled = fill_x[sample_indices]
        fill_y_sampled = fill_y[sample_indices]

        xi_all = np.concatenate([xi, fill_x_sampled])
        yi_all = np.concatenate([yi, fill_y_sampled])

        if weights is not None:
            weights_all = np.concatenate([weights, np.zeros(len(fill_x_sampled))])
        else:
            weights_all = np.concatenate([np.ones(len(xi)), np.zeros(len(fill_x_sampled))])
    else:
        xi_all = xi
        yi_all = yi
        weights_all = weights

    # 构建密度图
    density = np.zeros((h, w), dtype=float)
    for i in range(len(xi_all)):
        w_val = weights_all[i] if weights_all is not None else 1.0
        density[yi_all[i], xi_all[i]] += w_val

    if bandwidth is None:
        bandwidth = max(int(min(h, w) * 0.025), 8)

    density_smooth = gaussian_filter(density, sigma=bandwidth)

    # walkable_mask 只用于抑制密度渗入墙体
    if walkable_mask is not None:
        density_smooth = density_smooth * walkable_mask.astype(float)

    density_render = density_smooth
    if scale_to_kernel_area:
        density_render = density_smooth * (2 * np.pi * (float(bandwidth) ** 2))

    cm = _get_cmap(cmap)
    img_f = img_arr / 255.0

    # ── 有 coverage_mask：仅在有效区域（fill_mask=True）叠加热力色，黑色区域保留原图 ──
    if coverage_mask is not None:
        fill_mask = coverage_mask.astype(bool)

        vmax = density_render.max()
        if vmax > 0:
            pos_vals = density_render[fill_mask & (density_render > 0)]
            if len(pos_vals) == 0:
                pos_vals = density_render[density_render > 0]
            norm_max = float(vmax) if norm_percentile is None else (
                float(np.percentile(pos_vals, norm_percentile)) if len(pos_vals) else float(vmax)
            )
            if norm_max <= 0 or not np.isfinite(norm_max):
                norm_max = float(vmax)
            density_norm = np.clip(density_render / norm_max, 0, 1)

            heat_rgba = cm(density_norm)  # (H, W, 4)
            heat_rgb  = heat_rgba[:, :, :3]  # (H, W, 3)

            # 仅对 fill_mask=True 区域做固定 alpha 叠加，黑色外围保留原图
            overlay = img_f.copy()
            overlay[fill_mask] = (
                img_f[fill_mask] * (1 - alpha) + heat_rgb[fill_mask] * alpha
            )
        else:
            overlay = img_f.copy()

        return np.clip(overlay, 0, 1), density_render

    # ── 无 coverage_mask：全图固定 alpha 叠加，0值区显示最低颜色，结构线透过来 ──
    vmax = density_render.max()
    if vmax <= 0:
        return img_f, density

    pos_vals = density_render[density_render > 0]
    norm_max = float(vmax) if norm_percentile is None else (
        float(np.percentile(pos_vals, norm_percentile)) if len(pos_vals) else float(vmax)
    )
    if norm_max <= 0 or not np.isfinite(norm_max):
        norm_max = float(vmax)
    density_norm = np.clip(density_render / norm_max, 0, 1)

    heat_rgba = cm(density_norm)
    heat_rgb  = heat_rgba[:, :, :3]

    # 全图固定 alpha 叠加：0密度区显示最低颜色，结构线通过半透明可见
    overlay = img_f * (1 - alpha) + heat_rgb * alpha
    return np.clip(overlay, 0, 1), density_render


def _make_rbf_overlay(img_arr, x, y, values, alpha=0.65, cmap='RdYlBu_r',
                      walkable_mask=None, coverage_mask=None, kernel='linear', smoothing=None,
                      neighbors=None, epsilon=None, vmin_override=None, vmax_override=None):
    """使用 RBFInterpolator 对稀疏测点生成连续标量场热力图。

    适用于环境温湿度/光照/CO2/PM 等连续测点数据；
    不适用于到访频次这类事件密度分布。
    
    coverage_mask : bool 数组 (H,W)，False = background.png 黑色区域（禁止上色）。
                   提供后采用"填充均值点"策略：
                   在 coverage_mask=True 区域均匀撒均值点，确保整个区域都有插值数据，
                   RBF插值后实现完整标量场，无明显边界。
    未提供 coverage_mask 时：仅有插值数据处做 alpha 叠加（原有行为）。
    
    返回 (overlay RGB float[0,1], field_2d, vmin, vmax)
    """
    h, w = img_arr.shape[:2]
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    values = np.asarray(values, dtype=float)

    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(values)
    x = x[valid]
    y = y[valid]
    values = values[valid]
    if len(values) < 3:
        return img_arr / 255.0, None, None, None

    # 原始测点坐标（像素空间）
    pts = np.column_stack([x, y])
    grid_x, grid_y = np.meshgrid(np.arange(w, dtype=float), np.arange(h, dtype=float))
    grid_pts = np.column_stack([grid_x.ravel(), grid_y.ravel()])

    if smoothing is None:
        vstd = float(np.nanstd(values)) if len(values) else 0.0
        smoothing = max(vstd * 0.05, 1e-6)

    try:
        rbf_kwargs = dict(kernel=kernel, smoothing=smoothing)
        if neighbors is not None:
            rbf_kwargs['neighbors'] = int(neighbors)
        if epsilon is not None and kernel in ('gaussian', 'multiquadric', 'inverse_multiquadric', 'inverse_quadratic'):
            rbf_kwargs['epsilon'] = epsilon
        rbf = RBFInterpolator(pts, values, **rbf_kwargs)
        field = rbf(grid_pts).reshape(h, w)
    except Exception:
        from scipy.interpolate import griddata
        field = griddata(pts, values, (grid_x, grid_y), method='linear')
        field_nearest = griddata(pts, values, (grid_x, grid_y), method='nearest')
        field = np.where(np.isnan(field), field_nearest, field)

    # coverage_mask 区域内用 nearest 填洞，确保整个可测区域都有值（不填均值点）
    if coverage_mask is not None:
        fill_mask = coverage_mask.astype(bool)
        nan_in_fill = fill_mask & ~np.isfinite(field)
        if np.any(nan_in_fill):
            from scipy.interpolate import griddata
            known_mask = fill_mask & np.isfinite(field)
            if np.any(known_mask):
                ky, kx = np.where(known_mask)
                kv = field[known_mask]
                ny, nx = np.where(nan_in_fill)
                filled = griddata(
                    np.column_stack([kx, ky]),
                    kv,
                    np.column_stack([nx, ny]),
                    method='nearest'
                )
                field[nan_in_fill] = filled

    # walkable_mask 仅用于抑制墙体渗透
    effective_mask = merge_masks(walkable_mask, coverage_mask)
    if effective_mask is not None:
        walk = effective_mask.astype(bool)
        if np.any(walk):
            field = np.where(walk, field, np.nan)

    finite_vals = field[np.isfinite(field)]
    if finite_vals.size == 0:
        return img_arr / 255.0, None, None, None

    vmin = float(vmin_override) if vmin_override is not None else float(np.nanpercentile(finite_vals, 2))
    vmax = float(vmax_override) if vmax_override is not None else float(np.nanpercentile(finite_vals, 98))
    if not np.isfinite(vmin) or not np.isfinite(vmax) or np.isclose(vmin, vmax):
        vmin = float(np.nanmin(finite_vals))
        vmax = float(np.nanmax(finite_vals))
        if np.isclose(vmin, vmax):
            vmax = vmin + 1e-6

    field_clip = np.clip(field, vmin, vmax)
    field_norm = (field_clip - vmin) / (vmax - vmin + 1e-9)
    field_norm = np.where(np.isfinite(field_norm), field_norm, 0.0)

    cm = _get_cmap(cmap)
    img_f = img_arr / 255.0

    # ── 有 coverage_mask：仅在 fill_mask 区域叠加热力色 ──────────────────────
    if coverage_mask is not None:
        fill_mask = coverage_mask.astype(bool)

        heat_rgba = cm(field_norm)
        heat_rgb = heat_rgba[:, :, :3]

        # 只对 fill_mask 区域做 alpha 叠加，背景区域保持原图
        overlay = img_f.copy()
        overlay[fill_mask] = (
            img_f[fill_mask] * (1 - alpha) + heat_rgb[fill_mask] * alpha
        )

        return np.clip(overlay, 0, 1), field, vmin, vmax

    # ── 无 coverage_mask：原有行为，仅有插值数据处做 alpha 叠加 ───────────
    heat_rgba = cm(field_norm)
    heat_rgb = heat_rgba[:, :, :3]

    alpha_map = np.full((h, w), alpha, dtype=float)
    if effective_mask is not None:
        alpha_map = alpha_map * effective_mask.astype(float)
    alpha_map = np.where(np.isfinite(field), alpha_map, 0.0)

    overlay = img_f * (1 - alpha_map[:, :, None]) + heat_rgb * alpha_map[:, :, None]
    return np.clip(overlay, 0, 1), field, vmin, vmax


def _clean_behavior_df(df, require_t=True):
    """过滤 BehaviorNum / t 列中无法转换为数字的行（如 '/'、'卫生间' 等字符串）。
    返回清洗后的 DataFrame（原始索引重置）。"""
    mask = pd.to_numeric(df['BehaviorNum'], errors='coerce').notna()
    if require_t and 't' in df.columns:
        mask = mask & pd.to_numeric(df['t'], errors='coerce').notna()
    df = df[mask].copy()
    df['BehaviorNum'] = pd.to_numeric(df['BehaviorNum'], errors='coerce').astype(int)
    if require_t and 't' in df.columns:
        df['t'] = pd.to_numeric(df['t'], errors='coerce')
    return df.reset_index(drop=True)


def _styled_axes(ax, th=None):
    if th is None:
        th = _theme('dark')
    ax.set_facecolor(th['ax_bg2'])
    for sp in ax.spines.values():
        sp.set_edgecolor(th['spine'])
    ax.tick_params(colors=th['tick'], labelsize=9)


def _legend_upper_right(ax, th=None, **kwargs):
    """Place legends at the upper-right outside the plotting area."""
    if th is None:
        th = _theme('dark')
    defaults = {
        'loc': 'upper left',
        'bbox_to_anchor': (1.01, 1.0),
        'borderaxespad': 0,
        'facecolor': th['legend_bg'],
        'edgecolor': th.get('spine', th.get('legend_edge', th['legend_bg'])),
        'labelcolor': th.get('bar_label', th.get('tick', th['text'])),
        'fontsize': 8,
    }
    defaults.update(kwargs)
    return ax.legend(**defaults)


def _bar_common(ax, x_vals, y_vals, color=None, xlabel='区域编号', ylabel='', th=None,
                show_mean=True, color_above=None, color_below=None):
    """绘制通用柱状图，自动显示均值线并用不同颜色区分均值上下的柱子。
    show_mean: 是否显示均值线（默认 True）
    color_above/color_below: 均值线上方/下方的颜色（None 则自动取 accent / 互补色）
    """
    if th is None:
        th = _theme('dark')
    if color is None:
        color = th.get('accent', '#7c5cfc')
    y_arr = np.asarray(y_vals, dtype=float)
    mean_val = float(y_arr.mean()) if len(y_arr) > 0 else 0.0

    if show_mean:
        if color_above is None:
            color_above = color
        if color_below is None:
            same_as_above = str(color_above).lower() == str(color).lower()
            color_below = th.get('accent', '#7c5cfc') if same_as_above and str(color_above).lower() == '#00c9a7' else '#00c9a7'

    bar_colors = []
    for v in y_arr:
        if show_mean:
            bar_colors.append(color_above if v >= mean_val else color_below)
        else:
            bar_colors.append(color)

    bars = ax.bar([str(v) for v in x_vals], y_arr, color=bar_colors, alpha=0.85, width=0.6,
                  edgecolor=th['bar_edge'], linewidth=0.5)
    for bar in bars:
        h = bar.get_height()
        label_text = f'{h:.2f}' if h != int(h) else str(int(h))
        ax.text(bar.get_x() + bar.get_width() / 2, h + abs(h) * 0.01 + 1e-9,
                label_text, ha='center', va='bottom', color=th['bar_label'], fontsize=8)
    ax.set_xlabel(xlabel, color=th['subtext'], fontsize=10)
    ax.set_ylabel(ylabel, color=th['subtext'], fontsize=10)
    ax.yaxis.grid(True, color=th['grid'], linewidth=0.5)
    ax.set_axisbelow(True)

    if show_mean and len(y_arr) > 0:
        mean_color = '#ff5e5e'
        ax.axhline(mean_val, color=mean_color, linestyle='--', linewidth=1.5,
                   label=f'均值 {mean_val:.2f}')
        from matplotlib.patches import Patch
        handles = [
            Patch(facecolor=color_above, alpha=0.85, label='高于均值'),
            Patch(facecolor=color_below, alpha=0.85, label='低于均值'),
            plt.Line2D([0], [0], color=mean_color, linestyle='--', linewidth=1.5, label=f'均值 {mean_val:.2f}'),
        ]
        _legend_upper_right(ax, th, handles=handles)


def _set_sparse_xticks(ax, labels):
    labels = [str(v) for v in labels]
    n = len(labels)
    if n <= 3:
        ax.set_xticks(range(n))
        ax.set_xticklabels(labels, fontsize=8)
        return
    idxs = [0, n // 2, n - 1]
    dedup = []
    for i in idxs:
        if i not in dedup:
            dedup.append(i)
    ax.set_xticks(dedup)
    ax.set_xticklabels([labels[i] for i in dedup], fontsize=8)


def _extract_satisfaction_groups(df):
    """从问卷数据中提取满意度列分组。

    约定：
    - Satisfaction: 整体满意度
    - Satisfaction1~8: 空间满意度
    - Satisfaction9~24: 设计要素满意度（若存在）
    """
    sat_cols = [c for c in df.columns if c.startswith('Satisfaction') and c != 'Satisfaction']
    sat_cols = sorted(sat_cols, key=lambda c: int(c.replace('Satisfaction', '')) if c.replace('Satisfaction', '').isdigit() else 10**9)
    region_cols = []
    design_cols = []
    for c in sat_cols:
        suffix = c.replace('Satisfaction', '')
        if suffix.isdigit():
            idx = int(suffix)
            if 1 <= idx <= 8:
                region_cols.append(c)
            elif idx >= 9:
                design_cols.append(c)
        else:
            region_cols.append(c)
    return sat_cols, region_cols, design_cols


# ─────────────────────────────────────────────
# A2 使用时长
# ─────────────────────────────────────────────

@analysis_bp.route('/usetime', methods=['POST'])
def usetime():
    try:
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        required = {'X', 'Y', 'Region'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        df = df.dropna(subset=['X', 'Y', 'Region'])
        if len(df) == 0:
            return jsonify({'error': '没有有效的 X/Y/Region 数据'}), 400

        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        weights = np.full(len(df), USAGE_SECONDS_PER_RECORD, dtype=float)
        regions = df['Region'].astype(int).values

        img = load_img(img_file)

        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param

        # 按区域累计时长
        reg_ids = np.sort(np.unique(regions))
        reg_durations = np.array([weights[regions == r].sum() for r in reg_ids])

        # 热力叠加：每条定位记录代表 10 秒停留时长
        _bg_file = request.files.get('background_img')
        _coverage = extract_measurement_mask(load_img(_bg_file)) if _bg_file is not None else extract_measurement_mask(img)
        overlay, freq_grid = _make_heatmap_overlay(img, x, y, weights=weights, alpha=0.65, cmap='jet',
                                                    walkable_mask=extract_walkable_mask(img),
                                                    coverage_mask=_coverage,
                                                    scale_to_kernel_area=True)

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('空间使用时长热力图', color=th['text'], fontsize=13, pad=10)

        sm = plt.cm.ScalarMappable(cmap='jet', norm=mcolors.Normalize(0, float(freq_grid.max()) if float(freq_grid.max()) > 0 else 1.0))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('停留时长 (s)', color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, reg_ids, reg_durations, color='#00c9a7', ylabel='时长 (s)', th=th)
        ax1.set_title('各空间单元使用时长', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'seconds_per_record': USAGE_SECONDS_PER_RECORD,
            'total_duration_s': int(weights.sum()),
            'avg_duration_s': round(float(reg_durations.mean()), 2),
            'max_duration_s': round(float(reg_durations.max()), 2),
            'min_duration_s': round(float(reg_durations.min()), 2),
            'region_count': int(len(reg_ids)),
            'peak_region': int(reg_ids[np.argmax(reg_durations)]),
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# A3 移动速率
# ─────────────────────────────────────────────

@analysis_bp.route('/speed', methods=['POST'])
def speed():
    try:
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        required = {'X', 'Y', 'Region', 't', 'UserID'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        img = load_img(img_file)
        x_all = df['X'].astype(float).values
        y_all = df['Y'].astype(float).values
        t_all = df['t'].astype(float).values
        regions_all = df['Region'].astype(int).values
        user_ids = df['UserID'].values
        reg_ids = np.sort(np.unique(regions_all))

        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param

        # 各空间单元停留时长之和
        reg_dwell = np.array([t_all[regions_all == r].sum() for r in reg_ids])

        # 各区域流线长度之和（按人员逐段累加）
        reg_length = np.zeros(len(reg_ids))
        for uid in np.unique(user_ids):
            mask = user_ids == uid
            ux, uy, ur = x_all[mask], y_all[mask], regions_all[mask]
            if len(ux) < 2:
                continue
            for i in range(len(ux) - 1):
                seg = np.sqrt((ux[i+1]-ux[i])**2 + (uy[i+1]-uy[i])**2) / SCALE
                r_cur = ur[i]
                if r_cur in reg_ids:
                    idx = np.where(reg_ids == r_cur)[0][0]
                    reg_length[idx] += seg * 0.5
                r_nxt = ur[i+1]
                if r_nxt in reg_ids:
                    idx = np.where(reg_ids == r_nxt)[0][0]
                    reg_length[idx] += seg * 0.5

        with np.errstate(divide='ignore', invalid='ignore'):
            mean_speed = np.where(reg_dwell > 0, reg_length / reg_dwell, 0)

        # 热力叠加（以速率为权重）
        weights = np.array([mean_speed[np.where(reg_ids == r)[0][0]] if r in reg_ids else 0
                            for r in regions_all])
        _bg_file = request.files.get('background_img')
        _coverage = extract_measurement_mask(load_img(_bg_file)) if _bg_file is not None else extract_measurement_mask(img)
        overlay, speed_grid = _make_heatmap_overlay(img, x_all, y_all, weights=weights, alpha=0.65, cmap='jet',
                                                     walkable_mask=extract_walkable_mask(img),
                                                     coverage_mask=_coverage)

        global_speed = reg_length.sum() / reg_dwell.sum() if reg_dwell.sum() > 0 else 0

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('空间移动速率热力图 (m/s)', color=th['text'], fontsize=13, pad=10)
        sm = plt.cm.ScalarMappable(cmap='jet', norm=mcolors.Normalize(0, float(speed_grid.max()) if float(speed_grid.max()) > 0 else 1.0))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('移动速率强度', color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, reg_ids, mean_speed, color='#f5a623', ylabel='速率 (m/s)', th=th,
                    show_mean=True, color_above='#f5a623', color_below='#00c9a7')
        ax1.set_title('各空间单元平均移动速率', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'global_speed_ms': round(float(global_speed), 2),
            'peak_speed_region': int(reg_ids[np.argmax(mean_speed)]),
            'region_count': int(len(reg_ids)),
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# A4 停留时长
# ─────────────────────────────────────────────

@analysis_bp.route('/duration', methods=['POST'])
def duration():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        region_name_map = _parse_region_name_map(request.form.get('region_name_map', ''))
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        required = {'X', 'Y', 'Region', 't'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        t = df['t'].astype(float).values
        regions = df['Region'].astype(int).values
        img = load_img(img_file)

        reg_ids = np.sort(np.unique(regions))
        reg_dwell = np.array([t[regions == r].sum() for r in reg_ids])

        _bg_file = request.files.get('background_img')
        _coverage = extract_measurement_mask(load_img(_bg_file)) if _bg_file is not None else extract_measurement_mask(img)
        overlay, freq_grid = _make_heatmap_overlay(img, x, y, weights=t, alpha=0.65, cmap='jet',
                                                    walkable_mask=extract_walkable_mask(img),
                                                    coverage_mask=_coverage)

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('空间停留时长热力图 (s)', color=th['text'], fontsize=13, pad=10)

        sm = plt.cm.ScalarMappable(cmap='jet', norm=mcolors.Normalize(0, float(t.max())))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('停留时长 (s)', color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, _region_labels(reg_ids, region_name_map), reg_dwell,
                    color=th['accent'], xlabel='空间单元', ylabel='时长 (s)', th=th)
        ax1.set_title('各空间单元停留时长', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'total_dwell_s': int(t.sum()),
            'avg_dwell_s': round(float(t.mean()), 1),
            'peak_region': int(reg_ids[np.argmax(reg_dwell)]),
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# A6 人员密度
# ─────────────────────────────────────────────

@analysis_bp.route('/density', methods=['POST'])
def density():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        required = {'X', 'Y', 'Region', 'UserID'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        regions = df['Region'].astype(int).values
        user_ids = df['UserID'].values
        img = load_img(img_file)

        reg_ids = np.sort(np.unique(regions))
        # 每区域独立人员数
        reg_unique_users = np.array([df[df['Region'] == r]['UserID'].nunique() for r in reg_ids])

        _bg_file = request.files.get('background_img')
        _coverage = extract_measurement_mask(load_img(_bg_file)) if _bg_file is not None else extract_measurement_mask(img)
        overlay, density_grid = _make_heatmap_overlay(img, x, y, alpha=0.65, cmap='jet',
                                                       walkable_mask=extract_walkable_mask(img),
                                                       coverage_mask=_coverage)

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('人员分布热力图', color=th['text'], fontsize=13, pad=10)
        sm = plt.cm.ScalarMappable(cmap='jet', norm=mcolors.Normalize(0, float(density_grid.max()) if float(density_grid.max()) > 0 else 1.0))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('人员分布密度', color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, reg_ids, reg_unique_users, color='#00c9a7', ylabel='独立人员数')
        ax1.set_title('各空间单元独立人员数', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'unique_users': int(df['UserID'].nunique()),
            'region_count': int(len(reg_ids)),
            'peak_region': int(reg_ids[np.argmax(reg_unique_users)]),
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# A7 空间开放程度
# ─────────────────────────────────────────────

@analysis_bp.route('/openness', methods=['POST'])
def openness():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        region_file = request.files.get('region_data')
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        required = {'X', 'Y', 'Region', 'UserID'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        regions = df['Region'].astype(int).values
        img = load_img(img_file)

        reg_ids = np.sort(np.unique(regions))
        reg_unique_users = np.array([df[df['Region'] == r]['UserID'].nunique() for r in reg_ids], dtype=float)

        # 若上传区域坐标文件则计算面积，否则用等权面积1
        if region_file is not None:
            rdf = load_df(region_file)
            areas = {}
            for rid in rdf['Region'].unique():
                pts = rdf[rdf['Region'] == rid][['X', 'Y']].values
                if len(pts) >= 3:
                    pts_c = np.vstack([pts, pts[0]])
                    a = 0.5 * abs(np.sum(pts_c[:-1, 0] * pts_c[1:, 1] - pts_c[1:, 0] * pts_c[:-1, 1]))
                    areas[rid] = a / (SCALE ** 2)
                else:
                    areas[rid] = 1.0
            reg_areas = np.array([areas.get(r, 1.0) for r in reg_ids])
        else:
            reg_areas = np.ones(len(reg_ids))

        with np.errstate(divide='ignore', invalid='ignore'):
            openness_val = np.where(reg_areas > 0, reg_unique_users / reg_areas, 0)

        global_open = df['UserID'].nunique() / reg_areas.sum() if reg_areas.sum() > 0 else 0

        _bg_file = request.files.get('background_img')
        _coverage = extract_measurement_mask(load_img(_bg_file)) if _bg_file is not None else extract_measurement_mask(img)
        overlay, open_grid = _make_heatmap_overlay(img, x, y, alpha=0.65, cmap='jet',
                                                    walkable_mask=extract_walkable_mask(img),
                                                    coverage_mask=_coverage)

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('空间开放程度热力图', color=th['text'], fontsize=13, pad=10)
        sm = plt.cm.ScalarMappable(cmap='jet', norm=mcolors.Normalize(0, float(open_grid.max()) if float(open_grid.max()) > 0 else 1.0))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('空间开放程度强度', color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, reg_ids, openness_val, color='#f5a623', ylabel='人/㎡')
        ax1.axhline(global_open, color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'整体 {global_open:.3f}')
        _legend_upper_right(ax1, th)
        ax1.set_title('各空间单元开放程度 (人/㎡)', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'unique_users': int(df['UserID'].nunique()),
            'global_openness': round(float(global_open), 4),
            'peak_region': int(reg_ids[np.argmax(openness_val)]),
            'region_count': int(len(reg_ids)),
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# A8 拓扑连接关系
# ─────────────────────────────────────────────

@analysis_bp.route('/topology', methods=['POST'])
def topology():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        region_name_map = _parse_region_name_map(request.form.get('region_name_map', ''))
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        if loc_file is None:
            return jsonify({'error': '请上传定位数据'}), 400

        df = load_df(loc_file)
        required = {'X', 'Y', 'Region', 'UserID'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        regions = df['Region'].astype(int).values
        user_ids = df['UserID'].values
        reg_ids = np.sort(np.unique(regions[regions > 0]))
        n = len(reg_ids)
        rid2idx = {r: i for i, r in enumerate(reg_ids)}

        # 构建转移矩阵
        trans = np.zeros((n, n), dtype=int)
        for uid in np.unique(user_ids):
            mask = user_ids == uid
            ur = regions[mask]
            for i in range(len(ur) - 1):
                fr, to = ur[i], ur[i + 1]
                if fr != to and fr in rid2idx and to in rid2idx:
                    trans[rid2idx[fr], rid2idx[to]] += 1

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        # 左：转移矩阵热图
        ax0 = axes[0]
        _styled_axes(ax0, th)
        im = ax0.imshow(trans, cmap='YlOrRd', aspect='auto')
        ax0.set_xticks(range(n)); ax0.set_xticklabels(_region_labels(reg_ids, region_name_map, prefix=''), fontsize=8, rotation=30, ha='right')
        ax0.set_yticks(range(n)); ax0.set_yticklabels(_region_labels(reg_ids, region_name_map, prefix=''), fontsize=8)
        ax0.set_xlabel('目标空间单元', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('出发空间单元', color=th['subtext'], fontsize=10)
        ax0.set_title('区域人员转移矩阵', color=th['text'], fontsize=13, pad=10)
        cbar = fig.colorbar(im, ax=ax0, fraction=0.04, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)

        # 右：入度/出度柱状图
        ax1 = axes[1]
        _styled_axes(ax1, th)
        in_deg = trans.sum(axis=0)
        out_deg = trans.sum(axis=1)
        bw = 0.35
        xs = np.arange(n)
        ax1.bar(xs - bw/2, in_deg, width=bw, color=th['accent'], alpha=0.85, label='入流')
        ax1.bar(xs + bw/2, out_deg, width=bw, color='#00c9a7', alpha=0.85, label='出流')
        ax1.set_xticks(xs); ax1.set_xticklabels(_region_labels(reg_ids, region_name_map, prefix=''), fontsize=8, rotation=30, ha='right')
        ax1.set_xlabel('空间单元', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('流量', color=th['subtext'], fontsize=10)
        ax1.set_title('各空间单元人员流入/流出量', color=th['text'], fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        fig2, ax2 = plt.subplots(figsize=(9, 8))
        fig2.patch.set_facecolor(th['fig_bg'])
        ax2.set_facecolor(th['fig_bg'])
        ax2.set_aspect('equal')
        ax2.axis('off')
        ax2.set_title('区域拓扑网络图', color=th['text'], fontsize=13, pad=10)
        df_tmp = df[df['Region'].astype(int).isin(reg_ids)].copy()
        cx = np.array([df_tmp[df_tmp['Region'].astype(int) == r]['X'].astype(float).mean() for r in reg_ids])
        cy = np.array([df_tmp[df_tmp['Region'].astype(int) == r]['Y'].astype(float).mean() for r in reg_ids])
        def _norm01(arr):
            lo, hi = arr.min(), arr.max()
            return (arr - lo) / (hi - lo + 1e-9) * 0.85 + 0.05
        nx_pos = _norm01(cx)
        ny_pos = 1.0 - _norm01(cy)
        max_t = trans.max() if trans.max() > 0 else 1
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                w = trans[i, j]
                if w == 0:
                    continue
                rad = 0.15 if trans[j, i] > 0 else 0.0
                ax2.annotate('', xy=(nx_pos[j], ny_pos[j]), xytext=(nx_pos[i], ny_pos[i]),
                             xycoords='axes fraction', textcoords='axes fraction',
                             arrowprops=dict(arrowstyle='-|>', color='#4facfe',
                                             lw=0.5 + 3.5 * (w / max_t),
                                             alpha=0.25 + 0.65 * (w / max_t),
                                             connectionstyle=f'arc3,rad={rad}'),
                             annotation_clip=False)
        total_flow = in_deg + out_deg
        max_flow = total_flow.max() if total_flow.max() > 0 else 1
        node_r = np.clip(0.025 + 0.040 * (total_flow / max_flow), 0.02, 0.07)
        cmap_n = _get_cmap('plasma')
        for i in range(n):
            color = cmap_n(0.2 + 0.7 * (total_flow[i] / max_flow))
            circ = plt.Circle((nx_pos[i], ny_pos[i]), node_r[i], transform=ax2.transAxes,
                              color=color, ec='white', lw=1.2, zorder=5, clip_on=False)
            ax2.add_patch(circ)
            ax2.text(nx_pos[i], ny_pos[i],
                     f"{_region_label(reg_ids[i], region_name_map, prefix='')}\n{int(total_flow[i])}人",
                     ha='center', va='center', fontsize=8, fontweight='bold',
                     color='white', transform=ax2.transAxes, zorder=6, linespacing=1.05)
        ax2.set_xlim(0, 1)
        ax2.set_ylim(0, 1)
        plt.tight_layout(pad=2)
        img3_b64 = fig_to_base64(fig2)
        plt.close(fig2)

        # 构建节点数据供前端展示
        nodes = [{'region': int(reg_ids[i]), 'in': int(in_deg[i]), 'out': int(out_deg[i])}
                 for i in range(n)]
        summary = {
            'region_count': n,
            'total_transitions': int(trans.sum()),
            'nodes': nodes,
        }
        return jsonify({'image': img_b64, 'image2': img3_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# A9 轨迹差异系数
# ─────────────────────────────────────────────

@analysis_bp.route('/difference', methods=['POST'])
def difference():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        loc_file = request.files.get('loc_data')
        img_file = request.files.get('layout_img')
        if loc_file is None or img_file is None:
            return jsonify({'error': '请上传定位数据和平面图'}), 400

        df = load_df(loc_file)
        required = {'X', 'Y', 'UserID', 'Region'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        img = load_img(img_file)
        user_ids = df['UserID'].values
        per_ids = np.unique(user_ids)
        reg_ids = np.sort(np.unique(df['Region'].astype(int).values))

        # 每人轨迹总长
        per_lengths = {}
        for uid in per_ids:
            ud = df[df['UserID'] == uid]
            ux, uy = ud['X'].astype(float).values, ud['Y'].astype(float).values
            if len(ux) > 1:
                per_lengths[uid] = float(np.sum(np.sqrt(np.diff(ux)**2 + np.diff(uy)**2))) / SCALE
            else:
                per_lengths[uid] = 0.0
        lengths = np.array([per_lengths[u] for u in per_ids])
        avg_len = lengths[lengths > 0].mean() if (lengths > 0).any() else 1
        diff_coeff_per = lengths / avg_len  # 人员差异系数

        # 各区域流线长度均值差异系数
        reg_len_sums = {}
        reg_len_counts = {}
        for uid in per_ids:
            ud = df[df['UserID'] == uid]
            ux = ud['X'].astype(float).values
            uy = ud['Y'].astype(float).values
            ur = ud['Region'].astype(int).values
            for i in range(len(ux) - 1):
                seg = np.sqrt((ux[i+1]-ux[i])**2 + (uy[i+1]-uy[i])**2) / SCALE
                for r in [ur[i], ur[i+1]]:
                    reg_len_sums[r] = reg_len_sums.get(r, 0.0) + seg * 0.5
                    reg_len_counts[r] = reg_len_counts.get(r, 0) + 1

        reg_means = np.array([reg_len_sums.get(r, 0) / max(reg_len_counts.get(r, 1), 1) for r in reg_ids])
        global_mean = reg_means[reg_means > 0].mean() if (reg_means > 0).any() else 1
        diff_coeff_reg = reg_means / global_mean

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        _styled_axes(ax0, th)
        ax0.bar([str(u) for u in per_ids], diff_coeff_per,
                color=[th['accent'] if v >= 1.0 else '#00c9a7' for v in diff_coeff_per],
                alpha=0.85, width=0.6)
        ax0.axhline(1.0, color='#ff5e5e', linestyle='--', linewidth=1.5, label='基准线(=1)')
        ax0.set_xlabel('人员编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('差异系数', color=th['subtext'], fontsize=10)
        ax0.set_title('人员轨迹长度差异系数', color=th['text'], fontsize=13, pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        _set_sparse_xticks(ax0, per_ids)
        fig.patch.set_facecolor(th['fig_bg'])

        ax1 = axes[1]
        _styled_axes(ax1, th)
        ax1.bar([str(r) for r in reg_ids], diff_coeff_reg,
                color=['#f5a623' if v >= 1.0 else '#00c9a7' for v in diff_coeff_reg],
                alpha=0.85, width=0.6)
        ax1.axhline(1.0, color='#ff5e5e', linestyle='--', linewidth=1.5, label='基准线(=1)')
        ax1.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('差异系数', color=th['subtext'], fontsize=10)
        ax1.set_title('区域流线长度差异系数', color=th['text'], fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_users': int(len(per_ids)),
            'avg_length_m': round(float(avg_len), 1),
            'max_diff_user': str(per_ids[np.argmax(diff_coeff_per)]),
            'region_count': int(len(reg_ids)),
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# B5 环境参数
# ─────────────────────────────────────────────

@analysis_bp.route('/environment', methods=['POST'])
def environment():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        env_file = request.files.get('env_data')
        img_file = request.files.get('layout_img')
        param_num = int(request.form.get('param_num', 1))
        if env_file is None or img_file is None:
            return jsonify({'error': '请上传环境数据和平面图'}), 400

        df = load_df(env_file)
        required = {'X', 'Y', 'ParameterNum', 'Value'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        param_labels = {1: '温度(°C)', 2: '湿度(%)', 3: '光照(lux)', 4: '风速(m/s)', 5: '噪声(dB)'}
        label = param_labels.get(param_num, f'参数{param_num}')

        sub = df[df['ParameterNum'] == param_num].copy()
        sub = sub.dropna(subset=['X', 'Y', 'Value'])
        if sub.empty:
            return jsonify({'error': f'参数编号 {param_num} 缺少有效数值数据'}), 400

        ex = sub['X'].astype(float).values
        ey = sub['Y'].astype(float).values
        vals = sub['Value'].astype(float).values

        img = load_img(img_file)
        h_img, w_img = img.shape[:2]
        walkable = extract_walkable_mask(img)
        coverage_mask = None
        bgmask_file = request.files.get('background_img')
        if bgmask_file is not None:
            try:
                coverage_mask = extract_measurement_mask(load_img(bgmask_file))
            except Exception:
                coverage_mask = None
        kernel_map = {1: 'linear', 2: 'linear', 3: 'gaussian', 4: 'linear', 5: 'linear'}
        epsilon_map = {3: max(min(w_img, h_img) * 0.015, 4.0)}
        overlay, interp, vmin, vmax = _make_rbf_overlay(
            img, ex, ey, vals,
            alpha=0.65,
            cmap='RdYlBu_r',
            walkable_mask=walkable,
            coverage_mask=coverage_mask,
            kernel=kernel_map.get(param_num, 'linear'),
            smoothing=max(float(np.nanstd(vals)) * 0.03, 1e-6),
            neighbors=min(max(len(vals), 8), 24),
            epsilon=epsilon_map.get(param_num),
        )
        if interp is None:
            return jsonify({'error': '有效环境测点过少，无法进行空间插值'}), 400

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.scatter(ex, ey, c='white', s=24, zorder=5, edgecolors='#ffcc00', linewidths=0.8)
        ax0.axis('off')
        ax0.set_title(f'{label} 空间分布', color=th['text'], fontsize=13, pad=10)

        sm = plt.cm.ScalarMappable(cmap='RdYlBu_r', norm=mcolors.Normalize(vmin, vmax))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label(label, color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        ax1.scatter(range(len(vals)), vals, color=th['accent'], s=40, alpha=0.85, zorder=3)
        ax1.axhline(float(vals.mean()), color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'均值 {vals.mean():.2f}')
        ax1.set_xlabel('测点编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel(label, color=th['subtext'], fontsize=10)
        ax1.set_title(f'各测点{label}值', color=th['text'], fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'param': label,
            'num_points': int(len(vals)),
            'mean': round(float(vals.mean()), 2),
            'max': round(float(vals.max()), 2),
            'min': round(float(vals.min()), 2),
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# C1 行为发生人次
# ─────────────────────────────────────────────

@analysis_bp.route('/behavior_count', methods=['POST'])
def behavior_count():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        beh_file = request.files.get('behavior_data')
        img_file = request.files.get('layout_img')
        if beh_file is None or img_file is None:
            return jsonify({'error': '请上传行为数据和平面图'}), 400

        df = load_df(beh_file)
        required = {'X', 'Y', 'BehaviorNum', 'Region'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400
        df = _clean_behavior_df(df, require_t=False)
        if len(df) == 0:
            return jsonify({'error': '行为数据中无有效数值行'}), 400

        img = load_img(img_file)
        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        beh_nums = df['BehaviorNum'].astype(int).values
        regions = df['Region'].astype(int).values

        # 行为类型标签
        if 'behaviortype' in df.columns:
            beh_labels_map = df.groupby('BehaviorNum')['behaviortype'].first().to_dict()
        else:
            beh_labels_map = {b: f'行为{b}' for b in np.unique(beh_nums)}

        uniq_beh = np.sort(np.unique(beh_nums))
        uniq_reg = np.sort(np.unique(regions))
        beh_labels = [str(beh_labels_map.get(b, b)) for b in uniq_beh]

        count_matrix = np.zeros((len(uniq_reg), len(uniq_beh)), dtype=int)
        for i, r in enumerate(uniq_reg):
            for j, b in enumerate(uniq_beh):
                count_matrix[i, j] = int(((regions == r) & (beh_nums == b)).sum())

        # 散点图叠加
        palette = _get_cmap('tab10', len(uniq_beh))
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(img, alpha=0.5)
        for j, b in enumerate(uniq_beh):
            mask = beh_nums == b
            ax0.scatter(x[mask], y[mask], s=18, color=palette(j), alpha=0.75,
                        label=beh_labels[j], zorder=3)
        ax0.axis('off')
        ax0.set_title('各行为发生分布', color=th['text'], fontsize=13, pad=10)
        ax0.legend(loc='upper right', fontsize=7, ncol=2,
                   facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'])

        ax1 = axes[1]
        _styled_axes(ax1, th)
        bw = 0.7 / len(uniq_beh)
        xs = np.arange(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            ax1.bar(xs + j * bw - 0.35 + bw/2, count_matrix[:, j], width=bw,
                    color=palette(j), alpha=0.85, label=beh_labels[j])
        ax1.set_xticks(xs); ax1.set_xticklabels(uniq_reg, fontsize=8)
        ax1.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('人次', color=th['subtext'], fontsize=10)
        ax1.set_title('各空间单元行为发生人次', color=th['text'], fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'behavior_types': len(uniq_beh),
            'region_count': int(len(uniq_reg)),
            'behaviors': beh_labels,
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# C2 行为时长
# ─────────────────────────────────────────────

@analysis_bp.route('/behavior_duration', methods=['POST'])
def behavior_duration():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        beh_file = request.files.get('behavior_data')
        img_file = request.files.get('layout_img')
        if beh_file is None or img_file is None:
            return jsonify({'error': '请上传行为数据和平面图'}), 400

        df = load_df(beh_file)
        required = {'X', 'Y', 'BehaviorNum', 'Region', 't'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400
        df = _clean_behavior_df(df, require_t=True)
        if len(df) == 0:
            return jsonify({'error': '行为数据中无有效数值行'}), 400

        img = load_img(img_file)
        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        beh_nums = df['BehaviorNum'].astype(int).values
        regions = df['Region'].astype(int).values
        t = df['t'].astype(float).values

        if 'behaviortype' in df.columns:
            beh_labels_map = df.groupby('BehaviorNum')['behaviortype'].first().to_dict()
        else:
            beh_labels_map = {b: f'行为{b}' for b in np.unique(beh_nums)}

        uniq_beh = np.sort(np.unique(beh_nums))
        uniq_reg = np.sort(np.unique(regions))
        beh_labels = [str(beh_labels_map.get(b, b)) for b in uniq_beh]

        dur_matrix = np.zeros((len(uniq_reg), len(uniq_beh)))
        for i, r in enumerate(uniq_reg):
            for j, b in enumerate(uniq_beh):
                dur_matrix[i, j] = t[(regions == r) & (beh_nums == b)].sum()

        palette = _get_cmap('tab10', len(uniq_beh))

        # 热力叠加（以 t 为权重，加入 walkable_mask 和 coverage_mask）
        _bg_file = request.files.get('background_img')
        _coverage = extract_measurement_mask(load_img(_bg_file)) if _bg_file is not None else extract_measurement_mask(img)
        overlay, beh_grid = _make_heatmap_overlay(
            img, x, y, weights=t, alpha=0.65, cmap='jet',
            walkable_mask=extract_walkable_mask(img),
            coverage_mask=_coverage
        )

        # 图1：行为时长热力图（独立图）
        fig0, ax0 = plt.subplots(figsize=(9, 6))
        fig0.patch.set_facecolor(th['fig_bg'])
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('行为时长热力图 (s)', color=th['text'], fontsize=13, pad=10)
        vmax_beh = float(beh_grid.max()) if beh_grid is not None and float(beh_grid.max()) > 0 else 1.0
        sm = plt.cm.ScalarMappable(cmap='jet', norm=mcolors.Normalize(0, vmax_beh))
        sm.set_array([])
        cbar = fig0.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('行为时长强度', color=th['subtext'], fontsize=9)
        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig0)
        plt.close(fig0)

        # 图2：各空间单元行为时长柱状图（独立图，按行为类型分组）
        fig1, ax1 = plt.subplots(figsize=(9, 6))
        fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1, th)
        bw = 0.7 / max(len(uniq_beh), 1)
        xs = np.arange(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            ax1.bar(xs + j * bw - 0.35 + bw/2, dur_matrix[:, j], width=bw,
                    color=palette(j), alpha=0.85, label=beh_labels[j])
        ax1.set_xticks(xs)
        ax1.set_xticklabels(uniq_reg, fontsize=8)
        ax1.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('时长 (s)', color=th['subtext'], fontsize=10)
        ax1.set_title('各空间单元行为时长', color=th['text'], fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)
        plt.tight_layout(pad=2)
        img2_b64 = fig_to_base64(fig1)
        plt.close(fig1)

        summary = {
            'total_records': int(len(df)),
            'total_duration_s': int(t.sum()),
            'behavior_types': len(uniq_beh),
            'behaviors': beh_labels,
        }
        return jsonify({'image': img_b64, 'image2': img2_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# C3 行为发生率
# ─────────────────────────────────────────────

@analysis_bp.route('/behavior_rate', methods=['POST'])
def behavior_rate():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        beh_file = request.files.get('behavior_data')
        if beh_file is None:
            return jsonify({'error': '请上传行为数据'}), 400

        df = load_df(beh_file)
        required = {'BehaviorNum', 'Region', 't'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400
        df = _clean_behavior_df(df, require_t=True)

        beh_nums = df['BehaviorNum'].astype(int).values
        regions = df['Region'].astype(int).values
        t = df['t'].astype(float).values

        if 'behaviortype' in df.columns:
            beh_labels_map = df.groupby('BehaviorNum')['behaviortype'].first().to_dict()
        else:
            beh_labels_map = {b: f'行为{b}' for b in np.unique(beh_nums)}

        uniq_beh = np.sort(np.unique(beh_nums))
        uniq_reg = np.sort(np.unique(regions))
        beh_labels = [str(beh_labels_map.get(b, b)) for b in uniq_beh]

        rate_matrix = np.zeros((len(uniq_reg), len(uniq_beh)))
        for i, r in enumerate(uniq_reg):
            r_mask = regions == r
            total_t = t[r_mask].sum()
            for j, b in enumerate(uniq_beh):
                beh_t = t[r_mask & (beh_nums == b)].sum()
                rate_matrix[i, j] = beh_t / total_t if total_t > 0 else 0

        palette = _get_cmap('tab10', len(uniq_beh))
        fig0, ax0 = plt.subplots(figsize=(9, 6))
        fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0, th)
        bottom = np.zeros(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            ax0.bar(uniq_reg.astype(str), rate_matrix[:, j], bottom=bottom,
                    color=palette(j), alpha=0.85, label=beh_labels[j])
            bottom += rate_matrix[:, j]
        ax0.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('发生率', color=th['subtext'], fontsize=10)
        ax0.set_title('各空间单元行为发生率 (堆叠)', color=th['text'], fontsize=13, pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig0)
        plt.close(fig0)

        fig1, ax1 = plt.subplots(figsize=(9, 6))
        fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1, th)
        bw = 0.7 / len(uniq_beh)
        xs = np.arange(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            ax1.bar(xs + j * bw - 0.35 + bw/2, rate_matrix[:, j], width=bw,
                    color=palette(j), alpha=0.85, label=beh_labels[j])
        ax1.set_xticks(xs); ax1.set_xticklabels(uniq_reg, fontsize=8)
        ax1.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('发生率', color=th['subtext'], fontsize=10)
        ax1.set_title('各空间单元行为发生率 (分组)', color=th['text'], fontsize=13)
        _legend_upper_right(ax1, th)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)
        plt.tight_layout(pad=2)
        img2_b64 = fig_to_base64(fig1)
        plt.close(fig1)

        summary = {
            'total_records': int(len(df)),
            'behavior_types': len(uniq_beh),
            'behaviors': beh_labels,
            'region_count': int(len(uniq_reg)),
        }
        return jsonify({'image': img_b64, 'image2': img2_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# C4 行为复合度
# ─────────────────────────────────────────────

@analysis_bp.route('/behavior_entropy', methods=['POST'])
def behavior_entropy():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        beh_file = request.files.get('behavior_data')
        if beh_file is None:
            return jsonify({'error': '请上传行为数据'}), 400

        df = load_df(beh_file)
        required = {'BehaviorNum', 'Region', 't'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400
        df = _clean_behavior_df(df, require_t=True)

        beh_nums = df['BehaviorNum'].astype(int).values
        regions = df['Region'].astype(int).values
        t = df['t'].astype(float).values
        uniq_beh = np.sort(np.unique(beh_nums))
        uniq_reg = np.sort(np.unique(regions))

        def entropy(probs):
            probs = probs[probs > 0]
            return float(-np.sum(probs * np.log2(probs))) if len(probs) else 0.0

        reg_entropy = []
        for r in uniq_reg:
            r_mask = regions == r
            total_t = t[r_mask].sum()
            probs = np.array([t[r_mask & (beh_nums == b)].sum() / total_t if total_t > 0 else 0
                              for b in uniq_beh])
            reg_entropy.append(entropy(probs))

        user_entropy = []
        user_ids_col = df['UserID'].values if 'UserID' in df.columns else np.arange(len(df))
        uniq_users = np.unique(user_ids_col)
        for u in uniq_users:
            u_mask = user_ids_col == u
            total_t = t[u_mask].sum()
            probs = np.array([t[u_mask & (beh_nums == b)].sum() / total_t if total_t > 0 else 0
                              for b in uniq_beh])
            user_entropy.append(entropy(probs))

        fig0, ax0 = plt.subplots(figsize=(9, 6))
        fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0, th)
        _bar_common(ax0, uniq_reg, reg_entropy, color=th['accent'], ylabel='行为熵值 (bits)')
        ax0.set_title('各空间单元行为复合度', color=th['text'], fontsize=13, pad=10)
        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig0)
        plt.close(fig0)

        fig1, ax1 = plt.subplots(figsize=(9, 6))
        fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1, th)
        _bar_common(ax1, uniq_users, user_entropy, color='#00c9a7', ylabel='行为熵值 (bits)')
        ax1.set_title('各使用者行为复合度', color=th['text'], fontsize=13)
        plt.tight_layout(pad=2)
        img2_b64 = fig_to_base64(fig1)
        plt.close(fig1)

        summary = {
            'region_count': int(len(uniq_reg)),
            'user_count': int(len(uniq_users)),
            'avg_reg_entropy': round(float(np.mean(reg_entropy)), 3),
            'behavior_types': int(len(uniq_beh)),
        }
        return jsonify({'image': img_b64, 'image2': img2_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# C5 功能利用率
# ─────────────────────────────────────────────

@analysis_bp.route('/utilization', methods=['POST'])
def utilization():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        beh_file = request.files.get('behavior_data')
        region_file = request.files.get('region_data')
        if beh_file is None:
            return jsonify({'error': '请上传行为数据'}), 400

        df = load_df(beh_file)
        required = {'BehaviorNum', 'Region', 't'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400
        df = _clean_behavior_df(df, require_t=True)

        beh_nums = df['BehaviorNum'].astype(int).values
        regions = df['Region'].astype(int).values
        t = df['t'].astype(float).values

        if 'behaviortype' in df.columns:
            beh_labels_map = df.groupby('BehaviorNum')['behaviortype'].first().to_dict()
        else:
            beh_labels_map = {b: f'行为{b}' for b in np.unique(beh_nums)}

        uniq_beh = np.sort(np.unique(beh_nums))
        uniq_reg = np.sort(np.unique(regions))
        beh_labels = [str(beh_labels_map.get(b, b)) for b in uniq_beh]

        dur_matrix = np.zeros((len(uniq_reg), len(uniq_beh)))
        for i, r in enumerate(uniq_reg):
            for j, b in enumerate(uniq_beh):
                dur_matrix[i, j] = t[(regions == r) & (beh_nums == b)].sum()

        if region_file is not None:
            rdf = load_df(region_file)
            areas = {}
            for rid in rdf['Region'].unique():
                pts = rdf[rdf['Region'] == rid][['X', 'Y']].values
                if len(pts) >= 3:
                    pts_c = np.vstack([pts, pts[0]])
                    a = 0.5 * abs(np.sum(pts_c[:-1, 0] * pts_c[1:, 1] - pts_c[1:, 0] * pts_c[:-1, 1]))
                    areas[rid] = a / (SCALE ** 2)
                else:
                    areas[rid] = 1.0
            reg_areas = np.array([areas.get(r, 1.0) for r in uniq_reg])
        else:
            reg_areas = np.ones(len(uniq_reg))

        util_matrix = dur_matrix / reg_areas[:, np.newaxis]
        total_util = util_matrix.sum(axis=1)
        with np.errstate(divide='ignore', invalid='ignore'):
            util_share_matrix = np.divide(
                util_matrix,
                total_util[:, np.newaxis],
                out=np.zeros_like(util_matrix),
                where=total_util[:, np.newaxis] > 0,
            )

        palette = _get_cmap('tab10', len(uniq_beh))
        fig0, ax0 = plt.subplots(figsize=(9, 6))
        fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0, th)
        bottom = np.zeros(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            seg_bars = ax0.bar(uniq_reg.astype(str), util_share_matrix[:, j], bottom=bottom,
                                color=palette(j), alpha=0.85, label=beh_labels[j])
            for bi, bar in enumerate(seg_bars):
                h = util_share_matrix[bi, j]
                if h > 0.02:
                    ax0.text(bar.get_x() + bar.get_width()/2, bottom[bi] + h/2, f'{h:.1%}',
                             ha='center', va='center', color='white', fontsize=7, fontweight='bold')
            bottom += util_share_matrix[:, j]
        ax0.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('占比', color=th['subtext'], fontsize=10)
        ax0.set_title('各空间单元功能利用率占比 (堆叠)', color=th['text'], fontsize=13, pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        fig0.patch.set_facecolor(th['fig_bg'])
        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig0)
        plt.close(fig0)

        fig1, ax1 = plt.subplots(figsize=(9, 6))
        fig1.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1, th)
        _bar_common(ax1, uniq_reg, total_util, color='#f5a623', ylabel='s/㎡')
        global_util = dur_matrix.sum() / reg_areas.sum() if reg_areas.sum() > 0 else 0
        ax1.axhline(global_util, color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'全局均值 {global_util:.1f}')
        _legend_upper_right(ax1, th)
        ax1.set_title('各空间单元总功能利用率', color=th['text'], fontsize=13)
        plt.tight_layout(pad=2)
        img2_b64 = fig_to_base64(fig1)
        plt.close(fig1)

        summary = {
            'region_count': int(len(uniq_reg)),
            'behavior_types': int(len(uniq_beh)),
            'global_util': round(float(global_util), 2),
            'behaviors': beh_labels,
        }
        return jsonify({'image': img_b64, 'image2': img2_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# D3 整体满意度
# ─────────────────────────────────────────────

@analysis_bp.route('/satisfaction', methods=['POST'])
def satisfaction():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        ques_file = request.files.get('ques_data_overall') or request.files.get('ques_data')
        if ques_file is None:
            return jsonify({'error': '请上传整体满意度问卷数据'}), 400

        df = load_df(ques_file)
        score_col = 'Satisfaction' if 'Satisfaction' in df.columns else 'Satisfaction1'
        required = {'UserNum', score_col}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        user_ids = df['UserNum'].values
        scores = df[score_col].astype(float).values
        avg_score = float(scores.mean())

        # 仅生成右侧分布直方图（左侧个人评分改为前端Canvas交互图）
        fig, ax1 = plt.subplots(1, 1, figsize=(7, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax1, th)
        bins = [0, 60, 70, 80, 90, 100]
        labels_hist = ['<60', '60-70', '70-80', '80-90', '90-100']
        counts, _ = np.histogram(scores, bins=bins)
        bars_h = ax1.bar(labels_hist, counts, color='#a78bfa', alpha=0.85, width=0.6)
        for bar in bars_h:
            h = bar.get_height()
            if h > 0:
                ax1.text(bar.get_x() + bar.get_width() / 2, h + 0.2, str(int(h)),
                         ha='center', va='bottom', color=th['bar_label'], fontsize=9)
        ax1.set_xlabel('分数段', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('人数', color=th['subtext'], fontsize=10)
        ax1.set_title('满意度分布', color=th['text'], fontsize=13)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)
        ax1.axhline(avg_score, color='#ff5e5e', linestyle='--', linewidth=1.5, label=f'均值 {avg_score:.2f}')
        _legend_upper_right(ax1, th)

        plt.tight_layout(pad=2)
        img_dist_b64 = fig_to_base64(fig)
        plt.close(fig)

        bar_data = [[str(uid), float(s)] for uid, s in zip(user_ids, scores)]
        summary = {
            'total_users': int(len(df)),
            'avg_score': round(avg_score, 1),
            'max_score': int(scores.max()),
            'min_score': int(scores.min()),
        }
        return jsonify({'image_dist': img_dist_b64, 'bar_data': bar_data,
                        'avg_score': round(avg_score, 1), 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# D4 空间区域满意度
# ─────────────────────────────────────────────

@analysis_bp.route('/satisfaction_region', methods=['POST'])
def satisfaction_region():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        ques_file = request.files.get('ques_data_region') or request.files.get('ques_data')
        if ques_file is None:
            return jsonify({'error': '请上传空间单元满意度问卷数据'}), 400

        df = load_df(ques_file)
        if 'UserNum' not in df.columns:
            return jsonify({'error': '缺少 UserNum 列'}), 400

        region_cols = [c for c in df.columns if c != 'UserNum']
        if not region_cols:
            return jsonify({'error': '未找到空间单元满意度列'}), 400

        avg_vals = df[region_cols].apply(pd.to_numeric, errors='coerce').mean().values
        reg_ids = []
        for c in region_cols:
            try:
                reg_ids.append(int(str(c).replace('Satisfaction', '')))
            except Exception:
                reg_ids.append(str(c))
        avg_score = float(avg_vals.mean())

        fig0, ax0 = plt.subplots(figsize=(9, 6))
        fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0, th)
        colors = ['#7c5cfc' if v >= avg_score else '#00c9a7' for v in avg_vals]
        ax0.bar([str(r) for r in reg_ids], avg_vals, color=colors, alpha=0.85, width=0.6)
        ax0.axhline(avg_score, color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'均值 {avg_score:.1f}')
        ax0.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('满意度均值', color=th['subtext'], fontsize=10)
        ax0.set_title('各空间单元满意度', color=th['text'], fontsize=13, pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig0)
        plt.close(fig0)

        fig1 = plt.figure(figsize=(9, 6))
        fig1.patch.set_facecolor(th['fig_bg'])
        ax1 = fig1.add_subplot(111, polar=True)
        ax1.set_facecolor(th['ax_bg2'])
        theta = np.linspace(0, 2 * np.pi, len(reg_ids), endpoint=False)
        vals_r = np.append(avg_vals, avg_vals[0])
        theta_r = np.append(theta, theta[0])
        ax1.plot(theta_r, vals_r, color=th['accent'], linewidth=2)
        ax1.fill(theta_r, vals_r, color=th['accent'], alpha=0.2)
        ax1.set_xticks(theta)
        ax1.set_xticklabels([str(r) for r in reg_ids], color=th['subtext'], fontsize=8)
        ax1.tick_params(colors=th['cbar_tick'])
        ax1.set_title('区域满意度雷达', color=th['text'], fontsize=13, pad=15)
        ax1.spines['polar'].set_color('#2d2d3d')
        ax1.grid(color=th['grid'], linewidth=0.5)
        plt.tight_layout(pad=2)
        img2_b64 = fig_to_base64(fig1)
        plt.close(fig1)

        region_details = [{'region': str(r), 'avg_score': round(float(v), 1)}
                          for r, v in zip(reg_ids, avg_vals)]
        summary = {
            'region_count': int(len(reg_ids)),
            'avg_score': round(avg_score, 1),
            'best_region': str(reg_ids[int(np.argmax(avg_vals))]),
            'worst_region': str(reg_ids[int(np.argmin(avg_vals))]),
            'regions': region_details,
        }
        return jsonify({'image': img_b64, 'image2': img2_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# D5 设计要素满意度
# ─────────────────────────────────────────────

@analysis_bp.route('/satisfaction_design', methods=['POST'])
def satisfaction_design():
    try:
        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param
        ques_file = request.files.get('ques_data_design') or request.files.get('ques_data')
        if ques_file is None:
            return jsonify({'error': '请上传设计要素满意度问卷数据'}), 400

        df = load_df(ques_file)
        if 'UserNum' not in df.columns:
            return jsonify({'error': '缺少 UserNum 列'}), 400

        design_cols = [c for c in df.columns if c != 'UserNum']
        if not design_cols:
            return jsonify({'error': '未找到设计要素满意度列'}), 400

        avg_vals = df[design_cols].apply(pd.to_numeric, errors='coerce').mean().values
        factor_ids = [str(c).replace('设计要素', '') for c in design_cols]
        avg_score = float(avg_vals.mean())

        fig0, ax0 = plt.subplots(figsize=(9, 6))
        fig0.patch.set_facecolor(th['fig_bg'])
        _styled_axes(ax0, th)
        colors = ['#7c5cfc' if v >= avg_score else '#00c9a7' for v in avg_vals]
        ax0.bar([str(r) for r in factor_ids], avg_vals, color=colors, alpha=0.85, width=0.6)
        ax0.axhline(avg_score, color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'均值 {avg_score:.1f}')
        ax0.set_xlabel('设计要素编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('满意度均值', color=th['subtext'], fontsize=10)
        ax0.set_title('各设计要素满意度', color=th['text'], fontsize=13, pad=10)
        _legend_upper_right(ax0, th)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig0)
        plt.close(fig0)

        fig1 = plt.figure(figsize=(9, 6))
        fig1.patch.set_facecolor(th['fig_bg'])
        ax1 = fig1.add_subplot(111, polar=True)
        ax1.set_facecolor(th['ax_bg2'])
        theta = np.linspace(0, 2 * np.pi, len(factor_ids), endpoint=False)
        vals_r = np.append(avg_vals, avg_vals[0])
        theta_r = np.append(theta, theta[0])
        ax1.plot(theta_r, vals_r, color=th['accent'], linewidth=2)
        ax1.fill(theta_r, vals_r, color=th['accent'], alpha=0.2)
        ax1.set_xticks(theta)
        ax1.set_xticklabels([str(r) for r in factor_ids], color=th['subtext'], fontsize=8)
        ax1.tick_params(colors=th['cbar_tick'])
        ax1.set_title('设计要素满意度雷达', color=th['text'], fontsize=13, pad=15)
        ax1.spines['polar'].set_color('#2d2d3d')
        ax1.grid(color=th['grid'], linewidth=0.5)
        plt.tight_layout(pad=2)
        img2_b64 = fig_to_base64(fig1)
        plt.close(fig1)

        factor_details = [{'factor': str(r), 'avg_score': round(float(v), 1)}
                          for r, v in zip(factor_ids, avg_vals)]
        summary = {
            'factor_count': int(len(factor_ids)),
            'avg_score': round(avg_score, 1),
            'best_factor': str(factor_ids[int(np.argmax(avg_vals))]),
            'worst_factor': str(factor_ids[int(np.argmin(avg_vals))]),
            'factors': factor_details,
        }
        return jsonify({'image': img_b64, 'image2': img2_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
