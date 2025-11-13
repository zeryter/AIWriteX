#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import asyncio
import json
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ai_write_x.utils import log
from ..state import get_app_state


router = APIRouter()


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket日志连接"""
    await websocket.accept()
    connection_id = f"conn_{int(time.time() * 1000)}"
    app_state = get_app_state()
    app_state.active_connections[connection_id] = websocket

    try:
        while True:
            # 保持连接活跃，接收心跳消息
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        if connection_id in app_state.active_connections:
            del app_state.active_connections[connection_id]
    except Exception as e:
        log.print_log(f"WebSocket连接错误: {str(e)}", "error")
        if connection_id in app_state.active_connections:
            del app_state.active_connections[connection_id]


async def broadcast_log(message: str, msg_type: str = "info"):
    """广播日志消息到所有连接的WebSocket客户端"""
    app_state = get_app_state()

    if not app_state.active_connections:
        return

    log_data = {"type": msg_type, "message": message, "timestamp": time.time()}

    disconnected = []
    for conn_id, websocket in app_state.active_connections.items():
        try:
            await websocket.send_text(json.dumps(log_data))
        except Exception:
            disconnected.append(conn_id)

    # 清理断开的连接
    for conn_id in disconnected:
        app_state.active_connections.pop(conn_id, None)


async def start_log_monitoring():
    """启动日志监控任务"""
    app_state = get_app_state()

    while app_state.is_running and app_state.log_queue:
        try:
            # 非阻塞获取日志消息
            try:
                log_msg = app_state.log_queue.get_nowait()
                message = log_msg.get("message", "")
                msg_type = log_msg.get("type", "info")

                await broadcast_log(message, msg_type)

                # 检查任务完成
                if msg_type == "internal" and "任务执行完成" in message:
                    app_state.is_running = False
                    app_state.current_process = None
                    app_state.log_queue = None
                    await broadcast_log("任务执行完成", "success")
                    break

            except Exception:
                # 队列为空，短暂等待
                await asyncio.sleep(0.1)
                continue

        except Exception as e:
            await broadcast_log(f"日志监控错误: {str(e)}", "error")
            break
