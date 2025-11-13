#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import sys
import asyncio
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_write_x.utils.async_task_manager import task_manager_context, TaskStatus


async def async_job(name: str, delay: float):
    await asyncio.sleep(delay)
    return f"async-{name}-done"


def sync_job(name: str, delay: float):
    time.sleep(delay)
    return f"sync-{name}-done"


async def main():
    print("== AsyncTaskManager validation ==")
    async with task_manager_context(max_workers=4, max_concurrent_tasks=10) as manager:
        tid_async = manager.submit_task(
            coroutine=async_job("A", 1.0),
            name="async_task_A",
        )

        tid_sync = manager.submit_sync_task(
            func=sync_job,
            args=("B", 1.5),
            name="sync_task_B",
        )

        res_a = await manager.wait_for_task(tid_async, timeout=5)
        print("[ASYNC]", tid_async, res_a)

        status_b = manager.get_task_status(tid_sync)
        print("[SYNC-STATUS]", tid_sync, status_b)

        res_b = await manager.wait_for_task(tid_sync, timeout=5)
        print("[SYNC]", tid_sync, res_b)

    print("== Manager stopped cleanly ==")


if __name__ == "__main__":
    asyncio.run(main())

