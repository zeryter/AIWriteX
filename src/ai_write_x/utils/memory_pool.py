"""
内存池管理与大文本归一化工具
提供复用缓冲区、控制大文本占用与统一释放接口
"""

import threading
from typing import Optional


class ByteBufferPool:
    """简单的字节缓冲池，避免频繁分配/释放大块内存"""

    def __init__(self, chunk_size: int = 1024 * 1024, max_chunks: int = 8):
        self.chunk_size = chunk_size
        self.max_chunks = max_chunks
        self._pool: list[bytearray] = []
        self._lock = threading.Lock()

    def acquire(self) -> bytearray:
        with self._lock:
            if self._pool:
                return self._pool.pop()
        return bytearray(self.chunk_size)

    def release(self, buffer: bytearray):
        if buffer is None:
            return
        with self._lock:
            if len(self._pool) < self.max_chunks:
                # 归一化大小，避免过大块驻留
                if len(buffer) != self.chunk_size:
                    buffer = bytearray(self.chunk_size)
                self._pool.append(buffer)


def normalize_large_text(text: str, max_len: int = 200_000) -> str:
    """对超长文本做截断与空白归一化，避免内存暴涨"""
    if not isinstance(text, str):
        text = str(text)
    if len(text) > max_len:
        # 保留头尾信息，减少信息损失
        head = text[: max_len // 2]
        tail = text[-max_len // 2 :]
        text = head + "\n...\n" + tail
    # 规范空白字符
    return " ".join(text.split())


# 全局缓冲池实例
_global_pool: Optional[ByteBufferPool] = None


def get_global_byte_pool() -> ByteBufferPool:
    global _global_pool
    if _global_pool is None:
        _global_pool = ByteBufferPool()
    return _global_pool