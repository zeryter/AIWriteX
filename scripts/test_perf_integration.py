#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import os
import time
import asyncio
import sys
from pathlib import Path

# 允许从 src/ 目录导入项目包
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_write_x.core.async_processor import AsyncContentProcessor
from ai_write_x.core.monitoring import WorkflowMonitor
from ai_write_x.utils.memory_pool import (
    ByteBufferPool,
    get_global_byte_pool,
    normalize_large_text,
)
from ai_write_x.utils.security_manager import get_security_manager
from ai_write_x.security.input_validator import InputValidator


async def _async_tasks_demo():
    async def simple_task(delay: float, value: str):
        await asyncio.sleep(delay)
        return value

    processor = AsyncContentProcessor(max_concurrency=2)
    start = time.time()
    results = await processor.gather(
        [
            lambda: asyncio.create_task(simple_task(1.0, "a")),
            lambda: asyncio.create_task(simple_task(1.0, "b")),
            lambda: asyncio.create_task(simple_task(1.0, "c")),
        ]
    )
    duration = time.time() - start
    print(f"[ASYNC] results={results}, duration={duration:.2f}s (expected ~1s)")
    assert results == ["a", "b", "c"], "Async gather results mismatch"
    assert 0.8 <= duration <= 1.6, "Expected ~1s since tasks run concurrently"


def _monitor_demo():
    monitor = WorkflowMonitor.get_instance()
    monitor.start_timer("segment1")
    time.sleep(0.2)
    monitor.stop_timer("segment1", "test_workflow")

    metrics = monitor.get_metrics()
    has_key = any(k.startswith("test_workflow:segment1") for k in metrics.keys())
    print(f"[MONITOR] has segment metric: {has_key}")
    assert has_key, "Missing segment metric in WorkflowMonitor"


def _memory_pool_demo():
    pool = get_global_byte_pool()
    buf = pool.acquire()
    assert isinstance(buf, bytearray), "Acquire did not return bytearray"
    buf[:4] = b"TEST"
    pool.release(buf)
    buf2 = pool.acquire()
    print(f"[MEMORY] buffer size={len(buf2)} bytes")
    long_text = "x" * 400_000
    normalized = normalize_large_text(long_text)
    print(f"[MEMORY] normalized length={len(normalized)} (orig=400000)")
    assert len(normalized) < len(long_text), "normalize_large_text did not reduce size"


def _security_demo():
    manager = get_security_manager()
    original_key = "sk-test-1234567890abcdef"  # 模拟OpenAI风格密钥
    encrypted = manager.encrypt_api_key(original_key)
    os.environ["OPENAI_API_KEY_ENCRYPTED"] = encrypted

    # 验证取回与格式
    retrieved = manager.get_api_key("OPENAI_API_KEY")
    validator = InputValidator()
    is_valid = validator.validate_api_key(retrieved, provider="openai")
    print(f"[SECURITY] decrypted head={retrieved[:4]}..., valid={is_valid}")
    assert retrieved == original_key, "Decrypted key mismatch"
    assert is_valid, "API key format validation failed"


def main():
    print("== Running performance integration tests ==")
    asyncio.run(_async_tasks_demo())
    _monitor_demo()
    _memory_pool_demo()
    _security_demo()
    print("== All integration tests passed ==")


if __name__ == "__main__":
    main()