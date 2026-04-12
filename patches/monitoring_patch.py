#!/usr/bin/env python3
"""
ThingsBoard Gateway 关键函数监控补丁
将此文件复制到 thingsboard_gateway/storage/file/ 目录
"""

import time
from functools import wraps
from thingsboard_gateway.monitor_cpu import function_stats, stats_lock
import logging

log = logging.getLogger('storage')

# 监控装饰器
def monitor_storage(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()

        try:
            result = func(*args, **kwargs)
            return result
        finally:
            elapsed_time = time.perf_counter() - start_time
            func_name = f"storage.{func.__name__}"

            with stats_lock:
                function_stats[func_name].add_call(elapsed_time)

            # 记录慢查询
            if elapsed_time > 0.01:  # 10ms
                log.warning(f"[SLOW] {func.__name__} took {elapsed_time*1000:.2f}ms")

    return wrapper


# ============ 文件存储读取监控 ============

# 在 event_storage_reader.py 的 read() 方法开头添加
def monitored_read(original_read):
    @wraps(original_read)
    def wrapper(self, *args, **kwargs):
        start_time = time.perf_counter()
        file_count = len(self.files.get_data_files())

        try:
            result = original_read(self, *args, **kwargs)
            return result
        finally:
            elapsed_time = time.perf_counter() - start_time

            with stats_lock:
                function_stats['storage.EventStorageReader.read'].add_call(elapsed_time)
                function_stats[f'storage.read_with_{file_count}_files'].add_call(elapsed_time)

            if elapsed_time > 0.1:  # 100ms
                log.warning(
                    f"[SLOW_READ] {file_count} files, "
                    f"took {elapsed_time*1000:.2f}ms, "
                    f"batch size: {len(self.current_batch) if self.current_batch else 0}"
                )

    return wrapper


# 在 event_storage_reader.py 的 get_or_init_buffered_reader() 方法添加
def monitored_get_or_init_buffered_reader(original_func):
    @wraps(original_func)
    def wrapper(self, pointer):
        start_time = time.perf_counter()
        lines_to_skip = pointer.get_line()

        try:
            result = original_func(self, pointer)
            return result
        finally:
            elapsed_time = time.perf_counter() - start_time

            with stats_lock:
                function_stats['storage.get_or_init_buffered_reader'].add_call(elapsed_time)
                function_stats[f'storage.skip_{lines_to_skip}_lines'].add_call(elapsed_time)

            if elapsed_time > 0.05:  # 50ms
                log.warning(
                    f"[SLOW_SKIP] Skipped {lines_to_skip} lines, "
                    f"took {elapsed_time*1000:.2f}ms"
                )

    return wrapper


# 在 event_storage_reader.py 的 get_next_file() 方法添加
def monitored_get_next_file(original_func):
    @wraps(original_func)
    def wrapper(self, files, new_pos):
        start_time = time.perf_counter()
        file_count = len(files.get_data_files())

        try:
            result = original_func(self, files, new_pos)
            return result
        finally:
            elapsed_time = time.perf_counter() - start_time

            with stats_lock:
                function_stats['storage.get_next_file'].add_call(elapsed_time)
                function_stats[f'storage.find_next_in_{file_count}_files'].add_call(elapsed_time)

            if elapsed_time > 0.01:  # 10ms
                log.warning(
                    f"[SLOW_FIND] Searched through {file_count} files, "
                    f"took {elapsed_time*1000:.2f}ms"
                )

    return wrapper


# ============ BACnet 连接器监控 ============

# 在 bacnet_connector.py 的 __main_loop() 方法添加
def monitored_bacnet_main_loop(original_func):
    @wraps(original_func)
    def wrapper(self, *args, **kwargs):
        start_time = time.perf_counter()

        try:
            result = original_func(self, *args, **kwargs)
            return result
        finally:
            elapsed_time = time.perf_counter() - start_time

            with stats_lock:
                function_stats['bacnet.__main_loop'].add_call(elapsed_time)

            if elapsed_time > 0.5:  # 500ms
                log.warning(
                    f"[SLOW_BACNET] Main loop iteration took {elapsed_time*1000:.2f}ms"
                )

    return wrapper


# 在 bacnet_connector.py 的 __read_multiple_properties() 方法添加
def monitored_read_multiple(original_func):
    @wraps(original_func)
    async def wrapper(self, device):
        start_time = time.perf_counter()
        device_name = device.device_info.device_name

        try:
            result = await original_func(self, device)
            return result
        finally:
            elapsed_time = time.perf_counter() - start_time

            with stats_lock:
                function_stats['bacnet.read_multiple_properties'].add_call(elapsed_time)
                function_stats[f'bacnet.read_{device_name}'].add_call(elapsed_time)

            if elapsed_time > 1.0:  # 1 秒
                log.warning(
                    f"[SLOW_DEVICE] Device {device_name} read took {elapsed_time*1000:.2f}ms"
                )

    return wrapper


# ============ 主服务监控 ============

# 在 tb_gateway_service.py 的 __send_to_storage() 方法添加
def monitored_send_to_storage(original_func):
    @wraps(original_func)
    def wrapper(self, *args, **kwargs):
        start_time = time.perf_counter()
        queue_size = self.__converted_data_queue.qsize()

        try:
            result = original_func(self, *args, **kwargs)
            return result
        finally:
            elapsed_time = time.perf_counter() - start_time

            with stats_lock:
                function_stats['gateway.__send_to_storage'].add_call(elapsed_time)
                function_stats[f'gateway.process_queue_size_{queue_size}'].add_call(elapsed_time)

            if elapsed_time > 0.1:  # 100ms
                log.warning(
                    f"[SLOW_STORAGE] Queue size: {queue_size}, "
                    f"took {elapsed_time*1000:.2f}ms"
                )

    return wrapper


# ============ 应用补丁的说明 ============

"""
使用说明：

1. 在 event_storage_reader.py 文件顶部添加：
   from thingsboard_gateway.storage.file.monitoring_patch import (
       monitored_read,
       monitored_get_or_init_buffered_reader,
       monitored_get_next_file
   )

2. 在 EventStorageReader 类定义后添加：
   # 原始方法保存
   _original_read = read
   _original_get_or_init_buffered_reader = get_or_init_buffered_reader
   _original_get_next_file = get_next_file

   # 应用监控
   read = monitored_read(_original_read)
   get_or_init_buffered_reader = monitored_get_or_init_buffered_reader(_original_get_or_init_buffered_reader)
   get_next_file = monitored_get_next_file(_original_get_next_file)

3. 在 bacnet_connector.py 中类似地应用 BACnet 监控

4. 运行一段时间后，使用 monitor_cpu.py 生成报告：
   python3 -m thingsboard_gateway.monitor_cpu --save-report

5. 或者实时查看：
   python3 -m thingsboard_gateway.monitor_cpu --top 20
"""
