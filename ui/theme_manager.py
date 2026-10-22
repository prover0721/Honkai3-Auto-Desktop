# -*- coding: utf-8 -*-
"""
GameHub 主题与时间自适应管理器
支持:
1. 亮色模式 (白色背景)
2. 暗色模式 (黑色背景)
3. 跟随时间自适应调节 (07:00 ~ 19:00 白天亮色, 19:00 ~ 07:00 夜间暗色)
4. 跟随 Windows 系统外观
"""
import datetime
import json
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from qfluentwidgets import Theme, isDarkTheme, setTheme

SETTINGS_FILE = Path(__file__).parent / "ui_settings.json"


class ThemeMode:
    LIGHT = "light"
    DARK = "dark"
    TIME_AUTO = "time_auto"
    SYSTEM = "system"


class ThemeManager(QObject):
    # 信号通知所有页面控制台和界面元素更新配色: 参数 is_dark (bool)
    theme_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.current_mode = self.load_mode()
        self._last_applied_is_dark = None

    def load_mode(self) -> str:
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("theme_mode", ThemeMode.LIGHT)
            except Exception:
                pass
        return ThemeMode.LIGHT

    def save_mode(self, mode: str):
        self.current_mode = mode
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"theme_mode": mode}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ThemeManager] 保存主题设置失败: {e}")

    def get_time_status_text(self) -> str:
        now = datetime.datetime.now()
        hour = now.hour
        is_day = 7 <= hour < 19
        status = "白天时段 (应用亮色白色外观)" if is_day else "夜间时段 (应用暗色护眼外观)"
        return f"当前系统时间 {now.strftime('%H:%M')}，处于{status}"

    def check_and_apply(self, mode: str = None):
        if mode:
            self.save_mode(mode)
        else:
            mode = self.current_mode

        target_dark = False

        if mode == ThemeMode.LIGHT:
            setTheme(Theme.LIGHT)
            target_dark = False
        elif mode == ThemeMode.DARK:
            setTheme(Theme.DARK)
            target_dark = True
        elif mode == ThemeMode.SYSTEM:
            setTheme(Theme.AUTO)
            target_dark = isDarkTheme()
        elif mode == ThemeMode.TIME_AUTO:
            hour = datetime.datetime.now().hour
            is_day = 7 <= hour < 19
            if is_day:
                setTheme(Theme.LIGHT)
                target_dark = False
            else:
                setTheme(Theme.DARK)
                target_dark = True

        if self._last_applied_is_dark != target_dark:
            self._last_applied_is_dark = target_dark
            self.theme_changed.emit(target_dark)


theme_manager = ThemeManager()
