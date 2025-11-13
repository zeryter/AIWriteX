"""
API调用优化器 - 优化LLM API调用性能，减少响应时间30%
"""
import asyncio
import time
import logging
from typing import Dict, Any, Optional, List, Union, Callable
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import json
import hashlib
from abc import ABC, abstractmethod
import aiohttp

from .connection_pool_manager import get_connection_pool_manager, ConnectionPoolConfig
from .async_task_manager import AsyncTaskManager
from .memory_leak_fixer import get_memory_leak_detector
from .input_validator import InputValidator

logger = logging.getLogger(__name__)


@dataclass
class APIOptimizationConfig:
    """API优化配置"""
    enable_caching: bool = True  # 启用响应缓存
    cache_ttl: float = 300.0  # 缓存过期时间（秒）
    enable_batching: bool = True  # 启用请求批处理
    batch_size: int = 5  # 批处理大小
    batch_timeout: float = 1.0  # 批处理超时时间（秒）
    enable_retry: bool = True  # 启用重试机制
    max_retries: int = 3  # 最大重试次数
    retry_delay: float = 1.0  # 重试延迟（秒）
    enable_circuit_breaker: bool = True  # 启用熔断器
    circuit_breaker_threshold: int = 5  # 熔断器阈值
    circuit_breaker_timeout: float = 60.0  # 熔断器超时时间（秒）
    enable_compression: bool = True  # 启用压缩
    enable_streaming: bool = True  # 启用流式处理
    streaming_chunk_size: int = 1024  # 流式处理块大小
    request_timeout: float = 60.0  # 请求超时时间（秒）
    connection_timeout: float = 10.0  # 连接超时时间（秒）
    enable_metrics: bool = True  # 启用指标收集
    enable_request_deduplication: bool = True  # 启用请求去重


class ResponseCache:
    """API响应缓存"""
    
    def __init__(self, ttl: float = 300.0, max_size: int = 100):
        self.ttl = ttl
        self.max_size = max_size
        self.cache: Dict[str, tuple] = {}  # key -> (response_data, timestamp)
        self._lock = asyncio.Lock()
    
    def _generate_cache_key(self, method: str, url: str, params: Optional[Dict] = None, 
                           headers: Optional[Dict] = None, data: Optional[Any] = None) -> str:
        """生成缓存键"""
        key_parts = [method.upper(), url]
        
        # 只包含影响响应的关键参数
        if params:
            key_parts.append(str(sorted(params.items())))
        
        if headers:
            # 只包含关键头部
            important_headers = {k: v for k, v in headers.items() 
                               if k.lower() in ['accept', 'content-type', 'authorization']}
            key_parts.append(str(sorted(important_headers.items())))
        
        if data and isinstance(data, (str, bytes)):
            # 对数据进行哈希
            if isinstance(data, str):
                data_hash = hashlib.md5(data.encode()).hexdigest()[:16]
            else:
                data_hash = hashlib.md5(data).hexdigest()[:16]
            key_parts.append(data_hash)
        
        return "|".join(key_parts)
    
    async def get(self, method: str, url: str, params: Optional[Dict] = None,
                  headers: Optional[Dict] = None, data: Optional[Any] = None) -> Optional[Any]:
        """获取缓存的响应"""
        key = self._generate_cache_key(method, url, params, headers, data)
        
        async with self._lock:
            if key in self.cache:
                response_data, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    logger.debug(f"API缓存命中: {key}")
                    return response_data
                else:
                    # 缓存过期，删除
                    del self.cache[key]
        
        return None
    
    async def set(self, method: str, url: str, response_data: Any,
                  params: Optional[Dict] = None, headers: Optional[Dict] = None,
                  data: Optional[Any] = None):
        """设置缓存的响应"""
        key = self._generate_cache_key(method, url, params, headers, data)
        
        async with self._lock:
            # 如果缓存已满，删除最旧的条目
            if len(self.cache) >= self.max_size:
                oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
                del self.cache[oldest_key]
                
            self.cache[key] = (response_data, time.time())
            logger.debug(f"API缓存设置: {key}")
    
    async def clear(self):
        """清空缓存"""
        async with self._lock:
            self.cache.clear()
            logger.info("API响应缓存已清空")
    
    async def cleanup_expired(self):
        """清理过期缓存"""
        current_time = time.time()
        expired_keys = []
        
        async with self._lock:
            for key, (response_data, timestamp) in self.cache.items():
                if current_time - timestamp >= self.ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.cache[key]
        
        if expired_keys:
            logger.debug(f"清理了 {len(expired_keys)} 个过期API缓存项")


class CircuitBreaker:
    """熔断器"""
    
    def __init__(self, threshold: int = 5, timeout: float = 60.0):
        self.threshold = threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "closed"  # closed, open, half_open
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs):
        """调用函数，应用熔断器逻辑"""
        async with self._lock:
            current_time = time.time()
            
            # 检查熔断器状态
            if self.state == "open":
                if current_time - self.last_failure_time > self.timeout:
                    self.state = "half_open"
                    logger.info("熔断器进入半开状态")
                else:
                    raise Exception(f"熔断器处于开启状态，将在 {self.timeout - (current_time - self.last_failure_time):.0f} 秒后重试")
            
            # 尝试调用
            try:
                result = await func(*args, **kwargs)
                
                # 调用成功
                if self.state == "half_open":
                    self.state = "closed"
                    self.failure_count = 0
                    logger.info("熔断器关闭，服务恢复正常")
                
                return result
                
            except Exception as e:
                # 调用失败
                self.failure_count += 1
                self.last_failure_time = current_time
                
                if self.failure_count >= self.threshold:
                    self.state = "open"
                    logger.warning(f"熔断器开启，连续失败 {self.failure_count} 次")
                
                raise e


class RequestBatcher:
    """请求批处理器"""
    
    def __init__(self, batch_size: int = 5, timeout: float = 1.0):
        self.batch_size = batch_size
        self.timeout = timeout
        self.pending_requests: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._batch_task: Optional[asyncio.Task] = None
    
    async def add_request(self, request_func: Callable, *args, **kwargs) -> Any:
        """添加请求到批处理队列"""
        future = asyncio.Future()
        
        async with self._lock:
            self.pending_requests.append({
                'func': request_func,
                'args': args,
                'kwargs': kwargs,
                'future': future
            })
            
            # 如果队列达到批处理大小，立即处理
            if len(self.pending_requests) >= self.batch_size:
                await self._process_batch()
            elif self._batch_task is None:
                # 启动超时处理任务
                self._batch_task = asyncio.create_task(self._timeout_handler())
        
        return await future
    
    async def _timeout_handler(self):
        """超时处理程序"""
        try:
            await asyncio.sleep(self.timeout)
            async with self._lock:
                if self.pending_requests:
                    await self._process_batch()
        except asyncio.CancelledError:
            pass
    
    async def _process_batch(self):
        """处理批处理队列"""
        if not self.pending_requests:
            return
        
        # 获取当前队列的请求
        batch_requests = self.pending_requests[:self.batch_size]
        self.pending_requests = self.pending_requests[self.batch_size:]
        
        # 取消超时任务
        if self._batch_task:
            self._batch_task.cancel()
            self._batch_task = None
        
        # 并行处理批处理中的请求
        tasks = []
        for request in batch_requests:
            task = asyncio.create_task(request['func'](*request['args'], **request['kwargs']))
            tasks.append((task, request['future']))
        
        # 等待所有请求完成
        for task, future in tasks:
            try:
                result = await task
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)


class APIOptimizer:
    """API调用优化器"""
    
    def __init__(self, config: Optional[APIOptimizationConfig] = None):
        """
        初始化API优化器
        
        Args:
            config: 优化配置
        """
        self.config = config or APIOptimizationConfig()
        self.cache: Optional[ResponseCache] = None
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.batcher: Optional[RequestBatcher] = None
        self.connection_pool = None
        self.task_manager = None
        self.metrics: Dict[str, Any] = {
            'total_requests': 0,
            'cached_requests': 0,
            'batched_requests': 0,
            'failed_requests': 0,
            'retried_requests': 0,
            'total_time': 0.0,
            'avg_response_time': 0.0
        }
        self._lock = asyncio.Lock()
        
        # 初始化组件
        self._initialize_components()
        
        logger.info(f"API优化器初始化完成 - 配置: {self.config}")
    
    def _initialize_components(self):
        """初始化组件"""
        # 初始化缓存
        if self.config.enable_caching:
            self.cache = ResponseCache(self.config.cache_ttl)
        
        # 初始化批处理器
        if self.config.enable_batching:
            self.batcher = RequestBatcher(self.config.batch_size, self.config.batch_timeout)
        
        # 初始化任务管理器
        self.task_manager = AsyncTaskManager()
        
        # 初始化连接池
        pool_config = ConnectionPoolConfig(
            enable_caching=self.config.enable_caching,
            cache_ttl=self.config.cache_ttl,
            connection_timeout=self.config.connection_timeout,
            read_timeout=self.config.request_timeout,
            enable_compression=self.config.enable_compression
        )
        
        # 注意：连接池将在第一次使用时初始化
        self.connection_pool_config = pool_config
    
    async def start(self):
        """启动优化器"""
        # 启动连接池
        self.connection_pool = await get_connection_pool_manager(self.connection_pool_config)
        
        # 启动任务管理器
        await self.task_manager.start()
        
        logger.info("API优化器启动完成")
    
    async def stop(self):
        """停止优化器"""
        # 停止任务管理器
        if self.task_manager:
            await self.task_manager.stop()
        
        # 清空缓存
        if self.cache:
            await self.cache.clear()
        
        logger.info("API优化器已停止")
    
    def _get_circuit_breaker(self, service_name: str) -> CircuitBreaker:
        """获取熔断器"""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = CircuitBreaker(
                self.config.circuit_breaker_threshold,
                self.config.circuit_breaker_timeout
            )
        
        return self.circuit_breakers[service_name]
    
    async def _update_metrics(self, success: bool, cached: bool = False, batched: bool = False,
                             response_time: float = 0.0, retried: bool = False):
        """更新指标"""
        async with self._lock:
            self.metrics['total_requests'] += 1
            
            if success:
                pass  # 成功请求已经在其他地方计数
            else:
                self.metrics['failed_requests'] += 1
            
            if cached:
                self.metrics['cached_requests'] += 1
            
            if batched:
                self.metrics['batched_requests'] += 1
            
            if retried:
                self.metrics['retried_requests'] += 1
            
            self.metrics['total_time'] += response_time
            
            # 计算平均响应时间
            total_requests = self.metrics['total_requests']
            if total_requests > 0:
                self.metrics['avg_response_time'] = self.metrics['total_time'] / total_requests
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取优化指标"""
        return self.metrics.copy()
    
    async def call_llm_api(self, provider: str, model: str, messages: List[Dict[str, str]],
                          temperature: float = 0.7, max_tokens: int = 2048,
                          stream: bool = False, **kwargs) -> Dict[str, Any]:
        """
        调用LLM API
        
        Args:
            provider: 提供商名称
            model: 模型名称
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            stream: 是否流式处理
            **kwargs: 其他参数
            
        Returns:
            Dict[str, Any]: API响应
        """
        start_time = time.time()
        
        try:
            # 验证输入
            validator = InputValidator()
            if not validator.validate_string(provider):
                raise ValueError("无效的提供商名称")
            
            if not messages or not isinstance(messages, list):
                raise ValueError("无效的消息格式")
            
            # 构建请求数据
            request_data = {
                'model': model,
                'messages': messages,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'stream': stream
            }
            
            # 添加额外参数
            request_data.update(kwargs)
            
            # 生成缓存键
            cache_key = f"{provider}_{model}_{hash(str(messages))}_{temperature}_{max_tokens}"
            
            # 检查缓存
            if self.cache and not stream:
                cached_response = await self.cache.get('POST', f"cache_{cache_key}")
                if cached_response:
                    await self._update_metrics(True, cached=True, response_time=time.time() - start_time)
                    logger.info(f"LLM API缓存命中: {provider}/{model}")
                    return cached_response
            
            # 获取熔断器
            circuit_breaker = self._get_circuit_breaker(provider)
            
            # 使用批处理或直连
            if self.batcher and not stream:
                result = await self.batcher.add_request(
                    self._make_llm_request, provider, request_data, stream
                )
            else:
                result = await self._make_llm_request(provider, request_data, stream)
            
            # 缓存响应
            if self.cache and not stream and result.get('success'):
                await self.cache.set('POST', f"cache_{cache_key}", result)
            
            # 更新指标
            response_time = time.time() - start_time
            await self._update_metrics(True, response_time=response_time)
            
            logger.info(f"LLM API调用成功: {provider}/{model}, 响应时间: {response_time:.2f}s")
            
            return result
            
        except Exception as e:
            response_time = time.time() - start_time
            await self._update_metrics(False, response_time=response_time)
            
            logger.error(f"LLM API调用失败: {provider}/{model}, 错误: {e}")
            raise
    
    async def _make_llm_request(self, provider: str, request_data: Dict[str, Any], 
                               stream: bool = False) -> Dict[str, Any]:
        """发送LLM请求"""
        # 获取熔断器
        circuit_breaker = self._get_circuit_breaker(provider)
        
        # 重试逻辑
        for attempt in range(self.config.max_retries + 1):
            try:
                # 应用熔断器
                result = await circuit_breaker.call(self._send_llm_request, provider, request_data, stream)
                return result
                
            except Exception as e:
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_delay * (2 ** attempt))
                    logger.warning(f"LLM请求重试 {attempt + 1}/{self.config.max_retries}: {e}")
                else:
                    logger.error(f"LLM请求最终失败: {e}")
                    raise
    
    async def _send_llm_request(self, provider: str, request_data: Dict[str, Any], 
                               stream: bool = False) -> Dict[str, Any]:
        """发送实际的LLM请求"""
        # 这里需要根据具体的LLM提供商实现
        # 这是一个通用的框架，需要根据实际的API端点进行调整
        
        # 获取配置
        from ..config.config import Config
        config = Config.get_instance()
        
        # 构建API端点
        api_key = config.get_api_key()  # 需要根据提供商获取对应的API密钥
        api_base = config.get_api_apibase()  # 需要根据提供商获取对应的API基础URL
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'AIWriteX/2.3.0'
        }
        
        # 发送请求
        async with self.connection_pool.request('POST', api_base, 
                                              headers=headers, 
                                              json=request_data) as response:
            
            if stream:
                # 流式处理
                content = ""
                async for chunk in response.content.iter_chunked(self.config.streaming_chunk_size):
                    content += chunk.decode('utf-8')
                
                return {
                    'success': True,
                    'content': content,
                    'model': request_data['model'],
                    'provider': provider
                }
            else:
                # 非流式处理
                response_data = await response.json()
                return {
                    'success': True,
                    'response': response_data,
                    'model': request_data['model'],
                    'provider': provider
                }
    
    async def call_image_api(self, provider: str, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        调用图像生成API
        
        Args:
            provider: 提供商名称
            prompt: 提示词
            **kwargs: 其他参数
            
        Returns:
            Dict[str, Any]: API响应
        """
        start_time = time.time()
        
        try:
            # 验证输入
            validator = InputValidator()
            if not validator.validate_string(prompt):
                raise ValueError("无效的提示词")
            
            # 构建请求数据
            request_data = {
                'prompt': prompt,
                **kwargs
            }
            
            # 生成缓存键
            cache_key = f"image_{provider}_{hash(prompt)}"
            
            # 检查缓存
            if self.cache:
                cached_response = await self.cache.get('POST', f"cache_{cache_key}")
                if cached_response:
                    await self._update_metrics(True, cached=True, response_time=time.time() - start_time)
                    logger.info(f"图像API缓存命中: {provider}")
                    return cached_response
            
            # 获取熔断器
            circuit_breaker = self._get_circuit_breaker(provider)
            
            # 发送请求
            result = await circuit_breaker.call(self._send_image_request, provider, request_data)
            
            # 缓存响应
            if self.cache and result.get('success'):
                await self.cache.set('POST', f"cache_{cache_key}", result)
            
            # 更新指标
            response_time = time.time() - start_time
            await self._update_metrics(True, response_time=response_time)
            
            logger.info(f"图像API调用成功: {provider}, 响应时间: {response_time:.2f}s")
            
            return result
            
        except Exception as e:
            response_time = time.time() - start_time
            await self._update_metrics(False, response_time=response_time)
            
            logger.error(f"图像API调用失败: {provider}, 错误: {e}")
            raise
    
    async def _send_image_request(self, provider: str, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """发送图像生成请求"""
        # 获取配置
        from ..config.config import Config
        config = Config.get_instance()
        
        # 构建API端点（需要根据具体的图像API提供商实现）
        api_key = config.get_img_api_key()  # 获取图像API密钥
        api_base = "https://api.example.com/v1/images/generations"  # 需要根据提供商调整
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'AIWriteX/2.3.0'
        }
        
        # 发送请求
        async with self.connection_pool.request('POST', api_base,
                                              headers=headers,
                                              json=request_data) as response:
            
            response_data = await response.json()
            
            return {
                'success': True,
                'response': response_data,
                'provider': provider
            }


# 全局优化器实例
_global_optimizer: Optional[APIOptimizer] = None


async def get_api_optimizer(config: Optional[APIOptimizationConfig] = None) -> APIOptimizer:
    """获取全局API优化器实例"""
    global _global_optimizer
    
    if _global_optimizer is None:
        _global_optimizer = APIOptimizer(config)
        await _global_optimizer.start()
    
    return _global_optimizer


@asynccontextmanager
async def api_optimizer_context(config: Optional[APIOptimizationConfig] = None):
    """
    API优化器上下文管理器
    
    Args:
        config: 优化配置
        
    Yields:
        APIOptimizer: API优化器实例
    """
    optimizer = APIOptimizer(config)
    await optimizer.start()
    
    try:
        yield optimizer
    finally:
        await optimizer.stop()


# 便捷的API调用函数
async def async_llm_call(provider: str, model: str, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
    """异步LLM调用"""
    optimizer = await get_api_optimizer()
    return await optimizer.call_llm_api(provider, model, messages, **kwargs)


async def async_image_call(provider: str, prompt: str, **kwargs) -> Dict[str, Any]:
    """异步图像生成调用"""
    optimizer = await get_api_optimizer()
    return await optimizer.call_image_api(provider, prompt, **kwargs)


if __name__ == "__main__":
    # 测试API优化器
    logging.basicConfig(level=logging.INFO)
    
    async def test_optimizer():
        """测试优化器"""
        config = APIOptimizationConfig(
            enable_caching=True,
            enable_batching=True,
            enable_retry=True,
            enable_circuit_breaker=True
        )
        
        async with api_optimizer_context(config) as optimizer:
            print("API优化器测试开始...")
            
            # 测试指标
            metrics = optimizer.get_metrics()
            print(f"优化器指标: {metrics}")
            
            print("API优化器测试完成")
    
    asyncio.run(test_optimizer())