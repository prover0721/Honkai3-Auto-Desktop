# -*- coding: utf-8 -*-
"""
任务模块：邮件一键清理 (Task Mail Claim)
参考 Alas 规范：自动进入邮件列表，一键收取系统补偿、活动赠礼与日常奖励邮件
"""
import time
from typing import Tuple, Callable
import numpy as np

from games.honkai3.core.ui_vision import Template, UIVision
from games.honkai3.core.page import (
    PageNavigator,
    PAGE_MAIL,
    PAGE_MAIN,
    TPL_CONFIRM,
    TPL_HOME,
    TPL_RETURN,
)

TPL_MAIL_CLAIM = Template("QUICK_CLAIM.png", (0.418, 0.23), threshold=0.72)


def run_mail_task(
    window_rect: Tuple[int, int, int, int],
    capture_func: Callable[[], np.ndarray],
    navigator: PageNavigator,
    vision: UIVision,
    log_func=None,
    is_stopped_func=None,
) -> bool:
    """执行邮件一键清理任务"""
    if log_func:
        log_func("[*] 正在执行【邮件一键清理】...", "info")

    if is_stopped_func and is_stopped_func():
        return False

    # 1. 导航进入邮件页面
    if not navigator.ui_goto(PAGE_MAIL, window_rect, capture_func, log_func=log_func):
        if log_func:
            log_func("[!] 无法进入邮件界面，跳过", "warning")
        return True

    time.sleep(1.2)
    screen = capture_func()

    # 2. 检查是否有未领取的邮件并一键收取
    if screen is not None and vision.exists(screen, TPL_MAIL_CLAIM):
        if log_func:
            log_func("[+] 正在一键收取未读邮件道具与补偿...", "info")
        vision.click_template(window_rect, screen, TPL_MAIL_CLAIM, log_func=log_func)
        time.sleep(0.8)
        screen_c = capture_func()
        if screen_c is not None and vision.exists(screen_c, TPL_CONFIRM):
            vision.click_template(window_rect, screen_c, TPL_CONFIRM)
        if log_func:
            log_func("[★ 成功 ★] 邮件已全部清理完毕！", "success")
    else:
        if log_func:
            log_func("[+] 暂无待领取的邮件奖励", "info")

    # 3. 返回主菜单
    vision.click_template(window_rect, capture_func(), TPL_RETURN)
    return True
