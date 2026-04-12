#!/bin/bash
# ThingsBoard Gateway 火焰图生成脚本
# 使用方法：./generate_flamegraph.sh

set -e

echo "正在安装火焰图工具..."

# 检查是否已安装 flamegraph
if [ ! -d "/tmp/flamegraph" ]; then
    git clone https://github.com/brendangregg/FlameGraph /tmp/flamegraph
fi

# 创建输出目录
PROFILE_DIR="/var/log/thingsboard-gateway/profile"
mkdir -p "$PROFILE_DIR"

echo "正在生成火焰图..."

# 查找最新的 profiler 文件
LATEST_PROF=$(ls -t "$PROFILE_DIR"/*.prof 2>/dev/null | head -1)

if [ -z "$LATEST_PROF" ]; then
    echo "错误：未找到 profiler 文件！"
    echo "请先运行: python3 profile_gateway.py"
    exit 1
fi

echo "使用 profiler 文件: $LATEST_PROF"

# 生成火焰图
FLAMEGRAPH_DIR="/tmp/flamegraph"
OUTPUT_FILE="$PROFILE_DIR/flamegraph_$(date +%Y%m%d_%H%M%S).svg"

python3 -m gprof2dot -f pstats "$LATEST_PROF" | \
    dot -Tsvg -o "$OUTPUT_FILE"

echo "火焰图已生成: $OUTPUT_FILE"

# 尝试用浏览器打开
if command -v xdg-open &> /dev/null; then
    xdg-open "$OUTPUT_FILE"
elif command -v open &> /dev/null; then
    open "$OUTPUT_FILE"
else
    echo "请在浏览器中打开: $OUTPUT_FILE"
fi

# 同时生成文本格式的调用树
echo ""
echo "==================== 调用树（前 100 层）===================="
python3 -m gprof2dot -f pstats "$LATEST_PROF" | head -100
