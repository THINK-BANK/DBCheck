#!/usr/bin/env bash
#
# build_and_run.sh — 一键重建并运行 DBCheck Docker 镜像
#
# 用途：删除旧容器 → 重新构建镜像（上下文为仓库根目录）→ 启动容器 → 跟随日志
# 适用：openEuler / Linux / WSL / Git Bash（x86_64 原生环境）
#
# 注意：
#   - 构建期需联网：pip 装依赖 + 从 atomgit.com 下载 drivers.zip（下载失败会故意报错退出）
#   - 镜像内 VERSION.txt 在 Dockerfile 中是硬编码字面量，--build-arg 改不了它，本脚本不传该参数
#   - 数据通过 volume 持久化（/app/data 等），重建容器不会丢数据
#
set -euo pipefail

# ── 路径解析：脚本在 build/，仓库根目录是其父目录 ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── 可配置项（环境变量覆盖）──
IMAGE="${IMAGE:-jackge12345/dbcheck:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-dbcheck}"
PORT="${PORT:-5003}"
DOCKERFILE="${DOCKERFILE:-deploy/Dockerfile}"
MEM_LIMIT="${MEM_LIMIT:-2g}"

# CPU 架构：原生 x86_64 直接打 amd64 即可；如需强制可设 PLATFORM=linux/amd64
PLATFORM="${PLATFORM:-}"

cd "${REPO_ROOT}"

echo "=================================================="
echo " DBCheck 一键构建并运行"
echo " 仓库根目录 : ${REPO_ROOT}"
echo " 镜像       : ${IMAGE}"
echo " 容器名     : ${CONTAINER_NAME}"
echo " 端口       : ${PORT}"
echo " Dockerfile : ${DOCKERFILE}"
echo "=================================================="

# ── 0) 前置检查 ──
if ! command -v docker >/dev/null 2>&1; then
  echo "❌ 未找到 docker，请先安装 Docker Engine 后再运行。" >&2
  exit 1
fi

# ── 1) 删除旧容器（若存在）──
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "🧹 删除旧容器 ${CONTAINER_NAME} ..."
  docker rm -f "${CONTAINER_NAME}" >/dev/null
  echo "✅ 旧容器已删除"
else
  echo "ℹ️  没有名为 ${CONTAINER_NAME} 的旧容器，跳过删除"
fi

# ── 2) 构建镜像（上下文 = 仓库根目录）──
echo "🔨 开始构建镜像 ${IMAGE} ..."
BUILD_ARGS=()
if [ -n "${PLATFORM}" ]; then
  BUILD_ARGS+=(--platform "${PLATFORM}")
fi

# --no-cache 确保 numpy<2 等修复真正生效；如需加速可去掉
docker build \
  "${BUILD_ARGS[@]}" \
  --no-cache \
  -t "${IMAGE}" \
  -f "${DOCKERFILE}" \
  .

echo "✅ 镜像构建完成：${IMAGE}"

# ── 3) 启动容器（数据用 volume 持久化）──
echo "🚀 启动容器 ${CONTAINER_NAME} ..."
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "${PORT}:5003" \
  --memory="${MEM_LIMIT}" \
  --memory-swap="${MEM_LIMIT}" \
  -v dbcheck_data:/app/data \
  -v dbcheck_pro_data:/app/data/pro_data \
  -v dbcheck_reports:/app/data/reports \
  "${IMAGE}"

echo "✅ 容器已启动：${CONTAINER_NAME}（端口 ${PORT}）"

# ── 4) 跟随日志（Ctrl+C 退出日志跟随，不影响容器运行）──
echo "📜 跟随日志（Ctrl+C 退出日志查看，容器继续后台运行）："
echo "--------------------------------------------------"
docker logs -f "${CONTAINER_NAME}"
