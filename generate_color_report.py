#!/usr/bin/env python3
"""生成详细的颜色分析报告和对比图"""

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

import sys
sys.path.insert(0, '.')
from api.analysis import _make_heatmap_overlay, _make_rbf_overlay, extract_measurement_mask, extract_walkable_mask

def create_comparison_report():
    """创建详细的对比报告"""
    
    # 加载图片
    img = np.array(Image.open('博物馆数据0521/1.png').convert('RGB'))
    bg_img = np.array(Image.open('博物馆数据0521/background.png').convert('RGB'))
    coverage_mask = extract_measurement_mask(bg_img)
    
    h, w = img.shape[:2]
    
    # 生成测试数据
    np.random.seed(42)
    
    # 测试1: 高斯密度热力图
    n_points = 500
    x1 = np.random.uniform(w*0.2, w*0.8, n_points)
    y1 = np.random.uniform(h*0.2, h*0.8, n_points)
    
    overlay1, _ = _make_heatmap_overlay(
        img, x1, y1, 
        alpha=0.70, 
        cmap='plasma',
        coverage_mask=coverage_mask
    )
    
    # 测试2: RBF插值热力图
    n_points2 = 20
    x2 = np.random.uniform(w*0.2, w*0.8, n_points2)
    y2 = np.random.uniform(h*0.2, h*0.8, n_points2)
    values2 = np.random.uniform(20, 30, n_points2)
    
    overlay2, _, _, _ = _make_rbf_overlay(
        img, x2, y2, values2,
        alpha=0.65,
        cmap='RdYlBu_r',
        coverage_mask=coverage_mask,
        kernel='linear'
    )
    
    # 创建对比图
    fig = plt.figure(figsize=(18, 12))
    fig.patch.set_facecolor('#0f1117')
    
    # 第一行：原图和coverage mask
    ax1 = plt.subplot(3, 3, 1)
    ax1.imshow(img)
    ax1.set_title('原始平面图', color='white', fontsize=12)
    ax1.axis('off')
    
    ax2 = plt.subplot(3, 3, 2)
    ax2.imshow(bg_img)
    ax2.set_title('Background Mask', color='white', fontsize=12)
    ax2.axis('off')
    
    ax3 = plt.subplot(3, 3, 3)
    mask_vis = np.zeros((h, w, 3), dtype=np.uint8)
    mask_vis[coverage_mask] = [0, 255, 0]  # 绿色表示可测量区域
    mask_vis[~coverage_mask] = [255, 0, 0]  # 红色表示背景
    ax3.imshow(mask_vis)
    ax3.set_title(f'Coverage区域 (绿色={np.sum(coverage_mask):,}px)', color='white', fontsize=12)
    ax3.axis('off')
    
    # 第二行：高斯密度热力图
    ax4 = plt.subplot(3, 3, 4)
    ax4.imshow(overlay1)
    ax4.set_title('高斯密度热力图 (plasma)', color='white', fontsize=12)
    ax4.axis('off')
    
    # 放大局部区域
    ax5 = plt.subplot(3, 3, 5)
    zoom_x, zoom_y, zoom_size = w//2, h//2, 200
    ax5.imshow(overlay1[zoom_y:zoom_y+zoom_size, zoom_x:zoom_x+zoom_size])
    ax5.set_title('局部放大 (检查边缘)', color='white', fontsize=12)
    ax5.axis('off')
    
    # 颜色直方图
    ax6 = plt.subplot(3, 3, 6)
    overlay1_uint8 = (overlay1 * 255).astype(np.uint8)
    coverage_pixels = overlay1_uint8[coverage_mask]
    ax6.hist(coverage_pixels[:, 0], bins=50, alpha=0.5, color='red', label='R')
    ax6.hist(coverage_pixels[:, 1], bins=50, alpha=0.5, color='green', label='G')
    ax6.hist(coverage_pixels[:, 2], bins=50, alpha=0.5, color='blue', label='B')
    ax6.set_title('RGB分布 (Coverage区域)', color='white', fontsize=12)
    ax6.set_facecolor('#1a1f2e')
    ax6.tick_params(colors='white')
    ax6.legend()
    
    # 第三行：RBF插值热力图
    ax7 = plt.subplot(3, 3, 7)
    ax7.imshow(overlay2)
    ax7.set_title('RBF插值热力图 (RdYlBu_r)', color='white', fontsize=12)
    ax7.axis('off')
    
    # 放大局部区域
    ax8 = plt.subplot(3, 3, 8)
    ax8.imshow(overlay2[zoom_y:zoom_y+zoom_size, zoom_x:zoom_x+zoom_size])
    ax8.set_title('局部放大 (检查边缘)', color='white', fontsize=12)
    ax8.axis('off')
    
    # 颜色直方图
    ax9 = plt.subplot(3, 3, 9)
    overlay2_uint8 = (overlay2 * 255).astype(np.uint8)
    coverage_pixels2 = overlay2_uint8[coverage_mask]
    ax9.hist(coverage_pixels2[:, 0], bins=50, alpha=0.5, color='red', label='R')
    ax9.hist(coverage_pixels2[:, 1], bins=50, alpha=0.5, color='green', label='G')
    ax9.hist(coverage_pixels2[:, 2], bins=50, alpha=0.5, color='blue', label='B')
    ax9.set_title('RGB分布 (Coverage区域)', color='white', fontsize=12)
    ax9.set_facecolor('#1a1f2e')
    ax9.tick_params(colors='white')
    ax9.legend()
    
    plt.tight_layout()
    plt.savefig('color_analysis_report.png', dpi=150, facecolor='#0f1117')
    print("✅ 详细报告已保存到: color_analysis_report.png")
    
    # 生成文本报告
    print("\n" + "="*70)
    print("颜色覆盖分析报告")
    print("="*70)
    
    for name, overlay_uint8 in [("高斯密度热力图", overlay1_uint8), ("RBF插值热力图", overlay2_uint8)]:
        print(f"\n【{name}】")
        coverage_pixels = overlay_uint8[coverage_mask]
        
        # 统计
        r_mean, g_mean, b_mean = np.mean(coverage_pixels, axis=0)
        r_std, g_std, b_std = np.std(coverage_pixels, axis=0)
        
        print(f"  RGB均值: R={r_mean:.1f}, G={g_mean:.1f}, B={b_mean:.1f}")
        print(f"  RGB标准差: R={r_std:.1f}, G={g_std:.1f}, B={b_std:.1f}")
        
        # 检查异常值
        white_count = np.sum(np.all(coverage_pixels == 255, axis=1))
        black_count = np.sum(np.all(coverage_pixels == 0, axis=1))
        near_white = np.sum(np.all(coverage_pixels > 240, axis=1))
        
        print(f"  纯白色(255,255,255): {white_count} ({white_count/len(coverage_pixels)*100:.4f}%)")
        print(f"  纯黑色(0,0,0): {black_count} ({black_count/len(coverage_pixels)*100:.4f}%)")
        print(f"  接近白色(>240): {near_white} ({near_white/len(coverage_pixels)*100:.4f}%)")
        
        if white_count == 0 and near_white < len(coverage_pixels) * 0.01:
            print(f"  ✅ 通过：无透明/白色区域")
        else:
            print(f"  ⚠️  警告：存在异常白色像素")

if __name__ == '__main__':
    create_comparison_report()
