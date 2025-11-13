"""
异步任务管理器 - 提供异步处理和并发控制功能
"""
import asyncio
import concurrent.futures
import threading
import time
from typing import Any, Callable, Optional, Dict, List, Union, Coroutine
from dataclasses import dataclass, field
from enum import Enum
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class AsyncTask:
    """异步任务数据结构"""
    task_id: str
    name: str
    coroutine: Optional[Coroutine] = None
    future: Optional[concurrent.futures.Future] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[Exception] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    timeout: Optional[float] = None
    callback: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AsyncTaskManager:
    """异步任务管理器 - 管理异步任务的生命周期"""
    
    def __init__(self, max_workers: int = 10, max_concurrent_tasks: int = 50):
        """
        初始化异步任务管理器
        
        Args:
            max_workers: 最大工作线程数
            max_concurrent_tasks: 最大并发任务数
        """
        self.max_workers = max_workers
        self.max_concurrent_tasks = max_concurrent_tasks
        self.tasks: Dict[str, AsyncTask] = {}
        self.task_queue: asyncio.Queue = asyncio.Queue(maxsize=max_concurrent_tasks)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._shutdown = False
        self._lock = threading.Lock()
        self._task_counter = 0
        
        logger.info(f"异步任务管理器初始化完成 - 最大工作线程: {max_workers}, 最大并发任务: {max_concurrent_tasks}")
    
    async def start(self):
        """启动任务管理器"""
        if self._shutdown:
            logger.warning("任务管理器已关闭，无法启动")
            return
        
        # 启动任务处理循环
        asyncio.create_task(self._process_tasks())
        logger.info("异步任务管理器启动完成")
    
    async def stop(self, timeout: float = 30.0):
        """
        停止任务管理器
        
        Args:
            timeout: 停止超时时间
        """
        logger.info("正在停止异步任务管理器...")
        self._shutdown = True
        
        # 取消所有待处理任务
        await self.cancel_all_tasks()
        
        # 等待所有任务完成
        start_time = time.time()
        while self.get_running_tasks_count() > 0:
            if time.time() - start_time > timeout:
                logger.warning("停止超时，强制关闭剩余任务")
                break
            await asyncio.sleep(0.1)
        
        # 关闭线程池
        self.executor.shutdown(wait=True, cancel_futures=True)
        logger.info("异步任务管理器已停止")
    
    def submit_task(
        self,
        coroutine: Coroutine,
        name: str = "",
        timeout: Optional[float] = None,
        callback: Optional[Callable] = None,
        metadata: Optional[Dict[str, Any]] = None,
        future: Optional[concurrent.futures.Future] = None,
    ) -> str:
        """
        提交异步任务
        
        Args:
            coroutine: 异步协程
            name: 任务名称
            timeout: 任务超时时间（秒）
            callback: 任务完成回调函数
            metadata: 任务元数据
            
        Returns:
            str: 任务ID
        """
        if self._shutdown:
            raise RuntimeError("任务管理器已关闭")
        
        with self._lock:
            self._task_counter += 1
            task_id = f"{name}_{self._task_counter}_{int(time.time() * 1000)}"
        
        task = AsyncTask(
            task_id=task_id,
            name=name,
            coroutine=coroutine,
            timeout=timeout,
            callback=callback,
            metadata=metadata or {}
        )
        task.future = future
        
        self.tasks[task_id] = task
        
        # 将任务添加到队列
        try:
            self.task_queue.put_nowait(task)
        except asyncio.QueueFull:
            logger.warning(f"任务队列已满，无法添加任务: {task_id}")
            del self.tasks[task_id]
            raise RuntimeError("任务队列已满")
        
        logger.info(f"任务已提交: {task_id} - {name}")
        return task_id
    
    def submit_sync_task(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        name: str = "",
        timeout: Optional[float] = None,
        callback: Optional[Callable] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        提交同步任务到线程池
        
        Args:
            func: 同步函数
            args: 函数参数
            kwargs: 函数关键字参数
            name: 任务名称
            timeout: 任务超时时间（秒）
            callback: 任务完成回调函数
            metadata: 任务元数据
            
        Returns:
            str: 任务ID
        """
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(self.executor, func, *args, **(kwargs or {}))

        async def await_future():
            return await future

        return self.submit_task(
            coroutine=await_future(),
            name=name or func.__name__,
            timeout=timeout,
            callback=callback,
            metadata=metadata,
            future=future,
        )
    
    async def _process_tasks(self):
        """处理任务队列"""
        while not self._shutdown:
            try:
                # 从队列获取任务
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                
                # 启动任务执行
                asyncio.create_task(self._execute_task(task))
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"任务处理循环出错: {e}")
    
    async def _execute_task(self, task: AsyncTask):
        """执行单个任务"""
        task.status = TaskStatus.RUNNING
        task.start_time = time.time()
        
        logger.info(f"开始执行任务: {task.task_id}")
        
        try:
            # 设置超时
            if task.timeout:
                task.result = await asyncio.wait_for(task.coroutine, timeout=task.timeout)
            else:
                task.result = await task.coroutine
            
            task.status = TaskStatus.COMPLETED
            logger.info(f"任务执行成功: {task.task_id}")
            
        except asyncio.TimeoutError:
            task.status = TaskStatus.TIMEOUT
            task.error = TimeoutError(f"任务超时: {task.timeout}秒")
            logger.warning(f"任务超时: {task.task_id}")
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = e
            logger.error(f"任务执行失败: {task.task_id}, 错误: {e}")
        
        finally:
            task.end_time = time.time()
            
            # 执行回调函数
            if task.callback:
                try:
                    if asyncio.iscoroutinefunction(task.callback):
                        await task.callback(task)
                    else:
                        task.callback(task)
                except Exception as e:
                    logger.error(f"任务回调函数出错: {task.task_id}, 错误: {e}")
    
    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """获取任务状态"""
        task = self.get_task(task_id)
        return task.status if task else None
    
    def get_task_result(self, task_id: str) -> Any:
        """获取任务结果"""
        task = self.get_task(task_id)
        return task.result if task else None
    
    def get_task_error(self, task_id: str) -> Optional[Exception]:
        """获取任务错误"""
        task = self.get_task(task_id)
        return task.error if task else None
    
    def get_task_duration(self, task_id: str) -> Optional[float]:
        """获取任务执行时间"""
        task = self.get_task(task_id)
        if not task or not task.start_time:
            return None
        
        end_time = task.end_time or time.time()
        return end_time - task.start_time
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        
        if task.status == TaskStatus.RUNNING:
            # 取消正在运行的任务
            if task.future and not task.future.done():
                task.future.cancel()
        
        task.status = TaskStatus.CANCELLED
        logger.info(f"任务已取消: {task_id}")
        return True
    
    async def cancel_all_tasks(self):
        """取消所有任务"""
        for task_id in list(self.tasks.keys()):
            self.cancel_task(task_id)
        
        logger.info("所有任务已取消")
    
    def get_all_tasks(self) -> List[AsyncTask]:
        """获取所有任务"""
        return list(self.tasks.values())
    
    def get_running_tasks(self) -> List[AsyncTask]:
        """获取正在运行的任务"""
        return [task for task in self.tasks.values() if task.status == TaskStatus.RUNNING]
    
    def get_pending_tasks(self) -> List[AsyncTask]:
        """获取待处理的任务"""
        return [task for task in self.tasks.values() if task.status == TaskStatus.PENDING]
    
    def get_completed_tasks(self) -> List[AsyncTask]:
        """获取已完成的任务"""
        return [task for task in self.tasks.values() if task.status == TaskStatus.COMPLETED]
    
    def get_failed_tasks(self) -> List[AsyncTask]:
        """获取失败的任务"""
        return [task for task in self.tasks.values() if task.status == TaskStatus.FAILED]
    
    def get_tasks_count(self) -> Dict[str, int]:
        """获取任务统计"""
        return {
            "total": len(self.tasks),
            "pending": len(self.get_pending_tasks()),
            "running": len(self.get_running_tasks()),
            "completed": len(self.get_completed_tasks()),
            "failed": len(self.get_failed_tasks()),
            "cancelled": len([t for t in self.tasks.values() if t.status == TaskStatus.CANCELLED]),
            "timeout": len([t for t in self.tasks.values() if t.status == TaskStatus.TIMEOUT])
        }
    
    def get_running_tasks_count(self) -> int:
        """获取正在运行的任务数量"""
        return len(self.get_running_tasks())
    
    def remove_completed_tasks(self, max_age: float = 3600):
        """
        移除已完成的任务
        
        Args:
            max_age: 最大保留时间（秒）
        """
        current_time = time.time()
        removed_count = 0
        
        for task_id in list(self.tasks.keys()):
            task = self.tasks[task_id]
            
            # 只移除已完成、失败、取消或超时的任务
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT]:
                # 检查任务是否过期
                if task.end_time and (current_time - task.end_time) > max_age:
                    del self.tasks[task_id]
                    removed_count += 1
        
        if removed_count > 0:
            logger.info(f"已移除 {removed_count} 个过期任务")
    
    async def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """
        等待任务完成
        
        Args:
            task_id: 任务ID
            timeout: 等待超时时间（秒）
            
        Returns:
            Any: 任务结果
            
        Raises:
            TimeoutError: 等待超时
            Exception: 任务执行错误
        """
        start_time = time.time()
        
        while True:
            task = self.get_task(task_id)
            if not task:
                raise ValueError(f"任务不存在: {task_id}")
            
            # 检查任务是否完成
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT]:
                if task.error:
                    raise task.error
                return task.result
            
            # 检查超时
            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(f"等待任务超时: {task_id}")
            
            # 等待一段时间
            await asyncio.sleep(0.1)


# 全局任务管理器实例
_global_task_manager: Optional[AsyncTaskManager] = None


def get_task_manager() -> AsyncTaskManager:
    """获取全局任务管理器实例"""
    global _global_task_manager
    
    if _global_task_manager is None:
        _global_task_manager = AsyncTaskManager()
    
    return _global_task_manager


@asynccontextmanager
async def task_manager_context(max_workers: int = 10, max_concurrent_tasks: int = 50):
    """
    任务管理器上下文管理器
    
    Args:
        max_workers: 最大工作线程数
        max_concurrent_tasks: 最大并发任务数
        
    Yields:
        AsyncTaskManager: 任务管理器实例
    """
    manager = AsyncTaskManager(max_workers, max_concurrent_tasks)
    await manager.start()
    
    try:
        yield manager
    finally:
        await manager.stop()


# 便捷的异步函数装饰器
def async_task(name: str = "", timeout: Optional[float] = None, callback: Optional[Callable] = None):
    """
    异步任务装饰器
    
    Args:
        name: 任务名称
        timeout: 任务超时时间（秒）
        callback: 任务完成回调函数
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            # 获取任务管理器
            manager = get_task_manager()
            
            task_name = name or func.__name__

            if asyncio.iscoroutinefunction(func):
                coroutine = func(*args, **kwargs)
                task_id = manager.submit_task(
                    coroutine=coroutine,
                    name=task_name,
                    timeout=timeout,
                    callback=callback,
                )
            else:
                task_id = manager.submit_sync_task(
                    func=func,
                    args=args,
                    kwargs=kwargs,
                    name=task_name,
                    timeout=timeout,
                    callback=callback,
                )
            
            return task_id
        
        return wrapper
    return decorator
