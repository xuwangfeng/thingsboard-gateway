# ThingsBoard Gateway 性能诊断指南

本指南帮助你定位 ThingsBoard Gateway CPU 100% 的根本原因。

## 方法 1：使用 cProfile（推荐用于首次诊断）

### 步骤 1：使用 Profile 脚本启动网关

```bash
# 停止现有的网关服务
sudo systemctl stop thingsboard-gateway

# 使用 profile 脚本启动
cd /path/to/thingsboard-gateway
python3 profile_gateway.py
```

### 步骤 2：让网关运行一段时间

- 让网关运行 **1-2 小时**，或者直到 CPU 100%
- 按 `Ctrl+C` 停止网关

### 步骤 3：查看性能报告

脚本会自动打印性能报告，输出格式如下：

```
==================== TOP 50 最耗 CPU 的函数（按累积时间排序）====================
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
    50000    45.23    0.00    120.45    0.02 event_storage_reader.py:134(get_or_init_buffered_reader)
    50000    30.12    0.00     80.34    0.00 event_storage_reader.py:136(readline)
    10000    15.67    0.00     60.23    0.06 event_storage_reader.py:165(read_state_file)
...
```

### 步骤 4：分析结果

**关键指标：**

1. **tottime（自身时间）** - 函数本身执行时间
   - 如果 `readline` 的 tottime 很高 → **跳过行是瓶颈**
   - 如果 `sorted` 的 tottime 很高 → **文件排序是瓶颈**

2. **cumtime（累积时间）** - 函数及其子函数总时间
   - 如果 `get_or_init_buffered_reader` 的 cumtime 很高 → **文件读取是瓶颈**
   - 如果 `read` 的 cumtime 很高 → **整个读取流程是瓶颈**

3. **ncalls（调用次数）** - 函数被调用次数
   - 如果 ncalls 非常高（>10000）→ **调用频率过高**

### 步骤 5：生成火焰图（可选）

```bash
chmod +x generate_flamegraph.sh
./generate_flamegraph.sh
```

火焰图会直观显示哪些函数占用了最多的 CPU 时间。

---

## 方法 2：使用 py-spy（推荐用于生产环境）

py-spy 可以在不修改代码的情况下监控运行中的 Python 进程。

### 安装 py-spy

```bash
pip3 install py-spy
```

### 监控运行中的进程

```bash
# 查找网关进程 PID
ps aux | grep tb_gateway

# 实时查看 top 函数（类似 top 命令）
sudo py-spy top --pid <PID>

# 生成火焰图
sudo py-spy record --pid <PID> --output profile.svg --duration 60

# 查看调用图
sudo py-spy dump --pid <PID> | grep -A 20 "event_storage"
```

### 解读输出

**py-spy top 输出示例：**

```
Collecting 60 seconds of profile data...
Total Samples: 60000
GIL: 45% (27000/60000)

  %Own  %Total  OwnTime  TotalTime  Function (filename:line)
  35.2%  42.1%   21.1s     25.3s    readline (event_storage_reader.py:136)
  15.8%  18.2%    9.5s     10.9s    sorted (event_storage_files.py:30)
  10.5%  12.1%    6.3s      7.3s    get_event_pack (tb_gateway_service.py:1431)
```

**关键发现：**
- 如果 `readline` 占用 35% → **文件逐行读取是问题**
- 如果 `sorted` 占用 15% → **文件排序是问题**
- 如果 `get_event_pack` 占用 10% → **频繁调用存储读取是问题**

---

## 方法 3：使用系统工具（无需修改代码）

### 使用 perf（Linux）

```bash
# 记录性能数据（运行 30 秒）
sudo perf record -g -p <PID> -- sleep 30

# 生成报告
sudo perf report

# 或者生成火焰图
sudo perf script | /tmp/flamegraph/stackcollapse-perf.pl | \
    /tmp/flamegraph/flamegraph.pl > perf-flamegraph.svg
```

### 使用 strace 追踪系统调用

```bash
# 追踪文件相关的系统调用
sudo strace -p <PID> -e trace=file -f -o strace.log &

# 运行一段时间后，分析日志
# 查看哪些文件被频繁访问
cat strace.log | grep "open.*data_" | wc -l

# 查看是否有大量的 lseek 或 read 调用
cat strace.log | grep -E "lseek|read" | head -50
```

**关键发现：**
- 如果有大量的 `read` 调用，每次只读少量数据 → **文件读取效率低**
- 如果有大量的 `lseek` 调用 → **文件指针频繁跳转**

---

## 方法 4：添加监控日志（需要修改代码）

### 快速添加日志到关键函数

编辑 `thingsboard_gateway/storage/file/event_storage_reader.py`:

```python
# 在文件顶部添加
import time
from logging import getLogger
log = getLogger("storage")

# 在 read() 方法开头添加
def read(self):
    start_time = time.time()
    file_count = len(self.files.get_data_files())

    # ... 原有代码 ...

    end_time = time.time()
    elapsed = (end_time - start_time) * 1000  # 转换为毫秒

    # 每隔一定次数记录一次（避免日志过多）
    if random.randint(1, 100) == 1:
        log.warning(
            f"[PERF] read() with {file_count} files took {elapsed:.2f}ms, "
            f"batch_size={len(self.current_batch) if self.current_batch else 0}"
        )

    return self.current_batch
```

### 在 get_or_init_buffered_reader() 添加日志

```python
def get_or_init_buffered_reader(self, pointer):
    start_time = time.time()
    lines_to_skip = pointer.get_line()

    # ... 原有代码 ...

    end_time = time.time()
    elapsed = (end_time - start_time) * 1000

    if lines_to_skip > 100 and elapsed > 10:
        log.warning(
            f"[PERF] Skipping {lines_to_skip} lines took {elapsed:.2f}ms"
        )

    return self.buffered_reader
```

### 在 __send_to_storage() 添加日志

编辑 `thingsboard_gateway/gateway/tb_gateway_service.py`:

```python
def __send_to_storage(self):
    while not self.stopped:
        loop_start = time.time()
        try:
            tasks = []
            collecting_start = int(monotonic() * 1000)
            batch_size = 1000

            # 原有的队列处理逻辑...

            loop_end = time.time()
            loop_elapsed = (loop_end - loop_start) * 1000

            if loop_elapsed > 100:  # 超过 100ms 就记录
                log.warning(
                    f"[PERF] __send_to_storage loop took {loop_elapsed:.2f}ms, "
                    f"processed={len(tasks)} tasks, "
                    f"queue_size={self.__converted_data_queue.qsize()}"
                )
        except Exception as e:
            log.error("Error while sending data to storage!", exc_info=e)
```

---

## 方法 5：使用 eBPF 工具（高级用户）

### 使用 offsche

```bash
# 安装
sudo apt-get install bpfcc-tools

# 追踪 Python 函数调用
sudo trace.py -p <PID> 'syscalls:sys_enter_openat'

# 或者使用 profile 工具
sudo profile.py -p <PID> -F 99 -a 60
```

---

## 诊断决策树

根据你的发现选择修复方案：

```
问题定位
    |
    ├─ readline() 占用最高？
    │   └─> 问题：逐行跳过文件内容
    │       修复：使用字节偏移量（seek）代替逐行读取
    │
    ├─ sorted() 占用最高？
    │   └─> 问题：频繁排序文件列表
    │       修复：缓存排序结果
    │
    ├─ get_event_pack() 调用频率过高？
    │   └─> 问题：主循环无延迟
    │       修复：添加适当的 sleep/wait
    │
    ├─ Base64 编解码占用高？
    │   └─> 问题：Base64 编解码开销
    │       修复：考虑去掉 Base64 或使用更快的方法
    │
    └─ JSON 解析占用高？
        └─> 问题：频繁的 JSON 解析
            修复：缓存解析结果或减少解析次数
```

---

## 常见问题诊断结果

### 场景 1：文件数量多（>5000）

**症状：**
- `sorted()` 在 profiler 中排第一
- `get_data_files()` 被频繁调用

**根本原因：**
每次调用都重新排序所有文件

**修复：**
在 `EventStorageFiles` 类中缓存排序结果

---

### 场景 2：单个文件行数多（>5000）

**症状：**
- `readline()` 在 profiler 中排第一
- 每次打开文件都要跳过大量行

**根本原因：**
使用 `readline()` 逐行跳过，效率极低

**修复：**
使用 `seek()` 直接跳转到字节偏移量

---

### 场景 3：调用频率过高

**症状：**
- 函数本身的执行时间很短（<1ms）
- 但调用次数极高（>10000 次/秒）

**根本原因：**
主循环没有适当的等待机制

**修复：**
在主循环中添加 `await asyncio.sleep()` 或使用 `queue.get()` 阻塞等待

---

## 快速诊断脚本

创建 `quick_diagnose.sh`:

```bash
#!/bin/bash

echo "=== ThingsBoard Gateway 快速诊断 ==="

# 检查进程
PID=$(ps aux | grep tb_gateway | grep -v grep | awk '{print $2}' | head -1)

if [ -z "$PID" ]; then
    echo "错误：网关进程未运行"
    exit 1
fi

echo "进程 PID: $PID"

# 检查 CPU
echo -e "\n=== CPU 使用率 ==="
top -b -n 1 -p $PID | tail -1

# 检查文件数量
echo -e "\n=== 存储文件统计 ==="
DATA_DIR="/var/lib/thingsboard-gateway/data"
if [ -d "$DATA_DIR" ]; then
    FILE_COUNT=$(ls -1 "$DATA_DIR"/data_*.txt 2>/dev/null | wc -l)
    echo "数据文件数量: $FILE_COUNT"

    if [ $FILE_COUNT -gt 0 ]; then
        echo -e "\n文件大小分布:"
        ls -lh "$DATA_DIR"/data_*.txt | awk '{print $5}' | sort | uniq -c
    fi
fi

# 检查线程数
echo -e "\n=== 线程信息 ==="
THREADS=$(ps -o nlwp -p $PID | tail -1)
echo "线程数量: $THREADS"

# 检查内存
echo -e "\n=== 内存使用 ==="
ps -p $PID -o rss,vsz,%mem | tail -1

# 检查打开的文件描述符
echo -e "\n=== 文件描述符 ==="
FD_COUNT=$(ls -1 /proc/$PID/fd 2>/dev/null | wc -l)
echo "打开的文件描述符数量: $FD_COUNT"

# 建议
echo -e "\n=== 诊断建议 ==="

if [ $FILE_COUNT -gt 5000 ]; then
    echo "⚠️  警告：文件数量过多（$FILE_COUNT）"
    echo "   建议：清理旧文件或增加文件删除策略"
fi

if [ $THREADS -gt 100 ]; then
    echo "⚠️  警告：线程数量过多（$THREADS）"
    echo "   建议：检查是否有线程泄漏"
fi
```

使用方法：

```bash
chmod +x quick_diagnose.sh
./quick_diagnose.sh
```

---

## 下一步

1. **选择一种诊断方法**（推荐从方法 1 或 2 开始）
2. **收集 1-2 小时的性能数据**
3. **分析报告找到瓶颈**
4. **应用相应的修复方案**
5. **验证修复效果**

需要我帮你分析诊断报告或实施具体的修复吗？
