#!/usr/bin/env python3
"""
ThingsBoard Gateway 实时 CPU 监控脚本
可以监控特定函数的执行时间和调用频率
使用方法：
1. 在需要监控的代码中导入此模块
2. 使用 @monitor_function 装饰器
3. 或者直接运行此脚本进行系统级监控
"""

import time
import threading
import psutil
import logging
from collections import defaultdict
from functools import wraps
from datetime import datetime
import json

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('CPU_Monitor')

# 全局统计信息
class FunctionStats:
    def __init__(self):
        self.call_count = 0
        self.total_time = 0.0
        self.max_time = 0.0
        self.min_time = float('inf')
        self.last_time = 0.0

    def add_call(self, elapsed_time):
        self.call_count += 1
        self.total_time += elapsed_time
        self.max_time = max(self.max_time, elapsed_time)
        self.min_time = min(self.min_time, elapsed_time)
        self.last_time = elapsed_time

    def get_stats(self):
        avg_time = self.total_time / self.call_count if self.call_count > 0 else 0
        return {
            'call_count': self.call_count,
            'total_time': self.total_time * 1000,  # 转换为毫秒
            'avg_time': avg_time * 1000,
            'max_time': self.max_time * 1000,
            'min_time': self.min_time * 1000 if self.min_time != float('inf') else 0,
            'last_time': self.last_time * 1000
        }

# 全局函数统计字典
function_stats = defaultdict(FunctionStats)
stats_lock = threading.Lock()

def monitor_function(func_name=None):
    """
    函数性能监控装饰器

    使用示例：
    @monitor_function()
    def my_function():
        pass

    或者指定名称：
    @monitor_function("CustomName")
    def my_function():
        pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed_time = time.perf_counter() - start_time
                name = func_name or func.__name__

                with stats_lock:
                    function_stats[name].add_call(elapsed_time)

                # 如果函数执行时间超过阈值，记录警告
                if elapsed_time > 0.1:  # 100ms
                    logger.warning(
                        f"SLOW CALL: {name} took {elapsed_time*1000:.2f}ms"
                    )

        return wrapper
    return decorator


class CpuMonitorThread(threading.Thread):
    """后台 CPU 监控线程"""

    def __init__(self, interval=5.0, top_n=20):
        super().__init__()
        self.interval = interval
        self.top_n = top_n
        self.stopped = False
        self.daemon = True

    def run(self):
        """定期打印性能统计"""
        logger.info(f"CPU 监控线程启动，间隔 {self.interval} 秒")

        while not self.stopped:
            time.sleep(self.interval)
            self.print_stats()

    def print_stats(self):
        """打印当前的性能统计"""
        with stats_lock:
            if not function_stats:
                return

            # 按总耗时排序
            sorted_funcs = sorted(
                function_stats.items(),
                key=lambda x: x[1].total_time,
                reverse=True
            )

            print("\n" + "="*100)
            print(f"性能统计报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*100)
            print(f"{'函数名':<60} {'调用次数':>10} {'总耗时(ms)':>15} {'平均耗时(ms)':>15} {'最大耗时(ms)':>15} {'最后调用(ms)':>15}")
            print("-"*100)

            for func_name, stats in sorted_funcs[:self.top_n]:
                stat = stats.get_stats()
                print(
                    f"{func_name:<60} "
                    f"{stat['call_count']:>10} "
                    f"{stat['total_time']:>15.2f} "
                    f"{stat['avg_time']:>15.2f} "
                    f"{stat['max_time']:>15.2f} "
                    f"{stat['last_time']:>15.2f}"
                )

            # 显示进程级别统计
            process = psutil.Process()
            cpu_percent = process.cpu_percent(interval=0.1)
            memory_info = process.memory_info()

            print("-"*100)
            print(f"进程 CPU: {cpu_percent:.1f}% | 内存: {memory_info.rss / 1024 / 1024:.1f} MB")
            print("="*100 + "\n")

    def stop(self):
        """停止监控"""
        self.stopped = True


# 导出的便捷函数
def start_monitor(interval=5.0):
    """启动 CPU 监控"""
    monitor = CpuMonitorThread(interval=interval)
    monitor.start()
    return monitor


def print_report():
    """立即打印当前的性能报告"""
    monitor = CpuMonitorThread()
    monitor.print_stats()


def get_slow_functions(threshold_ms=100, top_n=10):
    """获取执行缓慢的函数"""
    with stats_lock:
        slow_funcs = []

        for func_name, stats in function_stats.items():
            stat = stats.get_stats()
            if stat['avg_time'] > threshold_ms:
                slow_funcs.append({
                    'name': func_name,
                    'stats': stat
                })

        # 按平均耗时排序
        slow_funcs.sort(key=lambda x: x['stats']['avg_time'], reverse=True)
        return slow_funcs[:top_n]


def save_report_to_file(filename=None):
    """保存性能报告到文件"""
    if filename is None:
        filename = f"/var/log/thingsboard-gateway/profile/cpu_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with stats_lock:
        report = {
            'timestamp': datetime.now().isoformat(),
            'functions': {
                name: stats.get_stats()
                for name, stats in function_stats.items()
            }
        }

    with open(filename, 'w') as f:
        json.dump(report, f, indent=2)

    logger.info(f"性能报告已保存到: {filename}")
    return filename


if __name__ == '__main__':
    # 独立运行时进行系统级监控
    print("ThingsBoard Gateway CPU 监控工具")
    print("="*50)

    try:
        pid = int(input("请输入 ThingsBoard Gateway 进程 PID: "))
    except ValueError:
        print("无效的 PID")
        exit(1)

    try:
        process = psutil.Process(pid)
        print(f"\n正在监控进程: {process.name()} (PID: {pid})")
        print(f"启动时间: {datetime.fromtimestamp(process.create_time())}")
        print(f"CPU 核心数: {psutil.cpu_count()}")

        # 开始监控
        monitor = CpuMonitorThread(interval=5.0)
        monitor.start()

        print("\n监控中... (按 Ctrl+C 停止)\n")

        # 持续显示进程状态
        while True:
            cpu_percent = process.cpu_percent(interval=1.0)
            memory_info = process.memory_info()
            threads = process.num_threads()
            connections = len(process.connections())

            print(f"\rCPU: {cpu_percent:5.1f}% | "
                  f"内存: {memory_info.rss / 1024 / 1024:6.1f} MB | "
                  f"线程: {threads:3d} | "
                  f"连接: {connections:3d}", end='', flush=True)

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n监控已停止")
        monitor.stop()
        save_report_to_file()
    except psutil.NoSuchProcess:
        print(f"\n错误：进程 {pid} 不存在")
    except Exception as e:
        print(f"\n错误：{e}")
