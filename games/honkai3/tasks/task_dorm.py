# -*- coding: utf-8 -*-
"""
任务模块：家园金币、体力提取与打工 (Task Dorm Bonus & Errands)
：收取家园累积金币与溢出体能，一键收取昨日打工奖励并委派今日最优女武神
"""
import time
from typing import Tuple, Callable
import numpy as np

from games.honkai3.core.ui_vision import Template, UIVision
from games.honkai3.core.popup import TPL_ERRAND_CONFIRM_TITLE
from games.honkai3.core.page import (
    PageNavigator,
    PAGE_DORM,
    PAGE_ERRAND,
    PAGE_MAIN,
    TPL_CONFIRM,
    TPL_HOME,
    TPL_RETURN,
)

TPL_DORM_GOLD = Template("V2_DORM_GOLD.png", (-0.227, -0.170), threshold=0.75)
TPL_DORM_STAMINA = Template("V2_DORM_STAMINA.png", (-0.350, -0.152), threshold=0.75)
TPL_CLAIM_STAMINA = Template("CLAIM_STAMINA.png", (0.092, 0.156), threshold=0.70)
TPL_DORM_STAMINA_CLOSE = Template("DORM_STAMINA_CLOSE.png", (0.349, -0.181), threshold=0.70)

TPL_ERRAND_CLAIM = Template("V2_ERRAND_CLAIM.png", (0.398, 0.448), threshold=0.75)
TPL_ERRAND_DISPATCH = Template("V2_ERRAND_DISPATCH.png", (0.267, 0.448), threshold=0.75)
TPL_ERRAND_CONFIRM_DISPATCH = Template("QUICK_ERRAND_CONFIRM.png", (0.141, 0.363), threshold=0.85)


def finish_errand_dispatch(window_rect, capture_func, vision, log_func=None,
                           is_stopped_func=None, require_confirmation=False):
    """处理打工专属确认层，且仅在新截图确认该层消失后继续。"""
    clicked = False
    for _ in range(8):
        if is_stopped_func and is_stopped_func():
            return False
        screen = capture_func()
        if screen is None:
            time.sleep(0.5)
            continue
        if not vision.exists(screen, TPL_ERRAND_CONFIRM_TITLE):
            if clicked or not require_confirmation:
                return True
        elif not clicked:
            if vision.click_template(window_rect, screen, TPL_ERRAND_CONFIRM_DISPATCH, log_func=log_func):
                clicked = True
                if log_func:
                    log_func("[+] 已确认【一键打工】，等待打工确认层关闭...", "info")
        time.sleep(0.5)
    if log_func:
        log_func("[!] 未能确认打工弹窗已处理，停止家园任务，保留现场供检查。", "warning")
    return False


def run_dorm_task(
    window_rect: Tuple[int, int, int, int],
    capture_func: Callable[[], np.ndarray],
    navigator: PageNavigator,
    vision: UIVision,
    log_func=None,
    is_stopped_func=None,
) -> bool:
    """执行家园金币收取、体力提取与一键打工（仅操作已识别控件）。"""
    if log_func:
        log_func("[*] 正在执行【家园福利与打工委派】...", "info")

    if is_stopped_func and is_stopped_func():
        return False

    # 允许从上一次卡住的确认弹窗恢复，处理完成后才导航。
    if not finish_errand_dispatch(window_rect, capture_func, vision, log_func, is_stopped_func):
        return False

    # 1. 导航到家园主界面
    if not navigator.ui_goto(PAGE_DORM, window_rect, capture_func, log_func=log_func):
        if log_func:
            log_func("[!] 导航至家园界面失败；为避免坐标误触，家园任务安全终止。", "warning")
        return False

    time.sleep(1.2)
    screen = capture_func()

    # 2. 收取家园金币 (金色胶囊)
    if screen is not None:
        if vision.exists(screen, TPL_DORM_GOLD):
            if log_func:
                log_func("[+] 检测到家园金币已产出，正在一键收取...", "info")
            if not vision.click_template(window_rect, screen, TPL_DORM_GOLD, log_func=log_func):
                return False
        elif log_func:
            log_func("[*] 未识别到家园金币胶囊，跳过收取，不执行坐标兜底。", "info")
        time.sleep(0.8)

    # 3. 提取体能存储罐溢出体力 (蓝色胶囊)
    screen = capture_func()
    if screen is not None:
        stamina_clicked = False
        if vision.exists(screen, TPL_DORM_STAMINA):
            if log_func:
                log_func("[+] 正在点击体能存储胶囊提取溢出体力...", "info")
            stamina_clicked = vision.click_template(
                window_rect, screen, TPL_DORM_STAMINA, log_func=log_func
            )
        elif log_func:
            log_func("[*] 未识别到体能存储胶囊，跳过提取，不执行坐标兜底。", "info")

        if vision.exists(screen, TPL_DORM_STAMINA) and not stamina_clicked:
            return False

        if stamina_clicked:
            time.sleep(0.8)
            # 若弹出提取确认，只点击真实识别到的确认按钮。
            screen_stamina = capture_func()
            if screen_stamina is not None and vision.exists(screen_stamina, TPL_CLAIM_STAMINA):
                vision.click_template(
                    window_rect, screen_stamina, TPL_CLAIM_STAMINA, log_func=log_func
                )
                time.sleep(0.6)

            # 旧实现会无条件点击 (85%W, 32%H) 关闭弹窗；该位置在当前家园布局
            # 会命中【神之键】场景热区。现在只允许识别到关闭按钮后点击。
            screen_stamina = capture_func()
            if screen_stamina is not None and vision.exists(screen_stamina, TPL_DORM_STAMINA_CLOSE):
                vision.click_template(
                    window_rect, screen_stamina, TPL_DORM_STAMINA_CLOSE, log_func=log_func
                )
                time.sleep(0.6)

    # 4. 进入打工界面 (点击家园底栏“打工”)
    if not navigator.ui_goto(PAGE_ERRAND, window_rect, capture_func, log_func=log_func):
        if log_func:
            log_func("[!] 无法进入家园打工界面", "warning")
        return False

    time.sleep(1.2)

    # 5. 收取已完成的打工奖励 (右下角【领取奖励】)
    screen = capture_func()
    if screen is not None:
        if vision.exists(screen, TPL_ERRAND_CLAIM):
            if log_func:
                log_func("[+] 正在一键收取昨日家园打工完成奖励...", "info")
            if not vision.click_template(window_rect, screen, TPL_ERRAND_CLAIM, log_func=log_func):
                return False
        elif log_func:
            log_func("[*] 当前没有可领取的家园打工奖励（可能尚未到完成时间或已领取），安全跳过；继续检查今日派遣。", "info")
        time.sleep(0.8)
        screen_conf = capture_func()
        if screen_conf is not None and vision.exists(screen_conf, TPL_CONFIRM):
            if not vision.click_template(window_rect, screen_conf, TPL_CONFIRM):
                return False
        time.sleep(0.8)

    # 6. 一键委派今日打工 (右下角【一键打工】)
    screen = capture_func()
    if screen is not None:
        if vision.exists(screen, TPL_ERRAND_DISPATCH):
            if log_func:
                log_func("[+] 正在执行今日女武神【一键打工】委派...", "info")
            if not vision.click_template(window_rect, screen, TPL_ERRAND_DISPATCH, log_func=log_func):
                return False
            if not finish_errand_dispatch(
                window_rect, capture_func, vision, log_func, is_stopped_func,
                require_confirmation=True,
            ):
                return False
        else:
            if navigator.detect_current_page(screen) is PAGE_ERRAND:
                if log_func:
                    log_func("[*] 当前处于打工页面，未检测到可派发项目（女武神已全部处于打工中），平滑完成打工流程。", "info")
            else:
                if log_func:
                    log_func("[!] 未识别到一键打工按钮且画面偏离打工页，安全停止。", "warning")
                return False
        time.sleep(1.0)

        # 若弹出确定或 S+ 提示
        for _ in range(2):
            screen_c = capture_func()
            if screen_c is None:
                break
            if vision.exists(screen_c, TPL_CONFIRM):
                if not vision.click_template(window_rect, screen_c, TPL_CONFIRM):
                    return False
                time.sleep(0.6)
            else:
                break

    if log_func:
        log_func("[+] 家园流程执行结束；仅执行了视觉确认成功的操作。", "success")

    # 留在家园，让下一步远征从家园底栏直接进入，避免多余的主页往返。
    time.sleep(0.5)
    return navigator.ui_goto(PAGE_DORM, window_rect, capture_func, log_func=log_func)
