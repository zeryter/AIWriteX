"""
连接池管理器 - 优化HTTP请求性能，减少连接建立开销
"""
import asyncio
import aiohttp
import time
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class ConnectionPoolConfig:
    """连接池配置"""
    total_connections: int = 100  # 总连接数
    per_host_connections: int = 30  # 每个主机的最大连接数
    connection_timeout: float = 30.0  # 连接超时时间（秒）
    read_timeout: float = 60.0  # 读取超时时间（秒）
    keepalive_timeout: float = 30.0  # 连接保持时间（秒）
    max_keepalive_connections: int = 50  # 最大保持连接数
    enable_cleanup: bool = True  # 是否启用清理
    cleanup_interval: float = 300.0  # 清理间隔（秒）
    retry_attempts: int = 3  # 重试次数
    retry_delay: float = 1.0  # 重试延迟（秒）
    enable_caching: bool = True  # 是否启用响应缓存
    cache_ttl: float = 300.0  # 缓存过期时间（秒）
    enable_compression: bool = True  # 是否启用压缩
    enable_redirects: bool = True  # 是否允许重定向
    max_redirects: int = 10  # 最大重定向次数
    user_agent: str = "AIWriteX/2.3.0"  # 用户代理


class ResponseCache:
    """简单的响应缓存"""
    
    def __init__(self, ttl: float = 300.0):
        self.ttl = ttl
        self.cache: Dict[str, tuple] = {}  # key -> (response_data, timestamp)
        self._lock = asyncio.Lock()
    
    def _generate_key(self, method: str, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> str:
        """生成缓存键"""
        key_parts = [method.upper(), url]
        if params:
            key_parts.append(str(sorted(params.items())))
        if headers:
            # 只包含影响响应的关键头部
            important_headers = {k: v for k, v in headers.items() if k.lower() in ['accept', 'content-type']}
            key_parts.append(str(sorted(important_headers.items())))
        return "|".join(key_parts)
    
    async def get(self, method: str, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> Optional[Any]:
        """获取缓存的响应"""
        key = self._generate_key(method, url, params, headers)
        
        async with self._lock:
            if key in self.cache:
                response_data, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    logger.debug(f"缓存命中: {key}")
                    return response_data
                else:
                    # 缓存过期，删除
                    del self.cache[key]
        
        return None
    
    async def set(self, method: str, url: str, response_data: Any, params: Optional[Dict] = None, headers: Optional[Dict] = None):
        """设置缓存的响应"""
        key = self._generate_key(method, url, params, headers)
        
        async with self._lock:
            self.cache[key] = (response_data, time.time())
            logger.debug(f"缓存设置: {key}")
    
    async def clear(self):
        """清空缓存"""
        async with self._lock:
            self.cache.clear()
            logger.info("响应缓存已清空")
    
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
            logger.debug(f"清理了 {len(expired_keys)} 个过期缓存项")


class ConnectionPoolManager:
    """HTTP连接池管理器"""
    
    def __init__(self, config: Optional[ConnectionPoolConfig] = None):
        """
        初始化连接池管理器
        
        Args:
            config: 连接池配置
        """
        self.config = config or ConnectionPoolConfig()
        self.session: Optional[aiohttp.ClientSession] = None
        self.connector: Optional[aiohttp.TCPConnector] = None
        self.cache: Optional[ResponseCache] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._request_stats: Dict[str, Any] = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'cached_requests': 0,
            'total_time': 0.0,
            'avg_response_time': 0.0
        }
        self._stats_lock = asyncio.Lock()
        
        logger.info(f"连接池管理器初始化完成 - 配置: {self.config}")
    
    async def start(self):
        """启动连接池管理器"""
        if self.session:
            logger.warning("连接池管理器已启动")
            return
        
        # 创建TCP连接器
        self.connector = aiohttp.TCPConnector(
            limit=self.config.total_connections,
            limit_per_host=self.config.per_host_connections,
            keepalive_timeout=self.config.keepalive_timeout,
            enable_cleanup_closed=self.config.enable_cleanup,
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        # 创建客户端会话
        timeout = aiohttp.ClientTimeout(
            total=self.config.connection_timeout + self.config.read_timeout,
            connect=self.config.connection_timeout,
            sock_read=self.config.read_timeout
        )
        
        # 创建默认头部
        default_headers = {
            'User-Agent': self.config.user_agent
        }
        
        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=timeout,
            headers=default_headers,
            trust_env=True
        )
        
        # 初始化缓存
        if self.config.enable_caching:
            self.cache = ResponseCache(self.config.cache_ttl)
        
        # 启动清理任务
        if self.config.enable_cleanup:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
        logger.info("连接池管理器启动完成")
    
    async def stop(self):
        """停止连接池管理器"""
        logger.info("正在停止连接池管理器...")
        
        # 取消清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # 关闭会话
        if self.session:
            await self.session.close()
            self.session = None
        
        # 关闭连接器
        if self.connector:
            await self.connector.close()
            self.connector = None
        
        # 清空缓存
        if self.cache:
            await self.cache.clear()
            self.cache = None
        
        logger.info("连接池管理器已停止")
    
    async def _periodic_cleanup(self):
        """定期清理任务"""
        try:
            while True:
                await asyncio.sleep(self.config.cleanup_interval)
                
                # 清理过期缓存
                if self.cache:
                    await self.cache.cleanup_expired()
                
                logger.debug("连接池定期清理完成")
        except asyncio.CancelledError:
            logger.info("清理任务已取消")
    
    async def _update_stats(self, success: bool, cached: bool = False, response_time: float = 0.0):
        """更新请求统计"""
        async with self._stats_lock:
            self._request_stats['total_requests'] += 1
            
            if success:
                self._request_stats['successful_requests'] += 1
            else:
                self._request_stats['failed_requests'] += 1
            
            if cached:
                self._request_stats['cached_requests'] += 1
            
            self._request_stats['total_time'] += response_time
            
            # 计算平均响应时间
            total_requests = self._request_stats['total_requests']
            if total_requests > 0:
                self._request_stats['avg_response_time'] = self._request_stats['total_time'] / total_requests
    
    def get_stats(self) -> Dict[str, Any]:
        """获取请求统计信息"""
        return self._request_stats.copy()
    
    @asynccontextmanager
    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """
        发送HTTP请求（上下文管理器）
        
        Args:
            method: 请求方法
            url: 请求URL
            **kwargs: 其他请求参数
            
        Yields:
            aiohttp.ClientResponse: 响应对象
        """
        start_time = time.time()
        
        try:
            # 检查缓存
            if self.cache and method.upper() == 'GET':
                cached_response = await self.cache.get(method, url, kwargs.get('params'), kwargs.get('headers'))
                if cached_response:
                    await self._update_stats(True, cached=True)
                    # 创建模拟响应
                    class CachedResponse:
                        def __init__(self, data):
                            self._data = data
                            self.status = 200
                        
                        async def json(self):
                            return self._data
                        
                        async def text(self):
                            return str(self._data)
                        
                        async def __aenter__(self):
                            return self
                        
                        async def __aexit__(self, exc_type, exc_val, exc_tb):
                            pass
                    
                    yield CachedResponse(cached_response)
                    return
            
            # 设置压缩
            if self.config.enable_compression:
                headers = kwargs.get('headers', {})
                headers.setdefault('Accept-Encoding', 'gzip, deflate')
                kwargs['headers'] = headers
            
            # 发送请求
            async with self.session.request(method, url, **kwargs) as response:
                response_time = time.time() - start_time
                
                # 处理重定向
                if self.config.enable_redirects and response.status in [301, 302, 307, 308]:
                    if response.headers.get('Location'):
                        redirect_url = response.headers['Location']
                        if not redirect_url.startswith('http'):
                            # 相对URL，构建完整URL
                            parsed_url = urlparse(url)
                            redirect_url = f"{parsed_url.scheme}://{parsed_url.netloc}{redirect_url}"
                        
                        # 递归处理重定向
                        async with self.request(method, redirect_url, **kwargs) as redirect_response:
                            await self._update_stats(True, response_time=response_time)
                            yield redirect_response
                        return
                
                # 缓存GET请求的响应
                if self.cache and method.upper() == 'GET' and response.status == 200:
                    try:
                        response_data = await response.json()
                        await self.cache.set(method, url, response_data, kwargs.get('params'), kwargs.get('headers'))
                    except Exception:
                        # 如果不是JSON响应，忽略缓存
                        pass
                
                await self._update_stats(response.status < 400, response_time=response_time)
                yield response
                
        except Exception as e:
            response_time = time.time() - start_time
            await self._update_stats(False, response_time=response_time)
            logger.error(f"HTTP请求失败: {method} {url}, 错误: {e}")
            raise
    
    async def get(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """发送GET请求"""
        return await self.request('GET', url, **kwargs).__aenter__()
    
    async def post(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """发送POST请求"""
        return await self.request('POST', url, **kwargs).__aenter__()
    
    async def put(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """发送PUT请求"""
        return await self.request('PUT', url, **kwargs).__aenter__()
    
    async def delete(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """发送DELETE请求"""
        return await self.request('DELETE', url, **kwargs).__aenter__()


# 全局连接池管理器实例
_global_pool_manager: Optional[ConnectionPoolManager] = None


async def get_connection_pool_manager(config: Optional[ConnectionPoolConfig] = None) -> ConnectionPoolManager:
    """获取全局连接池管理器实例"""
    global _global_pool_manager
    
    if _global_pool_manager is None:
        _global_pool_manager = ConnectionPoolManager(config)
        await _global_pool_manager.start()
    
    return _global_pool_manager


@asynccontextmanager
async def connection_pool_context(config: Optional[ConnectionPoolConfig] = None):
    """
    连接池管理器上下文管理器
    
    Args:
        config: 连接池配置
        
    Yields:
        ConnectionPoolManager: 连接池管理器实例
    """
    manager = ConnectionPoolManager(config)
    await manager.start()
    
    try:
        yield manager
    finally:
        await manager.stop()


# 便捷的HTTP请求函数
async def async_http_get(url: str, **kwargs) -> aiohttp.ClientResponse:
    """异步GET请求"""
    manager = await get_connection_pool_manager()
    return await manager.get(url, **kwargs)


async def async_http_post(url: str, **kwargs) -> aiohttp.ClientResponse:
    """异步POST请求"""
    manager = await get_connection_pool_manager()
    return await manager.post(url, **kwargs)


async def async_http_put(url: str, **kwargs) -> aiohttp.ClientResponse:
    """异步PUT请求"""
    manager = await get_connection_pool_manager()
    return await manager.put(url, **kwargs)


async def async_http_delete(url: str, **kwargs) -> aiohttp.ClientResponse:
    """异步DELETE请求"""
    manager = await get_connection_pool_manager()
    return await manager.delete(url, **kwargs)