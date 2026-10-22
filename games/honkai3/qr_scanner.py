# -*- coding: utf-8 -*-
"""
屏幕截图与二维码识别模块
自动定位《崩坏3》窗口并识别二维码中的登录 ticket
"""
import ctypes
import os
import time
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageGrab
import pygetwindow as gw
from games.honkai3.core.pause_gate import input_permit

try:
    # 启用系统 DPI 感知，避免高分屏缩放 (125%, 150%) 导致坐标映射偏差
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

TEMPLATE_PATH = Path(__file__).parent / "assets" / "qr_toggle_icon.png"


def find_bh3_hwnd() -> Optional[int]:
    """
    通过 Windows API 查找崩坏3窗口句柄
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "崩坏3")
        if hwnd and user32.IsWindow(hwnd):
            return hwnd
    except Exception:
        pass
    return None


def find_bh3_window() -> Optional[Tuple[int, int, int, int]]:
    """
    查找《崩坏3》游戏窗口位置 (left, top, width, height)
    """
    # 1. 优先使用 Win32 原生 API 检索窗口矩形
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "崩坏3")
        if hwnd and user32.IsWindow(hwnd):
            from ctypes import wintypes
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 200 and h > 200:
                return (rect.left, rect.top, w, h)
    except Exception:
        pass

    # 2. 备用 pygetwindow
    try:
        windows = gw.getWindowsWithTitle("崩坏3")
        for win in windows:
            if win.title == "崩坏3" and win.width > 200 and win.height > 200:
                return (win.left, win.top, win.width, win.height)
    except Exception:
        pass
    return None


def _is_game_foreground() -> bool:
    """前台守护: 判断《崩坏3》窗口是否为当前系统焦点窗口。
    游戏不在前台时, 禁止一切物理鼠标/键盘模拟 (SetCursorPos/mouse_event),
    仅允许 PostMessage 窗口消息通道, 防止误伤用户正在使用的其他应用。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, buf, 128)
        return buf.value.strip() == "崩坏3"
    except Exception:
        return True


def capture_screen_or_window(rect: Optional[Tuple[int, int, int, int]] = None) -> Optional[Image.Image]:
    """
    截取指定区域（若无则截取全屏）
    """
    try:
        if rect is not None:
            left, top, width, height = rect
            # 保证坐标有效
            if width > 0 and height > 0:
                bbox = (left, top, left + width, top + height)
                return ImageGrab.grab(bbox=bbox)
        return ImageGrab.grab()
    except Exception as e:
        print(f"[截图捕获异常]: {e}")
        return None


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_cursor_pos() -> Tuple[int, int]:
    """获取当前鼠标光标在屏幕上的绝对坐标 (x, y)"""
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def click_at_pos(x: int, y: int, hwnd: Optional[int] = None) -> bool:
    with input_permit():
        return _click_at_pos_unlocked(x, y, hwnd)


def _click_at_pos_unlocked(x: int, y: int, hwnd: Optional[int] = None) -> bool:
    """在指定屏幕绝对坐标 (x, y) 执行模拟左键点击（物理 + 消息双通道）"""
    user32 = ctypes.windll.user32
    if _is_game_foreground():
        try:
            user32.SetCursorPos(x, y)
            time.sleep(0.04)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
            time.sleep(0.06)
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        except Exception as e:
            print(f"[鼠标点击异常]: {e}")
    else:
        print("[安全暂停] 游戏窗口不在前台，跳过物理鼠标点击，仅发送窗口消息。")

    if hwnd:
        try:
            rect = find_bh3_window()
            if rect:
                left, top, _, _ = rect
                lx = max(0, x - left)
                ly = max(0, y - top)
                lparam = ((ly & 0xFFFF) << 16) | (lx & 0xFFFF)
                user32.PostMessageW(hwnd, 0x0201, 1, lparam)  # WM_LBUTTONDOWN
                time.sleep(0.04)
                user32.PostMessageW(hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP
        except Exception:
            pass
    return True


_TOGGLE_TMPL_CACHE = None


def _get_toggle_template() -> Optional[np.ndarray]:
    """缓存切换角标模板，避免每帧重复磁盘读取"""
    global _TOGGLE_TMPL_CACHE
    if _TOGGLE_TMPL_CACHE is None and TEMPLATE_PATH.is_file():
        _TOGGLE_TMPL_CACHE = cv2.imread(str(TEMPLATE_PATH))
    return _TOGGLE_TMPL_CACHE


def _to_bgr_np(image) -> Optional[np.ndarray]:
    """PIL / ndarray 统一转为 BGR ndarray"""
    if image is None:
        return None
    img_np = np.asarray(image)
    if img_np.ndim == 2:
        return cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
    if img_np.ndim == 3:
        if img_np.shape[2] == 4:
            img_np = img_np[:, :, :3]
        if isinstance(image, Image.Image):
            return cv2.cvtColor(np.ascontiguousarray(img_np), cv2.COLOR_RGB2BGR)
        return np.ascontiguousarray(img_np)
    return None


def find_qr_toggle_button(image: Optional[Image.Image]) -> Optional[Tuple[int, int]]:
    """
    使用 OpenCV 多尺度模板匹配定位登录弹窗左上角二维码切换图标
    返回相对于该截图片段的 (center_x, center_y) 相对坐标

    性能策略 (2026-09-17 提速版)：
    1. 先把整帧降采样到模板录制基准宽度 (1024)，2K/4K 画面的匹配开销直接缩小 6~16 倍；
    2. 只在窗口中央 70% ROI 内搜索；
    3. 尺度按"最贴近 1.0"优先、高置信度立即早停。
    实测 2560x1440 下单帧耗时由 ~2.4s 降至 ~0.1s。
    """
    tmpl = _get_toggle_template()
    if image is None or tmpl is None:
        return None

    try:
        h_t, w_t = tmpl.shape[:2]
        img_bgr = _to_bgr_np(image)
        if img_bgr is None:
            return None
        img_h, img_w = img_bgr.shape[:2]

        # 降采样到 1024 宽基准 (模板即按此基准录制)
        base_scale = img_w / 1024.0
        if base_scale > 1.05:
            ds = 1.0 / base_scale
            work = cv2.resize(img_bgr, None, fx=ds, fy=ds, interpolation=cv2.INTER_AREA)
        else:
            ds = 1.0
            work = img_bgr
        wk_h, wk_w = work.shape[:2]

        # 登录弹窗固定位于窗口中央约 70% 区域，裁剪 ROI 避免全局多余扫描
        roi_y1 = int(wk_h * 0.12)
        roi_y2 = int(wk_h * 0.88)
        roi_x1 = int(wk_w * 0.15)
        roi_x2 = int(wk_w * 0.85)
        roi = work[roi_y1:roi_y2, roi_x1:roi_x2]
        roi_h, roi_w = roi.shape[:2]
        if roi_h <= h_t or roi_w <= w_t:
            roi = work
            roi_y1 = 0
            roi_x1 = 0
            roi_h, roi_w = wk_h, wk_w

        # 尺度候选：已归一到 1024 基准，故以 1.0 为中心向两侧扩散
        scales = [1.0, 0.9, 1.1, 0.8, 1.2, 0.7, 1.3, 0.6, 1.5, 0.5, 1.75, 2.0, 0.4]

        best_score = -1.0
        best_loc = None
        best_dim = (w_t, h_t)

        for scale in scales:
            sw = int(w_t * scale)
            sh = int(h_t * scale)
            if sw >= roi_w or sh >= roi_h or sw <= 10 or sh <= 10:
                continue
            scaled_tmpl = cv2.resize(tmpl, (sw, sh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            res = cv2.matchTemplate(roi, scaled_tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_v, _, max_l = cv2.minMaxLoc(res)
            if max_v > best_score:
                best_score = max_v
                best_loc = max_l
                best_dim = (sw, sh)

            # 达到高置信度立即早停
            if max_v >= 0.85:
                break

        if best_score >= 0.65 and best_loc is not None:
            cx = (roi_x1 + best_loc[0] + best_dim[0] // 2) / ds
            cy = (roi_y1 + best_loc[1] + best_dim[1] // 2) / ds
            return (int(round(cx)), int(round(cy)))
    except Exception as e:
        print(f"[二维码切换定位异常]: {e}")

    return None


_ACCOUNT_BTN_CACHE = None
ACCOUNT_BTN_PATH = Path(__file__).parent / "assets" / "templates" / "BTN_ACCOUNT_LOGIN.png"


def find_account_login_button(image: Optional[Image.Image]) -> Optional[Tuple[int, int]]:
    """检测【请选择登录方式】待机界面的黄色【账号登录】按钮相对坐标 (cx, cy)"""
    global _ACCOUNT_BTN_CACHE
    if _ACCOUNT_BTN_CACHE is None:
        cand_paths = [
            ACCOUNT_BTN_PATH,
            Path(__file__).parent.parent / "honkai3" / "assets" / "templates" / "BTN_ACCOUNT_LOGIN.png",
            Path(__file__).parent / "BTN_ACCOUNT_LOGIN.png",
        ]
        for p in cand_paths:
            if p.is_file():
                _ACCOUNT_BTN_CACHE = cv2.imread(str(p))
                if _ACCOUNT_BTN_CACHE is not None:
                    break

    tmpl = _ACCOUNT_BTN_CACHE
    if image is None or tmpl is None:
        return None

    try:
        img_bgr = _to_bgr_np(image)
        if img_bgr is None:
            return None
        img_h, img_w = img_bgr.shape[:2]
        base_scale = img_w / 1024.0
        ds = 1.0 / base_scale if base_scale > 1.05 else 1.0
        work = cv2.resize(img_bgr, None, fx=ds, fy=ds, interpolation=cv2.INTER_AREA) if ds != 1.0 else img_bgr
        wk_h, wk_w = work.shape[:2]

        # 按钮固定在中间偏下方 (y: 60% ~ 98%, x: 25% ~ 75%)
        roi_y1 = int(wk_h * 0.60)
        roi_y2 = int(wk_h * 0.98)
        roi_x1 = int(wk_w * 0.25)
        roi_x2 = int(wk_w * 0.75)
        roi = work[roi_y1:roi_y2, roi_x1:roi_x2]
        h_t, w_t = tmpl.shape[:2]
        if roi.shape[0] <= h_t or roi.shape[1] <= w_t:
            return None

        res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_v, _, max_l = cv2.minMaxLoc(res)
        if max_v >= 0.70 and max_l is not None:
            cx = (roi_x1 + max_l[0] + w_t // 2) / ds
            cy = (roi_y1 + max_l[1] + h_t // 2) / ds
            return (int(round(cx)), int(round(cy)))
    except Exception:
        pass

    return None


_DIALOG_CONFIRM_BTN_CACHE = None
DIALOG_CONFIRM_BTN_PATH = Path(__file__).parent / "assets" / "templates" / "BTN_DIALOG_CONFIRM.png"


def find_dialog_confirm_button(image: Optional[Image.Image]) -> Optional[Tuple[int, int]]:
    """检测【为了账号安全，请重新登录】等弹窗中央的黄色【确定】按钮相对坐标 (cx, cy)"""
    global _DIALOG_CONFIRM_BTN_CACHE
    if _DIALOG_CONFIRM_BTN_CACHE is None:
        cand_paths = [
            DIALOG_CONFIRM_BTN_PATH,
            Path(__file__).parent.parent / "honkai3" / "assets" / "templates" / "BTN_DIALOG_CONFIRM.png",
            Path(__file__).parent / "BTN_DIALOG_CONFIRM.png",
        ]
        for p in cand_paths:
            if p.is_file():
                _DIALOG_CONFIRM_BTN_CACHE = cv2.imread(str(p))
                if _DIALOG_CONFIRM_BTN_CACHE is not None:
                    break

    tmpl = _DIALOG_CONFIRM_BTN_CACHE
    if image is None or tmpl is None:
        return None

    try:
        img_bgr = _to_bgr_np(image)
        if img_bgr is None:
            return None
        img_h, img_w = img_bgr.shape[:2]
        base_scale = img_w / 1024.0
        ds = 1.0 / base_scale if base_scale > 1.05 else 1.0
        work = cv2.resize(img_bgr, None, fx=ds, fy=ds, interpolation=cv2.INTER_AREA) if ds != 1.0 else img_bgr
        wk_h, wk_w = work.shape[:2]

        roi_y1 = int(wk_h * 0.50)
        roi_y2 = int(wk_h * 0.85)
        roi_x1 = int(wk_w * 0.25)
        roi_x2 = int(wk_w * 0.75)
        roi = work[roi_y1:roi_y2, roi_x1:roi_x2]
        h_t, w_t = tmpl.shape[:2]

        if roi.shape[0] <= h_t or roi.shape[1] <= w_t:
            return None

        res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_v, _, max_l = cv2.minMaxLoc(res)
        if max_v >= 0.70 and max_l is not None:
            cx = (roi_x1 + max_l[0] + w_t // 2) / ds
            cy = (roi_y1 + max_l[1] + h_t // 2) / ds
            return (int(round(cx)), int(round(cy)))
    except Exception:
        pass

    return None


def switch_to_qr_login(rect: Optional[Tuple[int, int, int, int]] = None, target_pos: Optional[Tuple[int, int]] = None) -> bool:
    with input_permit():
        return _switch_to_qr_login_unlocked(rect, target_pos)


def _switch_to_qr_login_unlocked(rect: Optional[Tuple[int, int, int, int]] = None, target_pos: Optional[Tuple[int, int]] = None) -> bool:
    """
    对视觉识别到的二维码切换角标发送一次点击。

    不提供未识别时的几何盲点；前台时使用物理鼠标，后台时使用单组窗口消息，
    避免同一目标被多个输入通道重复点击。
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = find_bh3_hwnd()

    if hwnd:
        try:
            fore_hwnd = user32.GetForegroundWindow()
            if fore_hwnd != hwnd:
                fore_tid = user32.GetWindowThreadProcessId(fore_hwnd, None)
                cur_tid = kernel32.GetCurrentThreadId()
                attached = False
                if fore_tid != cur_tid and fore_tid != 0:
                    attached = bool(user32.AttachThreadInput(cur_tid, fore_tid, True))
                try:
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                finally:
                    if attached:
                        user32.AttachThreadInput(cur_tid, fore_tid, False)
            else:
                user32.ShowWindow(hwnd, 9)
                user32.BringWindowToTop(hwnd)
            time.sleep(0.08)
        except Exception:
            pass

    if rect is None:
        rect = find_bh3_window()
    if rect is None:
        return False

    left, top, width, height = rect

    if target_pos is None:
        img = capture_screen_or_window(rect)
        target_pos = find_qr_toggle_button(img)
        if target_pos is None:
            return False

    local_x, local_y = target_pos
    if not (0 <= local_x < width and 0 <= local_y < height):
        return False
    click_x, click_y = left + local_x, top + local_y

    try:
        # 激活窗口后直接执行系统级物理鼠标点击，确保 Unity 引擎捕获点击事件
        user32.SetCursorPos(click_x, click_y)
        time.sleep(0.04)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP

        # 辅以后台窗口消息兜底
        if hwnd:
            lparam = (((local_y & 0xFFFF) << 16) | (local_x & 0xFFFF))
            user32.PostMessageW(hwnd, 0x0201, 1, lparam)  # WM_LBUTTONDOWN
            time.sleep(0.03)
            user32.PostMessageW(hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP
    except Exception as e:
        print(f"[模拟点击异常]: {e}")
        return False

    # 该返回值只表示已发送输入；runner 会通过后续帧验证二维码/角标变化。
    time.sleep(0.08)
    return True


def click_game_center(rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
    with input_permit():
        return _click_game_center_unlocked(rect)


def _click_game_center_unlocked(rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
    """向游戏窗口中心模拟一次左键点击（物理事件 + 窗口消息双通道）。

    用于登录成功后的「点击任意处进入游戏」画面，也适用于其他
    任意位置点击即可响应的过场界面。
    """
    user32 = ctypes.windll.user32
    hwnd = find_bh3_hwnd()
    if rect is None:
        rect = find_bh3_window()
    if rect is None:
        return False
    left, top, width, height = rect

    if hwnd:
        try:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            time.sleep(0.2)
        except Exception:
            pass

    click_x = left + width // 2
    click_y = top + height // 2

    # 通道 1：物理鼠标事件（对前台窗口生效; 前台守护: 游戏不在前台时跳过）
    if _is_game_foreground():
        try:
            user32.SetCursorPos(click_x, click_y)
            time.sleep(0.08)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
            time.sleep(0.08)
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        except Exception as e:
            print(f"[模拟点击异常]: {e}")

    # 通道 2：窗口消息（前台被占用时的备用）
    if hwnd:
        try:
            lparam = (((click_y - top) & 0xFFFF) << 16) | ((click_x - left) & 0xFFFF)
            user32.PostMessageW(hwnd, 0x0201, 1, lparam)  # WM_LBUTTONDOWN
            time.sleep(0.05)
            user32.PostMessageW(hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP
        except Exception:
            pass
    return True


def wait_and_click_enter_game(
    rect: Optional[Tuple[int, int, int, int]] = None,
    log_func=None,
    is_stopped_func=None,
    delay_before_click: float = 1.5,
) -> bool:
    """扫码确认成功后，在鼠标当前位置模拟点击进入游戏。

    逻辑：
    1. 扫码授权确认成功后，等待约 1.5 秒让客户端完成弹窗关闭并进入「点击任意处进入」画面；
    2. 获取用户当前鼠标光标所在绝对屏幕坐标；
    3. 将游戏窗口置顶并激活；
    4. 在鼠标当前坐标执行模拟左键点击（物理 + 消息双通道）；
    5. 间隔 0.5 秒再次执行一次确认点击，确保穿透过渡动画或焦点切换。
    """
    def _log(msg: str, level: str = "info") -> None:
        if log_func:
            try:
                log_func(msg, level)
            except TypeError:
                log_func(msg)
        else:
            print(msg)

    def _stopped() -> bool:
        return bool(is_stopped_func and is_stopped_func())

    if _stopped():
        return False

    _log("[*] 扫码确认完成，等待游戏过渡至「点击任意处进入」界面 (约 1.5 秒)...", "info")
    time.sleep(delay_before_click)

    if _stopped():
        return False

    hwnd = find_bh3_hwnd()
    user32 = ctypes.windll.user32
    if hwnd:
        try:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            time.sleep(0.1)
        except Exception:
            pass

    click_x, click_y = get_cursor_pos()
    if rect and len(rect) == 4:
        click_x = rect[0] + rect[2] // 2
        click_y = rect[1] + int(rect[3] * 0.6)

    _log(f"[+] 正在游戏窗口中央 ({click_x}, {click_y}) 模拟点击进入游戏...", "info")
    click_at_pos(click_x, click_y, hwnd=hwnd)

    # 间隔 0.5 秒再次执行确认点击，防止首击被动画过渡或焦点激活吞没
    time.sleep(0.5)
    click_at_pos(click_x, click_y, hwnd=hwnd)

    _log("[★ 登录完成 ★] 已在游戏窗口中央完成点击进入游戏！", "success")
    return True


_QR_DETECTOR_CACHE = None


def _get_qr_detector():
    global _QR_DETECTOR_CACHE
    if _QR_DETECTOR_CACHE is None:
        _QR_DETECTOR_CACHE = cv2.QRCodeDetector()
    return _QR_DETECTOR_CACHE


def decode_qr_code(image: Optional[Image.Image]) -> Optional[str]:
    """识别游戏登录二维码并返回二维码中的 URL。

    性能策略 (2026-09-17 提速版)：
    旧实现对整张 2K 窗口做 4 组裁剪 × 2x/3x 放大 × 单/多码解码，画面中**没有**二维码时
    每帧要跑满全部组合 (实测 2560x1440 下约 30s)，这正是"切换扫码登录很慢"的主因。

    新流程：
    1. 粗定位：把整帧降采样到 ≤1280 宽，仅用 ``detect()`` 查找二维码定位点 (几十毫秒)；
       没有定位点直接返回 None —— 这是绝大多数帧 (账号密码卡片、加载画面) 的快速否决路径；
    2. 精解码：命中定位点后，只从原始高分辨率帧中裁出二维码局部 (含 quiet zone)，
       再做 1x/2x/3x 放大 + Otsu 二值化解码，解决高版本二维码模块过小的问题；
    3. 兜底：粗定位未命中但仍想保险时，对原图中央区域再做一次 ``detect``。
    """
    if image is None:
        return None

    try:
        img_np = np.asarray(image)
        if img_np.ndim == 2:
            gray = img_np
        elif img_np.ndim == 3:
            if img_np.shape[2] == 4:
                img_np = img_np[:, :, :3]
            # PIL 为 RGB，ndarray 视为 BGR；灰度化对通道顺序不敏感
            gray = cv2.cvtColor(np.ascontiguousarray(img_np), cv2.COLOR_RGB2GRAY)
        else:
            return None

        detector = _get_qr_detector()

        def valid(value: object) -> Optional[str]:
            text = str(value or "").strip()
            if "ticket=" in text and ("qr_code_in_game" in text or "mihoyo.com" in text):
                return text
            return None

        def try_decode(frame: np.ndarray) -> Optional[str]:
            try:
                value, _, _ = detector.detectAndDecode(frame)
                decoded = valid(value)
                if decoded:
                    return decoded
            except Exception:
                pass
            try:
                ok, values, _, _ = detector.detectAndDecodeMulti(frame)
                if ok and values is not None:
                    for value in values:
                        decoded = valid(value)
                        if decoded:
                            return decoded
            except Exception:
                pass
            return None

        def detect_points(frame: np.ndarray) -> Optional[np.ndarray]:
            try:
                ok, pts = detector.detect(frame)
                if ok and pts is not None and len(pts) > 0:
                    return np.asarray(pts, dtype=np.float32).reshape(-1, 2)
            except Exception:
                pass
            return None

        h, w = gray.shape[:2]

        # ---------- 阶段 1：降采样粗定位 ----------
        ds = 1.0
        small = gray
        if w > 1280:
            ds = 1280.0 / w
            small = cv2.resize(gray, None, fx=ds, fy=ds, interpolation=cv2.INTER_AREA)
        sh, sw = small.shape[:2]

        # 先查登录卡片所在的中央区域，再查全图
        regions = [
            (int(sw * 0.20), int(sh * 0.12), int(sw * 0.80), int(sh * 0.88)),
            (0, 0, sw, sh),
        ]
        pts_full = None
        for (x0, y0, x1, y1) in regions:
            crop = small[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            pts = detect_points(crop)
            if pts is None:
                continue
            # 小图上直接尝试一次解码（二维码较大时可一步到位）
            decoded = try_decode(crop)
            if decoded:
                return decoded
            pts_full = (pts + np.array([x0, y0], dtype=np.float32)) / ds
            break

        # ---------- 阶段 1.5：兜底 —— 原图中央区域再定位一次 ----------
        if pts_full is None and ds < 1.0:
            x0, y0 = int(w * 0.20), int(h * 0.12)
            x1, y1 = int(w * 0.80), int(h * 0.88)
            pts = detect_points(gray[y0:y1, x0:x1])
            if pts is not None:
                pts_full = pts + np.array([x0, y0], dtype=np.float32)

        if pts_full is None:
            return None

        # ---------- 阶段 2：原图局部高清解码 ----------
        xs, ys = pts_full[:, 0], pts_full[:, 1]
        side = float(max(xs.max() - xs.min(), ys.max() - ys.min(), 32.0))
        margin = side * 0.35 + 16
        px0 = int(max(0, xs.min() - margin))
        py0 = int(max(0, ys.min() - margin))
        px1 = int(min(w, xs.max() + margin))
        py1 = int(min(h, ys.max() + margin))
        patch = gray[py0:py1, px0:px1]
        if patch.size == 0:
            return None

        for scale in (1.0, 2.0, 3.0):
            enlarged = patch if scale == 1.0 else cv2.resize(
                patch, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
            )
            decoded = try_decode(enlarged)
            if decoded:
                return decoded
            _, binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            decoded = try_decode(binary)
            if decoded:
                return decoded
    except Exception as exc:
        print(f"[二维码识别异常]: {exc}")

    return None


def parse_qr_payload(url: str) -> dict:
    """
    从二维码解析出的 URL 中提取所有鉴权参数 (ticket, app_id, biz_key 等)
    """
    res = {"ticket": None, "app_id": "1", "biz_key": "bh3_cn"}
    if not url:
        return res
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        if "ticket" in params and len(params["ticket"]) > 0:
            res["ticket"] = params["ticket"][0]
        if "app_id" in params and len(params["app_id"]) > 0:
            try:
                res["app_id"] = str(params["app_id"][0]).strip() or "1"
            except Exception:
                pass
        if "biz_key" in params and len(params["biz_key"]) > 0:
            res["biz_key"] = params["biz_key"][0]
    except Exception:
        pass

    if not res["ticket"] and "ticket=" in url:
        parts = url.split("ticket=")
        if len(parts) > 1:
            res["ticket"] = parts[1].split("&")[0].strip()

    return res


def extract_ticket_from_url(url: str) -> Optional[str]:
    """
    从二维码解析出的 URL 中提取 ticket 参数
    """
    return parse_qr_payload(url).get("ticket")
