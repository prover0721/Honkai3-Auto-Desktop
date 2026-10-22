# -*- coding: utf-8 -*-
"""
崩坏3 分区任务执行器
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from core.runtime_guard import RuntimeViolation

# 将当前游戏目录加入搜索路径，以便调用同级模块
CURRENT_DIR = Path(__file__).parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import mihoyo_api
import qr_scanner


def detect_bh3_path() -> Optional[str]:
    """
    自动从 Windows 注册表与常见磁盘目录查找本地 BH3.exe 路径
    """
    import winreg
    roots = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    subkeys = [
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall\bh3_cn_1_1_jGHBHlcOq1_production",
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall\崩坏3",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\bh3_cn_1_1_jGHBHlcOq1_production",
    ]
    for root in roots:
        for sk in subkeys:
            try:
                with winreg.OpenKey(root, sk) as key:
                    inst, _ = winreg.QueryValueEx(key, "InstallLocation")
                    if inst:
                        cand1 = os.path.join(inst, "games", "Honkai Impact 3rd Game", "BH3.exe")
                        if os.path.isfile(cand1):
                            return os.path.normpath(cand1)
                        cand2 = os.path.join(inst, "BH3.exe")
                        if os.path.isfile(cand2):
                            return os.path.normpath(cand2)
            except Exception:
                pass

    # 常见磁盘扫描备选
    common_cands = [
        r"D:\game\mhy\miHoYo Launcher\games\Honkai Impact 3rd Game\BH3.exe",
        r"C:\Program Files\miHoYo Launcher\games\Honkai Impact 3rd Game\BH3.exe",
        r"D:\Program Files\miHoYo Launcher\games\Honkai Impact 3rd Game\BH3.exe",
    ]
    for c in common_cands:
        if os.path.isfile(c):
            return os.path.normpath(c)
    return None


def detect_bh3_version(game_path: Optional[str] = None) -> str:
    """
    自动从米哈游启动器配置文件 config.ini 读取当前安装的真实游戏版本 (如 9.1.0)
    """
    import configparser
    path = game_path or detect_bh3_path()
    candidate_inis = []
    if path and os.path.isfile(path):
        candidate_inis.append(os.path.join(os.path.dirname(path), "config.ini"))
    candidate_inis.extend([
        r"D:\game\mhy\miHoYo Launcher\games\Honkai Impact 3rd Game\config.ini",
        r"C:\Program Files\miHoYo Launcher\games\Honkai Impact 3rd Game\config.ini",
        r"D:\Program Files\miHoYo Launcher\games\Honkai Impact 3rd Game\config.ini",
    ])
    for ini_path in candidate_inis:
        if os.path.isfile(ini_path):
            try:
                cp = configparser.ConfigParser()
                cp.read(ini_path, encoding="utf-8")
                if "General" in cp and "game_version" in cp["General"]:
                    v = cp["General"]["game_version"].strip()
                    if v:
                        return v
            except Exception:
                pass
    return "9.1.0"


def launch_game(game_path: Optional[str] = None) -> tuple[bool, str]:
    """
    启动本地崩坏3客户端 (以当前用户权限正常拉起，避免 Windows UIPI 消息拦截)
    """
    path = game_path or detect_bh3_path()
    if not path or not os.path.isfile(path):
        return False, f"未找到游戏可执行文件，请检查路径: {path}"

    work_dir = os.path.dirname(path)

    # 1. 优先使用系统原生关联正常拉起 (不加 runas 提权，确保与自动化工具处于同一特权级)
    try:
        os.startfile(path)
        return True, f"已成功拉起客户端: {os.path.basename(path)}"
    except Exception:
        pass

    # 2. 备选通过 subprocess 启动
    try:
        import subprocess
        subprocess.Popen([path], cwd=work_dir)
        return True, f"已成功拉起客户端: {os.path.basename(path)}"
    except Exception:
        pass

    # 3. 兜底 ShellExecuteW ("open" 动作而非 "runas")
    try:
        import ctypes
        ret = ctypes.windll.shell32.ShellExecuteW(None, "open", path, "", work_dir, 1)
        if ret > 32:
            return True, f"已拉起客户端: {os.path.basename(path)}"
    except Exception as e:
        return False, f"启动客户端异常: {e}"

    return False, "未能启动游戏客户端"


def run_auto_login(config: dict, log_func, is_stopped_func) -> bool:
    """执行免扫码登录任务"""
    uid = config.get("uid", 0)
    access_key = config.get("access_key", "")

    # 1. 检查游戏窗口，若未启动则自动启动
    rect = qr_scanner.find_bh3_window()
    if rect is None:
        game_path = config.get("game_path") or detect_bh3_path()
        if game_path and os.path.isfile(game_path):
            log_func(f"[*] 检测到《崩坏3》尚未运行，正在自动启动客户端...", "info")
            ok, msg = launch_game(game_path)
            if ok:
                log_func(f"[+] {msg}，正在高频监听窗口并等待界面渲染...", "info")
            else:
                log_func(f"[警告] {msg}", "warning")

    # 2. 核验 B 站凭证有效性
    has_valid_auth = False
    open_id = None
    combo_id = None
    combo_token = None
    dispatch = None

    try:
        clean_uid = int(str(uid).strip())
    except Exception:
        clean_uid = 0

    server_name = config.get("server_name") or config.get("server_type") or "B服"
    channel_id = str(config.get("channel_id") or "14")
    account_type = str(config.get("account_type") or "2")
    detected_ver = detect_bh3_version(config.get("game_path"))
    bh_ver = detected_ver or config.get("bh_ver", "9.1.0")
    if config.get("bh_ver") != bh_ver:
        config["bh_ver"] = bh_ver
        try:
            config_file = CURRENT_DIR / "config.json"
            if config_file.is_file():
                import json
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
    oa_token = config.get("oa_token", mihoyo_api.DEFAULT_OA_TOKEN)
    dispatch = config.get("dispatch", "")
    if not dispatch and account_type != "1":
        dispatch = mihoyo_api.get_game_dispatch(bh_ver, oa_token, CURRENT_DIR)
    if dispatch:
        log_func(f"[*] 调度服务器载荷已装载 (长度: {len(dispatch)})", "info")
    else:
        log_func("[*] 当前版本保持 PC 原生调度通道 (不注入外部 dispatch)", "info")

    saved_combo_token = config.get("combo_token")
    saved_open_id = config.get("open_id") or (str(clean_uid) if clean_uid > 0 else "")
    saved_combo_id = config.get("combo_id", "")

    # 1. 官服协议 (account_type == "1"): 直接加载 uid 与 token (保存在 access_key 或 combo_token)
    if account_type == "1":
        open_id = saved_open_id
        combo_token = saved_combo_token or access_key
        combo_id = saved_combo_id
        if open_id and combo_token:
            has_valid_auth = True
            log_func(f"[+] 已加载【{server_name}】官方登舰凭据 (UID: {open_id})", "success")
        else:
            log_func(f"[警告] 【{server_name}】凭据不完整，请在配置中重新导入扫码器备份！", "warning")
    # 2. B 站渠道服且具备 access_key：执行米哈游 GameSDK 握手与验签
    elif clean_uid > 0 and access_key and channel_id == "14":
        log_func(f"[*] 正在核验 B 站授权凭证 (UID: {clean_uid})...", "info")
        mi_res = mihoyo_api.verify_bili_account(clean_uid, access_key)
        if mi_res.get("retcode") == 0 and "data" in mi_res:
            mi_data = mi_res["data"]
            open_id = mi_data["open_id"]
            combo_id = mi_data["combo_id"]
            combo_token = mi_data["combo_token"]
            has_valid_auth = True
            log_func("[+] B 站凭证与米哈游协议握手成功！", "success")
        else:
            log_func(f"[警告] B 站凭据核验未通过: {mi_res.get('message', '未知错误')}（登录态已过期），请在控制台点击【🔑 账号授权】重新授权！", "warning")
            has_valid_auth = False
    # 3. 其他厂商渠道服（vivo/oppo/华为/小米/应用宝等）或未配置 access_key 的持久化 combo_token
    elif not access_key and saved_combo_token and saved_open_id:
        open_id = saved_open_id
        combo_id = saved_combo_id
        combo_token = saved_combo_token
        has_valid_auth = True
        log_func(f"[+] 已加载【{server_name}】免密登舰凭据！", "success")
    else:
        log_func(f"[提示] 当前尚未绑定有效【{server_name}】凭证。本次将执行窗口检测与自动切换二维码，若要实现秒级自动登舰，请点击【🔑 账号授权】完成绑定或导入备份！", "warning")

    log_func(f"[*] 正在监听《崩坏3》窗口并进入【{server_name}】智能登舰状态机 (最长等待 180 秒)...", "info")
    max_wait = 180  # 放宽至 180 秒，从容应对客户端防作弊与片头加载
    start_time = time.time()
    last_toggle_action_time = 0.0
    toggle_clicked_count = 0
    max_toggle_attempts = 3
    toggle_retry_interval = 2.0
    last_toggle_limit_log_time = 0.0
    last_status_log_time = 0.0
    # 状态 0 (舰桥/福利弹窗) 检测涉及十余次模板匹配 (2K 画面约 2.5s)，
    # 只需首帧立即检测，之后每 3 秒复查一次即可；其余帧全部让给二维码/角标识别，
    # 让"切换扫码 → 捕获二维码"的轮询间隔缩短到 0.3s 级别。
    last_state0_check_time = 0.0
    state0_interval = 3.0

    from games.honkai3.core.ui_vision import UIVision
    from games.honkai3.core.page import PageNavigator, PAGE_MAIN, TPL_MAIN_GOTO_BATTLE
    from games.honkai3.core.popup import (
        PopupHandler,
        TPL_POPUP_CLAIM, TPL_TAB_SIGNIN, TPL_MONTHLY_SIGNIN_TAB,
        TPL_MONTHLY_CLAIM, TPL_MONTHLY_500_CLAIM,
        TPL_7DAY_CLAIM, TPL_SIGNIN_CLAIM, TPL_EVENT_FLAG, TPL_EVENT_PROMO_TITLE,
        TPL_EVENT_PROMO_CLOSE, TPL_ABYSS_SETTLE, TPL_ABYSS_DYNAMIC, TPL_NEW_ITEM, TPL_PROMO_DISMISS_HINT
    )
    pre_vision = UIVision()
    pre_navigator = PageNavigator(pre_vision)
    # 状态 0 只做"是否已在游戏内"的判定，必须使用本函数自己的视觉上下文。
    # 不能引用下面 _get_context() 才创建的 popup_handler/screen，否则未进入
    # 该分支时会抛 UnboundLocalError，导致免扫码登录直接失败。
    pre_popup = PopupHandler(pre_vision)

    while time.time() - start_time < max_wait:
        if is_stopped_func():
            log_func("[!] 用户已中止任务", "warning")
            return False

        rect = qr_scanner.find_bh3_window()
        if not rect:
            now = time.time()
            if now - last_status_log_time > 5.0:
                elapsed = int(now - start_time)
                log_func(f"[*] 等待《崩坏3》游戏主窗口启动中... ({elapsed}s / {max_wait}s)", "info")
                last_status_log_time = now
            time.sleep(1)
            continue

        img = qr_scanner.capture_screen_or_window(rect)
        if img is None:
            time.sleep(0.5)
            continue

        # 状态 0：前置自适应检测 —— 若游戏已在运行且已处于舰桥或登录开门弹窗，直接跳过扫码进入就绪状态
        # (节流：首帧 + 每 3 秒一次，避免每帧 2 秒以上的模板匹配拖慢扫码切换)
        has_popup = False
        at_main = False
        now_s0 = time.time()
        if now_s0 - last_state0_check_time >= state0_interval:
            last_state0_check_time = now_s0
            has_popup = (
                pre_vision.exists(img, TPL_PROMO_DISMISS_HINT) or
                pre_vision.exists(img, TPL_POPUP_CLAIM) or
                pre_vision.exists(img, TPL_TAB_SIGNIN) or
                pre_vision.exists(img, TPL_MONTHLY_SIGNIN_TAB) or
                pre_vision.exists(img, TPL_MONTHLY_CLAIM) or
                pre_vision.exists(img, TPL_MONTHLY_500_CLAIM) or
                pre_vision.exists(img, TPL_7DAY_CLAIM) or
                pre_vision.exists(img, TPL_SIGNIN_CLAIM) or
                pre_vision.exists(img, TPL_EVENT_FLAG) or
                (pre_vision.exists(img, TPL_EVENT_PROMO_TITLE) and
                 pre_vision.exists(img, TPL_EVENT_PROMO_CLOSE)) or
                pre_vision.exists(img, TPL_ABYSS_SETTLE) or
                pre_vision.exists(img, TPL_NEW_ITEM)
            )
            at_main = has_popup or (
                pre_navigator.detect_current_page(img) == PAGE_MAIN or
                pre_vision.exists(img, PAGE_MAIN.flag) or
                pre_vision.exists(img, TPL_MAIN_GOTO_BATTLE)
            )
            # 关闭控件全画幅搜索在 2K 画面上约 1.6s/帧，必须留在 3 秒节流块内，
            # 否则扫码/角标轮询会被拖慢到不可用。
            if not (has_popup or at_main):
                at_main = pre_popup.has_close(img) is True
        if has_popup or at_main:
            log_func("[+] 检测到游戏当前已处于运行与登录状态（已进入舰桥或登录福利弹窗），无需重复扫码！", "success")
            w_rect, capture, nav, vis, popup_handler = _get_context(log_func)
            if not (w_rect and capture and vis):
                return False
            if w_rect and capture and vis:
                bridge_ok = wait_until_bridge_ready(
                    window_rect=w_rect,
                    capture_func=capture,
                    navigator=nav,
                    vision=vis,
                    popup_handler=popup_handler,
                    log_func=log_func,
                    is_stopped_func=is_stopped_func,
                )
                if not bridge_ok:
                    return False
            return True

        # 状态 A：画面中已出现二维码（无论由程序翻转还是用户手动切换）
        qr_text = qr_scanner.decode_qr_code(img)
        if qr_text:
            qr_info = qr_scanner.parse_qr_payload(qr_text)
            ticket = qr_info.get("ticket")
            app_id = qr_info.get("app_id", 1)
            biz_key = qr_info.get("biz_key", "bh3_cn")
            if ticket:
                log_func(f"[+] 成功捕获登录二维码 (Ticket: {ticket[:10]}..., AppID: {app_id})", "success")
                if not has_valid_auth:
                    log_func(f"[★ 捕获成功 ★] 已成功检测到二维码并解析出 Ticket！请在平台配置中点击【🔑 账号授权】绑定【{server_name}】凭据，即可全自动免扫码登舰；本次登录尚未完成。", "warning")
                    return False

                if not dispatch and account_type != "1":
                    dispatch = mihoyo_api.get_game_dispatch(bh_ver, oa_token, CURRENT_DIR)

                if not dispatch and account_type != "1":
                    # 强熔断保护：B服/渠道服若无有效 dispatch，严禁发起自动扫码与确认
                    # 否则会向客户端推送空数据导致 ArgumentNullException 崩溃
                    if now - last_toggle_limit_log_time > 5.0:
                        log_func(f"[安全熔断] 当前版本 ({bh_ver}) 尚未获取到有效 dispatch 调度包。保持二维码展示，请使用手机端直接扫码登录！", "warning")
                        last_toggle_limit_log_time = now
                    time.sleep(1)
                    continue

                log_func("[*] 正在向米哈游服务器发送扫码通知 (qrcode/scan)...", "info")
                # scan 与 confirm 必须共用同一个 ts：服务端按扫码阶段记录的
                # device/app_id/ts/ticket 校验 confirm 的签名。
                scan_ts = int(time.time() * 1000)
                scan_res = mihoyo_api.scan_qrcode(ticket, app_id=app_id, biz_key=biz_key, ts=scan_ts)
                if scan_res.get("retcode") != 0:
                    log_func(f"[!] 扫码通知返回异常: {scan_res.get('message')}", "warning")
                    time.sleep(1)
                    continue

                log_func(f"[*] 正在向米哈游服务器发送【{server_name}】免密授权确认 (qrcode/confirm)...", "info")
                confirm_res = mihoyo_api.confirm_qrcode(
                    ticket=ticket,
                    open_id=open_id,
                    combo_id=combo_id,
                    combo_token=combo_token,
                    dispatch=dispatch,
                    app_id=app_id,
                    channel_id=channel_id,
                    account_type=account_type,
                    biz_key=biz_key,
                    sign_ts=scan_ts
                )

                if confirm_res.get("retcode") == 0:
                    log_func(f"[★ 成功 ★] 【{server_name}】登录授权成功！", "success")
                    # 登录成功后客户端会停在「点击任意处进入」画面，
                    # 自动等待该画面出现并模拟点击，直到进入游戏加载。
                    try:
                        qr_scanner.wait_and_click_enter_game(
                            rect,
                            log_func=log_func,
                            is_stopped_func=is_stopped_func,
                        )
                    except Exception as e:
                        log_func(f"[提示] 自动点击进入游戏环节异常: {e}，如停在「点击进入」画面请手动点击。", "warning")

                    # 等待游戏脱离电梯加载期并真正抵达舰桥主界面（或自动消解登录弹窗）
                    w_rect, capture, navigator, vision, popup_handler = _get_context(log_func)
                    if not (w_rect and capture and vision):
                        return False
                    if w_rect and capture and vision:
                        bridge_ok = wait_until_bridge_ready(
                            window_rect=w_rect,
                            capture_func=capture,
                            navigator=navigator,
                            vision=vision,
                            popup_handler=popup_handler,
                            log_func=log_func,
                            is_stopped_func=is_stopped_func,
                        )
                        if not bridge_ok:
                            return False
                    return True
                else:
                    log_func(f"[错误] 授权确认失败: {confirm_res.get('message')} (retcode: {confirm_res.get('retcode')})", "error")
                    return False

        # 状态 B：只对视觉识别到的二维码切换角标点击。
        # 若角标持续存在，说明界面没有翻转，间隔重试最多三次；不再要求角标先消失，
        # 否则第一次点击未生效时会永久等待，也不对未识别画面做几何盲点。
        now = time.time()
        toggle_pos = qr_scanner.find_qr_toggle_button(img)
        if toggle_pos is not None:
            if toggle_clicked_count >= max_toggle_attempts:
                # 已达到最大重试次数，保持等待并适度休眠，避免高频占用 CPU
                time.sleep(0.5)
                continue
            if now - last_toggle_action_time < toggle_retry_interval:
                # 间隔防抖：等待界面翻转动画或二维码呈现
                time.sleep(0.1)
                continue
            last_toggle_action_time = now
            toggle_clicked_count += 1
            log_func(f"[+] 画面已识别到扫码切换角标 (坐标: {toggle_pos})，发送第 {toggle_clicked_count}/{max_toggle_attempts} 次切换单击...", "info")
            if not qr_scanner.switch_to_qr_login(rect, target_pos=toggle_pos):
                log_func("[错误] 扫码切换角标点击未能发送（窗口不可用或坐标无效）。", "error")
                return False
            time.sleep(0.5)
            continue
        else:
            dialog_btn_pos = qr_scanner.find_dialog_confirm_button(img)
            if dialog_btn_pos is not None:
                if now - last_toggle_action_time > 2.0:
                    last_toggle_action_time = now
                    log_func(f"[+] 画面识别到提示弹窗【确定】(坐标: {dialog_btn_pos})，自动单击消解弹窗...", "info")
                    qr_scanner.click_at_pos(rect[0] + dialog_btn_pos[0], rect[1] + dialog_btn_pos[1])
                    time.sleep(0.5)
                    continue

            account_btn_pos = qr_scanner.find_account_login_button(img)
            if account_btn_pos is not None:
                if now - last_toggle_action_time > 2.0:
                    last_toggle_action_time = now
                    log_func(f"[+] 画面识别到【请选择登录方式】(按钮坐标: {account_btn_pos})，自动单击【账号登录】调起登录弹窗...", "info")
                    qr_scanner.click_at_pos(rect[0] + account_btn_pos[0], rect[1] + account_btn_pos[1])
                    time.sleep(0.5)
                    continue

            # 状态 C：当前没有可识别的二维码或切换角标，可能仍在加载；耐心等待，不乱点。
            elapsed = int(now - start_time)
            if now - last_status_log_time > 5.0:
                log_func(f"[*] 游戏正在加载或等待到达登录卡片... ({elapsed}s / {max_wait}s)", "info")
                last_status_log_time = now

        time.sleep(0.08)

    log_func("[超时] 180 秒内未检测到登录二维码，请确认游戏是否正常启动并停留在登录界面！", "error")
    return False


def _get_context(log_func):
    rect = qr_scanner.find_bh3_window()
    if not rect:
        log_func("[!] 未检测到《崩坏3》游戏主窗口，请确认游戏是否已启动！", "error")
        return None, None, None, None, None

    from games.honkai3.core.ui_vision import UIVision, activate_game_window, to_bgr
    from games.honkai3.core.page import PageNavigator
    from games.honkai3.core.popup import PopupHandler

    vision = UIVision()
    navigator = PageNavigator(vision)
    popup_handler = PopupHandler(vision)

    # GameHub 启动子任务时通常仍占据前台。登录阶段可通过窗口消息完成，
    # 但日常任务使用受前台守护保护的物理输入；若不在这里主动接管焦点，
    # 后续所有点击都会被安全拒绝。只在每个任务建立上下文时激活一次，
    # 用户在任务运行中主动切走后仍会触发安全暂停。
    if not activate_game_window(log_func=log_func, timeout=3.0):
        return None, None, None, None, None

    def capture():
        r = qr_scanner.find_bh3_window()
        if not r:
            return None
        if tuple(r) != tuple(rect):
            log_func('[安全终止] 游戏窗口位置或大小改变，旧任务坐标失效，请重新启动当前任务。', 'error')
            return None
        return qr_scanner.capture_screen_or_window(r)

    # 模板按 1280×720 的 16:9 画布制作；不兼容的窗口比例会让 ROI 和
    # 点击位置同时偏移。允许标题栏/边框造成的小幅误差，超出则拒绝动作。
    first_frame = to_bgr(capture())
    if first_frame is None:
        log_func("[安全终止] 游戏截图失败，请检查窗口/截图方式，未执行日常点击。", "error")
        return None, None, None, None, None
    frame_h, frame_w = first_frame.shape[:2]
    if frame_h < 360 or abs(frame_w / frame_h - 16 / 9) > 0.10:
        log_func(
            f"[安全终止] 游戏截图尺寸 {frame_w}×{frame_h} 不适合当前 16:9 模板，"
            "请将游戏设为 16:9 后重试；未执行日常点击。",
            "error",
        )
        return None, None, None, None, None

    return rect, capture, navigator, vision, popup_handler


def wait_until_bridge_ready(
    window_rect,
    capture_func,
    navigator,
    vision,
    popup_handler,
    log_func=None,
    is_stopped_func=None,
    max_wait: int = 50,
) -> bool:
    """
    等待资源加载并清理已识别的签到、福利及活动弹窗。
    清理后重新截图确认舰桥；误入已适配的活动页时识别返回。
    未知界面保持等待，只有确认舰桥才返回 True。
    """
    if log_func:
        log_func("[*] 正在等待游戏完成资源加载并进入舰桥主界面 (最长等待 50 秒)...", "info")

    from games.honkai3.core.page import PAGE_MAIN, PAGE_PART2, TPL_PART2_BACK, TPL_EVENT_ACTIVITY_BACK
    from games.honkai3.core.popup import (
        TPL_POPUP_CLAIM, TPL_TAB_SIGNIN, TPL_MONTHLY_SIGNIN_TAB,
        TPL_MONTHLY_CLAIM, TPL_MONTHLY_500_CLAIM,
        TPL_7DAY_CLAIM, TPL_SIGNIN_CLAIM, TPL_EVENT_FLAG, TPL_EVENT_PROMO_TITLE,
        TPL_EVENT_PROMO_CLOSE, TPL_ABYSS_SETTLE, TPL_ABYSS_DYNAMIC, TPL_NEW_ITEM, TPL_PROMO_DISMISS_HINT
    )

    start_t = time.time()

    while time.time() - start_t < max_wait:
        if is_stopped_func and is_stopped_func():
            return False

        screen = capture_func()
        if screen is None:
            time.sleep(1.0)
            continue

        now = time.time()
        elapsed = int(now - start_t)

        if navigator.detect_current_page(screen) is PAGE_PART2:
            if not vision.click_template(window_rect, screen, TPL_PART2_BACK, log_func=log_func):
                return False
            if log_func:
                log_func("[恢复] 已识别第二部场景，点击左上角返回，等待主界面。", "info")
            time.sleep(1.0)
            continue

        # 1. 检查是否有登录拦截弹窗 (第二部福利、每日签到、月卡、活动公告、深渊结算等)
        has_event_promo = (vision.exists(screen, TPL_EVENT_PROMO_TITLE)
                           or vision.exists(screen, TPL_PROMO_DISMISS_HINT))
        has_popup = (
            vision.exists(screen, TPL_POPUP_CLAIM) or
            vision.exists(screen, TPL_TAB_SIGNIN) or
            vision.exists(screen, TPL_MONTHLY_SIGNIN_TAB) or
            vision.exists(screen, TPL_MONTHLY_CLAIM) or
            vision.exists(screen, TPL_MONTHLY_500_CLAIM) or
            vision.exists(screen, TPL_7DAY_CLAIM) or
            vision.exists(screen, TPL_SIGNIN_CLAIM) or
            vision.exists(screen, TPL_EVENT_FLAG) or
            has_event_promo or
            vision.exists(screen, TPL_ABYSS_SETTLE) or vision.exists(screen, TPL_ABYSS_DYNAMIC) or
            vision.exists(screen, TPL_NEW_ITEM)
        )

        if has_popup or popup_handler.has_close(screen) is True:
            if log_func:
                log_func(f"[+] 检测到登录弹窗（福利/签到/月卡/活动宣传等），先清理并重新确认舰桥 (耗时 {elapsed}s)...", "info")
                log_func("[*] 正在一键清理开门弹窗...", "info")
            popup_handler.handle_all_clear(window_rect, capture_func, log_func=log_func)
            time.sleep(1.0)
            continue

        # 若此前误入活动页面，点击录屏中校准过的左上角返回；继续等待，直到真正回到舰桥。
        if vision.click_template(window_rect, screen, TPL_EVENT_ACTIVITY_BACK, log_func=log_func):
            if log_func:
                log_func("[!] 检测到已进入活动页面，已点击识别到的返回控件；回到舰桥后继续日常。", "warning")
            time.sleep(1.0)
            continue

        # 2. 检测是否直接进入了主界面 (主界面标志 或 出击按钮 或 页面识别)
        at_main = navigator.detect_current_page(screen) == PAGE_MAIN

        if at_main:
            if log_func:
                log_func(f"[★ 就绪 ★] 游戏已成功载入舰桥主界面 (耗时 {elapsed}s)！", "success")
            time.sleep(1.0)
            return True

        if elapsed % 6 == 0 and elapsed > 0:
            if log_func:
                log_func(f"[*] 尚未识别到舰桥或活动返回控件；继续等待且不做坐标盲点 ({elapsed}s / {max_wait}s)", "info")

        time.sleep(1.0)

    if log_func:
        log_func("[错误] 等待舰桥主界面超时 (50s)，未能成功进入主界面或消除弹窗！为防止盲目执行日常任务，流水线终止。", "error")
    return False


def close_game(log_func=None) -> bool:
    """优雅终止 BH3.exe 游戏进程并释放系统显存与内存"""
    import psutil
    closed = False
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            pname = proc.info.get('name') or ""
            if pname.lower() in ('bh3.exe', 'honkai3.exe'):
                proc.terminate()
                closed = True
                if log_func:
                    log_func(f"[+] 游戏进程 (PID: {proc.info['pid']}) 已收到终止信号，正在退出...", "info")
        except Exception:
            pass
    if closed and log_func:
        log_func("[★ 退出 ★] 《崩坏3》客户端已顺利退出，显存与系统资源已释放！", "success")
    return closed


def run_task(task_id: str, config: dict, log_func, is_stopped_func) -> bool:
    from core.runtime_guard import RuntimeViolation
    from games.honkai3.core.task_guard import HonkaiTaskGuard
    from games.honkai3.core.page import PAGE_MAIN, PAGE_DORM
    if is_stopped_func():
        return False
    if task_id == 'auto_login':
        return run_auto_login(config, log_func, is_stopped_func)
    if task_id == 'auto_close':
        return close_game(log_func=log_func)
    if task_id == 'arena_sweep':
        import datetime
        now = datetime.datetime.now()
        if now.weekday() == 0 or (now.weekday() == 1 and now.hour < 4):
            log_func('[跳过] 记忆战场处于结算关闭期，无需出击。', 'info')
            return True
    context = _get_context(log_func)
    rect, capture, navigator, vision, popup_handler = context
    if not rect:
        return False
    guard = HonkaiTaskGuard(task_id, rect, capture, navigator, vision, popup_handler, log_func, is_stopped_func)
    try:
        guard.prepare()
        success = _dispatch_guarded_task(task_id, rect, guard.capture, navigator, vision, popup_handler, log_func, is_stopped_func)
        expected = PAGE_DORM if task_id == 'dorm_errand' else PAGE_MAIN
        return guard.finish(success, expected)
    except RuntimeViolation as exc:
        log_func('[任务终止] ' + str(exc), 'error')
        return False
    except Exception as exc:
        try:
            guard.runtime.fail('任务异常: ' + type(exc).__name__ + ': ' + str(exc))
        except RuntimeViolation:
            pass
        return False
    finally:
        guard.close()


def _dispatch_guarded_task(task_id, rect, capture, navigator, vision, popup_handler, log_func, is_stopped_func):
    if task_id == "handle_popups":
        log_func("[*] 正在扫描并清理主界面弹窗（月卡/签到/结算/公告）...", "info")
        return wait_until_bridge_ready(rect, capture, navigator, vision, popup_handler, log_func, is_stopped_func)

    elif task_id == "daily_sweep":
        from games.honkai3.tasks.task_sweep import run_sweep_task
        log_func("[*] 日常流程版本 2026-10-11：统一推荐页→材料远征→减负→确定。", "info")
        return run_sweep_task(rect, capture, navigator, vision, log_func, is_stopped_func)

    elif task_id == "arena_sweep":
        from games.honkai3.tasks.task_arena import run_arena_task
        return run_arena_task(rect, capture, navigator, vision, popup_handler, log_func, is_stopped_func)

    elif task_id == "dorm_errand":
        from games.honkai3.tasks.task_dorm import run_dorm_task
        return run_dorm_task(rect, capture, navigator, vision, log_func, is_stopped_func)

    elif task_id == "expedition":
        from games.honkai3.tasks.task_expedition import run_expedition_task
        log_func("[*] 日常流程版本 2026-10-08：远征作战奖励确定→一键远征→远征派遣。", "info")
        return run_expedition_task(rect, capture, navigator, vision, log_func, is_stopped_func)

    elif task_id == "daily_errand":
        # 兼容项：合并执行家园与远征
        from games.honkai3.tasks.task_dorm import run_dorm_task
        from games.honkai3.tasks.task_expedition import run_expedition_task
        from games.honkai3.core.daily_ui import TPL_EXPEDITION_DIALOG, reward_dialog_visible
        screen = capture()
        pending_expedition = (screen is not None and (
            vision.exists(screen, TPL_EXPEDITION_DIALOG) or reward_dialog_visible(screen, vision)))
        if pending_expedition:
            # Finish the interrupted expedition before navigating through home.
            if not run_expedition_task(rect, capture, navigator, vision, log_func, is_stopped_func):
                return False
            return run_dorm_task(rect, capture, navigator, vision, log_func, is_stopped_func)
        ok1 = run_dorm_task(rect, capture, navigator, vision, log_func, is_stopped_func)
        if not ok1:
            return False
        ok2 = run_expedition_task(rect, capture, navigator, vision, log_func, is_stopped_func)
        return ok1 and ok2

    elif task_id == "missions":
        from games.honkai3.tasks.task_mission import run_mission_task
        return run_mission_task(rect, capture, navigator, vision, log_func, is_stopped_func)

    else:
        log_func(f"[警告] 未知任务类型: {task_id}", "warning")
        return False
