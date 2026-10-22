"""2026-10 screenshot-calibrated daily UI and confirmed modal transitions."""
import time
import cv2
from games.honkai3.core.ui_vision import Template, to_bgr

TPL_ERRAND_MAP = Template('V3_ERRAND_MAP_FLAG.png', (-0.107, -0.460), threshold=0.85)
TPL_EXPEDITION_PAGE = Template('V3_EXPEDITION_FLAG.png', (-0.363, -0.324), threshold=0.85)
TPL_EXPEDITION_DIALOG = Template('V3_EXPEDITION_DISPATCH_TITLE.png', (0.0, -0.4), threshold=0.85)
TPL_EXPEDITION_SEND = Template('V3_EXPEDITION_DISPATCH_BUTTON.png', (0.145, 0.372), threshold=0.85)
TPL_REWARD_DIALOG = Template('V3_REWARD_TITLE.png', (0.0, -0.285), threshold=0.85)
TPL_REWARD_CLAIM_DIALOG = Template('V4_REWARD_CLAIM_TITLE.png', (0.0, -0.285), threshold=0.85)
TPL_EXPEDITION_REWARD_DIALOG = Template('V5_EXPEDITION_REWARD_TITLE.png', (0.0, -0.285), threshold=0.85)
TPL_REWARD_CONFIRM = Template('CONFIRM_BUTTON.png', (0.0, 0.257), threshold=0.85)
TPL_MATERIAL_PAGE = Template('V3_MATERIAL_FLAG.png', (0.0, -0.348), threshold=0.85)
TPL_SWEEP_DIALOG = Template('V3_SWEEP_TITLE.png', (0.0, -0.272), threshold=0.85)
TPL_SWEEP_CONFIRM = Template('V3_SWEEP_BUTTON.png', (0.0, 0.236), threshold=0.85)
TPL_MATERIAL_MISSION = Template('V3_MISSION_MATERIAL_TITLE.png', threshold=0.87)
REWARD_DIALOGS = (TPL_REWARD_DIALOG, TPL_REWARD_CLAIM_DIALOG, TPL_EXPEDITION_REWARD_DIALOG)
BLOCKING_DIALOGS = (TPL_EXPEDITION_DIALOG, *REWARD_DIALOGS, TPL_SWEEP_DIALOG)


def reward_dialog_visible(screen, vision):
    return any(vision.exists(screen, title) for title in REWARD_DIALOGS)


def claim_reward(window_rect, screen, vision, log_func=None):
    """Click a reward confirmation only when its title is also visible."""
    if not reward_dialog_visible(screen, vision):
        return False
    return vision.click_template(window_rect, screen, TPL_REWARD_CONFIRM, log_func=log_func)


def confirm_and_wait(window_rect, capture_func, navigator, vision, title, button,
                     expected_page, log_func=None, is_stopped_func=None):
    """Send a modal action once; wait for its disappearance and the expected page."""
    clicked = False
    for _ in range(12):
        if is_stopped_func and is_stopped_func():
            return False
        screen = capture_func()
        if screen is None:
            time.sleep(0.5)
            continue
        visible = (reward_dialog_visible(screen, vision) if title is TPL_REWARD_DIALOG
                   else vision.exists(screen, title))
        if visible:
            if not clicked:
                if not vision.click_template(window_rect, screen, button, log_func=log_func):
                    return False
                clicked = True
        elif clicked:
            if reward_dialog_visible(screen, vision) and not vision.exists(screen, TPL_REWARD_CONFIRM):
                return False
            if claim_reward(window_rect, screen, vision, log_func):
                time.sleep(0.6)
                continue
            if navigator.detect_current_page(screen) is expected_page:
                return True
        time.sleep(0.5)
    if log_func:
        log_func(f'[!] [{title.name}] 未完成确认或未回到预期页面，停止本任务。', 'warning')
    return False


def click_material_mission(window_rect, screen, vision, log_func=None):
    """Locate 材料活动, then match 前往 within that same row and column."""
    screen = to_bgr(screen)
    if screen is None:
        return False
    label = vision.match(screen, TPL_MATERIAL_MISSION)
    if label is None:
        return False
    height, width = screen.shape[:2]
    x, y, _ = label
    target = Template('V3_MISSION_GOTO_LABEL.png',
                      (x / width - 0.5 + 0.208, y / height - 0.5 + 0.087),
                      rgb=True, threshold=0.87, roi_margin=(0.065, 0.045))
    return vision.click_template(window_rect, screen, target, log_func=log_func)


def stage_is_reached(screen, match):
    """Require the cyan daily-progress bar to reach the chest, not just its icon."""
    screen = to_bgr(screen)
    if screen is None or match is None:
        return False
    height, width = screen.shape[:2]
    x, y = match[:2]
    scale = width / 1280
    x0, x1 = int(x - 70 * scale), int(x - 40 * scale)
    y0, y1 = int(y - 4 * scale), int(y + 4 * scale)
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height or x1 <= x0 or y1 <= y0:
        return False
    region = cv2.cvtColor(screen[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    cyan = cv2.inRange(region, (75, 120, 140), (105, 255, 255))
    return cv2.countNonZero(cyan) / cyan.size > 0.12
