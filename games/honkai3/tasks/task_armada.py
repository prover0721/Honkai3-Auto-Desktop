# -*- coding: utf-8 -*-
"""
任务模块：舰团委托回收与奖池 (Task Armada Commission & Rewards)
：自动提交今日最多8次物资委托回收，放入奖励池，并收取舰团阶段奖励 (完美适配全新 UI)
"""
import time
from typing import Tuple, Callable
import numpy as np

from games.honkai3.core.ui_vision import Template, UIVision
from games.honkai3.core.page import (
    PageNavigator,
    PAGE_ARMADA,
    PAGE_COMMISSION,
    PAGE_ARMADA_REWARD,
    PAGE_MAIN,
    TPL_CONFIRM,
    TPL_RETURN,
    TPL_HOME,
)

# 第二部全新 UI 舰团专属模板与锚点
TPL_ARMADA_SUBMIT = Template("V2_ARMADA_SUBMIT_BTN.png", (0.22, 0.408), threshold=0.75)
TPL_ARMADA_REWARD_TAB = Template("V2_ARMADA_REWARD_TAB.png", (0.413, -0.139), threshold=0.75)
TPL_COMMISSION_CONFIRM = Template("COMMISSION_SUBMIT_CONFIRM.png", (0.135, 0.159), threshold=0.70)
TPL_COMMISSION_PUT = Template("COMMISSION_PUT.png", (0.0, 0.137), threshold=0.70)
TPL_ARMADA_REWARD_CLAIM = Template("ARMADA_REWARD_CLAIM.png", (0.212, 0.225), threshold=0.70)


def run_armada_task(
    window_rect: Tuple[int, int, int, int],
    capture_func: Callable[[], np.ndarray],
    navigator: PageNavigator,
    vision: UIVision,
    log_func=None,
    is_stopped_func=None,
) -> bool:
    """执行舰团委托提交与奖池领取 (适配第二部全新 UI)"""
    if log_func:
        log_func("[*] 正在执行【舰团委托回收与奖池】...", "info")

    if is_stopped_func and is_stopped_func():
        return False

    # 1. 导航进入舰团委托界面
    if not navigator.ui_goto(PAGE_COMMISSION, window_rect, capture_func, log_func=log_func):
        if log_func:
            log_func("[!] 无法进入舰团委托界面，可能未加入舰团或正在加载，跳过", "warning")
        return False

    time.sleep(1.0)

    # 2. 循环提交委托 (最多尝试 8 次)
    submitted_count = 0
    for round_idx in range(8):
        if is_stopped_func and is_stopped_func():
            return False

        screen = capture_func()
        if screen is None:
            time.sleep(0.5)
            continue

        # 检查是否存在【提交】按钮
        can_submit = False
        if vision.exists(screen, TPL_ARMADA_SUBMIT):
            can_submit = vision.click_template(window_rect, screen, TPL_ARMADA_SUBMIT, log_func=log_func)
            if not can_submit:
                return False

        if can_submit:
            time.sleep(0.6)
            screen_c = capture_func()
            if screen_c is not None:
                # 若有确认弹窗
                if vision.exists(screen_c, TPL_CONFIRM):
                    vision.click_template(window_rect, screen_c, TPL_CONFIRM)
                    time.sleep(0.5)
                elif vision.exists(screen_c, TPL_COMMISSION_CONFIRM):
                    vision.click_template(window_rect, screen_c, TPL_COMMISSION_CONFIRM)
                    time.sleep(0.5)

                screen_p = capture_func()
                if screen_p is not None and vision.exists(screen_p, TPL_COMMISSION_PUT):
                    vision.click_template(window_rect, screen_p, TPL_COMMISSION_PUT)
                    time.sleep(0.5)

            submitted_count += 1
            if log_func:
                log_func(f"[+] 已触发第 {submitted_count} 次舰团委托提交", "info")
            time.sleep(0.8)
            continue

        # 若未检测到提交按钮，说明今日 8 次已交满或材料不足
        break

    if log_func:
        log_func(f"[+] 舰团委托提交阶段结束，累计触发提交: {submitted_count} 次", "info")

    # 3. 切换至舰团奖池页签并领取奖励
    screen = capture_func()
    if screen is not None:
        if vision.exists(screen, TPL_ARMADA_REWARD_TAB):
            if log_func:
                log_func("[*] 正在切换至【舰团奖池】页签...", "info")
            if not vision.click_template(window_rect, screen, TPL_ARMADA_REWARD_TAB, log_func=log_func):
                return False
        else:
            if log_func:
                log_func("[!] 未识别到舰团奖池页签，跳过奖池领取，不使用旧坐标。", "warning")
            return navigator.ui_goto(PAGE_MAIN, window_rect, capture_func, log_func=log_func)
        time.sleep(1.0)

        screen_r = capture_func()
        if screen_r is not None:
            if vision.exists(screen_r, TPL_ARMADA_REWARD_CLAIM):
                if not vision.click_template(window_rect, screen_r, TPL_ARMADA_REWARD_CLAIM, log_func=log_func):
                    return False
                time.sleep(0.8)
            else:
                if log_func:
                    log_func("[*] 未识别到可领取的舰团奖池奖励，跳过领取。", "info")
                return navigator.ui_goto(PAGE_MAIN, window_rect, capture_func, log_func=log_func)

            screen_conf = capture_func()
            if screen_conf is not None and vision.exists(screen_conf, TPL_CONFIRM):
                vision.click_template(window_rect, screen_conf, TPL_CONFIRM)
            if log_func:
                log_func("[+] 舰团奖池领取入口已触发；仅对识别出的确认按钮执行点击。", "info")

    # 4. 返回主菜单
    time.sleep(0.5)
    return_screen = capture_func()
    if return_screen is None:
        return_screen = screen
    if return_screen is not None:
        vision.click_template(window_rect, return_screen, TPL_HOME)
    return True
