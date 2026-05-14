"""
空间分析后端 API
三个核心功能：到访频次热力图、人员轨迹、空间聚类
"""

import io
import json
import base64
import numpy as np
import pandas as pd
from flask import Blueprint, request, jsonify
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.font_manager as _fm

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
from scipy.ndimage import gaussian_filter
from PIL import Image

analysis_bp = Blueprint('analysis', __name__)

SCALE = 18.06  # px / meter


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
        return pd.read_csv(file_storage)
    return pd.read_excel(file_storage)


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

        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        img = load_img(img_file)

        # KDE 渐变热力图（无栅格）
        overlay, density = _make_heatmap_overlay(img, x, y, alpha=0.70, cmap='plasma')

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('到访频次热力图', color=th['text'], fontsize=13, pad=10)

        sm = plt.cm.ScalarMappable(cmap='plasma', norm=mcolors.Normalize(0, 1))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('到访密度', color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)

        if 'Region' in df.columns:
            region_cnt = df.groupby('Region').size().reset_index(name='count')
            _bar_common(ax1, region_cnt['Region'], region_cnt['count'],
                        color=th['accent'], ylabel='到访人次', th=th)
            ax1.set_title('各区域到访频次', color=th['text'], fontsize=13)
        else:
            ax1.text(0.5, 0.5, '无区域数据\n(需要 Region 列)',
                     ha='center', va='center', color=th['subtext'], fontsize=11,
                     transform=ax1.transAxes)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        n_nonzero = int((density > density.max() * 0.05).sum())
        peak_raw = float(density.max())
        summary = {
            'total_records': int(len(df)),
            'unique_users': int(df['UserID'].nunique()) if 'UserID' in df.columns else '-',
            'peak_frequency': round(peak_raw, 2) if peak_raw < 10 else int(round(peak_raw)),
            'covered_area_pct': round(n_nonzero / density.size * 100, 1),
        }
        return jsonify({'image': img_b64, 'summary': summary})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
        total_lengths = {}

        for idx, uid in enumerate(user_ids):
            ud = df[df['UserID'] == uid].reset_index(drop=True)
            x_arr = ud['X'].values
            y_arr = ud['Y'].values
            color = palette(idx)

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

            ax0.plot(x_s, y_s, color=color, lw=1.2, alpha=0.85)
            ax0.scatter(x_arr[0], y_arr[0], c=[color], s=40,
                        marker='o', zorder=5, edgecolors='white', linewidths=0.5)
            ax0.scatter(x_arr[-1], y_arr[-1], c=[color], s=40,
                        marker='D', zorder=5, edgecolors='white', linewidths=0.5)

            # 轨迹长度（米）
            dx = np.diff(x_arr); dy = np.diff(y_arr)
            total_lengths[uid] = float(np.sum(np.sqrt(dx**2 + dy**2)) / SCALE)

        ax0.set_title('人员移动轨迹', color=th['text'], fontsize=13, pad=10)

        # 图例（最多显示 12 人）
        legend_n = min(12, len(user_ids))
        handles = [plt.Line2D([0], [0], color=palette(i), lw=2)
                   for i in range(legend_n)]
        labels_leg = [f'用户{uid}' for uid in user_ids[:legend_n]]
        ax0.legend(handles, labels_leg, loc='upper right',
                   fontsize=7, ncol=2,
                   facecolor=th['legend_bg'], edgecolor=th['legend_edge'],
                   labelcolor=th['tick'])

        # 右：轨迹长度排行
        ax1 = axes[1]
        _styled_axes(ax1, th)

        sorted_len = sorted(total_lengths.items(), key=lambda x: x[1], reverse=True)
        uids_s = [str(u) for u, _ in sorted_len]
        lens_s = [l for _, l in sorted_len]

        bars = ax1.barh(uids_s, lens_s, color='#00c9a7', alpha=0.85, height=0.6)
        for bar in bars:
            ax1.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                     f'{bar.get_width():.1f}m',
                     va='center', color=th['bar_label'], fontsize=8)
        ax1.set_xlabel('轨迹长度 (m)', color=th['subtext'], fontsize=10)
        ax1.set_title('人员轨迹长度', color=th['text'], fontsize=13)
        ax1.xaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)
        ax1.invert_yaxis()

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

        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
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

        img = load_img(img_file)

        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        # 左：聚类散点叠加图
        ax0 = axes[0]
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

        # 右：各簇人数 & 中心坐标
        ax1 = axes[1]
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
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

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
        return jsonify({'image': img_b64, 'summary': summary})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────
# 共用工具：热力图叠加生成
# ─────────────────────────────────────────────

def _make_heatmap_overlay(img_arr, x, y, weights=None, alpha=0.70, cmap='jet',
                          bandwidth=None, theme='dark'):
    """KDE 像素级高斯密度热力图叠加，返回 (overlay RGB float[0,1], density_2d)"""
    h, w = img_arr.shape[:2]

    xi = np.clip(np.round(x).astype(int), 0, w - 1)
    yi = np.clip(np.round(y).astype(int), 0, h - 1)

    density = np.zeros((h, w), dtype=float)
    for i in range(len(xi)):
        w_val = weights[i] if weights is not None else 1.0
        density[yi[i], xi[i]] += w_val

    # 固定小带宽保留聚集点细节
    if bandwidth is None:
        bandwidth = max(int(min(h, w) * 0.025), 8)

    density_smooth = gaussian_filter(density, sigma=bandwidth)

    vmax = density_smooth.max()
    if vmax <= 0:
        return img_arr / 255.0, density

    # 99 分位数拉伸
    pos_vals = density_smooth[density_smooth > 0]
    p99 = np.percentile(pos_vals, 99) if len(pos_vals) else vmax
    density_norm = np.clip(density_smooth / p99, 0, 1)

    # gamma < 1 让边缘衰减更平缓（0.5 → 平方根曲线，过渡更柔和）
    density_soft = np.power(density_norm, 0.45)

    cm = _get_cmap(cmap)
    heat_rgba = cm(density_norm)          # 颜色仍按线性密度取色
    heat_rgb  = heat_rgba[:, :, :3]
    heat_alpha = density_soft * alpha     # 透明度用软化后的值，边缘更柔

    img_f = img_arr / 255.0
    overlay = img_f * (1 - heat_alpha[:, :, None]) + heat_rgb * heat_alpha[:, :, None]
    return np.clip(overlay, 0, 1), density_smooth


def _styled_axes(ax, th=None):
    if th is None:
        th = _theme('dark')
    ax.set_facecolor(th['ax_bg2'])
    for sp in ax.spines.values():
        sp.set_edgecolor(th['spine'])
    ax.tick_params(colors=th['tick'], labelsize=9)


def _bar_common(ax, x_vals, y_vals, color=None, xlabel='区域编号', ylabel='', th=None):
    if th is None:
        th = _theme('dark')
    if color is None:
        color = th.get('accent', '#7c5cfc')
    bars = ax.bar([str(v) for v in x_vals], y_vals, color=color, alpha=0.85, width=0.6,
                  edgecolor=th['bar_edge'], linewidth=0.5)
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + bar.get_height() * 0.01,
                f'{bar.get_height():.1f}', ha='center', va='bottom', color=th['bar_label'], fontsize=8)
    ax.set_xlabel(xlabel, color=th['subtext'], fontsize=10)
    ax.set_ylabel(ylabel, color=th['subtext'], fontsize=10)
    ax.yaxis.grid(True, color=th['grid'], linewidth=0.5)
    ax.set_axisbelow(True)


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
        required = {'X', 'Y', 'Region', 't'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        t = df['t'].astype(float).values
        regions = df['Region'].astype(int).values

        img = load_img(img_file)
        h_img, w_img = img.shape[:2]

        theme_name = request.form.get('theme', 'dark')
        th = _theme(theme_name)
        accent_param = request.form.get('accent')
        if accent_param:
            th['accent'] = accent_param

        # 按区域累计时长
        reg_ids = np.sort(np.unique(regions))
        reg_durations = np.array([t[regions == r].sum() for r in reg_ids])

        # 热力叠加（以 t 为权重）
        overlay, freq_grid = _make_heatmap_overlay(img, x, y, weights=t, alpha=0.65, cmap='jet')

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('空间使用时长热力图', color=th['text'], fontsize=13, pad=10)

        sm = plt.cm.ScalarMappable(cmap='jet', norm=mcolors.Normalize(0, float(freq_grid.max())))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('停留时长 (s)', color=th['subtext'], fontsize=9)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, reg_ids, reg_durations, color='#00c9a7', ylabel='时长 (s)', th=th)
        ax1.set_title('各区域使用时长', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'total_duration_s': int(t.sum()),
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

        # 各区域停留时长之和
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
        overlay, _ = _make_heatmap_overlay(img, x_all, y_all, weights=weights, alpha=0.65, cmap='jet')

        global_speed = reg_length.sum() / reg_dwell.sum() if reg_dwell.sum() > 0 else 0

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('空间移动速率热力图 (m/s)', color=th['text'], fontsize=13, pad=10)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, reg_ids, mean_speed, color='#f5a623', ylabel='速率 (m/s)', th=th)
        ax1.axhline(global_speed, color='#ff5e5e', linestyle='--', linewidth=1.5, label=f'全局均值 {global_speed:.3f}')
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['legend_edge'], labelcolor=th['tick'], fontsize=8)
        ax1.set_title('各区域平均移动速率', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'global_speed_ms': round(float(global_speed), 4),
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

        overlay, freq_grid = _make_heatmap_overlay(img, x, y, weights=t, alpha=0.65, cmap='jet')

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
        _bar_common(ax1, reg_ids, reg_dwell, color=th['accent'], ylabel='时长 (s)')
        ax1.set_title('各区域停留时长', color=th['text'], fontsize=13)

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

        overlay, _ = _make_heatmap_overlay(img, x, y, alpha=0.65, cmap='jet')

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('人员分布热力图', color=th['text'], fontsize=13, pad=10)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, reg_ids, reg_unique_users, color='#00c9a7', ylabel='独立人员数')
        ax1.set_title('各区域独立人员数', color=th['text'], fontsize=13)

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

        overlay, _ = _make_heatmap_overlay(img, x, y, alpha=0.65, cmap='jet')

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('空间开放程度热力图', color=th['text'], fontsize=13, pad=10)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, reg_ids, openness_val, color='#f5a623', ylabel='人/㎡')
        ax1.axhline(global_open, color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'整体 {global_open:.3f}')
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax1.set_title('各区域开放程度 (人/㎡)', color=th['text'], fontsize=13)

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
        ax0.set_xticks(range(n)); ax0.set_xticklabels(reg_ids, fontsize=8)
        ax0.set_yticks(range(n)); ax0.set_yticklabels(reg_ids, fontsize=8)
        ax0.set_xlabel('目标区域', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('出发区域', color=th['subtext'], fontsize=10)
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
        ax1.set_xticks(xs); ax1.set_xticklabels(reg_ids, fontsize=8)
        ax1.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('流量', color=th['subtext'], fontsize=10)
        ax1.set_title('各区域人员流入/流出量', color=th['text'], fontsize=13)
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        # 构建节点数据供前端展示
        nodes = [{'region': int(reg_ids[i]), 'in': int(in_deg[i]), 'out': int(out_deg[i])}
                 for i in range(n)]
        summary = {
            'region_count': n,
            'total_transitions': int(trans.sum()),
            'nodes': nodes,
        }
        return jsonify({'image': img_b64, 'summary': summary})
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
        ax0.bar([str(u) for u in per_ids], diff_coeff_per, color=th['accent'], alpha=0.85, width=0.6)
        ax0.axhline(1.0, color='#ff5e5e', linestyle='--', linewidth=1.5, label='基准线(=1)')
        ax0.set_xlabel('人员编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('差异系数', color=th['subtext'], fontsize=10)
        ax0.set_title('人员轨迹长度差异系数', color=th['text'], fontsize=13, pad=10)
        ax0.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        fig.patch.set_facecolor(th['fig_bg'])

        ax1 = axes[1]
        _styled_axes(ax1, th)
        ax1.bar([str(r) for r in reg_ids], diff_coeff_reg, color='#f5a623', alpha=0.85, width=0.6)
        ax1.axhline(1.0, color='#ff5e5e', linestyle='--', linewidth=1.5, label='基准线(=1)')
        ax1.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('差异系数', color=th['subtext'], fontsize=10)
        ax1.set_title('区域流线长度差异系数', color=th['text'], fontsize=13)
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
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
        if sub.empty:
            return jsonify({'error': f'无参数编号 {param_num} 的数据'}), 400

        ex = sub['X'].astype(float).values
        ey = sub['Y'].astype(float).values
        vals = sub['Value'].astype(float).values

        img = load_img(img_file)
        h_img, w_img = img.shape[:2]

        # 散点插值到图像坐标系
        from scipy.interpolate import griddata
        xi = np.linspace(ex.min(), ex.max(), w_img)
        yi = np.linspace(ey.min(), ey.max(), h_img)
        xi_g, yi_g = np.meshgrid(xi, yi)
        interp = griddata((ex, ey), vals, (xi_g, yi_g), method='linear')
        interp_filled = griddata((ex, ey), vals, (xi_g, yi_g), method='nearest')
        interp = np.where(np.isnan(interp), interp_filled, interp)

        vmin, vmax = float(np.nanmin(interp)), float(np.nanmax(interp))
        interp_norm = (interp - vmin) / (vmax - vmin + 1e-9)
        cm = _get_cmap('RdYlBu_r')
        heat_rgb = cm(interp_norm)[:, :, :3]
        overlay = (img / 255.0) * 0.35 + heat_rgb * 0.65
        overlay = np.clip(overlay, 0, 1)

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.scatter(ex * (w_img / (ex.max() - ex.min() + 1)),
                    ey * (h_img / (ey.max() - ey.min() + 1)),
                    c='white', s=30, zorder=5, edgecolors='#ffcc00', linewidths=0.8)
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
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
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
        ax1.set_title('各区域行为发生人次', color=th['text'], fontsize=13)
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
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
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        # 热力叠加（以 t 为权重）
        overlay, _ = _make_heatmap_overlay(img, x, y, weights=t, alpha=0.65, cmap='jet')
        ax0 = axes[0]
        ax0.set_facecolor('white')
        ax0.imshow(overlay)
        ax0.axis('off')
        ax0.set_title('行为时长热力图 (s)', color=th['text'], fontsize=13, pad=10)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        bw = 0.7 / len(uniq_beh)
        xs = np.arange(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            ax1.bar(xs + j * bw - 0.35 + bw/2, dur_matrix[:, j], width=bw,
                    color=palette(j), alpha=0.85, label=beh_labels[j])
        ax1.set_xticks(xs); ax1.set_xticklabels(uniq_reg, fontsize=8)
        ax1.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('时长 (s)', color=th['subtext'], fontsize=10)
        ax1.set_title('各区域行为时长', color=th['text'], fontsize=13)
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'total_duration_s': int(t.sum()),
            'behavior_types': len(uniq_beh),
            'behaviors': beh_labels,
        }
        return jsonify({'image': img_b64, 'summary': summary})
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
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        _styled_axes(ax0, th)
        bottom = np.zeros(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            ax0.bar(uniq_reg.astype(str), rate_matrix[:, j], bottom=bottom,
                    color=palette(j), alpha=0.85, label=beh_labels[j])
            bottom += rate_matrix[:, j]
        ax0.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('发生率', color=th['subtext'], fontsize=10)
        ax0.set_title('各区域行为发生率 (堆叠)', color=th['text'], fontsize=13, pad=10)
        ax0.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        fig.patch.set_facecolor(th['fig_bg'])

        ax1 = axes[1]
        _styled_axes(ax1, th)
        bw = 0.7 / len(uniq_beh)
        xs = np.arange(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            ax1.bar(xs + j * bw - 0.35 + bw/2, rate_matrix[:, j], width=bw,
                    color=palette(j), alpha=0.85, label=beh_labels[j])
        ax1.set_xticks(xs); ax1.set_xticklabels(uniq_reg, fontsize=8)
        ax1.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('发生率', color=th['subtext'], fontsize=10)
        ax1.set_title('各区域行为发生率 (分组)', color=th['text'], fontsize=13)
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_records': int(len(df)),
            'behavior_types': len(uniq_beh),
            'behaviors': beh_labels,
            'region_count': int(len(uniq_reg)),
        }
        return jsonify({'image': img_b64, 'summary': summary})
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

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        _styled_axes(ax0, th)
        _bar_common(ax0, uniq_reg, reg_entropy, color=th['accent'], ylabel='行为熵值 (bits)')
        ax0.set_title('各区域行为复合度', color=th['text'], fontsize=13, pad=10)

        ax1 = axes[1]
        _styled_axes(ax1, th)
        _bar_common(ax1, uniq_users, user_entropy, color='#00c9a7', ylabel='行为熵值 (bits)')
        ax1.set_title('各使用者行为复合度', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'region_count': int(len(uniq_reg)),
            'user_count': int(len(uniq_users)),
            'avg_reg_entropy': round(float(np.mean(reg_entropy)), 3),
            'behavior_types': int(len(uniq_beh)),
        }
        return jsonify({'image': img_b64, 'summary': summary})
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

        palette = _get_cmap('tab10', len(uniq_beh))
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        _styled_axes(ax0, th)
        bottom = np.zeros(len(uniq_reg))
        for j, b in enumerate(uniq_beh):
            ax0.bar(uniq_reg.astype(str), util_matrix[:, j], bottom=bottom,
                    color=palette(j), alpha=0.85, label=beh_labels[j])
            bottom += util_matrix[:, j]
        ax0.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('s/㎡', color=th['subtext'], fontsize=10)
        ax0.set_title('各区域功能利用率 (堆叠)', color=th['text'], fontsize=13, pad=10)
        ax0.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        fig.patch.set_facecolor(th['fig_bg'])

        ax1 = axes[1]
        _styled_axes(ax1, th)
        total_util = util_matrix.sum(axis=1)
        _bar_common(ax1, uniq_reg, total_util, color='#f5a623', ylabel='s/㎡')
        global_util = dur_matrix.sum() / reg_areas.sum() if reg_areas.sum() > 0 else 0
        ax1.axhline(global_util, color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'全局均值 {global_util:.1f}')
        ax1.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax1.set_title('各区域总功能利用率', color=th['text'], fontsize=13)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'region_count': int(len(uniq_reg)),
            'behavior_types': int(len(uniq_beh)),
            'global_util': round(float(global_util), 2),
            'behaviors': beh_labels,
        }
        return jsonify({'image': img_b64, 'summary': summary})
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
        ques_file = request.files.get('ques_data')
        if ques_file is None:
            return jsonify({'error': '请上传问卷数据'}), 400

        df = load_df(ques_file)
        required = {'UserNum', 'Satisfaction'}
        if not required.issubset(df.columns):
            return jsonify({'error': f'缺少列: {required - set(df.columns)}'}), 400

        user_ids = df['UserNum'].values
        scores = df['Satisfaction'].astype(float).values
        avg_score = float(scores.mean())

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        _styled_axes(ax0, th)
        colors = ['#7c5cfc' if s >= avg_score else '#00c9a7' for s in scores]
        ax0.bar([str(u) for u in user_ids], scores, color=colors, alpha=0.85, width=0.6)
        ax0.axhline(avg_score, color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'均值 {avg_score:.1f}')
        ax0.set_xlabel('人员编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('满意度得分', color=th['subtext'], fontsize=10)
        ax0.set_title('空间整体满意度', color=th['text'], fontsize=13, pad=10)
        ax0.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        fig.patch.set_facecolor(th['fig_bg'])

        ax1 = axes[1]
        _styled_axes(ax1, th)
        bins = [0, 60, 70, 80, 90, 100]
        labels_hist = ['<60', '60-70', '70-80', '80-90', '90-100']
        counts, _ = np.histogram(scores, bins=bins)
        ax1.bar(labels_hist, counts, color='#a78bfa', alpha=0.85, width=0.6)
        ax1.set_xlabel('分数段', color=th['subtext'], fontsize=10)
        ax1.set_ylabel('人数', color=th['subtext'], fontsize=10)
        ax1.set_title('满意度分布', color=th['text'], fontsize=13)
        ax1.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax1.set_axisbelow(True)

        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        summary = {
            'total_users': int(len(df)),
            'avg_score': round(avg_score, 1),
            'max_score': int(scores.max()),
            'min_score': int(scores.min()),
        }
        return jsonify({'image': img_b64, 'summary': summary})
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
        ques_file = request.files.get('ques_data')
        if ques_file is None:
            return jsonify({'error': '请上传问卷数据'}), 400

        df = load_df(ques_file)
        if 'UserNum' not in df.columns:
            return jsonify({'error': '缺少 UserNum 列'}), 400

        # 满意度列：除 UserNum 和 Satisfaction 外的其余 SatisfactionX 列
        sat_cols = [c for c in df.columns if c.startswith('Satisfaction') and c != 'Satisfaction']
        if not sat_cols:
            return jsonify({'error': '未找到区域满意度列 (SatisfactionX)'}), 400

        avg_vals = df[sat_cols].mean().values
        # 从列名提取区域编号（如 Satisfaction3 → 3）
        reg_ids = []
        for c in sat_cols:
            try:
                reg_ids.append(int(c.replace('Satisfaction', '')))
            except Exception:
                reg_ids.append(c)
        avg_score = float(avg_vals.mean())

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])

        ax0 = axes[0]
        _styled_axes(ax0, th)
        colors = ['#7c5cfc' if v >= avg_score else '#00c9a7' for v in avg_vals]
        ax0.bar([str(r) for r in reg_ids], avg_vals, color=colors, alpha=0.85, width=0.6)
        ax0.axhline(avg_score, color='#ff5e5e', linestyle='--', linewidth=1.5,
                    label=f'均值 {avg_score:.1f}')
        ax0.set_xlabel('区域编号', color=th['subtext'], fontsize=10)
        ax0.set_ylabel('满意度均值', color=th['subtext'], fontsize=10)
        ax0.set_title('各区域满意度', color=th['text'], fontsize=13, pad=10)
        ax0.legend(facecolor=th['legend_bg'], edgecolor=th['spine'], labelcolor=th['bar_label'], fontsize=8)
        ax0.yaxis.grid(True, color=th['grid'], linewidth=0.5)
        ax0.set_axisbelow(True)
        fig.patch.set_facecolor(th['fig_bg'])

        # 右侧：雷达图
        ax1 = fig.add_subplot(122, polar=True)
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
        img_b64 = fig_to_base64(fig)
        plt.close(fig)

        region_details = [{'region': str(r), 'avg_score': round(float(v), 1)}
                          for r, v in zip(reg_ids, avg_vals)]
        summary = {
            'region_count': int(len(reg_ids)),
            'avg_score': round(avg_score, 1),
            'best_region': str(reg_ids[int(np.argmax(avg_vals))]),
            'worst_region': str(reg_ids[int(np.argmin(avg_vals))]),
            'regions': region_details,
        }
        return jsonify({'image': img_b64, 'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
