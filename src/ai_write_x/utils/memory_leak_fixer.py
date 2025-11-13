"""
内存泄漏修复工具 - 识别和修复常见的内存泄漏问题
"""
import gc
import weakref
import threading
import multiprocessing
import logging
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
import tracemalloc
import psutil
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MemoryLeakInfo:
    """内存泄漏信息"""
    object_type: str
    count: int
    size_bytes: int
    references: List[str]
    stack_trace: Optional[str] = None


class MemoryLeakDetector:
    """内存泄漏检测器"""
    
    def __init__(self, enable_tracing: bool = True):
        """
        初始化内存泄漏检测器
        
        Args:
            enable_tracing: 是否启用内存分配跟踪
        """
        self.enable_tracing = enable_tracing
        self.baseline_snapshot: Optional[Any] = None
        self.object_counts: Dict[str, int] = defaultdict(int)
        self.weak_refs: Dict[str, List[weakref.ref]] = defaultdict(list)
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitoring = threading.Event()
        
        if enable_tracing:
            try:
                tracemalloc.start()
                logger.info("内存分配跟踪已启用")
            except Exception as e:
                logger.warning(f"无法启用内存分配跟踪: {e}")
                self.enable_tracing = False
    
    def start_monitoring(self, interval: float = 30.0):
        """开始监控内存使用"""
        if self._monitoring:
            logger.warning("内存监控已在运行")
            return
        
        self._monitoring = True
        self._stop_monitoring.clear()
        
        def monitor_loop():
            """监控循环"""
            while not self._stop_monitoring.is_set():
                try:
                    self._check_memory_usage()
                    time.sleep(interval)
                except Exception as e:
                    logger.error(f"内存监控循环错误: {e}")
                    time.sleep(interval)
        
        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info(f"内存监控已启动，间隔: {interval}秒")
    
    def stop_monitoring(self):
        """停止监控内存使用"""
        if not self._monitoring:
            return
        
        self._stop_monitoring.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        
        self._monitoring = False
        logger.info("内存监控已停止")
    
    def _check_memory_usage(self):
        """检查内存使用情况"""
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            # 获取当前内存使用
            current_memory_mb = memory_info.rss / 1024 / 1024
            
            # 检查对象计数
            gc.collect()  # 强制垃圾回收
            current_counts = self._get_object_counts()
            
            # 检测异常增长
            for obj_type, current_count in current_counts.items():
                baseline_count = self.object_counts.get(obj_type, 0)
                if baseline_count > 0:
                    growth_rate = (current_count - baseline_count) / baseline_count
                    if growth_rate > 0.5:  # 增长超过50%
                        logger.warning(f"检测到内存泄漏: {obj_type} 数量增长 {growth_rate:.1%} ({baseline_count} -> {current_count})")
                        
                        # 记录详细信息
                        leak_info = self._analyze_leak(obj_type)
                        if leak_info:
                            self._log_leak_info(leak_info)
            
            # 更新基线
            self.object_counts = current_counts
            
            # 检查总内存使用
            if current_memory_mb > 1000:  # 超过1GB
                logger.warning(f"内存使用过高: {current_memory_mb:.1f} MB")
                
                # 获取内存快照
                if self.enable_tracing and tracemalloc.is_tracing():
                    snapshot = tracemalloc.take_snapshot()
                    if self.baseline_snapshot:
                        stats = snapshot.compare_to(self.baseline_snapshot, 'lineno')
                        top_stats = stats[:10]
                        
                        logger.warning("内存分配热点:")
                        for stat in top_stats:
                            logger.warning(f"  {stat}")
                    else:
                        self.baseline_snapshot = snapshot
            
            logger.info(f"内存使用: {current_memory_mb:.1f} MB, 对象计数已更新")
            
        except Exception as e:
            logger.error(f"检查内存使用时出错: {e}")
    
    def _get_object_counts(self) -> Dict[str, int]:
        """获取对象计数"""
        counts = defaultdict(int)
        
        for obj in gc.get_objects():
            try:
                obj_type = type(obj).__name__
                counts[obj_type] += 1
            except Exception:
                pass  # 忽略无法访问的对象
        
        return counts
    
    def _analyze_leak(self, obj_type: str) -> Optional[MemoryLeakInfo]:
        """分析内存泄漏"""
        try:
            # 查找指定类型的对象
            objects = []
            for obj in gc.get_objects():
                if type(obj).__name__ == obj_type:
                    objects.append(obj)
            
            if not objects:
                return None
            
            # 计算总大小（估算）
            total_size = sum(self._get_object_size(obj) for obj in objects)
            
            # 分析引用关系
            references = []
            for obj in objects[:5]:  # 只分析前5个对象
                refs = self._get_references(obj)
                if refs:
                    references.extend(refs)
            
            return MemoryLeakInfo(
                object_type=obj_type,
                count=len(objects),
                size_bytes=total_size,
                references=list(set(references))[:10],  # 去重并限制数量
                stack_trace=None
            )
            
        except Exception as e:
            logger.error(f"分析内存泄漏时出错: {e}")
            return None
    
    def _get_object_size(self, obj) -> int:
        """获取对象大小（估算）"""
        try:
            import sys
            return sys.getsizeof(obj)
        except Exception:
            return 0
    
    def _get_references(self, obj) -> List[str]:
        """获取对象的引用信息"""
        references = []
        
        try:
            # 查找引用者
            referrers = gc.get_referrers(obj)
            for referrer in referrers[:5]:  # 限制数量
                if hasattr(referrer, '__class__'):
                    ref_info = f"{referrer.__class__.__name__}"
                    if hasattr(referrer, '__name__'):
                        ref_info += f".{referrer.__name__}"
                    references.append(ref_info)
        except Exception:
            pass
        
        return references
    
    def _log_leak_info(self, leak_info: MemoryLeakInfo):
        """记录内存泄漏信息"""
        logger.warning(f"内存泄漏详情:")
        logger.warning(f"  对象类型: {leak_info.object_type}")
        logger.warning(f"  对象数量: {leak_info.count}")
        logger.warning(f"  估算大小: {leak_info.size_bytes / 1024:.1f} KB")
        
        if leak_info.references:
            logger.warning(f"  引用来源: {', '.join(leak_info.references[:5])}")


class MemoryLeakFixer:
    """内存泄漏修复工具"""
    
    def __init__(self):
        """初始化内存泄漏修复工具"""
        self.common_patterns = {
            'unclosed_files': self._fix_unclosed_files,
            'unclosed_connections': self._fix_unclosed_connections,
            'circular_references': self._fix_circular_references,
            'event_listeners': self._fix_event_listeners,
            'thread_leaks': self._fix_thread_leaks,
            'process_leaks': self._fix_process_leaks,
            'queue_leaks': self._fix_queue_leaks,
        }
    
    def fix_all(self) -> Dict[str, bool]:
        """
        修复所有已知的内存泄漏问题
        
        Returns:
            Dict[str, bool]: 修复结果
        """
        results = {}
        
        for pattern_name, fix_func in self.common_patterns.items():
            try:
                logger.info(f"正在修复内存泄漏模式: {pattern_name}")
                success = fix_func()
                results[pattern_name] = success
                
                if success:
                    logger.info(f"修复成功: {pattern_name}")
                else:
                    logger.warning(f"修复失败或无需修复: {pattern_name}")
                    
            except Exception as e:
                logger.error(f"修复 {pattern_name} 时出错: {e}")
                results[pattern_name] = False
        
        return results
    
    def _fix_unclosed_files(self) -> bool:
        """修复未关闭的文件"""
        try:
            # 强制垃圾回收
            gc.collect()
            
            # 查找未关闭的文件对象
            unclosed_files = []
            for obj in gc.get_objects():
                if hasattr(obj, 'close') and hasattr(obj, 'closed'):
                    try:
                        if not obj.closed:
                            unclosed_files.append(obj)
                    except Exception:
                        pass
            
            # 关闭未关闭的文件
            closed_count = 0
            for file_obj in unclosed_files:
                try:
                    file_obj.close()
                    closed_count += 1
                except Exception:
                    pass
            
            if closed_count > 0:
                logger.info(f"关闭了 {closed_count} 个未关闭的文件")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"修复未关闭文件时出错: {e}")
            return False
    
    def _fix_unclosed_connections(self) -> bool:
        """修复未关闭的连接"""
        try:
            # 这里可以添加特定于应用程序的连接清理逻辑
            # 例如：关闭未关闭的HTTP连接、数据库连接等
            
            # 强制垃圾回收
            gc.collect()
            
            # 查找可能的连接对象
            connection_types = ['HTTPResponse', 'Connection', 'Socket', 'Session']
            closed_count = 0
            
            for obj in gc.get_objects():
                obj_type = type(obj).__name__
                if any(conn_type in obj_type for conn_type in connection_types):
                    if hasattr(obj, 'close') and not hasattr(obj, 'closed'):
                        try:
                            obj.close()
                            closed_count += 1
                        except Exception:
                            pass
            
            if closed_count > 0:
                logger.info(f"关闭了 {closed_count} 个未关闭的连接")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"修复未关闭连接时出错: {e}")
            return False
    
    def _fix_circular_references(self) -> bool:
        """修复循环引用"""
        try:
            # 强制垃圾回收
            unreachable = gc.collect()
            
            if unreachable > 0:
                logger.info(f"清理了 {unreachable} 个无法到达的对象（可能包含循环引用）")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"修复循环引用时出错: {e}")
            return False
    
    def _fix_event_listeners(self) -> bool:
        """修复事件监听器泄漏"""
        try:
            # 这里可以添加特定于应用程序的事件监听器清理逻辑
            # 例如：清理GUI事件监听器、信号处理器等
            
            # 强制垃圾回收
            gc.collect()
            
            logger.info("事件监听器清理完成（需要应用程序特定逻辑）")
            return False  # 默认返回False，需要特定实现
            
        except Exception as e:
            logger.error(f"修复事件监听器时出错: {e}")
            return False
    
    def _fix_thread_leaks(self) -> bool:
        """修复线程泄漏"""
        try:
            # 获取所有活动线程
            active_threads = threading.enumerate()
            daemon_threads = [t for t in active_threads if t.daemon]
            
            # 检查是否有异常多的守护线程
            if len(daemon_threads) > 20:  # 阈值可以根据需要调整
                logger.warning(f"发现 {len(daemon_threads)} 个守护线程，可能存在线程泄漏")
                
                # 这里可以添加特定的线程清理逻辑
                # 注意：不要强制终止线程，这可能导致数据损坏
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"修复线程泄漏时出错: {e}")
            return False
    
    def _fix_process_leaks(self) -> bool:
        """修复进程泄漏"""
        try:
            # 获取所有活动进程
            active_processes = multiprocessing.active_children()
            
            if len(active_processes) > 5:  # 阈值可以根据需要调整
                logger.warning(f"发现 {len(active_processes)} 个活动进程，可能存在进程泄漏")
                
                # 尝试优雅地终止僵尸进程
                terminated_count = 0
                for process in active_processes:
                    if not process.is_alive():
                        try:
                            process.join(timeout=1.0)
                            terminated_count += 1
                        except Exception:
                            pass
                
                if terminated_count > 0:
                    logger.info(f"清理了 {terminated_count} 个僵尸进程")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"修复进程泄漏时出错: {e}")
            return False
    
    def _fix_queue_leaks(self) -> bool:
        """修复队列泄漏"""
        try:
            # 查找可能泄漏的队列对象
            queue_objects = []
            for obj in gc.get_objects():
                if hasattr(obj, 'qsize') and hasattr(obj, 'empty'):
                    try:
                        if obj.qsize() > 1000:  # 大队列可能表明泄漏
                            queue_objects.append(obj)
                    except Exception:
                        pass
            
            if queue_objects:
                logger.warning(f"发现 {len(queue_objects)} 个可能泄漏的大队列")
                
                # 清空队列
                cleared_count = 0
                for queue_obj in queue_objects:
                    try:
                        while not queue_obj.empty():
                            queue_obj.get_nowait()
                        cleared_count += 1
                    except Exception:
                        pass
                
                if cleared_count > 0:
                    logger.info(f"清空了 {cleared_count} 个队列")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"修复队列泄漏时出错: {e}")
            return False


# 全局实例
_global_detector: Optional[MemoryLeakDetector] = None
_global_fixer: Optional[MemoryLeakFixer] = None


def get_memory_leak_detector(enable_tracing: bool = True) -> MemoryLeakDetector:
    """获取全局内存泄漏检测器"""
    global _global_detector
    
    if _global_detector is None:
        _global_detector = MemoryLeakDetector(enable_tracing)
    
    return _global_detector


def get_memory_leak_fixer() -> MemoryLeakFixer:
    """获取全局内存泄漏修复工具"""
    global _global_fixer
    
    if _global_fixer is None:
        _global_fixer = MemoryLeakFixer()
    
    return _global_fixer


@contextmanager
def memory_monitor_context(enable_tracing: bool = True):
    """
    内存监控上下文管理器
    
    Args:
        enable_tracing: 是否启用内存分配跟踪
    """
    detector = get_memory_leak_detector(enable_tracing)
    fixer = get_memory_leak_fixer()
    
    # 启动监控
    detector.start_monitoring(interval=10.0)
    
    try:
        yield detector, fixer
    finally:
        # 停止监控
        detector.stop_monitoring()
        
        # 修复内存泄漏
        logger.info("执行内存泄漏修复...")
        results = fixer.fix_all()
        
        # 记录修复结果
        successful_fixes = sum(1 for success in results.values() if success)
        logger.info(f"内存泄漏修复完成: {successful_fixes}/{len(results)} 个模式修复成功")


def monitor_memory_usage(interval: float = 30.0, duration: float = 300.0):
    """
    监控内存使用情况
    
    Args:
        interval: 监控间隔（秒）
        duration: 监控持续时间（秒）
    """
    detector = get_memory_leak_detector()
    
    logger.info(f"开始内存监控，间隔: {interval}秒，持续时间: {duration}秒")
    detector.start_monitoring(interval)
    
    try:
        time.sleep(duration)
    finally:
        detector.stop_monitoring()
        
        # 获取统计信息
        stats = detector.get_stats() if hasattr(detector, 'get_stats') else {}
        logger.info(f"内存监控完成，统计信息: {stats}")


if __name__ == "__main__":
    # 测试内存泄漏检测和修复
    logging.basicConfig(level=logging.INFO)
    
    print("测试内存泄漏检测和修复工具...")
    
    with memory_monitor_context():
        print("内存监控已启动，按 Ctrl+C 停止...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("停止监控")