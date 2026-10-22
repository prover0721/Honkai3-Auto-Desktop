# -*- coding: utf-8 -*-
"""
任务执行器与后台调度线程
采用标准子进程隔离架构 (Process Isolation Architecture)
UI 仅作为无算力负担的管道监听器，具体的图像识别与任务逻辑在独立的 Python 子进程中运行，
彻底解决 UI 假死卡顿问题，并实现毫秒级一键强制终止能力。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import psutil
from PySide6.QtCore import QObject, QThread, Signal

from core.plugin_manager import plugin_manager
from games.honkai3.core import pause_gate

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


_active_honkai3_processes: List[subprocess.Popen] = []


def register_honkai3_process(proc: subprocess.Popen):
    """Register an active Honkai3 runner subprocess handle."""
    if proc not in _active_honkai3_processes:
        _active_honkai3_processes.append(proc)


def unregister_honkai3_process(proc: subprocess.Popen):
    """Unregister a finished Honkai3 runner subprocess handle."""
    if proc in _active_honkai3_processes:
        _active_honkai3_processes.remove(proc)


def _cleanup_dead_honkai3_processes():
    """Prune terminated processes from active handles list."""
    _active_honkai3_processes[:] = [p for p in _active_honkai3_processes if p.poll() is None]


def _honkai3_runner_processes():
    """Find automation runners for this project via active managed process handles (O(1))."""
    _cleanup_dead_honkai3_processes()
    matches = []
    for proc in _active_honkai3_processes:
        try:
            matches.append(psutil.Process(proc.pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return matches


def honkai3_automation_running() -> bool:
    """Instant O(1) check whether any Honkai3 runner subprocess is active."""
    _cleanup_dead_honkai3_processes()
    return bool(_active_honkai3_processes)


def pause_honkai3_automation() -> bool:
    """Pause every Honkai3 runner and close the shared input gate first."""
    runners = _honkai3_runner_processes()
    if not runners:
        return False
    suspended = []
    try:
        pause_gate.pause()
        for proc in runners:
            proc.suspend()
            suspended.append(proc)
        return True
    except (OSError, psutil.NoSuchProcess, psutil.AccessDenied):
        for proc in suspended:
            try:
                proc.resume()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass
        pause_gate.resume()
        return False


def resume_honkai3_automation() -> bool:
    """Resume every Honkai3 runner before opening the shared input gate."""
    resumed = True
    for proc in _honkai3_runner_processes():
        try:
            proc.resume()
        except psutil.NoSuchProcess:
            # A runner may finish between enumeration and resume.
            continue
        except (psutil.AccessDenied, OSError):
            resumed = False
    if resumed:
        pause_gate.resume()
    return resumed


def honkai3_automation_paused() -> bool:
    return pause_gate.is_paused()


class TaskSignals(QObject):
    """用于与 UI 主线程通信的 Qt 信号"""
    log_emitted = Signal(str, str, str)       # (game_id, log_text, level)
    task_status = Signal(str, str, str)       # (game_id, task_id, status: running/done/failed/idle)
    game_finished = Signal(str, bool, str)    # (game_id, success, summary)


class GameTaskWorker(QThread):
    """独立子进程任务监听工作器"""

    def __init__(self, game_id: str, task_ids: Optional[List[str]] = None):
        super().__init__()
        self.game_id = game_id
        self.task_ids = task_ids
        self.signals = TaskSignals()
        self._is_stopped = False
        self.proc: Optional[subprocess.Popen] = None
        self._finished_data = None

    def _kill_process(self):
        """利用 psutil 递归终止子进程树，实现操作系统级的秒级强杀"""
        if self.proc:
            if self.proc.poll() is None:
                pid = self.proc.pid
                try:
                    parent = psutil.Process(pid)
                    for child in parent.children(recursive=True):
                        try:
                            child.kill()
                        except Exception:
                            pass
                    parent.kill()
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass

    def stop(self):
        """用户点击【终止】时调用：立即标记并强杀子进程"""
        self._is_stopped = True
        # 只恢复本工作器以便终止；其他并行的崩坏3执行器仍保持暂停。
        if self.is_paused and self.proc and self.proc.poll() is None:
            try:
                psutil.Process(self.proc.pid).resume()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass
        self._kill_process()
        if self.game_id == "honkai3" and not honkai3_automation_running():
            pause_gate.resume()

    @property
    def is_paused(self) -> bool:
        return self.game_id == "honkai3" and honkai3_automation_paused()

    def pause(self) -> bool:
        """仅暂停崩坏3的自动化子进程，不暂停游戏客户端。"""
        if self.game_id != "honkai3":
            return False
        if self.is_paused:
            return True
        if not pause_honkai3_automation():
            return False
        self.log("[暂停] 所有崩坏3自动化执行已暂停；游戏客户端保持运行。", "warning")
        return True

    def resume(self, emit_log: bool = True) -> bool:
        """恢复已暂停的崩坏3自动化子进程。"""
        if self.game_id != "honkai3":
            return False
        if not resume_honkai3_automation():
            return False
        if emit_log:
            self.log("[继续] 崩坏3自动化执行已恢复。", "success")
        return True

    def log(self, text: str, level: str = "info"):
        self.signals.log_emitted.emit(self.game_id, str(text), level)

    def run(self):
        self._is_stopped = False
        self._finished_data = None

        plugin = plugin_manager.get_plugin(self.game_id)
        if not plugin:
            self.log(f"[错误] 未找到游戏分区: {self.game_id}", "error")
            self.signals.game_finished.emit(self.game_id, False, "未找到游戏分区")
            return

        cmd = [
            sys.executable,
            "-m",
            "core.cli_runner",
            "--game",
            self.game_id
        ]
        if self.task_ids:
            cmd.extend(["--tasks", ",".join(self.task_ids)])

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        # 上一轮若在暂停期间异常退出，清理无人持有的暂停态。
        if self.game_id == "honkai3" and not honkai3_automation_running():
            pause_gate.resume()

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                cwd=str(PROJECT_ROOT),
                env=env
            )
            if self.game_id == "honkai3":
                register_honkai3_process(self.proc)
        except Exception as e:
            self.log(f"[错误] 无法拉起任务子进程: {e}", "error")
            self.signals.game_finished.emit(self.game_id, False, "子进程启动失败")
            return

        try:
            # 实时逐行消费子进程输出流
            if self.proc.stdout:
                while not self._is_stopped:
                    try:
                        line = self.proc.stdout.readline()
                    except (ValueError, OSError):
                        break
                    if not line or self._is_stopped:
                        break

                    line_str = line.strip()
                    if not line_str:
                        continue

                    # 解析结构化 JSON 协议
                    if line_str.startswith("{") and line_str.endswith("}"):
                        try:
                            data = json.loads(line_str)
                            msg_type = data.get("_msg")
                            if msg_type == "log":
                                self.signals.log_emitted.emit(
                                    data.get("game_id", self.game_id),
                                    data.get("text", ""),
                                    data.get("level", "info")
                                )
                                continue
                            elif msg_type == "status":
                                self.signals.task_status.emit(
                                    data.get("game_id", self.game_id),
                                    data.get("task_id", ""),
                                    data.get("status", "running")
                                )
                                continue
                            elif msg_type == "finish":
                                self._finished_data = data
                                continue
                        except Exception:
                            pass

                    # 兜底：直接按普通文本推送到 UI 日志窗口
                    self.signals.log_emitted.emit(self.game_id, line_str, "info")

            # 若收到中断信号，确保彻底回收并通知 UI
            if self._is_stopped:
                self._kill_process()
                self.log("[!] 任务子进程已被用户强制终止。", "warning")
                self.signals.game_finished.emit(self.game_id, False, "用户已终止")
                return

            self.proc.wait()
            if self._finished_data:
                self.signals.game_finished.emit(
                    self._finished_data.get("game_id", self.game_id),
                    self._finished_data.get("success", False),
                    self._finished_data.get("summary", "执行结束")
                )
            else:
                is_ok = (self.proc.returncode == 0)
                desc = "全部完成" if is_ok else f"异常退出 (code: {self.proc.returncode})"
                self.signals.game_finished.emit(self.game_id, is_ok, desc)
        finally:
            if self.game_id == "honkai3" and self.proc:
                unregister_honkai3_process(self.proc)


class SequentialPipelineWorker(QThread):
    """顺序执行所有勾选游戏的一条龙中控线程 (基于子进程解耦)"""

    def __init__(self, game_ids: List[str]):
        super().__init__()
        self.game_ids = game_ids
        self.signals = TaskSignals()
        self._is_stopped = False
        self.current_worker: Optional[GameTaskWorker] = None

    def stop(self):
        self._is_stopped = True
        if self.current_worker:
            self.current_worker.stop()

    def run(self):
        self.signals.log_emitted.emit("pipeline", "=== 启动【全局一条龙】串行自动化流水线 ===", "info")
        for game_id in self.game_ids:
            if self._is_stopped:
                self.signals.log_emitted.emit("pipeline", "[!] 全局流水线已被用户终止", "warning")
                break

            plugin = plugin_manager.get_plugin(game_id)
            name = plugin.name if plugin else game_id
            self.signals.log_emitted.emit("pipeline", f"\n[串行调度] 准备运行下一分区: 【{name}】", "info")

            self.current_worker = GameTaskWorker(game_id)
            # 转发子进程产生的日志与任务状态至 UI
            self.current_worker.signals.log_emitted.connect(self.signals.log_emitted.emit)
            self.current_worker.signals.task_status.connect(self.signals.task_status.emit)
            self.current_worker.run()

            if self._is_stopped:
                break

            time.sleep(2)  # 分区切换缓冲 2 秒，以便操作系统完全释放显存与句柄

        self.signals.log_emitted.emit("pipeline", "=== 【全局一条龙】全部流程结束 ===\n", "success")
        self.signals.game_finished.emit("pipeline", True, "一条龙结束")
