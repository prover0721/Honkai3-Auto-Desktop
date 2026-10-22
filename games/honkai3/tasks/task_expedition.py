"""远征领取、专用派遣确认和返回主界面。"""
import time
from games.honkai3.core.ui_vision import Template
from games.honkai3.core.page import PAGE_EXPEDITION, PAGE_MAIN
from games.honkai3.core.daily_ui import (
    confirm_and_wait,
    reward_dialog_visible,
    TPL_EXPEDITION_DIALOG,
    TPL_EXPEDITION_SEND,
    TPL_REWARD_DIALOG,
    TPL_REWARD_CONFIRM,
)

TPL_EXPEDITION_FINISH = Template("V2_EXPEDITION_FINISH.png", threshold=0.85)
TPL_EXPEDITION_ONEKEY = Template("V2_EXPEDITION_ONEKEY.png", (0.389, 0.439), rgb=True, threshold=0.85)

def run_expedition_task(window_rect, capture_func, navigator, vision, log_func=None, is_stopped_func=None):
    def confirm_reward():
        """奖励弹窗未确认并验证远征页前，绝不允许导航点击背景。"""
        if log_func:
            log_func("[*] 等待远征奖励弹窗并点击【确定】；确认前不会离开远征页。", "info")
        return confirm_and_wait(
            window_rect, capture_func, navigator, vision,
            TPL_REWARD_DIALOG, TPL_REWARD_CONFIRM, PAGE_EXPEDITION,
            log_func, is_stopped_func,
        )

    screen = capture_func()
    # 上次停留在领奖弹窗时，也必须先确认；不能把它交给通用导航恢复。
    if screen is not None and reward_dialog_visible(screen, vision):
        if not confirm_reward():
            return False
        screen = capture_func()
    if screen is not None and vision.exists(screen, TPL_EXPEDITION_DIALOG):
        if not confirm_and_wait(window_rect, capture_func, navigator, vision, TPL_EXPEDITION_DIALOG,
                                TPL_EXPEDITION_SEND, PAGE_EXPEDITION, log_func, is_stopped_func):
            return False
        return navigator.ui_goto(PAGE_MAIN, window_rect, capture_func, log_func=log_func)
    if navigator.detect_current_page(screen) is not PAGE_EXPEDITION and not navigator.ui_goto(
        PAGE_EXPEDITION, window_rect, capture_func, log_func=log_func
    ):
        return False

    dispatched = False
    idle_frames = 0
    for _ in range(36):
        if is_stopped_func and is_stopped_func():
            return False
        screen = capture_func()
        if screen is None:
            time.sleep(0.5)
            continue
        # 奖励弹窗是模态层。先按专用标题和【确定】闭环处理；识别/点击/回页任一步
        # 失败都立刻停止，不能继续识别底层的一键远征或主菜单入口。
        if reward_dialog_visible(screen, vision):
            if not confirm_reward():
                return False
            idle_frames = 0
            continue

        page = navigator.detect_current_page(screen)
        if page is None:  # 动画或加载过渡帧，等待新截图
            time.sleep(0.5)
            continue
        if page is not PAGE_EXPEDITION:
            if log_func:
                log_func("[!] 领取奖励后页面不是远征页，停止后续操作。", "warning")
            return False

        if vision.exists(screen, TPL_EXPEDITION_FINISH):
            if not vision.click_template(window_rect, screen, TPL_EXPEDITION_FINISH, log_func=log_func):
                return False
            # 点【完成远征】后必须等到奖励弹窗、点击确定、并重新识别远征页。
            # confirm_and_wait 超时或弹窗按钮未命中时熔断，不允许落到主菜单导航。
            if not confirm_reward():
                return False
            idle_frames = 0
            continue

        if vision.exists(screen, TPL_EXPEDITION_ONEKEY):
            if not vision.click_template(window_rect, screen, TPL_EXPEDITION_ONEKEY, log_func=log_func):
                return False
            if not confirm_and_wait(window_rect, capture_func, navigator, vision, TPL_EXPEDITION_DIALOG,
                                    TPL_EXPEDITION_SEND, PAGE_EXPEDITION, log_func, is_stopped_func):
                return False
            dispatched = True
            break

        # 等待列表/按钮稳定，连续多帧无按钮才判断无法派遣。
        idle_frames += 1
        if idle_frames >= 4:
            if navigator.detect_current_page(screen) is PAGE_EXPEDITION:
                if log_func:
                    log_func("[*] 当前处于远征页面，未检测到可派遣项目（远征已全部派出或体力不足），正常结束远征。", "info")
                dispatched = True
                break
            else:
                if log_func:
                    log_func("[!] 远征页已偏离且未识别到一键远征按钮，安全停止。", "warning")
                return False
        time.sleep(0.5)

    if not dispatched:
        if log_func:
            log_func("[!] 等待远征派遣入口超时，停止后续日常。", "warning")
        return False
    return navigator.ui_goto(PAGE_MAIN, window_rect, capture_func, log_func=log_func)
