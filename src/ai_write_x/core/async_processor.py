"""
异步内容生成处理器
为统一工作流和纯内容引擎提供异步执行与并发控制
"""

import asyncio
import time
from typing import Any, Dict, Optional, Callable
import logging

from ai_write_x.core.base_framework import WorkflowConfig, ContentResult
from ai_write_x.core.monitoring import WorkflowMonitor


logger = logging.getLogger(__name__)


class AsyncContentProcessor:
    """异步内容生成处理器，管理任务队列与并发执行"""

    def __init__(self, max_concurrency: int = 2):
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._monitor = WorkflowMonitor.get_instance()
        self._shutdown = False

    async def run_workflow(self, config: WorkflowConfig, inputs: Dict[str, Any]) -> ContentResult:
        """异步执行内容工作流，带并发限制与耗时统计"""
        start = time.time()
        success = False
        async with self._semaphore:
            try:
                # 延迟导入，降低对外部依赖的耦合
                from ai_write_x.core.content_generation import ContentGenerationEngine
                engine = ContentGenerationEngine(config)
                result = engine.execute_workflow(inputs)
                success = True
                return result
            except Exception as e:
                logger.error(f"异步工作流执行失败: {e}")
                self._monitor.log_error(config.name, str(e), inputs)
                raise
            finally:
                duration = time.time() - start
                self._monitor.track_execution(config.name + "_async", duration, success, inputs)

    async def gather(self, tasks: list[Callable[[], asyncio.Future]]):
        """并发执行多个任务工厂，返回结果列表"""
        coros = [t() for t in tasks]
        return await asyncio.gather(*coros, return_exceptions=False)

    async def shutdown(self):
        """关闭处理器"""
        self._shutdown = True
        # 当前实现为轻量处理器，无需清理额外资源


# 便捷方法
async def run_async_content_workflow(config: WorkflowConfig, inputs: Dict[str, Any]) -> ContentResult:
    processor = AsyncContentProcessor()
    return await processor.run_workflow(config, inputs)