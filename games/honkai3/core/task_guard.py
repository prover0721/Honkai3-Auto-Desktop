"""Honkai3 adapter: popup interruptions and verified terminal pages."""
from pathlib import Path
import time
from core.runtime_guard import RuntimeGuard, RuntimeViolation
from games.honkai3.core.ui_vision import to_bgr


class HonkaiTaskGuard:
    def __init__(self, task, rect, capture, navigator, vision, popup, log, stopped):
        self.rect, self.raw_capture, self.navigator = rect, capture, navigator
        self.vision, self.popup, self.log, self.stopped = vision, popup, log, stopped
        self.task = task
        self.runtime = RuntimeGuard(task, max_age=15, on_failure=self.evidence)
        self.original_click = vision.click_point

        def click(window, x, y, jitter=3):
            from games.honkai3.core.pause_gate import input_permit
            # Wait for resume and hold the input mutex before validating age.
            # The native click acquires this same recursive Windows mutex.
            with input_permit():
                self.check()
                self.runtime.before_action((int(x)//10, int(y)//10))
                return self.original_click(window, x, y, jitter=jitter)

        vision.click_point = click

    def check(self):
        if self.stopped and self.stopped():
            self.runtime.fail('用户已停止任务')
        self.runtime.check()

    def evidence(self, reason, frame):
        folder = Path(__file__).resolve().parents[2] / 'diagnostics'
        folder.mkdir(exist_ok=True)
        stamp = str(time.time_ns())
        (folder / (stamp + '.txt')).write_text(reason, encoding='utf-8')
        if frame is not None:
            import cv2
            cv2.imwrite(str(folder / (stamp + '.png')), frame)
        if self.log:
            self.log('[闭环守卫] ' + reason, 'error')

    def raw(self):
        self.check()
        frame = to_bgr(self.raw_capture())
        self.runtime.observe(frame)
        return frame

    def capture(self):
        from games.honkai3.core.daily_ui import BLOCKING_DIALOGS
        from games.honkai3.core.popup import TPL_ERRAND_CONFIRM_TITLE
        for _ in range(8):
            screen = self.raw()
            owned_dialog = any(self.vision.exists(screen, marker)
                               for marker in (*BLOCKING_DIALOGS, TPL_ERRAND_CONFIRM_TITLE))
            if owned_dialog and not self.popup.interrupts(screen):
                # Let the active task obtain its own reward/dispatch evidence.
                # Generic popup cleanup must not consume that evidence first.
                return screen
            if not self.popup.recognizes(screen):
                return screen
            if not self.popup.handle(self.rect, screen, log_func=self.log, capture_func=self.raw):
                self.runtime.fail('弹窗仍存在且无法确认安全关闭控件；保留画面停止')
            time.sleep(0.4)
        self.runtime.fail('弹窗处理已达到上限；未确认页面恢复')

    def prepare(self):
        from games.honkai3.core.daily_ui import (
            TPL_EXPEDITION_DIALOG, TPL_SWEEP_DIALOG, REWARD_DIALOGS,
        )
        from games.honkai3.core.popup import TPL_ERRAND_CONFIRM_TITLE
        # Only the task that owns a supported recovery dialog may resume it.
        recovery = {
            'expedition': (TPL_EXPEDITION_DIALOG, *REWARD_DIALOGS),
            'daily_sweep': (TPL_SWEEP_DIALOG, *REWARD_DIALOGS),
            'dorm_errand': (TPL_ERRAND_CONFIRM_TITLE,),
            'daily_errand': (TPL_ERRAND_CONFIRM_TITLE, TPL_EXPEDITION_DIALOG, *REWARD_DIALOGS),
        }
        screen = self.capture()
        if any(self.vision.exists(screen, marker) for marker in recovery.get(self.task, ())):
            return
        if self.navigator.detect_current_page(screen) is None:
            self.runtime.fail('任务起始页面未知，停止导航')

    def finish(self, success, expected):
        self.runtime.finish(success)
        for attempt in range(3):
            screen = self.capture()
            page = self.navigator.detect_current_page(screen)
            if page is expected:
                second = self.capture()
                if self.navigator.detect_current_page(second) is expected:
                    return True
            if attempt == 0 and page is not None:
                if not self.navigator.ui_goto(expected, self.rect, self.capture, log_func=self.log):
                    break
            time.sleep(0.4)
        self.runtime.fail('任务结束页面未得到连续确认，不报告成功')

    def close(self):
        self.vision.click_point = self.original_click
