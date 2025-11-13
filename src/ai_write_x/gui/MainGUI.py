#!/usr/bin/python
# -*- coding: UTF-8 -*-

"""

主界面

"""

import sys
import subprocess
import time
import queue
import threading
import os
import glob
from collections import deque
from datetime import datetime
import PySimpleGUI as sg
import tkinter as tk

from ai_write_x.crew_main import ai_write_x_main

from ai_write_x.utils import comm
from ai_write_x.utils import utils
from ai_write_x.utils import log
from ai_write_x.config.config import Config

from ai_write_x.gui import ConfigEditor
from ai_write_x.gui import ArticleManager
from ai_write_x.gui import TemplateManager
from ai_write_x.config.config import DEFAULT_TEMPLATE_CATEGORIES
from ai_write_x.utils.path_manager import PathManager


__author__ = "iniwaper@gmail.com"
__copyright__ = "Copyright (C) 2025 iniwap"
# __date__ = "2025/04/17"

__version___ = "v2.3.0"


class MainGUI(object):
    def __init__(self):
        self._log_list = []
        self._update_queue = comm.get_update_queue()
        self._log_buffer = deque(maxlen=100)
        self._ui_log_path = (
            PathManager.get_log_dir() / f"UI_{datetime.now().strftime('%Y-%m-%d')}.log"
        )
        self._log_list = self.__get_logs()
        # 初始化日志系统为UI模式
        log.init_ui_mode()
        # 配置 CrewAI 日志处理器
        log.setup_logging("crewai", self._update_queue)

        # 统一的状态管理
        self._crew_process = None
        self._log_queue = None  # 进程间日志队列
        self._monitor_thread = None
        self._process_lock = threading.Lock()
        self._is_running = False
        self._task_stopping = False
        self._monitor_needs_restart = False

        self.load_saved_font()

        config = Config.get_instance()
        # 静默执行配置迁移，失败时自动使用默认配置
        if not config.migrate_config_if_needed():
            log.print_log("配置初始化失败，请检查系统环境", "warning")

        # 加载配置，不验证
        if not config.load_config():
            # 配置信息未填写，仅作提示，用户点击开始任务时才禁止操作并提示错误
            log.print_log(config.error_message, "error")

        # 获取模板分类和当前配置
        categories = PathManager.get_all_categories(DEFAULT_TEMPLATE_CATEGORIES)
        current_category = config.custom_template_category
        current_template = config.custom_template
        current_templates = (
            PathManager.get_templates_by_category(current_category) if current_category else []
        )

        # 设置主题
        sg.theme("systemdefault")

        menu_list = [
            ["配置", ["配置管理", "CrewAI文件", "AIForge文件"]],
            ["发布", ["文章管理"]],
            ["模板", ["模板管理"]],
            ["日志", self._log_list],
            ["帮助", ["帮助", "关于", "官网"]],
        ]

        # 根据平台选择菜单组件
        if sys.platform == "darwin":  # macOS
            menu_component = [sg.MenubarCustom(menu_list, key="-MENU-")]
            button_size = (12, 1.2)
            window_size = (650, 680)
        else:  # Windows 和 Linux
            menu_component = [sg.Menu(menu_list, key="-MENU-")]
            button_size = (15, 2)
            window_size = (650, 720)

        layout = [
            menu_component,
            # 顶部品牌区域
            [
                sg.Image(
                    s=(640, 120),
                    filename=utils.get_res_path(
                        os.path.join("UI", "bg.png"), os.path.dirname(__file__)
                    ),
                    key="-BG-IMG-",
                    expand_x=True,
                )
            ],
            # 使用提示区域
            [
                sg.Frame(
                    "",
                    [
                        [
                            sg.Text(
                                "💡 快速开始：1. 配置→配置管理 填写使用的 API KEY  2. 勾选自定义话题启用借鉴模式，默认使用热搜话题",  # noqa 501
                                font=("", 8),
                                text_color="#666666",
                                pad=((10, 10), (5, 5)),
                            )
                        ]
                    ],
                    border_width=0,
                    pad=((15, 15), (5, 10)),
                    expand_x=True,
                )
            ],
            # 主要配置区域
            [
                sg.Frame(
                    "借鉴模式",
                    [
                        # 话题配置行
                        [
                            sg.Text("自定义话题", size=(10, 1), pad=((10, 5), (8, 5))),
                            sg.Checkbox(
                                "",
                                key="-CUSTOM_TOPIC-",
                                enable_events=True,
                                pad=((8, 10), (8, 5)),
                                tooltip="启用自定义话题和借鉴文章模式",
                            ),
                            sg.InputText(
                                "",
                                key="-TOPIC_INPUT-",
                                disabled=True,
                                size=(35, 1),
                                pad=((0, 10), (8, 5)),
                                tooltip="输入自定义话题，或留空以自动获取热搜",
                                enable_events=True,
                            ),
                        ],
                        # 模板配置行
                        [
                            sg.Text("模板选择", size=(10, 1), pad=((10, 5), (5, 5))),
                            sg.Combo(
                                ["随机分类"] + categories,
                                default_value=current_category if current_category else "随机分类",
                                key="-TEMPLATE_CATEGORY-",
                                disabled=True,
                                size=(17, 1),
                                readonly=True,
                                enable_events=True,
                                pad=((15, 5), (5, 5)),
                            ),
                            sg.Combo(
                                ["随机模板"] + current_templates,
                                default_value=current_template if current_template else "随机模板",
                                key="-TEMPLATE-",
                                disabled=True,
                                size=(17, 1),
                                readonly=True,
                                pad=((5, 10), (5, 5)),
                            ),
                        ],
                        # 参考链接配置行
                        [
                            sg.Text("参考链接", size=(10, 1), pad=((10, 5), (5, 8))),
                            sg.InputText(
                                "",
                                key="-URLS_INPUT-",
                                disabled=True,
                                size=(30, 1),
                                pad=((15, 5), (5, 8)),
                                tooltip="多个链接用竖线(|)分隔",
                                enable_events=True,
                            ),
                            sg.Text("借鉴比例", size=(8, 1), pad=((10, 5), (5, 8))),
                            sg.Combo(
                                ["10%", "20%", "30%", "50%", "75%"],
                                default_value="30%",
                                key="-REFERENCE_RATIO-",
                                disabled=True,
                                size=(8, 1),
                                pad=((5, 10), (5, 8)),
                            ),
                        ],
                    ],
                    border_width=1,
                    relief=sg.RELIEF_RIDGE,
                    pad=((15, 15), (5, 15)),
                    expand_x=True,
                    font=("", 9, "bold"),
                )
            ],
            # 操作按钮区域
            [
                sg.Frame(
                    "",
                    [
                        [
                            sg.Push(),
                            sg.Button(
                                "开始执行",
                                size=button_size,
                                key="-START_BTN-",
                                button_color=("#FFFFFF", "#2E8B57"),
                                font=("", 10, "bold"),
                                pad=((10, 15), (10, 10)),
                            ),
                            sg.Button(
                                "停止执行",
                                size=button_size,
                                key="-STOP_BTN-",
                                disabled=not self._is_running,
                                button_color=("#FFFFFF", "#CD5C5C"),
                                font=("", 10, "bold"),
                                pad=((15, 10), (10, 10)),
                            ),
                            sg.Push(),
                        ]
                    ],
                    border_width=0,
                    pad=((15, 15), (5, 10)),
                    expand_x=True,
                )
            ],
            # 分隔线
            [sg.HSeparator(pad=((20, 20), (10, 10)))],
            # 日志控制区域
            [
                sg.Frame(
                    "运行日志",
                    [
                        [
                            sg.Text("显示条数:", size=(8, 1), pad=((10, 5), (5, 5))),
                            sg.Spin(
                                [10, 20, 50, 100, 200, 500, 1000],
                                initial_value=100,
                                key="-LOG_LIMIT-",
                                size=(8, 1),
                                pad=((5, 10), (5, 5)),
                            ),
                            sg.Button(
                                "应用",
                                key="-SET_LOG_LIMIT-",
                                size=(8, 1),
                                pad=((5, 10), (5, 5)),
                            ),
                            sg.Button(
                                "清空",
                                key="-CLEAR_LOG-",
                                size=(8, 1),
                                pad=((5, 10), (5, 5)),
                            ),
                        ],
                        [
                            sg.Multiline(
                                size=(90, 16),
                                key="-STATUS-",
                                autoscroll=True,
                                pad=((10, 10), (5, 10)),
                                # font=("Consolas", 9),
                                background_color="#F8F8F8",
                                text_color="#333333",
                            )
                        ],
                    ],
                    border_width=1,
                    relief=sg.RELIEF_RIDGE,
                    pad=((15, 15), (5, 15)),
                    expand_x=True,
                    font=("", 9, "bold"),
                )
            ],
        ]
        self._window = sg.Window(
            f"AIWriteX - {__version___}",
            layout,
            default_element_size=(12, 1),
            size=window_size,
            icon=utils.get_gui_icon(),
            finalize=True,
            resizable=False,
            element_justification="left",
            margins=(10, 10),
        )

        # 根据平台和菜单类型初始化菜单引用
        if sys.platform == "darwin":  # macOS 使用 MenubarCustom
            self._menu = None  # MenubarCustom 没有 TKMenu 属性
            self._use_menubar_custom = True
        else:  # Windows 和 Linux 使用标准 Menu
            self._menu = self._window["-MENU-"].TKMenu  # type: ignore
            self._use_menubar_custom = False

    def load_saved_font(self):
        """加载保存的字体设置"""
        saved_font = sg.user_settings_get_entry("-global_font-", "Helvetica|10")

        try:
            if "|" in saved_font:  # type: ignore
                # 新格式：字体名|大小
                font_name, size = saved_font.split("|", 1)  # type: ignore
            else:
                # 兼容旧格式
                parts = saved_font.split()  # type: ignore
                if len(parts) >= 2:
                    size = parts[-1]
                    font_name = " ".join(parts[:-1])
                else:
                    # 如果格式不正确，使用默认字体
                    sg.set_options(font="Helvetica 10")
                    return "Helvetica|10"

            # 检查是否为横向字体
            excluded_patterns = [
                "@",  # 横向字体通常以@开头
                "Vertical",  # 包含Vertical的字体
                "V-",  # 以V-开头的字体
                "縦",  # 日文中的纵向字体标识
                "Vert",  # 其他可能的纵向标识
            ]

            # 如果是横向字体，使用默认字体
            is_horizontal_font = any(pattern in font_name for pattern in excluded_patterns)
            if is_horizontal_font:
                sg.set_options(font="Helvetica 10")
                return "Helvetica|10"

            # 正常字体，应用设置
            font_tuple = (font_name, int(size))
            sg.set_options(font=font_tuple)
            return saved_font

        except Exception:
            sg.set_options(font="Helvetica 10")
            return "Helvetica|10"

    def __save_ui_log(self, log_entry):
        # 如果日志不存在，则更新日志列表
        need_update = False
        if not os.path.exists(self._ui_log_path):
            need_update = True

        with open(self._ui_log_path, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
            f.flush()

        if need_update:
            self._log_list = self.__get_logs()

        return need_update

    def __get_logs(self, max_files=5):
        try:
            # 获取所有 .log 文件
            log_dir = PathManager.get_log_dir()
            log_files = list(log_dir.glob("*.log"))
            if not log_files:
                return ["更多..."]

            # 按修改时间排序（降序）
            log_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

            # 提取文件名（不含路径），限制数量
            log_filenames = [os.path.basename(f) for f in log_files[:max_files]]
            if len(log_files) > max_files:
                log_filenames.append("更多...")

            return log_filenames
        except Exception as e:  # noqa 841
            return ["更多..."]

    def __update_menu(self):
        if self._use_menubar_custom:
            # MenubarCustom 需要重新创建整个菜单
            self.update_log_menu(self._log_list)
            return

        if self._menu is None:
            return  # 跳过菜单更新

        try:
            # 缓存"日志"菜单引用，初始化时查找一次
            if not hasattr(self, "_log_menu"):
                for i in range(self._menu.index(tk.END) + 1):
                    if self._menu.entrycget(i, "label") == "日志":
                        self._log_menu = self._menu.nametowidget(self._menu.entrycget(i, "menu"))
                        break
                else:
                    return

            # 清空"日志"菜单并更新
            self._log_menu.delete(0, tk.END)
            for log_item in self._log_list:
                self._log_menu.add_command(
                    label=log_item,
                    command=lambda item=log_item: self._window.write_event_value(item, None),
                )
        except Exception:
            pass

    def update_log_menu(self, log_list):
        """更新日志菜单（用于 MenubarCustom）"""
        self._log_list = log_list
        # 重建菜单
        menu_list = [
            ["配置", ["配置管理", "CrewAI文件", "AIForge文件"]],
            ["发布", ["文章管理"]],
            ["模板", ["模板管理"]],
            ["日志", self._log_list],
            ["帮助", ["帮助", "关于", "官网"]],
        ]
        # 刷新菜单
        try:
            self._window["-MENU-"].update(menu_definition=menu_list)
        except Exception:
            pass

    def _process_available_messages(self):
        """批量处理消息，带超时保护"""
        messages_processed = 0
        max_batch_size = 20  # 限制单次处理数量
        start_time = time.time()
        max_processing_time = 1.0  # 最大处理时间1秒

        try:
            while messages_processed < max_batch_size:
                # 超时保护
                if time.time() - start_time > max_processing_time:
                    break

                try:
                    log_msg = self._log_queue.get(timeout=0.05)  # type: ignore
                    self._process_log_message(log_msg)
                    messages_processed += 1
                except queue.Empty:
                    break
                except Exception:
                    continue  # 跳过错误消息，继续处理

        except Exception:
            pass

        return messages_processed

    def _handle_process_completion(self):
        """优雅处理进程完成"""
        try:
            if self._process_lock.acquire(timeout=2.0):  # 带超时的锁获取
                try:
                    if self._crew_process:
                        exit_code = self._crew_process.exitcode  # type: ignore

                        # 最后一次尝试清理剩余消息
                        self._drain_remaining_logs_with_timeout()
                        self._handle_task_completion(
                            exit_code == 0,
                            f"执行异常退出，退出码: {exit_code}" if exit_code != 0 else None,
                        )
                finally:
                    self._process_lock.release()  # 确保释放锁
        except Exception:
            # 即使出错也要确保状态重置
            self._reset_task_state()

    def _drain_remaining_logs_with_timeout(self, timeout=3.0):
        """带超时的剩余日志清理，确保所有消息都被处理"""
        start_time = time.time()
        messages_processed = 0

        while time.time() - start_time < timeout:
            try:
                log_msg = self._log_queue.get_nowait()  # type: ignore
                self._process_log_message(log_msg)
                messages_processed += 1
            except queue.Empty:
                # 短暂等待，可能还有延迟消息
                time.sleep(0.1)
                continue

        return messages_processed

    def _start_monitoring_with_restart(self):
        """带重启机制的监控线程启动"""

        def monitor_with_restart():
            restart_count = 0
            max_restarts = 3

            while restart_count < max_restarts and not self._task_stopping:
                try:
                    self._monitor_needs_restart = False
                    self._monitor_process_logs()

                    # 检查是否需要重启
                    if self._monitor_needs_restart and not self._task_stopping:
                        restart_count += 1
                        time.sleep(1.0)  # 短暂延迟后重启
                        continue
                    else:
                        break  # 正常退出

                except Exception:
                    restart_count += 1
                    time.sleep(1.0)

            if restart_count >= max_restarts:
                # 强制停止任务
                self._reset_task_state()

        self._monitor_thread = threading.Thread(target=monitor_with_restart, daemon=True)
        self._monitor_thread.start()

    def _monitor_process_logs(self):
        """多进程日志监控"""
        consecutive_errors = 0
        max_consecutive_errors = 5

        while True:
            try:
                # 使用非阻塞锁检查，避免死锁
                if not self._process_lock.acquire(blocking=False):
                    time.sleep(0.01)
                    continue

                try:
                    # 检查基本退出条件
                    if not self._log_queue or self._task_stopping:
                        break

                    # 基于进程的实际状态判断是否结束
                    process_ended = self._crew_process and self._crew_process.exitcode is not None  # type: ignore # noqa 501

                finally:
                    self._process_lock.release()

                # 批量处理消息，不依赖消息数量判断进程状态
                messages_processed = self._process_available_messages()

                # 只有进程真正结束时才进行完成处理
                if process_ended:
                    # 多重确认：再次尝试处理剩余消息
                    for _ in range(3):
                        remaining = self._process_available_messages()
                        if remaining == 0:
                            break
                        time.sleep(0.1)

                    # 确认进程完成
                    self._handle_process_completion()
                    break

                # 动态等待时间
                if messages_processed == 0:
                    time.sleep(0.1)
                else:
                    time.sleep(0.01)

                consecutive_errors = 0

            except Exception:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    self._monitor_needs_restart = True
                    break
                time.sleep(min(consecutive_errors * 0.5, 2.0))

    def _process_log_message(self, log_msg):
        """处理单条日志消息"""
        msg_type = log_msg.get("type", "unknown")
        message = log_msg.get("message", "")
        level = log_msg.get("level", "INFO")

        # 检查是否为错误级别的日志
        if msg_type == "log":
            if level == "ERROR":
                # self._display_log(message, "error")
                self._handle_task_completion(False, message)
                return
            else:
                self._display_log(message, level.lower())
        elif msg_type == "error":
            # self._display_log(message, "error")
            self._handle_task_completion(False, message)
            return
        elif msg_type == "print":
            self._display_log(message, "print")
        elif msg_type == "system":
            self._display_log(message, "system")
        elif msg_type == "success":
            self._display_log(message, "success")
            self._handle_task_completion(True)
        elif msg_type == "internal":
            # 内部消息，不显示到界面
            return
        else:
            self._display_log(message, msg_type)

    def _display_log(self, message, msg_type="info"):
        """显示日志到界面并保存到文件，统一格式化"""
        # 统一格式化日志条目
        formatted_log_entry = utils.format_log_message(message, msg_type)

        # 添加到缓冲区
        self._log_buffer.append(formatted_log_entry)

        # 保存到文件
        if self.__save_ui_log(formatted_log_entry):
            self.__update_menu()

        #  使用线程安全的方式更新界面
        self._window.write_event_value("-UPDATE_LOG-", formatted_log_entry)

    def _handle_task_completion(self, success, error_message=None):
        """处理任务完成事件"""
        try:
            # 清理可能残留的环境变量文件
            temp_dir = PathManager.get_temp_dir()
            env_files = glob.glob(str(temp_dir / "env_*.json"))

            for env_file in env_files:
                try:
                    os.remove(env_file)
                except Exception:
                    pass

        except Exception:
            pass
        # 发送任务完成事件到UI
        self._window.write_event_value(
            "-TASK_COMPLETED-", {"success": success, "error": error_message}
        )

    # 处理消息队列
    def process_queue(self):
        """处理线程队列消息"""
        try:
            msg = self._update_queue.get_nowait()
            if msg["type"] in ["status", "warning", "error"]:
                # 提取原始消息内容
                original_msg = msg["value"]

                # 处理特殊前缀
                if original_msg.startswith("PRINT:"):
                    clean_msg = original_msg[6:].strip()
                    self._display_log(clean_msg, "print")
                elif original_msg.startswith("FILE_LOG:"):
                    clean_msg = original_msg[9:].strip()
                    self._display_log(clean_msg, "file")
                elif original_msg.startswith("LOG:"):
                    clean_msg = original_msg[4:].strip()
                    self._display_log(clean_msg, "log")
                else:
                    self._display_log(original_msg, msg["type"])

                # 检查任务完成状态
                if msg["type"] == "status" and (
                    msg["value"].startswith("任务完成！") or msg["value"] == "任务执行完成"
                ):
                    self._window["-START_BTN-"].update(disabled=False)
                    self._window["-STOP_BTN-"].update(disabled=True)
                    with self._process_lock:
                        self._is_running = False
                        self._crew_process = None
                        self._log_queue = None

                # 处理错误和警告
                if msg["type"] == "error":
                    sg.popup_error(
                        f"任务错误: {msg['value']}",
                        title="错误",
                        icon=utils.get_gui_icon(),
                        non_blocking=True,
                        keep_on_top=True,
                    )
                    self._window["-START_BTN-"].update(disabled=False)
                    self._window["-STOP_BTN-"].update(disabled=True)
                    with self._process_lock:
                        self._is_running = False
                        self._crew_process = None
                        self._log_queue = None
                elif msg["type"] == "warning":
                    sg.popup(
                        f"出现错误但不影响运行，告警信息：{msg['value']}",
                        title="系统提示",
                        icon=utils.get_gui_icon(),
                        non_blocking=True,
                        keep_on_top=True,
                    )
        except queue.Empty:
            pass

    def _handle_start_button(self, values):
        """处理开始按钮点击"""
        # 强制清理任何残留状态
        with self._process_lock:
            if self._crew_process:
                if not self._crew_process.is_alive():  # type: ignore
                    self._crew_process = None
                    self._log_queue = None
                else:
                    # 有活跃进程，不允许启动新任务
                    sg.popup_error(
                        "任务正在运行中，请先停止当前任务",
                        title="系统提示",
                        icon=utils.get_gui_icon(),
                        keep_on_top=True,
                    )
                    return

            # 重置所有状态
            self._is_running = False
            self._task_stopping = False

        config = Config.get_instance()
        if not config.validate_config():
            sg.popup_error(
                f"无法执行，配置错误：{config.error_message}",
                title="系统提示",
                icon=utils.get_gui_icon(),
                non_blocking=True,
                keep_on_top=True,
            )
            return

        # 处理自定义话题、链接和借鉴比例
        if values["-CUSTOM_TOPIC-"]:
            topic = values["-TOPIC_INPUT-"].strip()
            if not topic:
                sg.popup_error(
                    "自定义话题不能为空",
                    title="系统提示",
                    icon=utils.get_gui_icon(),
                    non_blocking=True,
                    keep_on_top=True,
                )
                return
            config.custom_topic = topic
            urls_input = values["-URLS_INPUT-"].strip()
            if urls_input:
                urls = [url.strip() for url in urls_input.split("|") if url.strip()]
                valid_urls = [url for url in urls if utils.is_valid_url(url)]
                if len(valid_urls) != len(urls):
                    sg.popup_error(
                        "存在无效的URL，请检查输入（确保使用http://或https://）",
                        title="系统提示",
                        icon=utils.get_gui_icon(),
                        non_blocking=True,
                        keep_on_top=True,
                    )
                    return
                config.urls = valid_urls
            else:
                config.urls = []
            # 将比例转换为浮点数
            config.reference_ratio = float(values["-REFERENCE_RATIO-"].strip("%")) / 100
            config.custom_template_category = (
                values["-TEMPLATE_CATEGORY-"] if values["-TEMPLATE_CATEGORY-"] != "随机分类" else ""
            )
            config.custom_template = (
                values["-TEMPLATE-"] if values["-TEMPLATE-"] != "随机模板" else ""
            )
        else:
            config.custom_topic = ""
            config.urls = []
            config.reference_ratio = 0.0  # 重置为0
            config.custom_template_category = ""  # 自定义话题时，模板分类
            config.custom_template = ""  # 自定义话题时，模板

        # 收集需要同步到子进程的配置数据
        config_data = {
            "custom_topic": config.custom_topic,
            "urls": config.urls,
            "reference_ratio": config.reference_ratio,
            "custom_template_category": config.custom_template_category,
            "custom_template": config.custom_template,
        }

        sg.popup(
            "更多界面功能开发中，请关注项目 :)\n点击OK开始执行",
            title="系统提示",
            icon=utils.get_gui_icon(),
            keep_on_top=True,
        )

        self._window["-START_BTN-"].update(disabled=True)
        self._window["-STOP_BTN-"].update(disabled=False)

        # 启动新进程，传递配置数据
        try:
            result = ai_write_x_main(config_data)  # 传递配置数据
            if result and result[0] and result[1]:
                with self._process_lock:
                    self._crew_process, self._log_queue = result
                    self._is_running = True
                    self._task_stopping = False

                self._crew_process.start()  # type: ignore

                # 启动监控线程
                if self._monitor_thread and self._monitor_thread.is_alive():
                    # 等待之前的监控线程结束
                    self._monitor_thread.join(timeout=1.0)

                self._start_monitoring_with_restart()  # 使用重启机制
            else:
                # 更新UI
                self._window["-START_BTN-"].update(disabled=False)
                self._window["-STOP_BTN-"].update(disabled=True)
                sg.popup_error(
                    "执行启动失败，请检查配置",
                    title="错误",
                    icon=utils.get_gui_icon(),
                    keep_on_top=True,
                )
        except Exception as e:
            self._window["-START_BTN-"].update(disabled=False)
            self._window["-STOP_BTN-"].update(disabled=True)
            with self._process_lock:
                self._is_running = False
                self._crew_process = None
                self._log_queue = None
            sg.popup_error(
                f"启动执行时发生错误: {str(e)}",
                title="错误",
                icon=utils.get_gui_icon(),
                keep_on_top=True,
            )

    def _handle_stop_button(self):
        """处理停止按钮点击"""
        with self._process_lock:
            if not self._is_running:
                sg.popup(
                    "没有正在运行的任务",
                    title="系统提示",
                    icon=utils.get_gui_icon(),
                    keep_on_top=True,
                )
                return

            if not self._crew_process or not self._crew_process.is_alive():  # type: ignore
                self._reset_task_state()
                self._window["-START_BTN-"].update(disabled=False)
                self._window["-STOP_BTN-"].update(disabled=True)
                sg.popup(
                    "任务已经结束",
                    title="系统提示",
                    icon=utils.get_gui_icon(),
                    keep_on_top=True,
                )
                return

            self._task_stopping = True
            # 立即更新按钮状态，防止重复点击
            self._window["-STOP_BTN-"].update(disabled=True)

        self._display_log("正在停止任务...", "system")

        # 使用线程来处理进程终止，避免阻塞 UI
        def terminate_process():
            try:
                # 首先尝试优雅终止
                if self._crew_process and self._crew_process.is_alive():  # type: ignore
                    self._crew_process.terminate()  # type: ignore
                    self._crew_process.join(timeout=2.0)  # type: ignore

                    # 检查是否真正终止
                    if self._crew_process.is_alive():  # type: ignore
                        self._display_log("执行未响应，强制终止", "system")
                        self._crew_process.kill()  # type: ignore
                        self._crew_process.join(timeout=1.0)  # type: ignore

                        if self._crew_process.is_alive():  # type: ignore
                            self._display_log("警告：执行可能未完全终止", "warning")
                        else:
                            self._display_log("任务执行已强制终止", "system")
                    else:
                        self._display_log("任务执行已停止", "system")

                # 清理队列中的剩余消息
                if self._log_queue:
                    try:
                        while True:
                            self._log_queue.get_nowait()  # type: ignore
                    except queue.Empty:
                        pass

                self._reset_task_state()

                # 通过事件更新 UI
                self._window.write_event_value(
                    "-TASK_TERMINATED-",
                    {
                        "fully_stopped": (
                            not self._crew_process.is_alive() if self._crew_process else True  # type: ignore # noqa 501
                        )
                    },
                )
            except Exception as e:
                self._display_log(f"终止执行时出错: {str(e)}", "error")
                # 即使出错也要重置状态
                self._reset_task_state()
                self._window.write_event_value("-TASK_TERMINATED-", {"fully_stopped": False})

        # 在后台线程中执行终止操作
        terminate_thread = threading.Thread(target=terminate_process, daemon=True)
        terminate_thread.start()

    def _reset_task_state(self):
        """完全重置任务状态"""
        with self._process_lock:
            self._is_running = False
            self._task_stopping = False
            self._crew_process = None
            self._log_queue = None

        # 等待监控线程结束
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)
        self._monitor_thread = None

    def run(self):
        """主事件循环，处理用户交互"""
        try:
            while True:
                event, values = self._window.read(timeout=100)  # type: ignore

                if event == sg.WIN_CLOSED:  # always,  always give a way out!
                    if self._is_running and self._crew_process and self._crew_process.is_alive():  # type: ignore # noqa 501
                        self._crew_process.terminate()  # type: ignore
                        self._crew_process.join(timeout=2.0)  # type: ignore
                        if self._crew_process.is_alive():  # type: ignore
                            self._crew_process.kill()  # type: ignore
                    break

                # 处理自定义事件
                elif event == "-UPDATE_LOG-":
                    # 线程安全的日志更新
                    self._window["-STATUS-"].update(value="\n".join(self._log_buffer), append=False)
                    continue
                elif event == "-TASK_COMPLETED-":
                    # 处理任务完成事件
                    task_data = values["-TASK_COMPLETED-"]
                    self._window["-START_BTN-"].update(disabled=False)
                    self._window["-STOP_BTN-"].update(disabled=True)
                    if not task_data["success"] and task_data["error"]:
                        # 记录失败日志
                        self._display_log(f"任务执行出错: {task_data['error']}", "error")
                        sg.popup_error(
                            f"任务执行出错: {task_data['error']}",
                            title="系统提示",
                            icon=utils.get_gui_icon(),
                            keep_on_top=True,
                        )
                    else:
                        # 记录成功日志
                        self._display_log("任务执行完成", "success")
                        sg.popup(
                            "任务执行完成",
                            title="系统提示",
                            icon=utils.get_gui_icon(),
                            non_blocking=True,
                            keep_on_top=True,
                        )
                    continue
                elif event == "-TASK_TERMINATED-":
                    # 处理任务终止事件
                    self._window["-START_BTN-"].update(disabled=False)
                    self._window["-STOP_BTN-"].update(disabled=True)
                    sg.popup(
                        "任务已终止",
                        title="系统提示",
                        icon=utils.get_gui_icon(),
                        non_blocking=True,
                        keep_on_top=True,
                    )
                    continue

                # 处理 MenubarCustom 事件（格式为 "菜单::子菜单"）
                elif self._use_menubar_custom and "::" in str(event):
                    menu_parts = event.split("::")
                    if len(menu_parts) == 2:
                        main_menu, submenu = menu_parts
                        if main_menu == "配置":
                            if submenu == "配置管理":
                                event = "配置管理"
                            elif submenu == "CrewAI文件":
                                event = "CrewAI文件"
                            elif submenu == "AIForge文件":
                                event = "AIForge文件"
                        elif main_menu == "发布":
                            if submenu == "文章管理":
                                event = "文章管理"
                        elif main_menu == "模板":
                            if submenu == "模板管理":
                                event = "模板管理"
                        elif main_menu == "日志":
                            event = submenu  # 日志文件名
                        elif main_menu == "帮助":
                            if submenu == "帮助":
                                event = "帮助"
                            elif submenu == "关于":
                                event = "关于"
                            elif submenu == "官网":
                                event = "官网"

                elif event == "配置管理":
                    ConfigEditor.gui_start()
                elif event == "CrewAI文件":
                    try:
                        if sys.platform == "win32":
                            subprocess.run(["notepad", str(PathManager.get_config_path())])
                        elif sys.platform == "darwin":  # macOS
                            subprocess.run(
                                ["open", "-a", "TextEdit", str(PathManager.get_config_path())]
                            )
                        else:  # Linux
                            subprocess.run(["gedit", str(PathManager.get_config_path())])
                    except Exception as e:
                        sg.popup(
                            "无法打开CrewAI配置文件 :( \n错误信息：" + str(e),
                            title="系统提示",
                            icon=utils.get_gui_icon(),
                            keep_on_top=True,
                        )
                elif event == "AIForge文件":
                    try:
                        if sys.platform == "win32":
                            subprocess.run(
                                ["notepad", str(Config.get_instance().config_aiforge_path)]
                            )
                        elif sys.platform == "darwin":  # macOS
                            subprocess.run(
                                [
                                    "open",
                                    "-a",
                                    "TextEdit",
                                    str(Config.get_instance().config_aiforge_path),
                                ]
                            )
                        else:  # Linux
                            subprocess.run(
                                ["gedit", str(Config.get_instance().config_aiforge_path)]
                            )
                    except Exception as e:
                        sg.popup(
                            "无法打开AIForge配置文件 :( \n错误信息：" + str(e),
                            title="系统提示",
                            icon=utils.get_gui_icon(),
                            keep_on_top=True,
                        )
                elif event == "-CUSTOM_TOPIC-":
                    # 根据复选框状态启用/禁用输入框和下拉框
                    is_enabled = values["-CUSTOM_TOPIC-"]
                    self._window["-TOPIC_INPUT-"].update(disabled=not is_enabled)
                    self._window["-URLS_INPUT-"].update(disabled=not is_enabled)
                    self._window["-REFERENCE_RATIO-"].update(disabled=not is_enabled)
                    self._window["-TEMPLATE_CATEGORY-"].update(disabled=not is_enabled)
                    self._window["-TEMPLATE-"].update(disabled=not is_enabled)
                elif event == "-TEMPLATE_CATEGORY-":
                    selected_category = values["-TEMPLATE_CATEGORY-"]

                    if selected_category == "随机分类":
                        templates = ["随机模板"]
                        self._window["-TEMPLATE-"].update(
                            values=templates, value="随机模板", disabled=False
                        )
                    else:
                        templates = PathManager.get_templates_by_category(selected_category)

                        if not templates:
                            sg.popup_error(
                                f"分类 『{selected_category}』 的模板数量为0，不可选择",
                                title="系统提示",
                                icon=utils.get_gui_icon(),
                                keep_on_top=True,
                            )
                            self._window["-TEMPLATE_CATEGORY-"].update(value="随机分类")
                            self._window["-TEMPLATE-"].update(
                                values=["随机模板"], value="随机模板", disabled=False
                            )
                        else:
                            template_options = ["随机模板"] + templates
                            self._window["-TEMPLATE-"].update(
                                values=template_options, value="随机模板", disabled=False
                            )

                    self._window.refresh()
                elif event == "-START_BTN-":
                    self._handle_start_button(values)
                elif event == "-STOP_BTN-":
                    self._handle_stop_button()
                elif event == "关于":
                    sg.popup(
                        "关于软件 AIWriteX",
                        f"当前版本 {__version___}",
                        "Copyright (C) 2025 iniwap,All Rights Reserved",
                        title="系统提示",
                        icon=utils.get_gui_icon(),
                        keep_on_top=True,
                    )
                elif event == "官网":
                    utils.open_url("https://github.com/iniwap/AIWriteX")
                elif event == "帮助":
                    sg.popup(
                        "———————————配置说明———————————\n"
                        "1、微信公众号AppID，AppSecrect必填（自动发布时）\n"
                        "2、CrewAI使用的API的API KEY必填（使用的）\n"
                        "3、AIForge的模型提供商的API KEY必填（使用的）\n"
                        "4、其他使用默认即可，根据需求填写\n"
                        "———————————操作说明———————————\n"
                        "1、打开配置界面，首先填写必要的配置\n"
                        "2、点击开始执行，AI自动开始工作\n"
                        "3、陆续加入更多操作中...\n"
                        "———————————功能说明———————————\n"
                        "1、配置->配置管理：打开配置编辑界面\n"
                        "2、发布->发布管理：打开文章管理界面\n"
                        "3、模板->模板管理：打开模板管理界面\n"
                        "4、日志->日志文件：查看日志\n"
                        "5、配置->CrewAI/AIForge：直接查看或编辑配置文件\n"
                        "6、部分界面内容，悬停会有提示",
                        title="使用帮助",
                        icon=utils.get_gui_icon(),
                        keep_on_top=True,
                    )
                elif event == "-SET_LOG_LIMIT-":
                    self._log_buffer = deque(self._log_buffer, maxlen=values["-LOG_LIMIT-"])
                    self._window["-STATUS-"].update(value="\n".join(self._log_buffer))
                elif event == "-CLEAR_LOG-":
                    self._log_buffer.clear()
                    self._window["-STATUS-"].update(value="")
                elif event in self._log_list:
                    if event == "更多...":
                        logs_path = os.path.abspath(PathManager.get_log_dir())
                        if sys.platform == "win32":
                            logs_path = logs_path.replace("/", "\\")
                        filename = sg.popup_get_file(
                            "打开文件",
                            default_path=logs_path,
                            file_types=(("log文件", "*.log"),),
                            initial_folder=logs_path,
                            no_window=True,
                            keep_on_top=True,
                        )
                        if not filename:
                            continue

                        try:
                            if sys.platform == "win32":
                                subprocess.run(["notepad", filename])
                            elif sys.platform == "darwin":  # macOS
                                subprocess.run(["open", "-a", "TextEdit", filename])
                            else:  # Linux
                                subprocess.run(["gedit", filename])
                        except Exception as e:
                            sg.popup(
                                "无法打开日志文件 :( \n错误信息：" + str(e),
                                title="系统提示",
                                icon=utils.get_gui_icon(),
                                keep_on_top=True,
                            )
                    else:
                        try:
                            log_file_path = os.path.join(PathManager.get_log_dir(), event)
                            if sys.platform == "win32":
                                subprocess.run(["notepad", log_file_path])
                            elif sys.platform == "darwin":  # macOS
                                subprocess.run(["open", "-a", "TextEdit", log_file_path])
                            else:  # Linux
                                subprocess.run(["gedit", log_file_path])
                        except Exception as e:
                            sg.popup(
                                "无法打开日志文件 :( \n错误信息：" + str(e),
                                title="系统提示",
                                icon=utils.get_gui_icon(),
                                keep_on_top=True,
                            )

                elif event == "文章管理":
                    ArticleManager.gui_start()
                elif event == "模板管理":
                    TemplateManager.gui_start()
                elif event in ["-TOPIC_INPUT-", "-URLS_INPUT-"]:
                    if sys.platform == "darwin" and values[event]:
                        self._window[event].update(utils.fix_mac_clipboard(values[event]))

                # 处理队列更新（非阻塞）
                self.process_queue()
        except KeyboardInterrupt:
            # 捕获Ctrl+C，优雅退出
            pass
        except Exception as e:
            # 记录其他异常但不显示给用户
            self._display_log(f"应用程序异常: {str(e)}", "error")
        finally:
            if self._is_running and self._crew_process and self._crew_process.is_alive():  # type: ignore # noqa 501
                self._crew_process.terminate()  # type: ignore
                self._crew_process.join(timeout=2.0)  # type: ignore
                if self._crew_process.is_alive():  # type: ignore
                    self._crew_process.kill()  # type: ignore

            # 等待监控线程结束
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=1.0)

            self._window.close()


def gui_start():
    """启动GUI应用程序入口"""
    try:
        MainGUI().run()
    except KeyboardInterrupt:
        # 捕获Ctrl+C，静默退出
        pass
    except Exception:
        # 对于其他异常，也静默处理以避免显示堆栈跟踪
        pass


if __name__ == "__main__":
    gui_start()
