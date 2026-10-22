# -*- coding: utf-8 -*-
"""
GameHub 独立子进程任务执行器 (Headless CLI Runner)
负责在独立进程中加载各游戏分区插件并执行自动化日常任务。
通过 stdout 发送结构化 JSON 控制协议，实现与 UI 主进程的物理级进程隔离与防卡死解耦。
"""
import argparse
import json
import os
import signal
import sys
from pathlib import Path

# 确保项目根目录加入模块搜索路径
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 强制 stdout 与 stderr 为 UTF-8 编码与无缓冲
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from core.plugin_manager import plugin_manager


def emit_log(game_id: str, text: str, level: str = "info"):
    """向标准输出发送日志消息 (JSON 格式)"""
    payload = {
        "_msg": "log",
        "game_id": game_id,
        "text": str(text),
        "level": level
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def emit_status(game_id: str, task_id: str, status: str):
    """向标准输出发送任务状态变更 (JSON 格式)"""
    payload = {
        "_msg": "status",
        "game_id": game_id,
        "task_id": task_id,
        "status": status
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def emit_finish(game_id: str, success: bool, summary: str):
    """向标准输出发送任务完成状态 (JSON 格式)"""
    payload = {
        "_msg": "finish",
        "game_id": game_id,
        "success": success,
        "summary": summary
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)


_is_interrupted = False


def _signal_handler(signum, frame):
    global _is_interrupted
    _is_interrupted = True


# 注册中断信号
try:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
except Exception:
    pass


def main():
    parser = argparse.ArgumentParser(description="GameHub Headless CLI Task Runner")
    parser.add_argument("--game", required=True, help="目标游戏分区 ID (例如: honkai3)")
    parser.add_argument("--tasks", default="", help="执行的任务 ID 列表，以逗号分隔 (例如: auto_login,daily_sweep)")
    parser.add_argument("--config", default="", help="可选覆盖配置 (JSON 字符串或 JSON 文件路径)")

    args = parser.parse_args()
    game_id = args.game

    plugin = plugin_manager.get_plugin(game_id)
    if not plugin:
        emit_log(game_id, f"[错误] 未找到游戏分区: {game_id}", "error")
        emit_finish(game_id, False, "未找到游戏分区")
        sys.exit(1)

    runner_module = plugin.get_runner_module()
    if not runner_module:
        emit_log(game_id, f"[错误] 游戏分区【{plugin.name}】缺少 runner.py 执行入口", "error")
        emit_finish(game_id, False, "缺少执行入口")
        sys.exit(1)

    # 确定待执行的任务列表
    tasks_to_run = []
    if args.tasks.strip():
        req_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
        tasks_to_run = [t for t in plugin.tasks if t.get("id") in req_ids]
    else:
        tasks_to_run = [t for t in plugin.tasks if t.get("enabled", True)]

    if not tasks_to_run:
        emit_log(game_id, f"[*] 游戏【{plugin.name}】没有已启用的任务，跳过执行。", "warning")
        emit_finish(game_id, True, "无任务需执行")
        sys.exit(0)

    emit_log(game_id, f"=== [独立子进程] 开始执行【{plugin.name}】自动化任务 (PID: {os.getpid()}) ===", "info")
    overall_success = True

    for task in tasks_to_run:
        if game_id == "honkai3":
            from games.honkai3.core.pause_gate import wait_until_resumed
            wait_until_resumed()
        if _is_interrupted:
            emit_log(game_id, "[!] 收到进程终止信号，自动化任务已提前退出。", "warning")
            overall_success = False
            break

        task_id = task.get("id", "")
        task_name = task.get("name", task_id)
        emit_status(game_id, task_id, "running")
        emit_log(game_id, f"--> [正在执行] {task_name}...", "info")

        success = False
        try:
            success = runner_module.run_task(
                task_id=task_id,
                config=plugin.config,
                log_func=lambda txt, lvl="info": emit_log(game_id, txt, lvl),
                is_stopped_func=lambda: _is_interrupted
            )
            if success:
                emit_status(game_id, task_id, "done")
                emit_log(game_id, f"√ [{task_name}] 执行完成", "success")
            else:
                emit_status(game_id, task_id, "failed")
                emit_log(game_id, f"× [{task_name}] 执行失败", "error")
                overall_success = False
        except Exception as e:
            import traceback
            emit_status(game_id, task_id, "failed")
            emit_log(game_id, f"× [{task_name}] 抛出异常: {e}\n{traceback.format_exc()}", "error")
            overall_success = False


        if (not success and game_id == "honkai3"):
            emit_log(game_id, "[停止] 当前崩坏3任务未确认完成，本轮后续任务停止，保留当前游戏画面供排查。", "error")
            break

    status_desc = "全部完成" if overall_success else "部分失败"
    emit_log(game_id, f"=== 【{plugin.name}】子进程任务执行结束 ({status_desc}) ===\n", "info")
    emit_finish(game_id, overall_success, status_desc)
    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
