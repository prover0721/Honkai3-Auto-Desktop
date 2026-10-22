# -*- coding: utf-8 -*-
"""
二游自动化可视化总控平台 (GameHub) 主启动入口
"""
import sys
import os
import ctypes
import traceback
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
os.chdir(str(ROOT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 设置标准输入输出编码为 UTF-8，防止控制台中文乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def check_admin_privileges():
    """
    检查当前进程是否具备管理员权限；
    若未具备且未指定 --no-admin，则通过 Windows ShellExecuteW ("runas") 自动请求提权启动
    确保工具链具备穿透 UIPI 的全局窗口交互能力，用户开箱即用无需手动提权
    """
    if "--no-admin" in sys.argv:
        return

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False

    if not is_admin:
        script = os.path.abspath(sys.argv[0])
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{script}" {params}'.strip(), str(ROOT_DIR), 1
            )
            if ret > 32:
                sys.exit(0)
        except Exception as e:
            print(f"[提示] 请求管理员提权未通过: {e}")


if __name__ == "__main__":
    try:
        check_admin_privileges()
        from ui.fluent_app import launch_app
        launch_app()
    except Exception as e:
        err_msg = f"GameHub 启动失败或运行遇到严重异常:\n\n{traceback.format_exc()}"
        print(err_msg, file=sys.stderr)
        try:
            ctypes.windll.user32.MessageBoxW(0, err_msg, "GameHub 错误提示", 0x10)
        except Exception:
            pass
        sys.exit(1)
