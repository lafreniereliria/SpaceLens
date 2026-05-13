#!/usr/bin/env bash
# build_windows_docker.sh
# 在 Mac 上用 Docker 打包 Windows exe（无需 Windows 机器）
#
# 前提：已安装 Docker Desktop，并启用了 Rosetta/x86 模拟（或使用 linux/amd64）
#
# 用法：bash build_windows_docker.sh

set -e

IMAGE="tobix/pywine:3.11"   # 包含 Wine + Python 3.11 的 Docker 镜像
WORK_DIR="$(pwd)"

echo "=== SpaceLens Windows 打包（Docker + Wine）==="
echo "工作目录: $WORK_DIR"
echo ""
echo "1. 拉取 Docker 镜像（首次约需几分钟）..."
docker pull --platform linux/amd64 $IMAGE

echo ""
echo "2. 在容器内安装依赖并打包..."
docker run --rm \
  --platform linux/amd64 \
  -v "$WORK_DIR:/src" \
  -w /src \
  $IMAGE \
  bash -c "
    pip install -r requirements.txt pyinstaller &&
    pyinstaller build_windows.spec
  "

echo ""
echo "=== 打包完成 ==="
echo "输出位置: dist/SpaceLens/"
echo "可分发: 将 dist/SpaceLens/ 整个目录压缩发给 Windows 用户"
