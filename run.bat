@echo off
chcp 65001 >nul
title 崩坏3 全自动管家

cd /d "%~dp0"

echo ========================================================
echo     崩坏3 全自动管家 (Honkai3 Auto Desktop)
echo ========================================================
echo.

where uv >nul 2>nul
if %errorlevel% equ 0 (
    echo [*] 检测到 uv 包管理器，正在启动客户端...
    uv run python main.py
    goto end
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    echo [*] 正在启动客户端...
    python main.py
    goto end
)

echo [错误] 未在系统 PATH 中找到 Python 或 uv 环境，请先安装 Python 3.10+ 并勾选 Add to PATH。
pause

:end
