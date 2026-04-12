#!/usr/bin/env python3
"""
ThingsBoard Gateway 性能分析脚本
使用方法：python3 profile_gateway.py
"""

import cProfile
import pstats
import io
import pstats
from datetime import datetime
import os

def profile_gateway():
    """启动网关并进行性能分析"""

    # 导入网关主模块
    from thingsboard_gateway.tb_gateway import main

    # 创建 profiler
    profiler = cProfile.Profile()
    profiler.enable()

    try:
        # 启动网关
        main()
    except KeyboardInterrupt:
        print("\n收到停止信号，正在生成性能报告...")
    finally:
        profiler.disable()

        # 生成报告
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        profile_dir = "/var/log/thingsboard-gateway/profile"
        os.makedirs(profile_dir, exist_ok=True)

        # 保存详细统计数据
        stats_file = f"{profile_dir}/profile_{timestamp}.prof"
        profiler.dump_stats(stats_file)
        print(f"\n性能数据已保存到: {stats_file}")

        # 打印性能报告（按累积时间排序，显示前 50 个函数）
        print("\n" + "="*80)
        print("TOP 50 最耗 CPU 的函数（按累积时间排序）")
        print("="*80)

        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).strip_dirs()
        ps.sort_stats('cumulative')
        ps.print_stats(50)  # 显示前 50 个
        print(s.getvalue())

        # 打印性能报告（按自身时间排序）
        print("\n" + "="*80)
        print("TOP 50 最耗 CPU 的函数（按自身时间排序）")
        print("="*80)

        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).strip_dirs()
        ps.sort_stats('tottime')
        ps.print_stats(50)
        print(s.getvalue())

        # 特别关注 BACnet 和文件存储相关的函数
        print("\n" + "="*80)
        print("BACnet 相关函数性能")
        print("="*80)

        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).strip_dirs()
        ps.sort_stats('cumulative')
        ps.print_stats('bacnet')
        print(s.getvalue())

        print("\n" + "="*80)
        print("文件存储相关函数性能")
        print("="*80)

        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).strip_dirs()
        ps.sort_stats('cumulative')
        ps.print_stats('event_storage|file_storage')
        print(s.getvalue())

if __name__ == '__main__':
    profile_gateway()
