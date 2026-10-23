# -*- coding: utf-8 -*-
"""
任务模块：记忆战场一键减负与快速通关 (Task Memorial Arena Sweep)
 (适配第二部全新 UI)：
1. 自动判定周常周期（周二 04:00 ~ 周日 23:00 开放，周一结算期安全跳过）；
2. 导航至 出击 -> 挑战分类 -> 记忆战场大厅；
3. 直接点击大厅右下角官方【战场减负】黄色大按钮，一键全自动秒级扫荡全部强敌至 SS 阶位并吃满挑战次数；
4. 自动打开左下角【挑战次数奖励】一键收取星石、远古意志与活跃度宝箱；
5. 安全返回舰桥主界面。
"""
import datetime
import time
from typing import Callable, Optional, Tuple
import numpy as np

from games.honkai3.core.ui_vision import Template, UIVision
from games.honkai3.core.page import (
    PageNavigator,
    PAGE_BATTLE,
    PAGE_ARENA,
    PAGE_MAIN,
    TPL_RETURN,
    TPL_HOME,
    TPL_CONFIRM,
    TPL_BATTLE_CHALLENGE_TAB,
    TPL_BATTLE_GOTO_ARENA,
)
from games.honkai3.core.popup import PopupHandler

# 第二部全新 UI 记忆战场专属模板与锚点
TPL_ARENA_SWEEP = Template("V2_ARENA_SWEEP_BTN.png", (0.203, 0.439), threshold=0.75)
TPL_ARENA_CARD = Template("V2_ARENA_CARD.png", (-0.055, 0.393), threshold=0.75)  # 出击页【记忆战场】卡片标题 (实测 0.942)
TPL_QUICK_CLAIM = Template("QUICK_CLAIM.png", (0.35, 0.38), threshold=0.75)


def run_arena_task(
    window_rect: Tuple[int, int, int, int],
    capture_func: Callable[[], np.ndarray],
    navigator: PageNavigator,
    vision: UIVision,
    popup_handler: Optional[PopupHandler] = None,
    log_func=None,
    is_stopped_func=None,
) -> bool:
    """
    执行记忆战场全新 UI 一键减负与奖励领取任务
    """
    if log_func:
        log_func("=== 开始执行【记忆战场一键减负与快速通关】 ===", "info")

    if is_stopped_func and is_stopped_func():
        return False

    # 1. 周期时间检查：周一为结算关闭期 (周二 04:00 开启)
    now = datetime.datetime.now()
    weekday = now.weekday()  # 0: 周一, 1: 周二, ..., 6: 周日
    if weekday == 0 or (weekday == 1 and now.hour < 4):
        if log_func:
            log_func("[!] 记忆战场周一处于结算关闭期（将于周二 04:00 开启），自动跳过本次减负。", "warning")
        return True

    # 2. 页面导航：前往记忆战场
    if log_func:
        log_func("[*] 正在导航前往【记忆战场】...", "info")

    # 识别式导航: 出击页首屏(推荐分类)直接显示【记忆战场】卡片, 优先点击卡片进入
    entered = False
    if not navigator.ui_goto(PAGE_BATTLE, window_rect, capture_func, log_func=log_func):
        if log_func:
            log_func("[!] 无法进入出击界面，记忆战场任务终止。", "warning")
        return False
    time.sleep(0.8)
    screen = capture_func()
    if screen is not None and vision.exists(screen, TPL_ARENA_CARD):
        if log_func:
            log_func("[+] 出击页已识别到【记忆战场】卡片，正在点击进入...", "success")
        entered = vision.click_template(window_rect, screen, TPL_ARENA_CARD, log_func=log_func)
        if entered:
            time.sleep(1.5)
    else:
        # 推荐页没有卡片时, 尝试切到挑战分类后再识别 (全程识别式, 无盲点)
        if screen is not None and vision.exists(screen, TPL_BATTLE_CHALLENGE_TAB):
            vision.click_template(window_rect, screen, TPL_BATTLE_CHALLENGE_TAB, log_func=log_func)
            time.sleep(1.2)
            screen = capture_func()
        if screen is not None and vision.exists(screen, TPL_ARENA_CARD):
            entered = vision.click_template(window_rect, screen, TPL_ARENA_CARD, log_func=log_func)
            if entered:
                time.sleep(1.5)
    if not entered:
        if log_func:
            log_func("[!] 未在出击页识别到【记忆战场】卡片 (可能处于结算期或UI变动)，安全跳过本任务。", "warning")
        return False

    # 活动卡片会随版本更换。点击后必须确认已到记忆战场大厅，
    # 否则禁止在其他活动页面尝试减负或领取。
    screen = capture_func()
    if screen is None or navigator.detect_current_page(screen) != PAGE_ARENA:
        if log_func:
            log_func("[!] 点击卡片后未识别到记忆战场大厅；停止本任务，避免在其他活动页面误触。", "warning")
        return False

    # 清除进场可能弹出的段位晋级/结算提示
    if popup_handler:
        popup_handler.handle_all_clear(window_rect, capture_func, log_func=log_func)

    # 3. 第二部全新 UI 核心：大厅直接触发【战场减负】(一键扫荡全部强敌至 SS 阶位)
    time.sleep(1.0)
    screen = capture_func()
    if screen is not None:
        swept = False
        if vision.exists(screen, TPL_ARENA_SWEEP):
            if log_func:
                log_func("[+] 检测到右下角【战场减负】黄色大按钮，正在触发全战场一键减负...", "success")
            swept = vision.click_template(window_rect, screen, TPL_ARENA_SWEEP, log_func=log_func)
        else:
            if log_func:
                log_func("[!] 未识别到【战场减负】按钮 (可能次数已用完或界面不符)，跳过扫荡步骤。", "warning")
            swept = False

        if swept:
            time.sleep(1.0)
            screen_dialog = capture_func()
            if screen_dialog is not None:
                if vision.exists(screen_dialog, TPL_CONFIRM):
                    if log_func:
                        log_func("[+] 正在确认一键减负弹窗...", "info")
                    vision.click_template(window_rect, screen_dialog, TPL_CONFIRM, log_func=log_func)
                    time.sleep(1.0)
                # 未识别到确认按钮则不做任何盲点动作

            # 再次消解可能出现的减负结算物品弹窗
            if popup_handler:
                popup_handler.handle_all_clear(window_rect, capture_func, log_func=log_func)
            if log_func:
                log_func("[★ 成功 ★] 记忆战场强敌一键减负已全部完成！", "success")

    # 4. 领取战场累计挑战次数奖励 (左下角宝箱，约 (-0.42, 0.33))
    if log_func:
        log_func("[*] 正在检查记忆战场【挑战次数奖励】与阶段宝箱...", "info")

    screen = capture_func()
    if screen is not None and vision.exists(screen, TPL_QUICK_CLAIM):
        # 仅当画面上已识别到奖励领取入口时才尝试
        time.sleep(0.5)
        screen_reward = capture_func()
        if screen_reward is not None:
            if vision.exists(screen_reward, TPL_QUICK_CLAIM):
                vision.click_template(window_rect, screen_reward, TPL_QUICK_CLAIM, log_func=log_func)
                time.sleep(0.8)
                if popup_handler:
                    popup_handler.handle_all_clear(window_rect, capture_func, log_func=log_func)
                if log_func:
                    log_func("√ 记忆战场累计挑战次数奖励已领取！", "success")
            # 点击上方空白关闭弹窗
            # 奖励弹窗若已自动关闭，无需在活动页面点击空白。

    # 5. 安全返回舰桥
    if log_func:
        log_func("[*] 记忆战场任务结束，安全返回舰桥主界面...", "info")
    time.sleep(0.5)
    return_screen = capture_func()
    if return_screen is not None:
        vision.click_template(window_rect, return_screen, TPL_HOME)

    if log_func:
        log_func("=== 【记忆战场一键减负】执行完毕 ===\n", "success")
    return True
