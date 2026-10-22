# -*- coding: utf-8 -*-
"""
米哈游崩坏3 PC端 渠道服二维码鉴权与登录确认接口
基于 HonkaiScanner 开源协议实现。

注意：qrcode/confirm 的 dispatch 不是 PC 客户端的 query_gameserver 死数据，
而是 OA 登录流程使用的 gf_android_bilibili 调度载荷。客户端随后会根据
该载荷换取真正的网关与数据版本。
"""
import base64
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from typing import Any, Optional, Union

import requests

# 官方认证 Key (来自 HonkaiScanner 逆向提取)
BH3_KEY = "0ebc517adb1b62c6b408df153331f9aa"
DEFAULT_OA_TOKEN = "ebdda08dce6feb6bc552d393bae58c81"
# B 服协议固定值：channel_id 表示渠道，account_type 表示渠道服账号类型。
BILI_CHANNEL_ID = "14"
BILI_ACCOUNT_TYPE = "2"
DEFAULT_BIZ_KEY = "bh3_cn"
# 扫码确认使用的 device_id。参考实现读取手机 ANDROID_ID；本工具在 PC 上
# 运行，沿用实测成功的外置扫码器设备 ID（自其成功登录请求中提取）。
# 服务端把 device 记录进扫码会话并用于 confirm 验签，与账号凭据无绑定。
BILI_DEVICE_ID = "f770fbebc62ee6ef"
_DEAD_DISPATCH = "YeMJ1H0/nSVVsznghWZbMZDM0oNtsLhzI/NhBJg6THo="
_BIZ_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def bh3_sign(data_str: str) -> str:
    """计算米哈游接口专用的 HMAC-SHA256 签名。"""
    return hmac.new(
        BH3_KEY.encode("utf-8"),
        data_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _java_value(value: Any) -> str:
    """将 Python 值转换成 Java HashMap.toString() 中的值形式。

    外置扫码器在 confirm 请求中把 payload(JSONObject) 放入 HashMap 后签名。
    Python 直接对 dict 使用 repr 会产生单引号，和 Java 的 JSON 字符串不同，
    从而导致服务端校验失败。嵌套对象必须使用紧凑 JSON。
    """
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _signature_text(data: dict) -> str:
    return "&".join(
        f"{key}={_java_value(data[key])}"
        for key in sorted(data)
        if key != "sign"
    ).replace(" ", "")


def make_sign(data: dict) -> dict:
    """对请求字典进行参数字母序排序并附加 sign 签名。"""
    data["sign"] = bh3_sign(_signature_text(data))
    return data


def _normalise_biz_key(biz_key: str | None) -> str:
    value = str(biz_key or DEFAULT_BIZ_KEY).strip()
    return value if _BIZ_KEY_RE.fullmatch(value) else DEFAULT_BIZ_KEY


def _json_response(resp: requests.Response, error_prefix: str) -> dict:
    try:
        result = resp.json()
        return result if isinstance(result, dict) else {"retcode": -1, "message": f"{error_prefix}: 返回格式错误"}
    except Exception:
        text = (resp.text or "").strip()
        return {
            "retcode": -1,
            "message": f"{error_prefix}: HTTP {resp.status_code} 非 JSON 返回",
            "raw_length": len(text),
        }


def verify_bili_account(uid: int | str, access_key: str) -> dict:
    """向米哈游服务器核验 B 站游戏凭证，获取 open_id、combo_id、combo_token。"""
    url = "https://api-sdk.mihoyo.com/bh3_cn/combo/granter/login/v2/login"
    try:
        clean_uid = int(str(uid).strip())
    except Exception:
        clean_uid = 0

    account_data = json.dumps(
        {"uid": clean_uid, "access_key": str(access_key)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    body = make_sign(
        {
            "device": BILI_DEVICE_ID,
            "app_id": 1,
            "channel_id": 14,
            "data": account_data,
        }
    )
    try:
        resp = requests.post(
            url,
            data=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        return _json_response(resp, "米哈游凭证接口")
    except Exception as exc:
        return {"retcode": -1, "message": f"米哈游接口请求异常: {exc}"}


def _is_valid_dispatch(text: str) -> bool:
    """只接受可解码且不是 32 字节死回包的 Base64 调度载荷。"""
    text = (text or "").strip()
    if not text or text.startswith("{") or text == _DEAD_DISPATCH:
        return False
    try:
        decoded = base64.b64decode(text, validate=True)
    except Exception:
        return False
    return len(decoded) >= 64


# 9.0.0 版 B 服真实 OA dispatch（2026-09-13 从外置扫码器成功登录请求中提取）。
# 米哈游已将 region_list/OA 载荷改为 AES 加密回包，公开端点
# (query_dispatch / query_gameserver) 对 9.0.0 只返回死数据或过时数据，
# 无法再获取当前版本有效载荷。该值是版本级静态服务器配置（网关/区服地址），
# 大版本更新前稳定，可通过扫码器 App 日志的 enc_oaserver 字段刷新。
_KNOWN_DISPATCH_V9 = (
    "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"
)



# 静态种子映射字典（离线兜底，内置已提取的有效大版本）
_SEED_DISPATCH_MAP: dict[str, str] = {
    "9.0.0_gf_android_bilibili": _KNOWN_DISPATCH_V9,
    "9.0.0": _KNOWN_DISPATCH_V9,
}

# 高可用云端配置表源列表 (多源容灾)
_CLOUD_DISPATCH_URLS = [
    # 国内快速 CDN 节点 / GitHub 镜像
    "https://raw.githubusercontent.com/HonkaiScanner/bh3_dispatch_table/main/dispatch_table.json",
    "https://fastly.jsdelivr.net/gh/HonkaiScanner/bh3_dispatch_table@main/dispatch_table.json",
    "https://gitee.com/HonkaiScanner/bh3_dispatch_table/raw/main/dispatch_table.json",
]


def fetch_cloud_dispatch(version_key: str, timeout: float = 3.0) -> Optional[str]:
    """从高可用云端映射表或上游调度节点拉取最新版本的 dispatch。"""
    version_key = (version_key or "").strip()
    if not version_key:
        return None

    # 1. 优先遍历镜像配置表
    for url in _CLOUD_DISPATCH_URLS:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 GameHub/Auto"}, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                dispatches = data.get("dispatches", data)
                cand = dispatches.get(version_key) or dispatches.get(version_key.split("_")[0])
                if cand and _is_valid_dispatch(cand):
                    return cand.strip()
        except Exception:
            continue

    # 2. 备用：检查专用 B 服 OA 调度数据接口
    try:
        oa_url = "https://api.v6qbb.cloud/get_bh3_bilibili_oa"
        resp = requests.get(oa_url, headers={"User-Agent": "Mozilla/5.0 GameHub/Auto"}, timeout=timeout)
        if resp.status_code == 200:
            cand = resp.text.strip()
            if cand and _is_valid_dispatch(cand):
                return cand
    except Exception:
        pass

    # 3. 备用：尝试向官方扫码器上游端点查询
    try:
        upstream_url = f"https://api-v2.scanner.hellocraft.xyz/v4/query_dispatch/?version={version_key}"
        resp = requests.get(upstream_url, headers={"User-Agent": "okhttp/3.14.9"}, timeout=timeout)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("retcode") == 0 and res_json.get("data"):
                cand = res_json.get("data")
                if cand and _is_valid_dispatch(cand):
                    return cand.strip()
    except Exception:
        pass

    return None


def get_cached_dispatch(bh_ver: str, config_dir: Optional[Union[str, Path]] = None) -> Optional[str]:
    """从本地 config.json 读取 dispatch 缓存。"""
    cfg_paths = []
    if config_dir:
        cfg_paths.append(Path(config_dir) / "config.json")
    cfg_paths.extend([
        Path(__file__).parent / "config.json",
        Path.cwd() / "games" / "honkai3" / "config.json",
        Path.cwd() / "bh3_auto_login" / "config.json",
    ])
    req_key = f"{bh_ver}_gf_android_bilibili"
    for p in cfg_paths:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cache = cfg.get("dispatch_cache", {})
                cand = cache.get(req_key) or cache.get(bh_ver)
                if cand and _is_valid_dispatch(cand):
                    return cand.strip()
            except Exception:
                continue
    return None


def set_cached_dispatch(bh_ver: str, dispatch_val: str, config_dir: Optional[Union[str, Path]] = None) -> None:
    """将获取成功的 dispatch 持久化写入本地 config.json。"""
    if not _is_valid_dispatch(dispatch_val):
        return
    cfg_paths = []
    if config_dir:
        cfg_paths.append(Path(config_dir) / "config.json")
    cfg_paths.extend([
        Path(__file__).parent / "config.json",
        Path.cwd() / "games" / "honkai3" / "config.json",
        Path.cwd() / "bh3_auto_login" / "config.json",
    ])
    req_key = f"{bh_ver}_gf_android_bilibili"
    for p in cfg_paths:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "dispatch_cache" not in cfg or not isinstance(cfg["dispatch_cache"], dict):
                    cfg["dispatch_cache"] = {}
                cfg["dispatch_cache"][req_key] = dispatch_val
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=4)
            except Exception:
                continue


def get_game_dispatch(
    bh_ver: str = "9.1.0",
    oa_token: str = DEFAULT_OA_TOKEN,
    config_dir: Optional[Union[str, Path]] = None,
) -> str:
    """获取 B 服 OA 登录所需的调度载荷。

    三级自愈加载策略：
    1. 第一级：本地持久化缓存（config.json -> dispatch_cache，0 延迟秒登）；
    2. 第二级：静态离线种子映射（_SEED_DISPATCH_MAP，内置已知版本，断网兜底）；
    3. 第三级：自动向云端镜像/上游节点发起静默热拉取，拉取成功后自动回写本地缓存。
    """
    version = str(bh_ver or "9.1.0").strip()
    req_key = f"{version}_gf_android_bilibili"

    # 1. 检查本地缓存
    cached = get_cached_dispatch(version, config_dir)
    if cached:
        return cached

    # 2. 检查静态离线种子
    if req_key in _SEED_DISPATCH_MAP:
        return _SEED_DISPATCH_MAP[req_key]
    if version in _SEED_DISPATCH_MAP:
        return _SEED_DISPATCH_MAP[version]

    # 3. 自动向云端镜像/上游热拉取
    cloud_cand = fetch_cloud_dispatch(req_key)
    if cloud_cand:
        set_cached_dispatch(version, cloud_cand, config_dir)
        return cloud_cand

    return ""


def scan_qrcode(
    ticket: str,
    app_id: int = 1,
    biz_key: str = DEFAULT_BIZ_KEY,
    ts: Optional[int] = None,
) -> dict:
    """向米哈游发送已扫码通知（第一阶段握手）。

    ``ts`` 由调用方生成并与随后的 confirm 共用，**不要在两次握手各生成一次**。

    参考实现 QRScanner.start() 把 device/app_id/ts/ticket 存进同一个
    ``qr_check_map``，confirm 时只往这个 Map 里补一个 payload 再调
    ``Encrypt.bh3Sign``：也就是说 confirm 的签名用的是**扫码阶段的时间戳**，
    只有请求体里的 ``ts`` 是新生成的。服务端按扫码时记录的那份参数校验签名，
    两次握手各用各的 ts 会导致 confirm 验签失败。
    """
    url = f"https://api-sdk.mihoyo.com/{_normalise_biz_key(biz_key)}/combo/panda/qrcode/scan"
    scan_ts = int(ts) if ts is not None else int(time.time() * 1000)
    check = make_sign(
        {
            "app_id": int(app_id),
            "device": BILI_DEVICE_ID,
            "ticket": ticket,
            "ts": scan_ts,
        }
    )
    try:
        resp = requests.post(
            url,
            data=json.dumps(check, ensure_ascii=False, separators=(",", ":")),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        return _json_response(resp, "扫码通知接口")
    except Exception as exc:
        return {"retcode": -1, "message": f"扫码通知网络异常: {exc}"}


def confirm_qrcode(
    ticket: str,
    open_id: str,
    combo_id: str,
    combo_token: str,
    dispatch: str,
    app_id: int = 1,
    channel_id: str = BILI_CHANNEL_ID,
    account_type: str = BILI_ACCOUNT_TYPE,
    biz_key: str = DEFAULT_BIZ_KEY,
    sign_ts: Optional[int] = None,
) -> dict:
    """向米哈游发送确认登录授权通知（第二阶段握手）。

    ``sign_ts`` 必须是调用 scan_qrcode 时使用的那个 ts。参考实现中
    device/app_id/ticket/ts 在扫码阶段就固定下来并一直用于签名，confirm
    只额外并入 payload；请求体里的 ``ts`` 才是当前时间。二者混用会导致
    服务端验签失败，表现为 confirm 返回非 0 retcode。
    """
    url = f"https://api-sdk.mihoyo.com/{_normalise_biz_key(biz_key)}/combo/panda/qrcode/confirm"
    device = BILI_DEVICE_ID
    timestamp = int(time.time() * 1000)
    # 签名用的时间戳：优先复用扫码阶段那一次，缺失时才退回当前时间。
    signature_ts = int(sign_ts) if sign_ts is not None else timestamp

    # 支持两种模式：
    # 1. 官服协议 (account_type == "1"): proto="Account", raw 包含 uid 与 token
    # 2. 渠道服协议 (account_type == "2"): proto="Combo", 包含 channel_id、combo_token、dispatch 等
    if str(account_type) == "1":
        scan_raw = {
            "uid": str(open_id),
            "token": str(combo_token),
        }
        scan_payload = {
            "raw": json.dumps(scan_raw, ensure_ascii=False, separators=(",", ":")),
            "proto": "Account",
        }
    else:
        # 字段顺序严格对齐参考实现 QRScanner.genRequest()：
        #   raw      : heartbeat -> open_id -> device_id -> app_id -> channel_id ->
        #              asterisk_name -> combo_id -> account_type -> combo_token
        #   ext.data : accountType -> accountID -> dispatch -> accountToken
        scan_raw = {
            "heartbeat": False,
            "open_id": str(open_id),
            "device_id": device,
            "app_id": str(app_id),
            "channel_id": str(channel_id),
            "asterisk_name": "崩坏3扫码助手",
            "combo_id": str(combo_id or "0"),
            "account_type": str(account_type),
            "combo_token": str(combo_token),
        }
        scan_data = {
            "accountType": str(account_type),
            "accountID": str(open_id),
            "dispatch": str(dispatch or ""),
            "accountToken": str(combo_token),
        }
        scan_payload = {
            "raw": json.dumps(scan_raw, ensure_ascii=False, separators=(",", ":")),
            "proto": "Combo",
            "ext": json.dumps({"data": scan_data}, ensure_ascii=False, separators=(",", ":")),
        }

    # 参考实现不是对 Python dict repr 签名，而是对
    # device/app_id/ts/ticket/payload(JSONObject) 的 Java 字符串表示签名；
    # 其中 ts 取的是扫码阶段的值（qr_check_map 里的那个），不是本次请求体里的 ts。
    signature_fields = {
        "device": device,
        "app_id": str(app_id),
        "ts": signature_ts,
        "ticket": ticket,
        "payload": scan_payload,
    }
    scan_result = {
        "device": device,
        "app_id": int(app_id),
        "ts": timestamp,
        "ticket": ticket,
        "payload": scan_payload,
        "sign": bh3_sign(_signature_text(signature_fields)),
    }
    try:
        resp = requests.post(
            url,
            data=json.dumps(scan_result, ensure_ascii=False, separators=(",", ":")),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        return _json_response(resp, "授权确认接口")
    except Exception as exc:
        return {"retcode": -1, "message": f"授权确认网络异常: {exc}"}
