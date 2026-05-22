#!/usr/bin/env python3
"""测试热力图颜色覆盖情况，确保非background区域没有透明/白色"""

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 导入分析模块
import sys
sys.path.insert(0, '.')
from api.analysis import _make_heatmap_overlay, _make_rbf_overlay, extract_measurement_mask, extract_walkable_mask

def load_test_image(path):
    """加载测试图片"""
    img = Image.open(path).convert('RGB')
    return np.array(img)

def analyze_colors(overlay, coverage_mask, img_original, name="Test"):
    """分析热力图颜色分布"""
    print(f"\n{'='*60}")
    print(f"分析 {name}")
    print(f"{'='*60}")
    
    h, w = overlay.shape[:2]
    img_f = img_original / 255.0
    
    # 转换为 uint8 便于分析
    overlay_uint8 = (overlay * 255).astype(np.uint8)
    
    if coverage_mask is not None:
        fill_mask = coverage_mask.astype(bool)
        
        # 统计 coverage 区域内的颜色
        coverage_pixels = overlay_uint8[fill_mask]
        original_pixels = (img_f[fill_mask] * 255).astype(np.uint8)
        
        # 检查是否有像素等于原始底图（说明没有被上色）
        unchanged = np.all(coverage_pixels == original_pixels, axis=1)
        unchanged_count = np.sum(unchanged)
        unchanged_pct = unchanged_count / len(coverage_pixels) * 100 if len(coverage_pixels) > 0 else 0
        
        # 检查是否有纯白色（255,255,255）
        white_pixels = np.all(coverage_pixels == 255, axis=1)
        white_count = np.sum(white_pixels)
        white_pct = white_count / len(coverage_pixels) * 100 if len(coverage_pixels) > 0 else 0
        
        # 检查是否有接近白色的像素（RGB均>240）
        near_white = np.all(coverage_pixels > 240, axis=1)
        near_white_count = np.sum(near_white)
        near_white_pct = near_white_count / len(coverage_pixels) * 100 if len(coverage_pixels) > 0 else 0
        
        print(f"Coverage区域总像素数: {len(coverage_pixels):,}")
        print(f"未上色像素（等于原图）: {unchanged_count:,} ({unchanged_pct:.2f}%)")
        print(f"纯白色像素(255,255,255): {white_count:,} ({white_pct:.2f}%)")
        print(f"接近白色像素(>240): {near_white_count:,} ({near_white_pct:.2f}%)")
        
        # 颜色分布统计
        r_mean = np.mean(coverage_pixels[:, 0])
        g_mean = np.mean(coverage_pixels[:, 1])
        b_mean = np.mean(coverage_pixels[:, 2])
        print(f"RGB均值: R={r_mean:.1f}, G={g_mean:.1f}, B={b_mean:.1f}")
        
        # 检查结果
        if unchanged_pct > 1.0:
            print(f"⚠️  警告: {unchanged_pct:.2f}% 的coverage区域未被上色！")
        else:
            print(f"✅ 通过: 仅 {unchanged_pct:.2f}% 未上色（可接受）")
            
        if white_pct > 0.1:
            print(f"⚠️  警告: {white_pct:.2f}% 的coverage区域是纯白色！")
        else:
            print(f"✅ 通过: 纯白色像素 {white_pct:.4f}%（可接受）")
            
        if near_white_pct > 5.0:
            print(f"⚠️  警告: {near_white_pct:.2f}% 的coverage区域接近白色！")
        else:
            print(f"✅ 通过: 接近白色像素 {near_white_pct:.2f}%（可接受）")
    else:
        print("未提供 coverage_mask，跳过分析")

def test_heatmap_overlay():
    """测试 _make_heatmap_overlay 函数"""
    print("\n" + "="*60)
    print("测试 1: _make_heatmap_overlay (高斯密度热力图)")
    print("="*60)
    
    # 加载测试数据
    try:
        img = load_test_image('博物馆数据0521/1.png')
    except:
        print("⚠️  找不到测试图片，跳过测试")
        return
    
    try:
        bg_img = load_test_image('博物馆数据0521/background.png')
        coverage_mask = extract_measurement_mask(bg_img)
        print(f"✓ 加载 coverage_mask: {coverage_mask.shape}, True像素: {np.sum(coverage_mask):,}")
    except Exception as e:
        print(f"⚠️  找不到 background.png: {e}，使用 None")
        coverage_mask = None
    
    # 生成测试点（模拟到访数据）
    h, w = img.shape[:2]
    np.random.seed(42)
    n_points = 500
    x = np.random.uniform(w*0.2, w*0.8, n_points)
    y = np.random.uniform(h*0.2, h*0.8, n_points)
    
    # 调用函数
    overlay, density = _make_heatmap_overlay(
        img, x, y, 
        alpha=0.70, 
        cmap='plasma',
        walkable_mask=extract_walkable_mask(img) if coverage_mask is None else None,
        coverage_mask=coverage_mask
    )
    
    # 分析结果
    analyze_colors(overlay, coverage_mask, img, "高斯密度热力图")
    
    # 保存结果
    output_path = 'test_heatmap_output.png'
    plt.imsave(output_path, overlay)
    print(f"\n结果已保存到: {output_path}")

def test_rbf_overlay():
    """测试 _make_rbf_overlay 函数"""
    print("\n" + "="*60)
    print("测试 2: _make_rbf_overlay (RBF插值热力图)")
    print("="*60)
    
    # 加载测试数据
    try:
        img = load_test_image('博物馆数据0521/1.png')
    except:
        print("⚠️  找不到测试图片，跳过测试")
        return
    
    try:
        bg_img = load_test_image('博物馆数据0521/background.png')
        coverage_mask = extract_measurement_mask(bg_img)
        print(f"✓ 加载 coverage_mask: {coverage_mask.shape}, True像素: {np.sum(coverage_mask):,}")
    except Exception as e:
        print(f"⚠️  找不到 background.png: {e}，使用 None")
        coverage_mask = None
    
    # 生成测试点（模拟环境参数测点）
    h, w = img.shape[:2]
    np.random.seed(42)
    n_points = 20  # 稀疏测点
    x = np.random.uniform(w*0.2, w*0.8, n_points)
    y = np.random.uniform(h*0.2, h*0.8, n_points)
    values = np.random.uniform(20, 30, n_points)  # 模拟温度值
    
    # 调用函数
    overlay, field, vmin, vmax = _make_rbf_overlay(
        img, x, y, values,
        alpha=0.65,
        cmap='RdYlBu_r',
        walkable_mask=extract_walkable_mask(img) if coverage_mask is None else None,
        coverage_mask=coverage_mask,
        kernel='linear'
    )
    
    # 分析结果
    analyze_colors(overlay, coverage_mask, img, "RBF插值热力图")
    
    # 保存结果
    output_path = 'test_rbf_output.png'
    plt.imsave(output_path, overlay)
    print(f"\n结果已保存到: {output_path}")

if __name__ == '__main__':
    print("开始测试热力图颜色覆盖...")
    test_heatmap_overlay()
    test_rbf_overlay()
    print("\n" + "="*60)
    print("测试完成！")
    print("="*60)
