# -*- coding: utf-8 -*-
"""
崩坏3 视觉匹配与交互引擎 (UI Vision Engine)
提供多分辨率自适应模板匹配、局部 ROI 聚焦、RGB 颜色校验与精准键鼠模拟
"""
import os
import time
import random
import ctypes
import cv2
import numpy as np
from typing import Optional, Tuple, Union
from games.honkai3.core.pause_gate import input_permit

# Windows API 点击
user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_MOVE = 0x0001
SM_CXSCREEN = 0
SM_CYSCREEN = 1


def to_bgr(screen):
    """
    将输入画面统一转换为 BGR ndarray。
    兼容 qr_scanner.capture_screen_or_window() 返回的 PIL.Image (RGB)，
    修复将 PIL.Image 直接传入模板匹配导致的 AttributeError: 'Image' object has no attribute 'shape'。
    """
    if screen is None:
        return None
    if isinstance(screen, np.ndarray):
        return screen
    try:
        from PIL import Image
        if isinstance(screen, Image.Image):
            arr = np.array(screen.convert("RGB"))
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        pass
    return None


GAME_WINDOW_TITLE = "崩坏3"
_fg_warn_last = [0.0]


def is_game_foreground(title: str = None) -> bool:
    """
    前台守护: 判断游戏窗口当前是否为系统前台焦点窗口。
    自动化的一切鼠标/键盘动作都必须在游戏处于前台时才允许执行,
    防止用户切换到其他应用后, 模拟点击误伤其他程序。
    """
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, buf, 128)
        return buf.value.strip() == (title or GAME_WINDOW_TITLE)
    except Exception:
        # API 异常时保守放行, 避免整条流水线卡死
        return True


def activate_game_window(log_func=None, timeout: float = 3.0) -> bool:
    """
    在自动化任务开始时恢复并激活游戏窗口。

    只在任务建立视觉上下文时调用一次；任务运行期间若用户主动切走，
    click_point 的前台守护仍会拒绝后续物理输入，不会持续抢占焦点。
    """
    if is_game_foreground():
        return True

    try:
        hwnd = user32.FindWindowW(None, GAME_WINDOW_TITLE)
        if not hwnd or not user32.IsWindow(hwnd):
            if log_func:
                log_func("[!] 无法取得《崩坏3》窗口句柄，不能启动画面自动化。", "error")
            return False

        # SW_RESTORE 可同时处理最小化状态；BringWindowToTop 与
        # SetForegroundWindow 组合用于从 GameHub 切换到游戏。
        user32.ShowWindow(hwnd, 9)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

        deadline = time.time() + max(0.0, timeout)
        while time.time() <= deadline:
            if is_game_foreground():
                if log_func:
                    log_func("[+] 已激活《崩坏3》窗口，开始执行画面自动化。", "info")
                return True
            time.sleep(0.1)
    except Exception as exc:
        if log_func:
            log_func(f"[!] 激活《崩坏3》窗口失败: {exc}", "warning")

    if log_func:
        log_func(
            "[安全暂停] 游戏窗口未能切到前台；本轮不会伪报点击成功，请手动切回游戏后重试。",
            "warning",
        )
    return False


def guard_game_foreground(log_func=None, wait: bool = False, timeout: float = 0.0) -> bool:
    """
    动作前守护检查。
    :param wait: True 时阻塞等待用户切回游戏 (最多 timeout 秒), False 时立即返回结果
    :return: 游戏是否处于前台
    """
    if is_game_foreground():
        return True
    now = time.time()
    if now - _fg_warn_last[0] > 5.0:
        _fg_warn_last[0] = now
        msg = "[安全暂停] 检测到游戏窗口已切至后台，自动化动作已挂起，切回游戏窗口后将自动恢复..."
        if log_func:
            log_func(msg, "warning")
        else:
            print(msg)
    if not wait:
        return False
    deadline = now + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        if is_game_foreground():
            if log_func:
                log_func("[恢复] 游戏窗口已回到前台，自动化动作恢复执行。", "success")
            return True
    return False



class Template:
    """
    UI 模板定义
    :param name: 模板文件名 (如 RETURN_BUTTON.png)
    :param record_pos: 在 1280x720 基准分辨率下的归一化中心坐标 ((x - W/2)/W, (y - H/2)/H)
                       取值范围通常在 (-0.5, 0.5) 之间，例如 (-0.444, -0.256) 代表左上方返回按钮
    :param rgb: 是否启用色彩空间校验（避免匹配到置灰禁用的按钮）
    :param threshold: 默认匹配相似度阈值 (0.0 ~ 1.0)
    """
    def __init__(
        self,
        name: str,
        record_pos: Optional[Tuple[float, float]] = None,
        rgb: bool = False,
        threshold: float = 0.80,
        roi_margin: Optional[Tuple[float, float]] = None,
    ):
        self.name = os.path.basename(name)
        self.record_pos = record_pos
        self.rgb = rgb
        self.threshold = threshold
        self.roi_margin = roi_margin

    def __repr__(self):
        return f"<Template {self.name} pos={self.record_pos} rgb={self.rgb}>"


class UIVision:
    """
    视觉分析器与动作执行器
    """
    def __init__(self, template_dirs: Optional[list[str]] = None):
        if template_dirs is None:
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            self.template_dirs = [
                os.path.normpath(os.path.join(curr_dir, "..", "assets", "templates")),
                os.path.normpath(os.path.join(curr_dir, "..", "assets")),
                os.path.normpath(os.path.join(curr_dir, "..", "..", "bh3_auto_login", "assets", "templates")),
            ]
        else:
            self.template_dirs = template_dirs

        self._tpl_cache: dict[str, np.ndarray] = {}
        self.last_click_time = 0.0
        self.min_click_interval = 0.35  # 防止过高频连击

    def find_template_file(self, filename: str) -> Optional[str]:
        """按优先级检索模板文件路径"""
        for d in self.template_dirs:
            p = os.path.join(d, filename)
            if os.path.isfile(p):
                return p
        return None

    def get_template_img(self, filename: str) -> Optional[np.ndarray]:
        """读取并缓存模板图像"""
        if filename in self._tpl_cache:
            return self._tpl_cache[filename]

        p = self.find_template_file(filename)
        if not p:
            return None

        # 支持中文字符路径的 imread
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            self._tpl_cache[filename] = img
        return img

    def match(self, screen_bgr, template, threshold=None):
        # Repeated rules inspect the same captured array. Keep at most two frames
        # (the original and the temporary ambiguity mask), never cache across captures.
        if not isinstance(screen_bgr, np.ndarray):
            return self._match_uncached(screen_bgr, template, threshold)
        caches = getattr(self, '_frame_match_cache', [])
        for frame, results in caches:
            if frame is screen_bgr:
                break
        else:
            results = {}
            caches.append((screen_bgr, results))
            self._frame_match_cache = caches[-2:]
        key = (template.name, template.record_pos, template.rgb,
               template.threshold, template.roi_margin, threshold)
        if key not in results:
            results[key] = self._match_uncached(screen_bgr, template, threshold)
        return results[key]

    def _match_uncached(
        self,
        screen_bgr: np.ndarray,
        template: Template,
        threshold: Optional[float] = None,
    ) -> Optional[Tuple[int, int, float]]:
        """
        在画面中匹配模板
        :param screen_bgr: 游戏当前帧 BGR 图像
        :param template: Template 对象
        :param threshold: 匹配阈值，留空则使用 template.threshold
        :return: (client_x, client_y, score) 或 None
        """
        screen_bgr = to_bgr(screen_bgr)
        if screen_bgr is None or screen_bgr.size == 0:
            return None

        tpl_img = self.get_template_img(template.name)
        if tpl_img is None:
            return None
        # 拦截损坏或全纯色模板（避免全白/全黑产生 1.0 虚假满分匹配）
        if tpl_img.std() < 5.0:
            return None

        target_th = threshold if threshold is not None else template.threshold
        sh, sw = screen_bgr.shape[:2]
        th, tw = tpl_img.shape[:2]

        # 计算自适应缩放比（以 1280x720 为基准设计图）
        base_scale = sw / 1280.0

        # 若指定了基准记录坐标，则裁剪局部 ROI，提速 50 倍并防止全屏杂色误判
        roi_x0, roi_y0 = 0, 0
        search_region = screen_bgr

        if template.record_pos is not None:
            rx, ry = template.record_pos
            # 换算至画面绝对坐标
            exp_cx = int((rx + 0.5) * sw)
            exp_cy = int((ry + 0.5) * sh)

            # 缩放后的预期模板尺寸
            scaled_tw = int(tw * base_scale)
            scaled_th = int(th * base_scale)

            # 扩展 ROI 搜索范围 (±20% 边长裕量)
            mx, my = template.roi_margin or (0.16, 0.16)
            margin_w = max(int(sw * mx), int(scaled_tw * 1.5))
            margin_h = max(int(sh * my), int(scaled_th * 1.5))

            roi_x0 = max(0, exp_cx - margin_w)
            roi_y0 = max(0, exp_cy - margin_h)
            roi_x1 = min(sw, exp_cx + margin_w)
            roi_y1 = min(sh, exp_cy + margin_h)

            if roi_x1 > roi_x0 + scaled_tw and roi_y1 > roi_y0 + scaled_th:
                search_region = screen_bgr[roi_y0:roi_y1, roi_x0:roi_x1]
            else:
                # ROI 不足以容纳模板时回退全屏；坐标原点必须同步归零。
                roi_x0, roi_y0 = 0, 0

        reg_h, reg_w = search_region.shape[:2]

        # 尝试基准尺度及微小扰动尺度
        scales_to_try = [base_scale, base_scale * 0.96, base_scale * 1.04]
        best_match = None
        best_score = -1.0

        for sc in scales_to_try:
            target_tw = int(round(tw * sc))
            target_th_val = int(round(th * sc))

            if target_tw >= reg_w or target_th_val >= reg_h or target_tw < 4 or target_th_val < 4:
                continue

            scaled_tpl = cv2.resize(tpl_img, (target_tw, target_th_val), interpolation=cv2.INTER_AREA)

            # 模板匹配
            res = cv2.matchTemplate(search_region, scaled_tpl, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

            if max_val > best_score:
                best_score = max_val
                # 计算中心点在全图的坐标
                cx = roi_x0 + max_loc[0] + target_tw // 2
                cy = roi_y0 + max_loc[1] + target_th_val // 2
                best_match = (cx, cy, max_val, scaled_tpl, max_loc)

                # 高置信度早停
                if max_val >= 0.90:
                    break

        if not best_match or best_score < target_th:
            return None

        cx, cy, score, matched_tpl, (m_x, m_y) = best_match

        # 如果需要色彩空间二次验证 (防止置灰按钮匹配)
        if template.rgb:
            # 截取画面匹配块
            mw = matched_tpl.shape[1]
            mh = matched_tpl.shape[0]
            crop_patch = search_region[m_y:m_y+mh, m_x:m_x+mw]
            if crop_patch.shape == matched_tpl.shape:
                diff = cv2.absdiff(crop_patch, matched_tpl)
                mean_diff = np.mean(diff)
                # 色彩差异过大说明是灰态或异色伪目标
                if mean_diff > 45.0:
                    return None

        return (cx, cy, float(score))

    def match_candidates(self, screen_bgr, template):
        """Return up to two separated candidates, preserving ambiguity evidence."""
        screen_bgr = to_bgr(screen_bgr)
        first = self.match(screen_bgr, template)
        if first is None:
            return []
        image = self.get_template_img(template.name)
        if image is None:
            return []
        height, width = screen_bgr.shape[:2]
        radius_x = max(8, int(image.shape[1] * width / 1280))
        radius_y = max(8, int(image.shape[0] * width / 1280))
        x, y, _ = first
        masked = screen_bgr.copy()
        masked[max(0, y-radius_y):min(height, y+radius_y+1),
               max(0, x-radius_x):min(width, x+radius_x+1)] = 0
        second = self.match(masked, template)
        return [first, second] if second is not None else [first]

    def match_unique(self, screen_bgr, template):
        candidates = self.match_candidates(screen_bgr, template)
        return candidates[0] if len(candidates) == 1 else None

    def exists(
        self,
        screen_bgr: np.ndarray,
        template: Template,
        threshold: Optional[float] = None,
    ) -> bool:
        """判断模板是否存在于当前画面"""
        return self.match(screen_bgr, template, threshold) is not None

    def click_point(
        self,
        window_rect: Tuple[int, int, int, int],
        client_x: int,
        client_y: int,
        jitter: int = 3,
    ) -> bool:
        """
        在游戏窗口内点击指定客户区坐标 (client_x, client_y)
        :param window_rect: (left, top, width, height)
        :param jitter: 像素级防风控微扰动
        """
        with input_permit():
            # 前台焦点必须在暂停放行后重新检查。
            if not guard_game_foreground():
                return False

            now = time.time()
            if now - self.last_click_time < self.min_click_interval:
                time.sleep(self.min_click_interval - (now - self.last_click_time))

            left, top, win_w, win_h = window_rect
            right, bottom = left + win_w, top + win_h
            offset_x = random.randint(-jitter, jitter)
            offset_y = random.randint(-jitter, jitter)
            screen_x = max(left + 2, min(right - 2, left + client_x + offset_x))
            screen_y = max(top + 2, min(bottom - 2, top + client_y + offset_y))

            user32.SetCursorPos(screen_x, screen_y)
            time.sleep(0.03)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05 + random.uniform(0.01, 0.04))
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            self.last_click_time = time.time()
            return True

    def click_template(
        self,
        window_rect: Tuple[int, int, int, int],
        screen_bgr: np.ndarray,
        template: Template,
        threshold: Optional[float] = None,
        log_func=None,
        fallback_to_pos: bool = False,
    ) -> bool:
        """查找并点击模板，若未找到且 fallback_to_pos 为 True，则执行几何坐标兜底点击"""
        match_res = self.match(screen_bgr, template, threshold)
        if match_res:
            cx, cy, score = match_res
            if log_func:
                log_func(f"[+] 识别到目标 [{template.name}] (置信度: {score:.2f})，正在执行点击 ({cx}, {cy})...", "info")
            clicked = self.click_point(window_rect, cx, cy)
            if not clicked and log_func:
                log_func(
                    f"[安全暂停] 已识别目标 [{template.name}]，但游戏不在前台，点击未执行。",
                    "warning",
                )
            return clicked
        elif fallback_to_pos and template.record_pos:
            return self.click_pos(window_rect, screen_bgr, template.record_pos, log_func=log_func)
        return False

    def click_pos(
        self,
        window_rect: Tuple[int, int, int, int],
        screen_bgr: np.ndarray,
        record_pos: Tuple[float, float],
        jitter: int = 3,
        log_func=None,
    ) -> bool:
        """
        点击基准归一化坐标 (-0.5 ~ 0.5)
        :param window_rect: 游戏窗口矩形 (left, top, right, bottom)
        :param screen_bgr: 当前画面帧
        :param record_pos: 归一化中心坐标 (rx, ry)，例如 (-0.318, -0.450) 代表左上方
        """
        screen_bgr = to_bgr(screen_bgr)
        if screen_bgr is None or screen_bgr.size == 0:
            return False
        sh, sw = screen_bgr.shape[:2]
        rx, ry = record_pos
        client_x = int((rx + 0.5) * sw)
        client_y = int((ry + 0.5) * sh)
        if log_func:
            log_func(f"[*] 执行自适应几何坐标点击 (归一化: {rx:.3f}, {ry:.3f} -> 客户区像素: {client_x}, {client_y})...", "info")
        return self.click_point(window_rect, client_x, client_y, jitter=jitter)
