"""从主界面进入出击中的材料远征，减负后回任务页领奖。"""
import time
from games.honkai3.core.ui_vision import Template
from games.honkai3.core.page import (
    PAGE_MAIN, PAGE_BATTLE, PAGE_MATERIAL, TPL_RECOMMEND_SELECTED, TPL_RECOMMEND_TAB,
    TPL_BATTLE_GOTO_LITE,
)
from games.honkai3.core.daily_ui import (
    confirm_and_wait, TPL_SWEEP_DIALOG, TPL_SWEEP_CONFIRM,
    reward_dialog_visible, TPL_REWARD_DIALOG, TPL_REWARD_CONFIRM,
)

TPL_MATL_LITE = Template("V2_MATL_LITE_BTN.png", (0.398, 0.430), rgb=True, threshold=0.85)

def run_sweep_task(window_rect, capture_func, navigator, vision, log_func=None, is_stopped_func=None):
    if is_stopped_func and is_stopped_func():
        return False
    screen = capture_func()
    if screen is not None and reward_dialog_visible(screen, vision):
        if not confirm_and_wait(window_rect, capture_func, navigator, vision,
                                TPL_REWARD_DIALOG, TPL_REWARD_CONFIRM, PAGE_MATERIAL,
                                log_func, is_stopped_func):
            return False
        return navigator.ui_goto(PAGE_MAIN, window_rect, capture_func, log_func=log_func)
    pending = screen is not None and vision.exists(screen, TPL_SWEEP_DIALOG)
    if not pending and navigator.detect_current_page(screen) is not PAGE_MATERIAL:
        # 游戏记忆上次分类；统一在推荐分类进入材料远征。
        if navigator.detect_current_page(screen) is not PAGE_BATTLE:
            if not navigator.ui_goto(PAGE_BATTLE, window_rect, capture_func, log_func=log_func):
                if log_func:
                    log_func("[!] 未能从主界面进入出击入口。", "warning")
                return False
            screen = capture_func()
        if screen is None or navigator.detect_current_page(screen) is not PAGE_BATTLE:
            return False

        # 即使出击分类已有材料入口，也必须按用户要求先切换到推荐。
        if not vision.exists(screen, TPL_RECOMMEND_SELECTED):
            if not vision.exists(screen, TPL_RECOMMEND_TAB):
                if log_func:
                    log_func("[!] 推荐标签未识别到，停止以避免误点其它入口。", "warning")
                return False
            if not vision.click_template(window_rect, screen, TPL_RECOMMEND_TAB, log_func=log_func):
                return False
            sortie_ready = False
            for _ in range(12):
                time.sleep(0.25)
                screen = capture_func()
                if (screen is not None and vision.exists(screen, TPL_RECOMMEND_SELECTED)
                        and vision.exists(screen, TPL_BATTLE_GOTO_LITE)):
                    sortie_ready = True
                    break
                if is_stopped_func and is_stopped_func():
                    return False
            if not sortie_ready:
                if log_func:
                    log_func("[!] 切换推荐后未确认推荐选中及材料远征入口，安全停止。", "warning")
                return False

        if not navigator.ui_goto(PAGE_MATERIAL, window_rect, capture_func, log_func=log_func):
            if log_func:
                    log_func("[!] 已进入推荐分类，但未能打开材料远征。", "warning")
            return False
        # 导航成功以页面重新识别为准，不能在过渡帧使用旧截图点击。
        screen = capture_func()
    if not pending:
        if screen is None or navigator.detect_current_page(screen) is not PAGE_MATERIAL:
            return False
        if not vision.click_template(window_rect, screen, TPL_MATL_LITE, log_func=log_func):
            if log_func:
                log_func("[!] 材料活动页未识别到可用的一键减负，安全停止。", "warning")
            return False
    if not confirm_and_wait(window_rect, capture_func, navigator, vision, TPL_SWEEP_DIALOG,
                            TPL_SWEEP_CONFIRM, PAGE_MATERIAL, log_func, is_stopped_func):
        return False
    if not navigator.ui_goto(PAGE_MAIN, window_rect, capture_func, log_func=log_func):
        return False
    if log_func:
        log_func("[★ 成功 ★] 材料远征减负完成并已返回主界面；使命奖励将由后续任务统一领取。", "success")
    return True
