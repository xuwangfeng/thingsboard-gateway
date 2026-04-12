#!/bin/bash
# ThingsBoard Gateway 即时诊断脚本
# 无需修改代码，立即运行

set -e

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║     ThingsBoard Gateway CPU 100% 问题即时诊断工具                ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then
    echo "❌ 错误：此脚本需要 root 权限运行"
    echo "   请使用: sudo $0"
    exit 1
fi

# 查找网关进程
echo "🔍 正在查找 ThingsBoard Gateway 进程..."
PIDS=$(ps aux | grep -E 'tb_gateway|thingsboard-gateway' | grep -v grep | awk '{print $2}')

if [ -z "$PIDS" ]; then
    echo "❌ 错误：未找到运行中的网关进程"
    echo "   请确认网关正在运行"
    exit 1
fi

PID_COUNT=$(echo "$PIDS" | wc -l)

if [ $PID_COUNT -gt 1 ]; then
    echo "⚠️  警告：发现多个网关进程："
    echo "$PIDS"
    echo ""
    read -p "请输入要诊断的进程 PID: " PID
else
    PID=$PIDS
fi

echo "✓ 找到进程 PID: $PID"
echo ""

# 获取进程信息
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 进程基本信息"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 进程名称和命令
PROCESS_NAME=$(ps -p $PID -o comm=)
CMDLINE=$(ps -p $PID -o cmd= | head -c 100)
echo "进程名称: $PROCESS_NAME"
echo "命令行: $CMDLINE"
echo ""

# CPU 使用率（3 次采样取平均）
echo "正在采样 CPU 使用率（5秒）..."
CPU_USAGE=$(top -b -n 3 -d 1 -p $PID | grep $PID | awk '{sum+=$9; count++} END {print sum/count}')
echo "CPU 使用率: ${CPU_USAGE}%"

# 内存使用
MEMORY_INFO=$(ps -p $PID -o rss,vsz,%mem --no-headers | awk '{printf "RSS: %.1f MB, VSZ: %.1f MB, 内存百分比: %s%%\n", $1/1024, $2/1024, $3}')
echo "内存使用: $MEMORY_INFO"

# 线程数
THREAD_COUNT=$(ps -o nlwp -p $PID --no-headers | tr -d ' ')
echo "线程数量: $THREAD_COUNT"

# 运行时间
ELAPSED=$(ps -p $PID -o etime= --no-headers | tr -d ' ')
echo "运行时间: $ELAPSED"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📁 文件存储诊断"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 查找存储目录
STORAGE_DIRS=""
for DIR in /var/lib/thingsboard-gateway/data /var/log/thingsboard-gateway /tmp/thingsboard-gateway; do
    if [ -d "$DIR" ]; then
        STORAGE_DIRS="$DIR"
        break
    fi
done

if [ -z "$STORAGE_DIRS" ]; then
    # 尝试从进程的文件描述符中找到
    STORAGE_DIR=$(ls -l /proc/$PID/fd 2>/dev/null | grep -o '/[^[:space:]]*thingsboard[^[:space:]]*/data' | head -1)
    if [ -n "$STORAGE_DIR" ]; then
        STORAGE_DIRS=$(dirname "$STORAGE_DIR")
    fi
fi

if [ -z "$STORAGE_DIRS" ]; then
    echo "⚠️  警告：无法找到存储目录"
    echo "   请检查配置文件中的存储路径"
else
    echo "存储目录: $STORAGE_DIRS"
    echo ""

    # 统计数据文件
    if [ -d "$STORAGE_DIRS/data" ]; then
        DATA_DIR="$STORAGE_DIRS/data"
    elif [ -d "$STORAGE_DIRS" ]; then
        DATA_DIR="$STORAGE_DIRS"
    else
        DATA_DIR=""
    fi

    if [ -n "$DATA_DIR" ] && [ -d "$DATA_DIR" ]; then
        FILE_COUNT=$(ls -1 "$DATA_DIR"/data_*.txt 2>/dev/null | wc -l)
        echo "数据文件数量: $FILE_COUNT"

        if [ $FILE_COUNT -gt 0 ]; then
            # 文件总大小
            TOTAL_SIZE=$(du -sh "$DATA_DIR" | awk '{print $1}')
            echo "总存储大小: $TOTAL_SIZE"

            # 最大的 10 个文件
            echo ""
            echo "最大的 10 个文件:"
            ls -lhS "$DATA_DIR"/data_*.txt 2>/dev/null | head -10 | awk '{printf "  %s  %s\n", $5, $9}'

            # 文件行数统计（抽样）
            echo ""
            echo "文件行数分布（采样前 20 个文件）:"
            for file in $(ls -t "$DATA_DIR"/data_*.txt 2>/dev/null | head -20); do
                lines=$(wc -l < "$file" 2>/dev/null)
                if [ $lines -gt 0 ]; then
                    size=$(ls -lh "$file" | awk '{print $5}')
                    basename_file=$(basename "$file")
                    printf "  %-40s  %8s  %6d 行\n" "$basename_file" "$size" "$lines"
                fi            done
        else
            echo "  (没有找到数据文件)"
        fi
    fi

    # 检查 state 文件
    STATE_FILE=$(ls -1 "$DATA_DIR"/state_*.txt 2>/dev/null | head -1)
    if [ -n "$STATE_FILE" ]; then
        echo ""
        echo "State 文件内容:"
        cat "$STATE_FILE" 2>/dev/null || echo "  (无法读取)"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 系统资源分析"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 打开的文件描述符
FD_COUNT=$(ls -1 /proc/$PID/fd 2>/dev/null | wc -l)
echo "打开的文件描述符: $FD_COUNT"

# 检查是否有大量打开的 data 文件
OPEN_DATA_FILES=$(ls -l /proc/$PID/fd 2>/dev/null | grep -c 'data_' || echo "0")
if [ $OPEN_DATA_FILES -gt 10 ]; then
    echo "⚠️  警告：打开了 $OPEN_DATA_FILES 个数据文件"
fi

# 网络连接数
TCP_CONN_COUNT=$(netstat -anp 2>/dev/null | grep $PID | grep -c ESTABLISHED || echo "0")
echo "TCP 连接数: $TCP_CONN_COUNT"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 诊断结果与建议"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 分析 CPU 使用率
CPU_HIGH_THRESHOLD=80
if (( $(echo "$CPU_USAGE > $CPU_HIGH_THRESHOLD" | bc -l) )); then
    echo "🔴 严重：CPU 使用率过高 (${CPU_USAGE}%)"

    # 检查可能的瓶颈
    if [ -n "$FILE_COUNT" ] && [ $FILE_COUNT -gt 5000 ]; then
        echo ""
        echo "   💡 最可能的原因：文件数量过多导致排序和查找性能下降"
        echo ""
        echo "   证据："
        echo "      • 数据文件数量: $FILE_COUNT 个"
        echo "      • 这会导致 O(n log n) 的排序操作非常慢"
        echo ""
        echo "   ✅ 建议修复方案："
        echo "      1. 立即清理旧文件："
        echo "         cd $DATA_DIR && ls -t data_*.txt | tail -n +11 | xargs rm -f"
        echo ""
        echo "      2. 应用代码修复："
        echo "         • 在 EventStorageFiles 中缓存排序结果"
        echo "         • 使用字典索引代替线性查找"
    fi

    # 检查单个文件行数
    if [ -n "$DATA_DIR" ] && [ -d "$DATA_DIR" ]; then
        MAX_LINES=0
        for file in $(ls -t "$DATA_DIR"/data_*.txt 2>/dev/null | head -10); do
            lines=$(wc -l < "$file" 2>/dev/null || echo "0")
            if [ $lines -gt $MAX_LINES ]; then
                MAX_LINES=$lines
            fi
        done

        if [ $MAX_LINES -gt 5000 ]; then
            echo ""
            echo "   💡 次要原因：单个文件行数过多导致读取性能下降"
            echo ""
            echo "   证据："
            echo "      • 部分文件超过 $MAX_LINES 行"
            echo "      • 使用 readline() 跳过行的效率极低"
            echo ""
            echo "   ✅ 建议修复方案："
            echo "      • 使用字节偏移量（seek）代替逐行读取"
            echo "      • 在指针中记录字节位置而不是行号"
        fi
    fi

    # 检查线程数
    if [ $THREAD_COUNT -gt 100 ]; then
        echo ""
        echo "   💡 可能原因：线程数量过多"
        echo ""
        echo "   证据："
        echo "      • 当前线程数: $THREAD_COUNT"
        echo ""
        echo "   ✅ 建议修复方案："
        echo "      • 检查是否有线程泄漏"
        echo "      • 考虑使用线程池"
    fi

else
    echo "✓ CPU 使用率正常 (${CPU_USAGE}%)"
fi

# 检查内存
MEMORY_PERCENT=$(ps -p $PID -o %mem= --no-headers | tr -d ' ')
if (( $(echo "$MEMORY_PERCENT > 80" | bc -l) )); then
    echo "🔴 警告：内存使用率过高 (${MEMORY_PERCENT}%)"
    echo "   可能导致频繁的垃圾回收（GC），影响性能"
else
    echo "✓ 内存使用率正常 (${MEMORY_PERCENT}%)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 下一步操作"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. 生成详细的性能报告："
echo "   sudo python3 profile_gateway.py"
echo ""
echo "2. 使用 py-spy 实时监控："
echo "   sudo py-spy top --pid $PID"
echo ""
echo "3. 生成火焰图："
echo "   sudo py-spy record --pid $PID --output profile.svg --duration 60"
echo ""
echo "4. 查看完整的诊断指南："
echo "   cat DIAGNOSTIC_GUIDE.md"
echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "诊断完成！"
echo "══════════════════════════════════════════════════════════════════"
