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

# ── 桌面端原生文件对话框钩子 ──────────────────────────────
# desktop_app.py 启动时会注册此钩子，使 Flask 线程可安全触发 Qt 对话框
# 签名: (title, default_filename) -> str | None
_native_save_dialog_hook = None

def register_save_dialog_hook(fn):
    """由 desktop_app.py 调用，注册 Qt 原生保存对话框回调"""
    global _native_save_dialog_hook
    _native_save_dialog_hook = fn
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

        # 提取可行走区域 mask，屏蔽黑色墙体
        walkable = extract_walkable_mask(img)

        # KDE 渐变热力图（无栅格），热力不渗入墙体
        overlay, density = _make_heatmap_overlay(img, x, y, alpha=0.70, cmap='plasma',
                                                 walkable_mask=walkable)

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
# 内存会话缓存
# ─────────────────────────────────────────────
import uuid, time as _time, threading as _threading
from werkzeug.datastructures import FileStorage
from io import BytesIO

_sessions: dict = {}          # sid → {'results': {...}, 'ts': float, 'type': str}
_sess_lock = _threading.Lock()
_SESSION_TTL = 3600           # 1 小时 TTL

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


def _make_fs(data: bytes, filename: str) -> FileStorage:
    """从 bytes 重建 FileStorage"""
    return FileStorage(stream=BytesIO(data), filename=filename)


# ─────────────────────────────────────────────
# /api/run_all  —  一键计算所有指标（立即返回 sid，后台线程计算）
# ─────────────────────────────────────────────

def _bg_compute(sid, img_b, img_n, loc_b, loc_n, beh_b, beh_n,
                env_b, env_n, ques_b, ques_n, region_b, region_n,
                th):
    """后台线程：逐个计算指标，每算完一个就更新会话缓存"""

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

    def _update(name, result):
        """将单个指标结果写入会话缓存"""
        with _sess_lock:
            sess = _sessions.get(sid)
            if sess is None:
                return
            sess['results'][name] = result
            if result is not None and not result.get('error'):
                sess['computed'].append(name)
            else:
                # 记录跳过原因到 result
                if result is None:
                    sess['results'][name] = {'error': '数据不足，跳过（缺少必要文件或列）'}
                sess['skipped'].append(name)

    def _run_metric(name, fn):
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
        x = df['X'].astype(float).values
        y = df['Y'].astype(float).values
        img = load_img(mk(img_b, img_n))
        walkable = _get_walkable()
        overlay, density = _make_heatmap_overlay(img, x, y, alpha=0.70, cmap='plasma',
                                                  walkable_mask=walkable)
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor(th['fig_bg'])
        ax0 = axes[0]; ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('到访频次热力图', color=th['text'], fontsize=13, pad=10)
        sm = plt.cm.ScalarMappable(cmap='plasma', norm=mcolors.Normalize(0, 1))
        sm.set_array([]); cbar = fig.colorbar(sm, ax=ax0, fraction=0.03, pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'], labelsize=8)
        cbar.set_label('到访密度', color=th['subtext'], fontsize=9)
        ax1 = axes[1]; _styled_axes(ax1, th)
        if 'Region' in df.columns:
            rc = df.groupby('Region').size().reset_index(name='count')
            _bar_common(ax1, rc['Region'], rc['count'], color=th['accent'], ylabel='到访人次', th=th)
            ax1.set_title('各区域到访频次', color=th['text'], fontsize=13)
        plt.tight_layout(pad=2)
        img_b64 = fig_to_base64(fig); plt.close(fig)
        n_nz = int((density > density.max() * 0.05).sum())
        return {'image': img_b64, 'summary': {
            'total_records': int(len(df)),
            'unique_users': int(df['UserID'].nunique()) if 'UserID' in df.columns else '-',
            'peak_frequency': round(float(density.max()), 2),
            'covered_area_pct': round(n_nz / density.size * 100, 1),
        }}
    _run_metric('heatmap', _heatmap)

    # ── A2 使用时长 ──
    def _usetime():
        if not loc_b or not img_b: return None
        df = load_df(mk(loc_b, loc_n))
        if not {'X','Y','Region','t'}.issubset(df.columns): return None
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        t=df['t'].astype(float).values; regions=df['Region'].astype(int).values
        img=load_img(mk(img_b, img_n))
        reg_ids=np.sort(np.unique(regions))
        reg_dur=np.array([t[regions==r].sum() for r in reg_ids])
        overlay,fg=_make_heatmap_overlay(img,x,y,weights=t,alpha=0.65,cmap='jet',
                                          walkable_mask=_get_walkable())
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('空间使用时长热力图',color=th['text'],fontsize=13,pad=10)
        sm=plt.cm.ScalarMappable(cmap='jet',norm=mcolors.Normalize(0,float(fg.max())))
        sm.set_array([]); cbar=fig.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8)
        cbar.set_label('停留时长 (s)',color=th['subtext'],fontsize=9)
        ax1=axes[1]; _styled_axes(ax1,th)
        _bar_common(ax1,reg_ids,reg_dur,color='#00c9a7',ylabel='时长 (s)',th=th)
        ax1.set_title('各区域使用时长',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_records':int(len(df)),'total_duration_s':int(t.sum()),'region_count':int(len(reg_ids)),'peak_region':int(reg_ids[np.argmax(reg_dur)])}}
    _run_metric('usetime', _usetime)

    # ── A3 移动速率 ──
    def _speed():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','t','UserID'}.issubset(df.columns): return None
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
        overlay,_=_make_heatmap_overlay(img,x_all,y_all,weights=weights,alpha=0.65,cmap='jet',
                                         walkable_mask=_get_walkable())
        global_speed=reg_length.sum()/reg_dwell.sum() if reg_dwell.sum()>0 else 0
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('空间移动速率热力图 (m/s)',color=th['text'],fontsize=13,pad=10)
        ax1=axes[1]; _styled_axes(ax1,th)
        _bar_common(ax1,reg_ids,mean_speed,color='#f5a623',ylabel='速率 (m/s)',th=th)
        ax1.axhline(global_speed,color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'全局均值 {global_speed:.3f}')
        ax1.legend(facecolor=th['legend_bg'],edgecolor=th['legend_edge'],labelcolor=th['tick'],fontsize=8)
        ax1.set_title('各区域平均移动速率',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_records':int(len(df)),'global_speed_ms':round(float(global_speed),4),'peak_speed_region':int(reg_ids[np.argmax(mean_speed)]),'region_count':int(len(reg_ids))}}
    _run_metric('speed', _speed)

    # ── A4 停留时长 ──
    def _duration():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','t'}.issubset(df.columns): return None
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        t=df['t'].astype(float).values; regions=df['Region'].astype(int).values
        img=load_img(mk(img_b,img_n))
        reg_ids=np.sort(np.unique(regions))
        reg_dwell=np.array([t[regions==r].sum() for r in reg_ids])
        overlay,fg=_make_heatmap_overlay(img,x,y,weights=t,alpha=0.65,cmap='jet',
                                          walkable_mask=_get_walkable())
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('空间停留时长热力图 (s)',color=th['text'],fontsize=13,pad=10)
        sm=plt.cm.ScalarMappable(cmap='jet',norm=mcolors.Normalize(0,float(t.max())))
        sm.set_array([]); cbar=fig.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
        cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8); cbar.set_label('停留时长 (s)',color=th['subtext'],fontsize=9)
        ax1=axes[1]; _styled_axes(ax1,th)
        _bar_common(ax1,reg_ids,reg_dwell,color=th['accent'],ylabel='时长 (s)',th=th)
        ax1.set_title('各区域停留时长',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_records':int(len(df)),'total_dwell_s':int(t.sum()),'avg_dwell_s':round(float(t.mean()),1),'peak_region':int(reg_ids[np.argmax(reg_dwell)])}}
    _run_metric('duration', _duration)

    # ── A5 空间聚类 (trajectory cluster) ──
    def _cluster():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y'}.issubset(df.columns): return None
        img=load_img(mk(img_b,img_n))
        # 过滤不可走区域的点，再做聚类
        walkable=_get_walkable()
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        if walkable is not None:
            x,y=filter_points_in_mask(x,y,walkable)
        data_xy=np.column_stack([x,y]); k=max(2,min(5,len(data_xy)-1))
        centers,labels=_kmeans2(data_xy.astype(float),k,iter=10,minit='points',missing='warn',seed=42)
        inertia=float(sum(((data_xy[labels==i]-c)**2).sum() for i,c in enumerate(centers)))
        palette=_get_cmap('tab10',k)
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(img,alpha=0.35); ax0.axis('off')
        for ci in range(k):
            mask=labels==ci; ax0.scatter(x[mask],y[mask],s=12,color=palette(ci),alpha=0.7,label=f'簇 {ci+1}')
        ax0.scatter(centers[:,0],centers[:,1],s=160,c='white',marker='*',zorder=10,edgecolors='#ffcc00',linewidths=1)
        ax0.set_title(f'空间聚类分析 (k={k})',color=th['text'],fontsize=13,pad=10)
        ax0.legend(loc='upper right',fontsize=8,ncol=2,facecolor=th['legend_bg'],edgecolor=th['legend_edge'],labelcolor=th['tick'])
        ax1=axes[1]; _styled_axes(ax1,th)
        cluster_sizes=[int(np.sum(labels==ci)) for ci in range(k)]
        bars=ax1.bar([f'簇{ci+1}' for ci in range(k)],cluster_sizes,color=[palette(ci) for ci in range(k)],alpha=0.85,width=0.55,edgecolor=th['bar_edge'],linewidth=0.5)
        for bar in bars:
            ax1.text(bar.get_x()+bar.get_width()/2,bar.get_height()+0.5,str(int(bar.get_height())),ha='center',va='bottom',color=th['bar_label'],fontsize=9)
        ax1.set_ylabel('点位数量',color=th['subtext'],fontsize=10); ax1.set_title('各聚类点位分布',color=th['text'],fontsize=13)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'k':k,'total_points':len(x),'inertia':round(inertia,1)}}
    _run_metric('cluster', _cluster)

    # ── A6 人员密度 ──
    def _density_fn():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','UserID'}.issubset(df.columns): return None
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        regions=df['Region'].astype(int).values; img=load_img(mk(img_b,img_n))
        reg_ids=np.sort(np.unique(regions))
        reg_uu=np.array([df[df['Region']==r]['UserID'].nunique() for r in reg_ids])
        overlay,_=_make_heatmap_overlay(img,x,y,alpha=0.65,cmap='jet',walkable_mask=_get_walkable())
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('人员分布热力图',color=th['text'],fontsize=13,pad=10)
        ax1=axes[1]; _styled_axes(ax1,th)
        _bar_common(ax1,reg_ids,reg_uu,color='#00c9a7',ylabel='独立人员数',th=th)
        ax1.set_title('各区域独立人员数',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_records':int(len(df)),'unique_users':int(df['UserID'].nunique()),'region_count':int(len(reg_ids)),'peak_region':int(reg_ids[np.argmax(reg_uu)])}}
    _run_metric('density', _density_fn)

    # ── A7 空间开放程度 ──
    def _openness_fn():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','UserID'}.issubset(df.columns): return None
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
        overlay,_=_make_heatmap_overlay(img,x,y,alpha=0.65,cmap='jet',walkable_mask=_get_walkable())
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
        ax0.set_title('空间开放程度热力图',color=th['text'],fontsize=13,pad=10)
        ax1=axes[1]; _styled_axes(ax1,th)
        _bar_common(ax1,reg_ids,openness_val,color='#f5a623',ylabel='人/㎡',th=th)
        ax1.axhline(global_open,color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'整体 {global_open:.3f}')
        ax1.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax1.set_title('各区域开放程度 (人/㎡)',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'unique_users':int(df['UserID'].nunique()),'global_openness':round(float(global_open),4),'peak_region':int(reg_ids[np.argmax(openness_val)]),'region_count':int(len(reg_ids))}}
    _run_metric('openness', _openness_fn)

    # ── A8 拓扑连接关系 ──
    def _topology_fn():
        if not loc_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','Region','UserID'}.issubset(df.columns): return None
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
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; _styled_axes(ax0,th)
        im=ax0.imshow(trans,cmap='YlOrRd',aspect='auto')
        ax0.set_xticks(range(n)); ax0.set_xticklabels(reg_ids,fontsize=8)
        ax0.set_yticks(range(n)); ax0.set_yticklabels(reg_ids,fontsize=8)
        ax0.set_xlabel('目标区域',color=th['subtext'],fontsize=10); ax0.set_ylabel('出发区域',color=th['subtext'],fontsize=10)
        ax0.set_title('区域人员转移矩阵',color=th['text'],fontsize=13,pad=10)
        for i in range(n):
            for j in range(n):
                v=trans[i,j]
                if v>0: ax0.text(j,i,str(int(v)),ha='center',va='center',fontsize=7,color='black' if v<trans.max()*0.6 else 'white',fontweight='bold')
        cbar=fig.colorbar(im,ax=ax0,fraction=0.04,pad=0.02); cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8)
        ax1=axes[1]; _styled_axes(ax1,th)
        in_deg=trans.sum(axis=0); out_deg=trans.sum(axis=1); bw=0.35; xs=np.arange(n)
        bars_in=ax1.bar(xs-bw/2,in_deg,width=bw,color=th['accent'],alpha=0.85,label='入流')
        bars_out=ax1.bar(xs+bw/2,out_deg,width=bw,color='#00c9a7',alpha=0.85,label='出流')
        for bar in bars_in:
            h=bar.get_height()
            if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.02,str(int(h)),ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        for bar in bars_out:
            h=bar.get_height()
            if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.02,str(int(h)),ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(xs); ax1.set_xticklabels(reg_ids,fontsize=8)
        ax1.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax1.set_ylabel('流量',color=th['subtext'],fontsize=10)
        ax1.set_title('各区域人员流入/流出量',color=th['text'],fontsize=13)
        ax1.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'region_count':n,'total_transitions':int(trans.sum())}}
    _run_metric('topology', _topology_fn)

    # ── A9 轨迹差异系数 ──
    def _difference_fn():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','UserID','Region'}.issubset(df.columns): return None
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
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; _styled_axes(ax0,th)
        bars0=ax0.bar([str(u) for u in per_ids],diff_coeff_per,color=th['accent'],alpha=0.85,width=0.6)
        for bar in bars0:
            h=bar.get_height()
            ax0.text(bar.get_x()+bar.get_width()/2,h+h*0.01,f'{h:.2f}',ha='center',va='bottom',color=th['bar_label'],fontsize=8)
        ax0.axhline(1.0,color='#ff5e5e',linestyle='--',linewidth=1.5,label='基准线(=1)')
        ax0.set_xlabel('人员编号',color=th['subtext'],fontsize=10); ax0.set_ylabel('差异系数',color=th['subtext'],fontsize=10)
        ax0.set_title('人员轨迹长度差异系数',color=th['text'],fontsize=13,pad=10)
        ax0.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        ax1=axes[1]; _styled_axes(ax1,th)
        bars1=ax1.bar([str(r) for r in reg_ids],diff_coeff_reg,color='#f5a623',alpha=0.85,width=0.6)
        for bar in bars1:
            h=bar.get_height()
            ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.01,f'{h:.2f}',ha='center',va='bottom',color=th['bar_label'],fontsize=8)
        ax1.axhline(1.0,color='#ff5e5e',linestyle='--',linewidth=1.5,label='基准线(=1)')
        ax1.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax1.set_ylabel('差异系数',color=th['subtext'],fontsize=10)
        ax1.set_title('区域流线长度差异系数',color=th['text'],fontsize=13)
        ax1.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_users':int(len(per_ids)),'avg_length_m':round(float(avg_len),1),'max_diff_user':str(per_ids[np.argmax(diff_coeff_per)]),'region_count':int(len(reg_ids))}}
    _run_metric('difference', _difference_fn)

    # ── 人员轨迹 (trajectory) ──
    def _trajectory_fn():
        if not loc_b or not img_b: return None
        df=load_df(mk(loc_b,loc_n))
        if not {'X','Y','UserID'}.issubset(df.columns): return None
        img=load_img(mk(img_b,img_n))
        walkable=_get_walkable()
        user_ids=df['UserID'].unique(); palette=_get_cmap('tab20',len(user_ids)); total_lengths={}
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(img,alpha=0.4); ax0.axis('off')
        for idx,uid in enumerate(user_ids):
            ud=df[df['UserID']==uid].reset_index(drop=True)
            x_arr=ud['X'].values; y_arr=ud['Y'].values; color=palette(idx)
            # 过滤落在黑色区域（不可达）的数据点
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
            ax0.plot(x_s,y_s,color=color,lw=1.2,alpha=0.85)
            ax0.scatter(x_arr[0],y_arr[0],c=[color],s=40,marker='o',zorder=5,edgecolors='white',linewidths=0.5)
            ax0.scatter(x_arr[-1],y_arr[-1],c=[color],s=40,marker='D',zorder=5,edgecolors='white',linewidths=0.5)
            dx=np.diff(x_arr); dy=np.diff(y_arr); total_lengths[uid]=float(np.sum(np.sqrt(dx**2+dy**2))/SCALE)
        ax0.set_title('人员移动轨迹',color=th['text'],fontsize=13,pad=10)
        leg_n=min(12,len(user_ids))
        handles=[plt.Line2D([0],[0],color=palette(i),lw=2) for i in range(leg_n)]
        ax0.legend(handles,[f'用户{uid}' for uid in user_ids[:leg_n]],loc='upper right',fontsize=7,ncol=2,facecolor=th['legend_bg'],edgecolor=th['legend_edge'],labelcolor=th['tick'])
        ax1=axes[1]; _styled_axes(ax1,th)
        if not total_lengths:
            return None
        sorted_len=sorted(total_lengths.items(),key=lambda x:x[1],reverse=True)
        uids_s=[str(u) for u,_ in sorted_len]; lens_s=[l for _,l in sorted_len]
        bars=ax1.barh(uids_s,lens_s,color='#00c9a7',alpha=0.85,height=0.6)
        for bar in bars:
            ax1.text(bar.get_width()+0.1,bar.get_y()+bar.get_height()/2,f'{bar.get_width():.1f}m',va='center',color=th['bar_label'],fontsize=8)
        ax1.set_xlabel('轨迹长度 (m)',color=th['subtext'],fontsize=10); ax1.set_title('人员轨迹长度',color=th['text'],fontsize=13)
        ax1.xaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True); ax1.invert_yaxis()
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_users':len(user_ids),'avg_length_m':round(float(np.mean(list(total_lengths.values()))),1),'max_length_m':round(max(total_lengths.values()),1),'min_length_m':round(min(total_lengths.values()),1)}}
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
            if sub.empty: return None
            ex=sub['X'].astype(float).values; ey=sub['Y'].astype(float).values; vals=sub['Value'].astype(float).values
            img=load_img(mk(img_b,img_n)); h_img,w_img=img.shape[:2]
            from scipy.interpolate import griddata
            xi=np.linspace(ex.min(),ex.max(),w_img); yi=np.linspace(ey.min(),ey.max(),h_img)
            xi_g,yi_g=np.meshgrid(xi,yi)
            interp=griddata((ex,ey),vals,(xi_g,yi_g),method='linear')
            interp_filled=griddata((ex,ey),vals,(xi_g,yi_g),method='nearest')
            interp=np.where(np.isnan(interp),interp_filled,interp)
            vmin,vmax=float(np.nanmin(interp)),float(np.nanmax(interp))
            interp_norm=(interp-vmin)/(vmax-vmin+1e-9)
            cm=_get_cmap('RdYlBu_r'); heat_rgb=cm(interp_norm)[:,:,:3]
            overlay=np.clip((img/255.0)*0.35+heat_rgb*0.65,0,1)
            fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
            ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off')
            ax0.set_title(f'{label} 空间分布',color=th['text'],fontsize=13,pad=10)
            sm=plt.cm.ScalarMappable(cmap='RdYlBu_r',norm=mcolors.Normalize(vmin,vmax))
            sm.set_array([]); cbar=fig.colorbar(sm,ax=ax0,fraction=0.03,pad=0.02)
            cbar.ax.tick_params(colors=th['cbar_tick'],labelsize=8); cbar.set_label(label,color=th['subtext'],fontsize=9)
            ax1=axes[1]; _styled_axes(ax1,th)
            ax1.scatter(range(len(vals)),vals,color=th['accent'],s=40,alpha=0.85,zorder=3)
            for xi,vi in enumerate(vals):
                ax1.annotate(f'{vi:.2f}',(xi,vi),xytext=(0,6),textcoords='offset points',ha='center',va='bottom',color=th['bar_label'],fontsize=7)
            ax1.axhline(float(vals.mean()),color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'均值 {vals.mean():.2f}')
            ax1.set_xlabel('测点编号',color=th['subtext'],fontsize=10); ax1.set_ylabel(label,color=th['subtext'],fontsize=10)
            ax1.set_title(f'各测点{label}值',color=th['text'],fontsize=13)
            ax1.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
            ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
            plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
            return {'image':img_b64,'summary':{'param':label,'num_points':int(len(vals)),'mean':round(float(vals.mean()),2),'max':round(float(vals.max()),2),'min':round(float(vals.min()),2)}}
        return _inner

    for pn in range(1, 6):
        _run_metric(f'environment_p{pn}', _env_fn(pn))

    # ── C1-C4 行为指标 ──
    def _beh_count():
        if not beh_b or not img_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'X','Y','BehaviorNum','Region'}.issubset(df.columns): return None
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
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(img,alpha=0.5)
        for j,b in enumerate(uniq_beh):
            mask=beh_nums==b; ax0.scatter(x[mask],y[mask],s=18,color=palette(j),alpha=0.75,label=beh_labels[j],zorder=3)
        ax0.axis('off'); ax0.set_title('各行为发生分布',color=th['text'],fontsize=13,pad=10)
        ax0.legend(loc='upper right',fontsize=7,ncol=2,facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'])
        ax1=axes[1]; _styled_axes(ax1,th)
        bw=0.7/len(uniq_beh); xs=np.arange(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            bars_c=ax1.bar(xs+j*bw-0.35+bw/2,count_matrix[:,j],width=bw,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bar in bars_c:
                h=bar.get_height()
                if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.02,str(int(h)),ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(xs); ax1.set_xticklabels(uniq_reg,fontsize=8)
        ax1.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax1.set_ylabel('人次',color=th['subtext'],fontsize=10)
        ax1.set_title('各区域行为发生人次',color=th['text'],fontsize=13)
        ax1.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_records':int(len(df)),'behavior_types':len(uniq_beh),'region_count':int(len(uniq_reg)),'behaviors':beh_labels}}
    _run_metric('behavior_count', _beh_count)

    def _beh_dur():
        if not beh_b or not img_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'X','Y','BehaviorNum','Region','t'}.issubset(df.columns): return None
        img=load_img(mk(img_b,img_n))
        x=df['X'].astype(float).values; y=df['Y'].astype(float).values
        beh_nums=df['BehaviorNum'].astype(int).values; regions=df['Region'].astype(int).values; t=df['t'].astype(float).values
        beh_labels_map=df.groupby('BehaviorNum')['behaviortype'].first().to_dict() if 'behaviortype' in df.columns else {b:f'行为{b}' for b in np.unique(beh_nums)}
        uniq_beh=np.sort(np.unique(beh_nums)); uniq_reg=np.sort(np.unique(regions)); beh_labels=[str(beh_labels_map.get(b,b)) for b in uniq_beh]
        dur_matrix=np.zeros((len(uniq_reg),len(uniq_beh)))
        for i,r in enumerate(uniq_reg):
            for j,b in enumerate(uniq_beh): dur_matrix[i,j]=t[(regions==r)&(beh_nums==b)].sum()
        palette=_get_cmap('tab10',len(uniq_beh))
        overlay,_=_make_heatmap_overlay(img,x,y,weights=t,alpha=0.65,cmap='jet')
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; ax0.set_facecolor('white'); ax0.imshow(overlay); ax0.axis('off'); ax0.set_title('行为时长热力图 (s)',color=th['text'],fontsize=13,pad=10)
        ax1=axes[1]; _styled_axes(ax1,th)
        bw=0.7/len(uniq_beh); xs=np.arange(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            bars_d=ax1.bar(xs+j*bw-0.35+bw/2,dur_matrix[:,j],width=bw,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bar in bars_d:
                h=bar.get_height()
                if h>0: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.02,f'{h:.0f}',ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(xs); ax1.set_xticklabels(uniq_reg,fontsize=8)
        ax1.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax1.set_ylabel('时长 (s)',color=th['subtext'],fontsize=10)
        ax1.set_title('各区域行为时长',color=th['text'],fontsize=13)
        ax1.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_records':int(len(df)),'total_duration_s':int(t.sum()),'behavior_types':len(uniq_beh),'behaviors':beh_labels}}
    _run_metric('behavior_duration', _beh_dur)

    def _beh_rate():
        if not beh_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'BehaviorNum','Region','t'}.issubset(df.columns): return None
        beh_nums=df['BehaviorNum'].astype(int).values; regions=df['Region'].astype(int).values; t=df['t'].astype(float).values
        beh_labels_map=df.groupby('BehaviorNum')['behaviortype'].first().to_dict() if 'behaviortype' in df.columns else {b:f'行为{b}' for b in np.unique(beh_nums)}
        uniq_beh=np.sort(np.unique(beh_nums)); uniq_reg=np.sort(np.unique(regions)); beh_labels=[str(beh_labels_map.get(b,b)) for b in uniq_beh]
        rate_matrix=np.zeros((len(uniq_reg),len(uniq_beh)))
        for i,r in enumerate(uniq_reg):
            r_mask=regions==r; total_t=t[r_mask].sum()
            for j,b in enumerate(uniq_beh): rate_matrix[i,j]=t[r_mask&(beh_nums==b)].sum()/total_t if total_t>0 else 0
        palette=_get_cmap('tab10',len(uniq_beh))
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; _styled_axes(ax0,th); bottom=np.zeros(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            seg_bars=ax0.bar(uniq_reg.astype(str),rate_matrix[:,j],bottom=bottom,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bi,bar in enumerate(seg_bars):
                h=rate_matrix[bi,j]
                if h>0.02: ax0.text(bar.get_x()+bar.get_width()/2,bottom[bi]+h/2,f'{h:.1%}',ha='center',va='center',color='white',fontsize=7,fontweight='bold')
            bottom+=rate_matrix[:,j]
        ax0.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax0.set_ylabel('发生率',color=th['subtext'],fontsize=10)
        ax0.set_title('各区域行为发生率 (堆叠)',color=th['text'],fontsize=13,pad=10)
        ax0.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        ax1=axes[1]; _styled_axes(ax1,th)
        bw=0.7/len(uniq_beh); xs=np.arange(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            bars_r=ax1.bar(xs+j*bw-0.35+bw/2,rate_matrix[:,j],width=bw,color=palette(j),alpha=0.85,label=beh_labels[j])
            for bar in bars_r:
                h=bar.get_height()
                if h>0.01: ax1.text(bar.get_x()+bar.get_width()/2,h+h*0.04,f'{h:.1%}',ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(xs); ax1.set_xticklabels(uniq_reg,fontsize=8)
        ax1.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax1.set_ylabel('发生率',color=th['subtext'],fontsize=10)
        ax1.set_title('各区域行为发生率 (分组)',color=th['text'],fontsize=13)
        ax1.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax1.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax1.set_axisbelow(True)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'total_records':int(len(df)),'behavior_types':len(uniq_beh),'behaviors':beh_labels,'region_count':int(len(uniq_reg))}}
    _run_metric('behavior_rate', _beh_rate)

    def _beh_entropy():
        if not beh_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'BehaviorNum','Region','t'}.issubset(df.columns): return None
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
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; _styled_axes(ax0,th)
        _bar_common(ax0,uniq_reg,reg_entropy,color=th['accent'],ylabel='行为熵值 (bits)',th=th)
        ax0.set_title('各区域行为复合度',color=th['text'],fontsize=13,pad=10)
        ax1=axes[1]; _styled_axes(ax1,th)
        _bar_common(ax1,uniq_users,user_entropy,color='#00c9a7',ylabel='行为熵值 (bits)',th=th)
        ax1.set_title('各使用者行为复合度',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'region_count':int(len(uniq_reg)),'user_count':int(len(uniq_users)),'avg_reg_entropy':round(float(np.mean(reg_entropy)),3),'behavior_types':int(len(uniq_beh))}}
    _run_metric('behavior_entropy', _beh_entropy)

    # ── C5 功能利用率 ──
    def _util():
        if not beh_b: return None
        df=load_df(mk(beh_b,beh_n))
        if not {'BehaviorNum','Region','t'}.issubset(df.columns): return None
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
        palette=_get_cmap('tab10',len(uniq_beh))
        fig,axes=plt.subplots(1,2,figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=axes[0]; _styled_axes(ax0,th); bottom=np.zeros(len(uniq_reg))
        for j,b in enumerate(uniq_beh):
            ax0.bar(uniq_reg.astype(str),util_matrix[:,j],bottom=bottom,color=palette(j),alpha=0.85,label=beh_labels[j]); bottom+=util_matrix[:,j]
        ax0.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax0.set_ylabel('s/㎡',color=th['subtext'],fontsize=10)
        ax0.set_title('各区域功能利用率 (堆叠)',color=th['text'],fontsize=13,pad=10)
        ax0.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        ax1=axes[1]; _styled_axes(ax1,th)
        total_util=util_matrix.sum(axis=1)
        _bar_common(ax1,uniq_reg,total_util,color='#f5a623',ylabel='s/㎡',th=th)
        global_util=dur_matrix.sum()/reg_areas.sum() if reg_areas.sum()>0 else 0
        ax1.axhline(global_util,color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'全局均值 {global_util:.1f}')
        ax1.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax1.set_title('各区域总功能利用率',color=th['text'],fontsize=13)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'region_count':int(len(uniq_reg)),'behavior_types':int(len(uniq_beh)),'global_util':round(float(global_util),2),'behaviors':beh_labels}}
    _run_metric('utilization', _util)

    # ── D3 整体满意度 ──
    def _satisfaction_fn():
        if not ques_b: return None
        df=load_df(mk(ques_b,ques_n))
        if not {'UserNum','Satisfaction'}.issubset(df.columns): return None
        user_ids=df['UserNum'].values; scores=df['Satisfaction'].astype(float).values; avg_score=float(scores.mean())
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
        plt.tight_layout(pad=2); img_dist_b64=fig_to_base64(fig); plt.close(fig)
        bar_data=[[str(uid),float(s)] for uid,s in zip(user_ids,scores)]
        return {'image_dist':img_dist_b64,'bar_data':bar_data,'avg_score':round(avg_score,1),'summary':{'total_users':int(len(df)),'avg_score':round(avg_score,1),'max_score':int(scores.max()),'min_score':int(scores.min())}}
    _run_metric('satisfaction', _satisfaction_fn)

    # ── D4 空间区域满意度 ──
    def _sat_region():
        if not ques_b: return None
        df=load_df(mk(ques_b,ques_n))
        if 'UserNum' not in df.columns: return None
        sat_cols=[c for c in df.columns if c.startswith('Satisfaction') and c!='Satisfaction']
        if not sat_cols: return None
        avg_vals=df[sat_cols].mean().values
        reg_ids=[]
        for c in sat_cols:
            try: reg_ids.append(int(c.replace('Satisfaction','')))
            except: reg_ids.append(c)
        avg_score=float(avg_vals.mean())
        fig=plt.figure(figsize=(14,6)); fig.patch.set_facecolor(th['fig_bg'])
        ax0=fig.add_subplot(121); _styled_axes(ax0,th)
        colors=['#7c5cfc' if v>=avg_score else '#00c9a7' for v in avg_vals]
        bars_r=ax0.bar([str(r) for r in reg_ids],avg_vals,color=colors,alpha=0.85,width=0.6)
        for bar in bars_r:
            h=bar.get_height()
            ax0.text(bar.get_x()+bar.get_width()/2,h+1,f'{h:.1f}',ha='center',va='bottom',color=th['bar_label'],fontsize=8)
        ax0.axhline(avg_score,color='#ff5e5e',linestyle='--',linewidth=1.5,label=f'均值 {avg_score:.1f}')
        ax0.set_xlabel('区域编号',color=th['subtext'],fontsize=10); ax0.set_ylabel('满意度均值',color=th['subtext'],fontsize=10)
        ax0.set_title('各区域满意度',color=th['text'],fontsize=13,pad=10)
        ax0.legend(facecolor=th['legend_bg'],edgecolor=th['spine'],labelcolor=th['bar_label'],fontsize=8)
        ax0.yaxis.grid(True,color=th['grid'],linewidth=0.5); ax0.set_axisbelow(True)
        ax1=fig.add_subplot(122,polar=True); ax1.set_facecolor(th['ax_bg2'])
        theta=np.linspace(0,2*np.pi,len(reg_ids),endpoint=False)
        vals_r=np.append(avg_vals,avg_vals[0]); theta_r=np.append(theta,theta[0])
        ax1.plot(theta_r,vals_r,color=th['accent'],linewidth=2); ax1.fill(theta_r,vals_r,color=th['accent'],alpha=0.2)
        for i,(th_i,val) in enumerate(zip(theta,avg_vals)):
            ax1.annotate(f'{val:.1f}',(th_i,val),xytext=(0,6),textcoords='offset points',ha='center',va='bottom',color=th['bar_label'],fontsize=7)
        ax1.set_xticks(theta); ax1.set_xticklabels([str(r) for r in reg_ids],color=th['subtext'],fontsize=8)
        ax1.tick_params(colors=th['cbar_tick']); ax1.set_title('区域满意度雷达',color=th['text'],fontsize=13,pad=15)
        ax1.spines['polar'].set_color('#2d2d3d'); ax1.grid(color=th['grid'],linewidth=0.5)
        plt.tight_layout(pad=2); img_b64=fig_to_base64(fig); plt.close(fig)
        return {'image':img_b64,'summary':{'region_count':int(len(reg_ids)),'avg_score':round(avg_score,1),'best_region':str(reg_ids[int(np.argmax(avg_vals))]),'worst_region':str(reg_ids[int(np.argmin(avg_vals))])}}
    _run_metric('satisfaction_region', _sat_region)

    # ── 全部完成，标记 status + 存入数据库 ──
    with _sess_lock:
        sess = _sessions.get(sid)
        if sess is not None:
            sess['status'] = 'done'
            _save_project_to_db(sid, sess)


def _save_project_to_db(sid: str, sess: dict):
    """将会话结果写入本地数据库，并把结果持久化到磁盘文件夹（在后台线程调用，已持锁）"""
    try:
        from api.db import save_project as _db_save
        floorplan_b64  = _make_thumbnail(sess)
        result_folder  = _persist_results_to_disk(sid, sess)
        _db_save(
            name          = sess.get('project_name') or sess.get('folder') or '未命名项目',
            building_type = sess.get('type', ''),
            input_folder  = sess.get('folder', ''),
            session_id    = sid,
            computed      = sess.get('computed', []),
            skipped       = sess.get('skipped',  []),
            floorplan_b64 = floorplan_b64,
            files_md5     = sess.get('_files_md5'),
            result_folder = result_folder,
        )
    except Exception:
        pass  # 数据库写失败不影响主流程


def _persist_results_to_disk(sid: str, sess: dict) -> str | None:
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

        results  = sess.get('results',  {})
        computed = sess.get('computed', [])

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
            'computed':      computed,
            'skipped':       sess.get('skipped', []),
            'theme':         sess.get('theme', 'light'),
            'accent':        sess.get('accent', '#0ea5e9'),
        }
        with open(_os.path.join(result_dir, 'meta.json'), 'w', encoding='utf-8') as f:
            _json.dump(meta, f, ensure_ascii=False, indent=2)

        return result_dir
    except Exception:
        return None


def _make_thumbnail(sess: dict, max_size: int = 200) -> str | None:
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
    接收：layout_img, loc_data, behavior_data, env_data, ques_data, region_data (optional)
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
        ques_b, ques_n     = _read('ques_data')
        region_b, region_n = _read('region_data')

        # 计算各文件 MD5，用于去重
        import hashlib as _hashlib
        def _md5(b): return _hashlib.md5(b).hexdigest() if b else None
        files_md5 = {
            'img':    _md5(img_b),
            'loc':    _md5(loc_b),
            'beh':    _md5(beh_b),
            'env':    _md5(env_b),
            'ques':   _md5(ques_b),
            'region': _md5(region_b),
        }

        building_type = request.form.get('building_type', 'unknown')
        folder_name   = request.form.get('folder_name',   '')
        project_name  = request.form.get('project_name',  '')
        theme_name    = request.form.get('theme', 'dark')
        accent_param  = request.form.get('accent', '')

        th = _theme(theme_name)
        if accent_param:
            th['accent'] = accent_param

        # 立即创建会话（status = 'running'）
        sid = str(uuid.uuid4())
        with _sess_lock:
            _prune_sessions()
            _sessions[sid] = {
                'results':  {},
                'computed': [],
                'skipped':  [],
                'type':     building_type,
                'folder':   folder_name,
                'project_name': project_name or folder_name or '未命名项目',
                'ts':       _time.time(),
                'status':   'running',
                '_raw_img_b': img_b,     # 保留原图用于生成缩略图
                '_files_md5': files_md5, # 各文件 MD5，用于去重
                '_debug_img_b': img_b[:4] if img_b else None,
                '_debug_loc_b': loc_b[:4] if loc_b else None,
                '_debug_beh_b': beh_b[:4] if beh_b else None,
                '_debug_env_b': env_b[:4] if env_b else None,
                '_debug_ques_b': ques_b[:4] if ques_b else None,
                '_debug_files': {
                    'img': (img_n, len(img_b) if img_b else 0),
                    'loc': (loc_n, len(loc_b) if loc_b else 0),
                    'beh': (beh_n, len(beh_b) if beh_b else 0),
                    'env': (env_n, len(env_b) if env_b else 0),
                    'ques': (ques_n, len(ques_b) if ques_b else 0),
                    'region': (region_n, len(region_b) if region_b else 0),
                },
            }

        # 启动后台线程
        t = _threading.Thread(
            target=_bg_compute,
            args=(sid, img_b, img_n, loc_b, loc_n, beh_b, beh_n,
                  env_b, env_n, ques_b, ques_n, region_b, region_n, th),
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
        'computed':      sess.get('computed', []),
        'skipped':       sess.get('skipped',  []),
        'results':       sess.get('results',  {}),
        'status':        sess.get('status', 'running'),
        'debug_errors':  {k: v.get('error','') for k, v in sess.get('results', {}).items() if isinstance(v, dict) and v.get('error')},
    })


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
    接受 multipart/form-data：building_type + 核心文件（img/loc/beh/env/ques）。
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
            'ques': _md5(request.files.get('ques')),
        }
        # 过滤掉 None 值后再计算 dedup_key
        files_md5_nonempty = {k: v for k, v in files_md5.items() if v}

        dedup_key = _dedup_key(files_md5_nonempty, building_type)
        if not dedup_key:
            return jsonify({'duplicate': False})

        # 在数据库中查找相同 dedup_key
        with _lock:
            conn = _sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.row_factory = _sqlite3.Row
            try:
                rows = conn.execute(
                    'SELECT * FROM projects WHERE building_type = ? AND files_md5 IS NOT NULL',
                    (building_type,)
                ).fetchall()
                for row in rows:
                    try:
                        stored_md5_full = _j.loads(row['files_md5'] or '{}')
                    except Exception:
                        stored_md5_full = {}
                    # 只取核心键参与比对（忽略 region）
                    stored_md5_core = {k: v for k, v in stored_md5_full.items()
                                       if k in ('img', 'loc', 'beh', 'env', 'ques') and v}
                    if _dedup_key(stored_md5_core, row['building_type']) == dedup_key:
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

        if sess is not None and sess.get('status') == 'done':
            return jsonify({
                'session_id':    sid,
                'building_type': sess.get('type', ''),
                'folder_name':   sess.get('folder', ''),
                'project_name':  sess.get('project_name', proj['name']),
                'computed':      sess.get('computed', []),
                'skipped':       sess.get('skipped',  []),
                'results':       sess.get('results',  {}),
                'status':        'done',
                'from_db':       False,
            })

        # ── 2. 尝试从磁盘恢复（优先使用 DB 记录的 result_folder，可被 query 参数覆盖）──
        manual_folder = request.args.get('result_folder', '').strip()
        disk_folder   = manual_folder or proj.get('result_folder', '') or ''

        if disk_folder:
            restored = _restore_session_from_disk(sid, disk_folder)
            if restored:
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
                        )
                    except Exception:
                        pass
                return jsonify({
                    'session_id':    sid,
                    'building_type': restored.get('type', ''),
                    'folder_name':   restored.get('folder', ''),
                    'project_name':  restored.get('project_name', proj['name']),
                    'computed':      restored.get('computed', []),
                    'skipped':       restored.get('skipped',  []),
                    'results':       restored.get('results',  {}),
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
            'computed':      proj['computed'],
            'skipped':       proj['skipped'],
            'results':       {},
            'status':        'expired',
            'from_db':       True,
            'result_folder': proj.get('result_folder', ''),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _restore_session_from_disk(sid: str, result_folder: str) -> dict | None:
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

        return {
            'status':        'done',
            'ts':            _time.time(),
            'project_name':  meta.get('project_name', ''),
            'type':          meta.get('building_type', ''),
            'folder':        meta.get('folder_name', ''),
            'computed':      computed,
            'skipped':       meta.get('skipped', []),
            'theme':         meta.get('theme', 'light'),
            'accent':        meta.get('accent', '#0ea5e9'),
            'results':       results,
        }
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
                          bandwidth=None, theme='dark', walkable_mask=None):
    """KDE 像素级高斯密度热力图叠加，返回 (overlay RGB float[0,1], density_2d)
    
    walkable_mask: bool 数组 (H,W)，False 的区域（黑色墙体）不叠加热力色。
    """
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

    # ── 屏蔽不可走区域（墙体/黑色区域）──
    if walkable_mask is not None:
        density_smooth = density_smooth * walkable_mask.astype(float)

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
