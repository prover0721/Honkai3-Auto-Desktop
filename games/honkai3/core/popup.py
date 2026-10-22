# -*- coding: utf-8 -*-
"""
崩坏3 全局动态弹窗拦截消解器 (Alas Popup Interceptor)
自动识别并消除每日签到、月卡、深渊结算、版本活动等各类打断弹窗
"""
import time
from typing import Tuple, Optional, Callable
import numpy as np

from games.honkai3.core.ui_vision import Template, UIVision, to_bgr


# 弹窗关键识别与触控模板
TPL_CONFIRM_BTN = Template("CONFIRM_BUTTON.png", (0.0, 0.144), threshold=0.75)
# 普通关闭动作只接受识别到的右上角 X；全屏搜索只在已判定为弹窗的分支调用。
TPL_CLOSE_X = Template("NOTICE_CLOSE.png", (0.275, -0.30), rgb=True, threshold=0.90, roi_margin=(0.225, 0.20))
TPL_CLOSE_X_ALT = Template("EVENT_PROMO_CLOSE.png", (0.275, -0.30), rgb=True, threshold=0.90, roi_margin=(0.225, 0.20))

# 活动通知弹窗
TPL_EVENT_FLAG = Template("POPUP_EVENT_FLAG.png", (0.0, 0.24), threshold=0.75)
# 录屏中出现的活动宣传卡。标题与右上角关闭标记必须同时命中，避免把普通活动页面当成弹窗。
TPL_EVENT_PROMO_TITLE = Template("EVENT_PROMO_TITLE.png", (-0.17, -0.17), threshold=0.82)
TPL_EVENT_PROMO_CLOSE = Template("EVENT_PROMO_CLOSE.png", (0.467, -0.45), threshold=0.88, roi_margin=(0.035, 0.055))
TPL_PROMO_DISMISS_HINT = Template("V9_PROMO_DISMISS_HINT.png", (0.0, 0.426), rgb=True, threshold=0.88, roi_margin=(0.09, 0.04))
TPL_PROMO_CLOSE_CURRENT = Template("V9_PROMO_CLOSE.png", (0.467, -0.447), rgb=True, threshold=0.90, roi_margin=(0.025, 0.035))

# 第二部全新福利弹窗模板 (拾梦之旅、每日签到、月卡福利)
TPL_POPUP_CLAIM = Template("V2_POPUP_CLAIM.png", (0.083, 0.419), threshold=0.75)
TPL_TAB_SIGNIN = Template("V2_TAB_SIGNIN.png", (-0.422, -0.196), threshold=0.75)
# 月度日历签到页：不包含月份、日期或奖励内容，换月仍可匹配。
TPL_MONTHLY_SIGNIN_TAB = Template("V3_MONTHLY_SIGNIN_TAB.png", (-0.436, -0.338), threshold=0.85)
TPL_MONTHLY_SIGNIN_CLAIM = Template("V3_MONTHLY_SIGNIN_CLAIM.png", (0.082, 0.445), threshold=0.85)
TPL_ERRAND_CONFIRM_TITLE = Template("V3_ERRAND_CONFIRM_TITLE.png", (-0.003, -0.403), threshold=0.85)

# 7日签到 (旧版兼容)
TPL_7DAY_CLAIM = Template("7DAY_REWARD_CLAIM.png", (0.084, 0.234), threshold=0.75)
TPL_7DAY_CONFIRM = Template("7DAY_REWARD_CONFIRM.png", (-0.001, 0.145), threshold=0.75)

# 每日签到 (旧版兼容)
TPL_SIGNIN_CLAIM = Template("SIGNIN_REWARD_CLAIM.png", (0.083, 0.248), threshold=0.75)
TPL_SIGNIN_CONFIRM = Template("SIGNIN_REWARD_CONFIRM.png", (-0.001, 0.134), threshold=0.75)

# 月卡
TPL_MONTHLY_CLAIM = Template("MONTHLY_CARD_CLAIM.png", (0.082, 0.234), threshold=0.75)
TPL_MONTHLY_500_CLAIM = Template("MONTHLY_CARD_500_CLAIM.png", (0.446, 0.121), threshold=0.75)

# 深渊结算 (适配第二部全新 UI 与超弦空间周期结算)
TPL_ABYSS_SETTLE = Template("V2_ABYSS_SETTLE.png", (0.0, -0.300), threshold=0.75)
TPL_ABYSS_DYNAMIC = Template("V2_ABYSS_SETTLE.png", None, threshold=0.85)

# 凭证升级奖励
TPL_POPUP_BP_FLAG = Template("POPUP_BP_FLAG.png", (-0.137, 0.218), threshold=0.75)
TPL_POPUP_BP_CLAIM = Template("POPUP_BP_CLAIM.png", (0.137, 0.218), threshold=0.75)

# 获得新物品通用弹窗
TPL_NEW_ITEM = Template("NEW_ITEM_POPUP.png", (0.289, -0.01), threshold=0.75)


class PopupHandler:
    """
    弹窗拦截器
    """
    def __init__(self, vision: UIVision):
        self.vision = vision
        self._abyss_clicked = False

    def known_popup(self, screen):
        return any(self.vision.exists(screen, marker) for marker in (
            TPL_PROMO_DISMISS_HINT, TPL_EVENT_PROMO_TITLE, TPL_EVENT_FLAG,
            TPL_POPUP_CLAIM, TPL_TAB_SIGNIN, TPL_MONTHLY_SIGNIN_TAB,
            TPL_MONTHLY_CLAIM, TPL_MONTHLY_500_CLAIM, TPL_7DAY_CLAIM,
            TPL_SIGNIN_CLAIM, TPL_ABYSS_SETTLE, TPL_ABYSS_DYNAMIC,
            TPL_NEW_ITEM, TPL_POPUP_BP_FLAG))

    def recognizes(self, screen):
        return self.known_popup(screen) or self.has_close(screen)

    def interrupts(self, screen):
        """External interruptions, excluding task-owned rewards and confirmations."""
        return any(self.vision.exists(screen, marker) for marker in (
            TPL_PROMO_DISMISS_HINT, TPL_EVENT_PROMO_TITLE, TPL_EVENT_FLAG,
            TPL_POPUP_CLAIM, TPL_TAB_SIGNIN, TPL_MONTHLY_SIGNIN_TAB,
            TPL_MONTHLY_CLAIM, TPL_MONTHLY_500_CLAIM, TPL_7DAY_CLAIM,
            TPL_SIGNIN_CLAIM, TPL_ABYSS_SETTLE, TPL_ABYSS_DYNAMIC))

    def close_candidates(self, screen):
        if not isinstance(self.vision, UIVision):
            return []
        # Share results across handlers for this exact frame only; never reuse on a new capture.
        cached = getattr(self.vision, '_close_candidate_cache', None)
        if isinstance(cached, tuple) and cached[0] is screen:
            return list(cached[1])
        candidates = []
        for source in (TPL_CLOSE_X, TPL_CLOSE_X_ALT, TPL_PROMO_CLOSE_CURRENT):
            dynamic = Template(source.name, None, rgb=True, threshold=0.93)
            candidates.extend(self.vision.match_candidates(screen, dynamic))
        self.vision._close_candidate_cache = (screen, tuple(candidates))
        return candidates

    def has_close(self, screen):
        return bool(self.close_candidates(screen))

    def find_close(self, screen):
        candidates = self.close_candidates(screen)
        if not candidates:
            return None
        x, y, score = candidates[0]
        if any(abs(x-other[0]) > 12 or abs(y-other[1]) > 12 for other in candidates[1:]):
            return None
        return x, y, score

    def handle(
        self,
        window_rect: Tuple[int, int, int, int],
        screen_bgr: np.ndarray,
        log_func: Optional[Callable[[str, str], None]] = None,
        capture_func: Optional[Callable[[], np.ndarray]] = None,
    ) -> bool:
        """
        探测并消除一层弹窗
        :return: 若处理了任何弹窗返回 True，画面无弹窗返回 False
        """
        # Changed activity titles may still have a unique known close-control glyph.
        if not self.known_popup(screen_bgr) and self.has_close(screen_bgr):
            return self._click_close_x(window_rect, screen_bgr, log_func)
        # 宣传内容每期变化，底部关闭提示更稳定。它仅作标志，绝不点击提示或内容。
        if self.vision.exists(screen_bgr, TPL_PROMO_DISMISS_HINT):
            if isinstance(self.vision, UIVision):
                return self._click_close_x(window_rect, screen_bgr, log_func)
            match = self.vision.match(screen_bgr, TPL_PROMO_CLOSE_CURRENT)
            if not isinstance(match, tuple) or len(match) != 3:
                if self._click_close_x(window_rect, screen_bgr, log_func):
                    return True
                if log_func:
                    log_func("[!] 活动宣传层存在，但右上角叉号未确认；保留画面，不点击活动内容。", "warning")
                return False
            x, y, score = match
            if log_func:
                log_func(f"[+] 活动宣传叉号识别 {score:.3f}，点击 ({x}, {y})。", "info")
            return self.vision.click_point(window_rect, x, y, jitter=0)

        # 用户指定深渊结算出现时单击即可；同一持续可见层只发送一次点击。
        abyss_marker = (TPL_ABYSS_SETTLE if self.vision.exists(screen_bgr, TPL_ABYSS_SETTLE)
                        else TPL_ABYSS_DYNAMIC)
        if self.vision.exists(screen_bgr, abyss_marker):
            if self._abyss_clicked:
                return False
            clicked = self.vision.click_template(window_rect, screen_bgr, abyss_marker, log_func=log_func)
            self._abyss_clicked = clicked
            if clicked:
                if log_func:
                    log_func("[+] 已识别深渊结算弹窗，单击一次关闭，等待新画面。", "info")
                time.sleep(0.8)
            return clicked
        self._abyss_clicked = False

        # 宣传卡先于一切领奖分支处理，只有右上角叉号可点击。
        if self.vision.exists(screen_bgr, TPL_EVENT_PROMO_TITLE):
            if isinstance(self.vision, UIVision):
                return self._click_close_x(window_rect, screen_bgr, log_func)
            if not self.vision.exists(screen_bgr, TPL_EVENT_PROMO_CLOSE):
                if self._click_close_x(window_rect, screen_bgr, log_func):
                    return True
                if log_func:
                    log_func("[!] 宣传卡未识别到右上角叉号，保留画面等待，不执行其它领奖点击。", "warning")
                return False
            return self.vision.click_template(window_rect, screen_bgr, TPL_EVENT_PROMO_CLOSE, log_func=log_func)

        # 月度日历页必须先于旧版福利处理，避免旧标签坐标点到奖励格子。
        if self.vision.exists(screen_bgr, TPL_EVENT_FLAG):
            return self._click_close_x(window_rect, screen_bgr, log_func)

        if self.vision.exists(screen_bgr, TPL_MONTHLY_SIGNIN_TAB):
            if self._confirm_if_present(window_rect, capture_func, screen_bgr, log_func):
                time.sleep(0.5)
                return True
            # 领取和关闭分两轮处理；关闭只允许识别并点击弹窗右上角 X。
            cur = capture_func() if capture_func is not None else screen_bgr
            if cur is None or not self.vision.exists(cur, TPL_MONTHLY_SIGNIN_TAB):
                return False
            if self.vision.exists(cur, TPL_MONTHLY_SIGNIN_CLAIM):
                if log_func:
                    log_func("[+] 检测到月度每日签到页，点击已识别的【领取】按钮...", "info")
                clicked = self.vision.click_template(window_rect, cur, TPL_MONTHLY_SIGNIN_CLAIM, log_func=log_func)
                if clicked:
                    time.sleep(0.8)
                return clicked
            # 无新截图时不能判定奖励已领取，更不能在可能已回舰桥时发 ESC。
            if capture_func is None:
                return False
            if not self._click_close_x(window_rect, cur, log_func):
                if log_func:
                    log_func("[!] 月度签到奖励已处理，但未识别到右上角关闭叉号；停止操作。", "warning")
                return False
            time.sleep(0.5)
            return True

        # 0. 检查第二部全新登录福利弹窗 (拾梦之旅、每日签到、月卡福利)
        if self.vision.exists(screen_bgr, TPL_POPUP_CLAIM) or self.vision.exists(screen_bgr, TPL_TAB_SIGNIN):
            if log_func:
                log_func("[+] 检测到【第二部登录福利/签到弹窗】，开始全自动领取与消解...", "info")

            # 依次处理: 当前标签 -> 每日签到标签 -> 月卡福利标签。
            # 每一步都重新截图确认弹窗仍然存在, 弹窗一旦消失立即停手,
            # 严禁在舰桥主界面上执行任何残留盲点 (防止误触右下角退出等按钮)。
            tab_templates = [None, TPL_TAB_SIGNIN]
            for tab_template in tab_templates:
                cur = self._grab(capture_func, screen_bgr)
                if cur is None:
                    break
                if not (self.vision.exists(cur, TPL_POPUP_CLAIM) or self.vision.exists(cur, TPL_TAB_SIGNIN)):
                    if log_func:
                        log_func("[+] 福利弹窗已消失，停止后续标签点击，避免误触主界面。", "success")
                    return True
                if tab_template is not None:
                    if not self.vision.click_template(window_rect, cur, tab_template, log_func=log_func):
                        continue
                    time.sleep(0.7)
                    cur = self._grab(capture_func, cur)
                    if cur is None:
                        break
                # 仅当画面上确实识别到【领取】按钮时才点击, 不再使用几何盲点
                if self.vision.exists(cur, TPL_POPUP_CLAIM):
                    self.vision.click_template(window_rect, cur, TPL_POPUP_CLAIM, log_func=log_func)
                    time.sleep(0.8)
                    self._confirm_if_present(window_rect, capture_func, log_func=log_func)
                    time.sleep(0.4)

            # 关闭弹窗: 仅当弹窗标志仍在画面上且匹配到右上角 X 时执行。
            cur = self._grab(capture_func, screen_bgr)
            if cur is not None and (self.vision.exists(cur, TPL_POPUP_CLAIM) or self.vision.exists(cur, TPL_TAB_SIGNIN)):
                if log_func:
                    log_func("[+] 福利领取完毕，查找并点击弹窗右上角叉号...", "info")
                if not self._click_close_x(window_rect, cur, log_func):
                    if log_func:
                        log_func("[!] 未识别到福利弹窗右上角叉号；停止操作，不点击空白区域。", "warning")
                    return False
                time.sleep(0.5)
            elif cur is None:
                if log_func:
                    log_func("[!] 无法取得福利弹窗关闭前的新画面，停止关闭操作。", "warning")
                return False
            elif log_func:
                log_func("[+] 福利弹窗已自行消失，无需执行关闭点击。", "success")
            return True
        # 1. 检查月卡奖励
        if self.vision.click_template(window_rect, screen_bgr, TPL_MONTHLY_CLAIM, log_func=log_func):
            if log_func:
                log_func("[+] 触发【月卡奖励】领取，等待确认...", "info")
            time.sleep(0.6)
            self._confirm_if_present(window_rect, capture_func, log_func=log_func)
            return True

        if self.vision.click_template(window_rect, screen_bgr, TPL_MONTHLY_500_CLAIM, log_func=log_func):
            if log_func:
                log_func("[+] 触发【500日/特权月卡】领取...", "info")
            time.sleep(0.6)
            self._confirm_if_present(window_rect, capture_func, log_func=log_func)
            return True

        # 2. 检查 7 日签到奖励
        if self.vision.click_template(window_rect, screen_bgr, TPL_7DAY_CLAIM, log_func=log_func):
            if log_func:
                log_func("[+] 触发【七日登录福利】领取...", "info")
            time.sleep(0.6)
            self._confirm_if_present(window_rect, capture_func, log_func=log_func)
            return True

        # 3. 检查每日签到奖励
        if self.vision.click_template(window_rect, screen_bgr, TPL_SIGNIN_CLAIM, log_func=log_func):
            if log_func:
                log_func("[+] 触发【每日签到奖励】领取...", "info")
            time.sleep(0.6)
            self._confirm_if_present(window_rect, capture_func, log_func=log_func)
            return True

        # 5. 检查活动宣传卡；标题与叉号同时命中后点击叉号。
        if (
            self.vision.exists(screen_bgr, TPL_EVENT_PROMO_TITLE)
            and self.vision.exists(screen_bgr, TPL_EVENT_PROMO_CLOSE)
        ):
            if log_func:
                log_func("[+] 检测到活动宣传卡，点击已识别的右上角叉号...", "info")
            clicked = self.vision.click_template(window_rect, screen_bgr, TPL_EVENT_PROMO_CLOSE, log_func=log_func)
            time.sleep(0.5)
            return clicked

        if self.vision.exists(screen_bgr, TPL_EVENT_FLAG):
            if log_func:
                log_func("[+] 检测到【活动公告】弹窗，查找右上角叉号...", "info")
            if not self._click_close_x(window_rect, screen_bgr, log_func):
                if log_func:
                    log_func("[!] 活动公告未识别到关闭叉号，不执行点击。", "warning")
                return False
            time.sleep(0.5)
            return True

        # 6. 检查作战凭证升级奖励弹窗
        if self.vision.exists(screen_bgr, TPL_POPUP_BP_FLAG):
            if log_func:
                log_func("[+] 检测到【凭证等级提升】弹窗，点击领取并确认...", "info")
            self.vision.click_template(window_rect, screen_bgr, TPL_POPUP_BP_CLAIM, log_func=log_func)
            time.sleep(0.6)
            self._confirm_if_present(window_rect, capture_func, log_func=log_func)
            return True

        # 7. 检查获得新物品/通用确认弹窗
        if self.vision.exists(screen_bgr, TPL_NEW_ITEM):
            if log_func:
                log_func("[+] 检测到【获得新物品】弹窗，查找右上角叉号...", "info")
            if not self._click_close_x(window_rect, screen_bgr, log_func):
                if log_func:
                    log_func("[!] 未识别到物品弹窗关闭叉号，不执行盲点。", "warning")
                return False
            time.sleep(0.5)
            return True

        return False

    def handle_all_clear(
        self,
        window_rect: Tuple[int, int, int, int],
        capture_func: Callable[[], np.ndarray],
        log_func: Optional[Callable[[str, str], None]] = None,
        max_popups: int = 6,
    ):
        """循环处理所有堆叠弹窗，直到界面恢复静止"""
        for i in range(max_popups):
            screen = capture_func()
            if screen is None:
                break
            if not self.handle(window_rect, screen, log_func=log_func, capture_func=capture_func):
                break
            time.sleep(0.8)

    def _grab(self, capture_func, fallback=None):
        """优先重新截图获取最新画面, 失败时回退到旧帧"""
        if capture_func is not None:
            try:
                s = capture_func()
                return s
            except Exception:
                return None
        return fallback

    def _confirm_if_present(
        self,
        window_rect: Tuple[int, int, int, int],
        capture_func=None,
        fallback_screen=None,
        log_func=None,
    ) -> bool:
        """
        验证式确认: 重新截图, 仅当画面上真实存在【确定】按钮或【获得物品】结算层时才点击。
        画面干净时不做任何动作, 杜绝在舰桥主界面上的盲点误触。
        """
        cur = self._grab(capture_func, fallback_screen)
        if cur is None:
            return False
        if self.vision.exists(cur, TPL_CONFIRM_BTN):
            self.vision.click_template(window_rect, cur, TPL_CONFIRM_BTN, log_func=log_func)
            return True
        if self.vision.exists(cur, TPL_NEW_ITEM):
            # 物品展示层按弹窗规则关闭，只点击画面中识别到的叉号。
            return self._click_close_x(window_rect, cur, log_func)
        return False

    def _click_close_x(self, window_rect, screen_bgr, log_func=None) -> bool:
        """点击弹窗右上角 X 模板；没有识别到 X 时不发送任何输入。"""
        screen_bgr = to_bgr(screen_bgr)
        if screen_bgr is None:
            return False
        height, width = screen_bgr.shape[:2]
        if isinstance(self.vision, UIVision):
            found = self.find_close(screen_bgr)
            if found is None:
                return False
            x, y, score = found
            if log_func:
                log_func(f'[弹窗守卫] 在当前画面确认关闭控件 ({x}, {y})，置信度 {score:.3f}', 'info')
            return self.vision.click_point(window_rect, x, y, jitter=0)
        for template in (TPL_CLOSE_X, TPL_CLOSE_X_ALT):
            match = self.vision.match(screen_bgr, template)
            if not isinstance(match, tuple) or len(match) != 3:
                continue
            x, y, _score = match
            if x < width * 0.55 or y > height * 0.40:
                continue
            # 使用刚刚验证的同一匹配结果，禁止二次搜索换目标；叉号不加抖动。
            if log_func:
                log_func(f"[+] 已校验右上角关闭叉号，置信度 {_score:.2f}，点击 ({x}, {y})。", "info")
            return self.vision.click_point(window_rect, x, y, jitter=0)
        return False

    def _close_modal(self, window_rect: Tuple[int, int, int, int], screen_bgr: Optional[np.ndarray] = None):
        """仅通过识别到的右上角 X 关闭弹窗。"""
        if screen_bgr is None:
            return False
        return self._click_close_x(window_rect, screen_bgr)
