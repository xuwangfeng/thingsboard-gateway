# ThingsBoard Gateway CPU 诊断工具包

本工具包提供了多种方法来诊断和定位 ThingsBoard Gateway CPU 100% 的问题。

## 🚀 快速开始（推荐）

### 方法 1：立即诊断（无需修改代码）

```bash
# 1. 赋予执行权限
chmod +x diagnose_now.sh

# 2. 运行诊断
sudo ./diagnose_now.sh
```

这个脚本会：
- ✓ 自动找到网关进程
- ✓ 检查 CPU、内存、线程数
- ✓ 分析存储文件（数量、大小、行数）
- ✓ 给出诊断结果和修复建议

**输出示例：**
```
🔴 严重：CPU 使用率过高 (95.2%)

   💡 最可能的原因：文件数量过多导致排序和查找性能下降

   证据：
      • 数据文件数量: 8,432 个
      • 这会导致 O(n log n) 的排序操作非常慢

   ✅ 建议修复方案：
      1. 立即清理旧文件：...
```

---

## 📊 详细诊断工具

### 工具 1：cProfile 性能分析

```bash
# 停止现有服务
sudo systemctl stop thingsboard-gateway

# 使用 profiler 启动网关
python3 profile_gateway.py

# 运行 1-2 小时后按 Ctrl+C 停止
# 会自动生成性能报告
```

**输出包括：**
- TOP 50 最耗 CPU 的函数（按累积时间）
- TOP 50 最耗 CPU 的函数（按自身时间）
- BACnet 相关函数性能
- 文件存储相关函数性能

---

### 工具 2：py-spy 实时监控（推荐用于生产环境）

```bash
# 安装
pip3 install py-spy

# 实时查看 top 函数
sudo py-spy top --pid <PID>

# 生成火焰图
sudo py-spy record --pid <PID> --output profile.svg --duration 60

# 查看调用堆栈
sudo py-spy dump --pid <PID> | grep -A 20 "event_storage"
```

---

### 工具 3：火焰图生成

```bash
# 1. 先使用 profile_gateway.py 或 py-spy 收集数据

# 2. 生成火焰图
chmod +x generate_flamegraph.sh
./generate_flamegraph.sh

# 3. 在浏览器中打开生成的 SVG 文件
```

火焰图直观显示：
- 哪些函数占用 CPU 最多
- 函数调用关系
- 性能瓶颈位置

---

### 工具 4：实时函数监控

```bash
# 启动监控（在另一个终端）
python3 monitor_cpu.py

# 输入网关进程 PID
# 将每 5 秒显示一次性能统计
```

**输出示例：**
```
===================================================================================================
性能统计报告 - 2025-01-15 14:30:45
===================================================================================================
函数名                                                      调用次数    总耗时(ms)   平均耗时(ms)   最大耗时(ms)   最后调用(ms)
----------------------------------------------------------------------------------------------------
storage.EventStorageReader.read                             12500        6234.50         0.50          125.30         0.45
storage.get_or_init_buffered_reader                         12500        4521.20         0.36          98.50          0.32
storage.readline                                            850000       3890.00         0.00          5.20           0.00
----------------------------------------------------------------------------------------------------
进程 CPU: 95.2% | 内存: 1024.5 MB
===================================================================================================
```

---

## 🔍 问题定位决策树

使用诊断工具后，根据输出定位问题：

### 问题 1：readline() 占用最高

**症状：**
- profiler 显示 `readline` 占用 30%+ CPU
- py-spy 显示大量时间在 `event_storage_reader.py:136`

**根本原因：** 使用 `readline()` 逐行跳过文件内容

**修复：** 使用字节偏移量代替逐行读取

---

### 问题 2：sorted() 占用最高

**症状：**
- profiler 显示 `sorted` 或 `get_data_files` 占用 20%+ CPU
- 文件数量 > 5000

**根本原因：** 每次都重新排序所有文件

**修复：** 缓存排序结果

---

### 问题 3：调用频率过高

**症状：**
- 函数执行时间短（<1ms）但调用次数极高（>10000/秒）
- 主循环无延迟

**根本原因：** 忙等待

**修复：** 添加适当的 sleep 或使用阻塞式 queue.get()

---

### 问题 4：JSON 解析占用高

**症状：**
- `loads()` 或 `dumps()` 占用 15%+ CPU
- 每次读取都解析大量 JSON

**根本原因：** 频繁的 JSON 序列化/反序列化

**修复：** 缓存解析结果或减少解析次数

---

## 📋 诊断检查清单

使用以下清单确保全面诊断：

- [ ] 运行 `diagnose_now.sh` 获取基本信息
- [ ] 使用 `py-spy top` 实时查看 CPU 占用
- [ ] 运行 `profile_gateway.py` 收集详细性能数据
- [ ] 生成火焰图查看调用关系
- [ ] 检查存储文件数量和大小
- [ ] 查看系统日志（`journalctl -u thingsboard-gateway`）
- [ ] 检查线程数和内存使用
- [ ] 确认具体哪个连接器（BACnet/MQTT/Modbus等）

---

## 🛠️ 临时缓解措施

在实施永久修复前，可以采取以下临时措施：

### 措施 1：清理旧文件

```bash
# 备份
sudo cp -r /var/lib/thingsboard-gateway/data /var/lib/thingsboard-gateway/data.backup

# 删除旧文件（保留最新 100 个)
sudo bash -c '
cd /var/lib/thingsboard-gateway/data
ls -t data_*.txt | tail -n +101 | xargs rm -f
'

# 重启网关
sudo systemctl restart thingsboard-gateway
```

### 措施 2：调整配置减少文件生成

编辑配置文件，减少 `maxRecordsPerFile`：

```json
{
  "storage": {
    "type": "file",
    "file": {
      "maxRecordsPerFile": 10000,
      "maxFilesCount": 50
    }
  }
}
```

### 措施 3：切换到内存存储（如果内存足够）

```json
{
  "storage": {
    "type": "memory",
    "memory": {
      "maxRecordsCount": 10000
    }
  }
}
```

---

## 📞 获取帮助

如果需要进一步帮助：

1. **收集诊断信息**
   ```bash
   # 运行所有诊断工具
   sudo ./diagnose_now.sh > diagnostic_report.txt
   sudo py-spy top --pid <PID> --batch > py_spy_top.txt &
   sudo py-spy record --pid <PID> --output profile.svg --duration 60
   ```

2. **准备以下信息**
   - ThingsBoard Gateway 版本
   - 使用的连接器类型（BACnet/MQTT/Modbus等）
   - 设备数量
   - 配置文件（去除敏感信息）

3. **查看详细文档**
   - `DIAGNOSTIC_GUIDE.md` - 完整诊断指南
   - `monitoring_patch.py` - 代码级监控示例

---

## 🎯 预期修复效果

应用修复后：

| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| CPU 使用率 | 95-100% | 5-15% | ↓ 85% |
| 文件读取时间 | 500ms | 5ms | ↓ 99% |
| 响应延迟 | 高 | 低 | 显著改善 |
| 系统稳定性 | 频繁崩溃 | 稳定运行 | 显著改善 |

---

## 📚 相关文件

- `profile_gateway.py` - cProfile 性能分析脚本
- `diagnose_now.sh` - 立即诊断脚本
- `generate_flamegraph.sh` - 火焰图生成脚本
- `monitor_cpu.py` - 实时函数监控
- `monitoring_patch.py` - 代码级监控补丁
- `DIAGNOSTIC_GUIDE.md` - 完整诊断指南

---

## ⚠️ 注意事项

1. **生产环境谨慎使用**：某些工具需要停止网关
2. **备份数据**：清理文件前务必备份
3. **逐步修复**：建议先实施临时措施，再应用代码修复
4. **监控效果**：修复后继续监控确保问题解决

---

**开始诊断：**

```bash
chmod +x diagnose_now.sh
sudo ./diagnose_now.sh
```

祝诊断顺利！🎉
