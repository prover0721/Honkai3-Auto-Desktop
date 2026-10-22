# -*- coding: utf-8 -*-
"""
任务模块：每日使命600历练值宝箱与作战凭证 (Task Daily Missions & BP)
参考 Alas 规范：一键领取已达成的日常使命任务，依次领取阶段历练值宝箱（满额40水晶），并领取作战凭证升级奖励
"""
import time
from typing import Tuple, Callable
import numpy as np
from games.honkai3.core.daily_ui import stage_is_reached

from games.honkai3.core.ui_vision import Template, UIVision
from games.honkai3.core.page import (
    PageNavigator,
    PAGE_MISSION,
    PAGE_MAIN,
    TPL_CONFIRM,
    TPL_HOME,
    TPL_RETURN,
)

TPL_CLAIM_ALL = Template("V2_MISSION_CLAIM_ALL.png", (0.418, -0.331), rgb=True, threshold=0.85)
TPL_QUICK_CLAIM = Template("QUICK_CLAIM.png", (0.418, -0.187), threshold=0.75)
TPL_CLAIM_BTN = Template("V2_CLAIM_BTN.png", None, threshold=0.80)  # 黄色【领取】按钮 (全屏搜索, 实测 0.971)


def run_mission_task(
    window_rect: Tuple[int, int, int, int],
    capture_func: Callable[[], np.ndarray],
    navigator: PageNavigator,
    vision: UIVision,
    log_func=None,
    is_stopped_func=None,
) -> bool:
    """执行每日使命宝箱与作战凭证领取；只点击视觉确认可领取的宝箱。"""
    if log_func:
        log_func("[*] 正在执行【每日使命600历练值宝箱与作战凭证】...", "info")

    if is_stopped_func and is_stopped_func():
        return False

    # 1. 导航进入作战任务界面
    if not navigator.ui_goto(PAGE_MISSION, window_rect, capture_func, log_func=log_func):
        if log_func:
            log_func("[!] 无法进入任务界面", "warning")
        return False

    screen = capture_func()
    if screen is None or navigator.detect_current_page(screen) is not PAGE_MISSION:
        if log_func:
            log_func("[!] 当前画面未能确认为作战任务页；停止使命领取，避免错页点击。", "warning")
        return False

    time.sleep(1.2)
    screen = capture_func()

    # 2. 优先点击右上角【一键领取】清空全部已完成任务与历练值
    if screen is not None:
        if vision.exists(screen, TPL_CLAIM_ALL):
            if log_func:
                log_func("[+] 检测到右上角【一键领取】，正在一键清空全部使命任务与历练值...", "info")
            if not vision.click_template(window_rect, screen, TPL_CLAIM_ALL, log_func=log_func):
                return False
            time.sleep(1.0)
            # 消解获得物品弹窗
            screen_c = capture_func()
            if screen_c is not None and vision.exists(screen_c, TPL_CONFIRM):
                if not vision.click_template(window_rect, screen_c, TPL_CONFIRM):
                    return False
                time.sleep(0.6)

        # 2.1 逐个点击列表中的黄色【领取】按钮 (兜底: 一键领取可能不覆盖全部条目)
        for _ in range(6):
            if is_stopped_func and is_stopped_func():
                return False
            screen_r = capture_func()
            if screen_r is None:
                return False
            if navigator.detect_current_page(screen_r) is not PAGE_MISSION:
                if log_func:
                    log_func("[!] 领取弹窗后已离开作战任务页；停止后续使命点击。", "warning")
                return False
            if not vision.exists(screen_r, TPL_CLAIM_BTN):
                break
            if log_func:
                log_func("[+] 识别到【领取】按钮，正在点击...", "info")
            if not vision.click_template(window_rect, screen_r, TPL_CLAIM_BTN, log_func=log_func):
                return False
            time.sleep(0.8)
            screen_c = capture_func()
            if screen_c is not None and vision.exists(screen_c, TPL_CONFIRM):
                if not vision.click_template(window_rect, screen_c, TPL_CONFIRM):
                    return False
                time.sleep(0.5)

    # 3. 识别底栏 5 个阶段历练值宝箱 (100 -> 600)。
    # 这些模板对应未领取状态；模板匹配而非盲点坐标，可以跳过未达标/已领取的阶段。
    chest_templates = [
        ("100点宝箱", Template("DAILY_REWARD_100.png", (-0.100, 0.385), threshold=0.85)),
        ("200点宝箱", Template("DAILY_REWARD_200.png", (0.037, 0.385), threshold=0.85)),
        ("300点宝箱", Template("DAILY_REWARD_300.png", (0.175, 0.385), threshold=0.85)),
        ("450点宝箱", Template("DAILY_REWARD_450.png", (0.312, 0.385), threshold=0.85)),
        ("600点宝箱", Template("DAILY_REWARD_600.png", (0.450, 0.385), threshold=0.85)),
    ]

    claimed_chests = 0
    skipped_chests = 0
    for name, chest_template in chest_templates:
        if is_stopped_func and is_stopped_func():
            return False

        screen = capture_func()
        if screen is None or navigator.detect_current_page(screen) is not PAGE_MISSION:
            if log_func:
                log_func("[!] 宝箱检查时已离开作战任务页；停止领取。", "warning")
            return False

        chest_template.roi_margin = (0.04, 0.05)
        chest_match = vision.match(screen, chest_template)
        if not chest_match or not stage_is_reached(screen, chest_match):
            skipped_chests += 1
            if log_func:
                log_func(f"[*] 未检测到可领取的{name}（未达标或已领取），跳过。", "info")
            continue

        if not vision.click_template(window_rect, screen, chest_template, log_func=log_func):
            if log_func:
                log_func(f"[!] {name}识别后点击未执行，停止后续宝箱操作。", "warning")
            return False
        time.sleep(0.5)
        screen_c = capture_func()
        if screen_c is not None and vision.exists(screen_c, TPL_CONFIRM):
            if not vision.click_template(window_rect, screen_c, TPL_CONFIRM):
                return False
            time.sleep(0.5)
        claimed_chests += 1

    if log_func:
        log_func(
            f"[+] 每日使命阶段宝箱处理结束：识别并点击 {claimed_chests} 个，跳过 {skipped_chests} 个。"
            "是否达到600历练值以游戏内进度为准。",
            "success",
        )

    # 4. 返回主界面
    time.sleep(0.5)
    return_screen = capture_func()
    if return_screen is None:
        return False
    if return_screen is not None:
        vision.click_template(window_rect, return_screen, TPL_HOME)
    return navigator.ui_goto(PAGE_MAIN, window_rect, capture_func, log_func=log_func)
