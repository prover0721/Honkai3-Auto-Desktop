# -*- coding: utf-8 -*-
"""
哔哩哔哩游戏中心客户端 SDK 协议封装
用于通过账号密码或凭证验证获取 access_key 与 uid
"""
import base64
import hashlib
import json
import time
import urllib.parse
import requests
from Crypto.Cipher import PKCS1_v1_5 as Cipher_pkcs1_v1_5
from Crypto.PublicKey import RSA

BILI_LOGIN_BASE = "https://line1-sdk-center-login-sh.biligame.net/"
BILI_SECRET_SALT = "dbf8f1b4496f430b8a3c0f436a35b931"

BASE_PARAMS = {
    "operators": "5",
    "merchant_id": "590",
    "isRoot": "0",
    "domain_switch_count": "0",
    "sdk_type": "1",
    "sdk_log_type": "1",
    "support_abis": "x86,armeabi-v7a,armeabi",
    "access_key": "",
    "sdk_ver": "3.4.2",
    "oaid": "",
    "dp": "1280*720",
    "original_domain": "",
    "imei": "227656364311444",
    "version": "1",
    "udid": "KREhESMUIhUjFnJKNko2TDQFYlZkB3cdeQ==",
    "apk_sign": "4502a02a00395dec05a4134ad593224d",
    "platform_type": "3",
    "old_buvid": "XZA2FA4AC240F665E2F27F603ABF98C615C29",
    "android_id": "84567e2dda72d1d4",
    "fingerprint": "",
    "mac": "08:00:27:53:DD:12",
    "server_id": "378",
    "domain": "line1-sdk-center-login-sh.biligame.net",
    "app_id": "180",
    "version_code": "510",
    "net": "4",
    "pf_ver": "12",
    "cur_buvid": "XZA2FA4AC240F665E2F27F603ABF98C615C29",
    "c": "1",
    "brand": "Android",
    "channel_id": "1",
    "game_id": "180",
    "ver": "6.1.0",
    "model": "MuMu",
}


def calc_bili_sign_data(data: dict) -> str:
    """按哔哩哔哩游戏SDK规则进行参数签名"""
    ts = int(time.time())
    data["timestamp"] = ts
    data["client_timestamp"] = ts

    sign_raw = ""
    for key in sorted(data.keys()):
        sign_raw += str(data[key])
    sign_raw += BILI_SECRET_SALT
    sign = hashlib.md5(sign_raw.encode("utf-8")).hexdigest()

    encoded_pairs = []
    for key, val in data.items():
        if key in ("pwd", "seccode"):
            encoded_pairs.append(f"{key}={urllib.parse.quote(str(val), safe='')}")
        else:
            encoded_pairs.append(f"{key}={val}")
    encoded_pairs.append(f"sign={sign}")
    return "&".join(encoded_pairs)


def encrypt_rsa(message: str, public_key: str) -> str:
    """使用公钥进行 PKCS1_v1_5 RSA 加密"""
    rsakey = RSA.importKey(public_key)
    cipher = Cipher_pkcs1_v1_5.new(rsakey)
    cipher_bytes = cipher.encrypt(message.encode("utf-8"))
    return base64.b64encode(cipher_bytes).decode("utf-8")


def get_user_info(uid: int | str, access_key: str) -> dict:
    """
    验证 B 站 access_key 是否有效并获取用户名
    """
    params = BASE_PARAMS.copy()
    params["uid"] = str(uid)
    params["access_key"] = str(access_key)
    body = calc_bili_sign_data(params)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 BSGameSDK"
    }
    try:
        resp = requests.post(
            f"{BILI_LOGIN_BASE}api/client/user.info",
            data=body,
            headers=headers,
            timeout=8
        )
        return resp.json()
    except Exception as e:
        return {"code": -1, "message": str(e)}


def fetch_geetest_params() -> dict:
    """
    从 B 站官方游戏 SDK 接口获取极验验证码参数 (gt, challenge, ctoken, gt_user_id)
    优先使用游戏中心客户端专属 v2 接口，确保极验会话与游戏中心服务端对齐
    """
    params = BASE_PARAMS.copy()
    params["uid"] = ""
    body = calc_bili_sign_data(params)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 BSGameSDK"
    }
    # 1. 官方 GameSDK v2 专属极验接口
    try:
        resp = requests.post(
            f"{BILI_LOGIN_BASE}api/client/v2/start_captcha",
            data=body,
            headers=headers,
            timeout=8
        )
        data = resp.json()
        if data.get("code") == 0:
            return {
                "gt": data.get("gt", "ac597a4506fee079629df5d8b66dd4fe"),
                "challenge": data.get("challenge", ""),
                "ctoken": data.get("ctoken", ""),
                "captcha_type": data.get("captcha_type", "geetest"),
                "gt_user_id": data.get("gt_user_id", "")
            }
    except Exception:
        pass

    # 2. 官方 GameSDK v1 接口备用
    try:
        resp = requests.post(
            f"{BILI_LOGIN_BASE}api/client/start_captcha",
            data=body,
            headers=headers,
            timeout=8
        )
        data = resp.json()
        if data.get("code") == 0:
            return {
                "gt": data.get("gt", "245273d7fa73f7b657098bf7441fe12f"),
                "challenge": data.get("challenge", ""),
                "ctoken": "",
                "captcha_type": "geetest",
                "gt_user_id": data.get("gt_user_id", "")
            }
    except Exception:
        pass

    # 3. 兜底默认
    return {
        "gt": "ac597a4506fee079629df5d8b66dd4fe",
        "challenge": "",
        "ctoken": "",
        "captcha_type": "geetest",
        "gt_user_id": ""
    }


def login_by_password(
    account: str,
    password: str,
    challenge: str = "",
    validate: str = "",
    seccode: str = "",
    ctoken: str = "",
    gt_user_id: str = ""
) -> dict:
    """
    通过 B 站账号密码登录，获取 uid 与 access_key (支持极验滑块验证码透传)
    """
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 BSGameSDK"
    }

    # 第一步：获取 RSA 公钥
    rsa_params = BASE_PARAMS.copy()
    rsa_params["uid"] = ""
    body = calc_bili_sign_data(rsa_params)
    try:
        resp = requests.post(
            f"{BILI_LOGIN_BASE}api/client/rsa",
            data=body,
            headers=headers,
            timeout=8
        )
        rsa_json = resp.json()
    except Exception as e:
        return {"code": -1, "message": f"连接 B 站 RSA 接口失败: {e}"}

    if "rsa_key" not in rsa_json:
        return {"code": -1, "message": "获取 RSA 公钥失败", "raw": rsa_json}

    public_key = rsa_json["rsa_key"]
    hash_str = rsa_json.get("hash", "")
    encrypted_pwd = encrypt_rsa(hash_str + password, public_key)

    # 第二步：提交登录 (若有极验滑块票据则带入)
    sec = seccode + "|jct" if seccode and not seccode.endswith("|jct") else seccode

    login_params = BASE_PARAMS.copy()
    login_params["user_id"] = account
    login_params["pwd"] = encrypted_pwd
    login_params["uid"] = ""
    login_params["access_key"] = ""

    if validate:
        login_params["captcha_type"] = "geetest"
        login_params["challenge"] = challenge
        login_params["validate"] = validate
        login_params["seccode"] = sec
        login_params["captcha_code"] = challenge
        if ctoken:
            login_params["image_token"] = ctoken
        if gt_user_id:
            login_params["gt_user_id"] = gt_user_id

    body = calc_bili_sign_data(login_params)
    try:
        login_resp = requests.post(
            f"{BILI_LOGIN_BASE}api/client/login",
            data=body,
            headers=headers,
            timeout=10
        )
        res_json = login_resp.json()
        return res_json
    except Exception as e:
        return {"code": -1, "message": f"请求登录接口失败: {e}"}


# ==========================================
# B 站 TV / 移动端 OAuth 扫码登录协议
# 可直接获取全平台/移动端通用的 access_key 与 mid，免滑块、免密码
# ==========================================
BILI_TV_APPKEY = "4409e2ce8ffd12b8"
BILI_TV_SECRET = "59b43e04ad6965f34319062b478f83dd"
BILI_TV_AUTH_URL = "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
BILI_TV_POLL_URL = "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll"


def fetch_tv_qrcode() -> dict:
    """
    申请 B 站 TV/App OAuth 扫码登录二维码
    返回: {"code": 0, "url": "...", "auth_code": "..."} 或错误字典
    """
    ts = int(time.time())
    params = {
        "appkey": BILI_TV_APPKEY,
        "local_id": "0",
        "ts": str(ts),
    }
    query_str = urllib.parse.urlencode(sorted(params.items()))
    sign = hashlib.md5((query_str + BILI_TV_SECRET).encode("utf-8")).hexdigest()
    payload = f"{query_str}&sign={sign}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 BiliTV/1.0",
    }
    try:
        resp = requests.post(BILI_TV_AUTH_URL, data=payload, headers=headers, timeout=8)
        data = resp.json()
        if data.get("code") == 0 and "data" in data:
            d = data["data"]
            return {
                "code": 0,
                "url": d.get("url", ""),
                "auth_code": d.get("auth_code", ""),
            }
        return {"code": data.get("code", -1), "message": data.get("message", "申请二维码失败")}
    except Exception as e:
        return {"code": -1, "message": f"连接 B 站扫码服务失败: {e}"}


def poll_tv_qrcode(auth_code: str) -> dict:
    """
    轮询 B 站 TV/App OAuth 扫码状态
    返回:
      code == 0: 成功, {"code": 0, "data": {"access_token": "...", "mid": ..., ...}}
      code == 86039: 未扫码或等待确认
      code == 86038: 二维码已失效
    """
    ts = int(time.time())
    params = {
        "appkey": BILI_TV_APPKEY,
        "auth_code": str(auth_code),
        "local_id": "0",
        "ts": str(ts),
    }
    query_str = urllib.parse.urlencode(sorted(params.items()))
    sign = hashlib.md5((query_str + BILI_TV_SECRET).encode("utf-8")).hexdigest()
    payload = f"{query_str}&sign={sign}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 BiliTV/1.0",
    }
    try:
        resp = requests.post(BILI_TV_POLL_URL, data=payload, headers=headers, timeout=6)
        return resp.json()
    except Exception as e:
        return {"code": -1, "message": f"轮询扫码状态失败: {e}"}


