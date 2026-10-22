# -*- coding: utf-8 -*-
"""
崩坏3外置扫码器 (bh3_login_simulation) 凭据导入与备份解密模块
支持解密并读取手机扫码器导出的 scanner-backup-*.zip 备份，
支持全自动逆向解密 B 站 Game SDK 的 SecurePreferences 密文与 Java 序列化对象，
完整提取 B 站 UID、用户昵称、登录账号/手机号、密码及 access_key
"""
import base64
import hashlib
import hmac
import io
import json
import re
import sqlite3
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

from Crypto.Cipher import AES

BH_APP_KEY = "0ebc517adb1b62c6b408df153331f9aa"
SECURE_PREFS_IV = b"fldsjfodasjifuds"


def derive_aes_key(password: str) -> bytes:
    """
    还原 BackupActivity.kt 中的密钥派生算法：
    key = hmac_sha256(password, BH_APP_KEY)[:32]
    """
    hex_res = hmac.new(
        BH_APP_KEY.encode("utf-8"),
        password.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hex_res.encode("utf-8")[:32]


def aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """标准 AES-CBC 解密并移除 PKCS7 Padding"""
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    plaintext = cipher.decrypt(ciphertext)
    if not plaintext:
        return b""
    pad = plaintext[-1]
    if 1 <= pad <= 16 and plaintext.endswith(bytes([pad]) * pad):
        return plaintext[:-pad]
    return plaintext


def decrypt_scanner_backup(file_path: str, password: str = "") -> bytes:
    """
    解密外置扫码器导出的备份文件
    如果文件已经是明文 ZIP（文件头为 PK\x03\x04），则直接返回
    """
    with open(file_path, "rb") as f:
        raw_data = f.read()

    if raw_data.startswith(b"PK\x03\x04"):
        # 已经是标准 ZIP 压缩包
        return raw_data

    # 尝试使用给定密码及常用默认密码解密
    passwords_to_try = [password] if password else []
    passwords_to_try.extend(["123456", "", "admin", "000000", "bh3"])

    zero_iv = b"\x00" * 16

    for pwd in passwords_to_try:
        try:
            key = derive_aes_key(pwd)
            decrypted = aes_cbc_decrypt(raw_data, key, zero_iv)
            if decrypted.startswith(b"PK\x03\x04"):
                return decrypted
        except Exception:
            continue

    raise ValueError("无法解密扫码器备份文件，请检查密码是否正确！")


def _extract_android_ids_from_db(db_bytes: bytes) -> list[str]:
    """从 trackDatabase.db 中检索设备 android_id"""
    android_ids = []
    try:
        conn = sqlite3.connect(":memory:")
        conn.deserialize(db_bytes)
        cur = conn.cursor()
        cur.execute("SELECT deviceInfo FROM BaseBean WHERE deviceInfo LIKE '%android_id%' LIMIT 10")
        for row in cur.fetchall():
            info_str = row[0] or ""
            match = re.search(r'"android_id":\s*"([a-zA-Z0-9_-]+)"', info_str)
            if match:
                aid = match.group(1).strip()
                if aid and aid not in android_ids:
                    android_ids.append(aid)
        conn.close()
    except Exception:
        pass

    # 兜底纯文本正则匹配
    text = db_bytes.decode("latin1", errors="ignore")
    matches = re.findall(r'"android_id":"([a-zA-Z0-9_-]+)"', text)
    for m in matches:
        if m and m not in android_ids:
            android_ids.append(m)

    return android_ids


def _decrypt_secure_pref_string(enc_b64: str, candidates: list[str]) -> Optional[bytes]:
    """
    使用 SecurePreferences 规范解密加密字段
    AES/CBC/PKCS5Padding, IV: 'fldsjfodasjifuds', Key: SHA-256(seed)
    解密后进行 URLDecode 与 ISO-8859-1 字节转换，还原 Java 序列化流
    """
    try:
        enc_bytes = base64.b64decode(enc_b64)
    except Exception:
        return None

    for seed in candidates:
        try:
            key = hashlib.sha256(seed.encode("utf-8")).digest()
            plain = aes_cbc_decrypt(enc_bytes, key, SECURE_PREFS_IV)
            if not plain:
                continue
            text = plain.decode("utf-8", errors="ignore")
            decoded_str = urllib.parse.unquote(text)
            raw = decoded_str.encode("iso-8859-1")
            if raw.startswith(b"\xac\xed\x00\x05"):  # Java Serialized Object 魔数
                return raw
        except Exception:
            continue
    return None


def _parse_java_user_parcelable(raw_bytes: bytes) -> dict:
    """
    从反序列化的 UserParcelable / UserinfoCache 中解析凭据
    包含 uid_long, last_login_time, access_token, nickname, account, password
    """
    info = {
        "uid": "",
        "access_key": "",
        "username": "",
        "account": "",
        "password": "",
        "last_login_time": 0
    }

    # 1. 尝试从 Java 序列化对象基本类型数据段中直接提取 uid_long 与 last_login_time
    try:
        idx = raw_bytes.rfind(b"\x78\x70")  # TC_ENDBLOCKDATA TC_NULL
        if idx != -1 and idx + 2 + 46 <= len(raw_bytes):
            data_block = raw_bytes[idx + 2:]
            # last_login_time 位于 offset 18..26
            last_login = (
                (data_block[18] << 56) | (data_block[19] << 48) |
                (data_block[20] << 40) | (data_block[21] << 32) |
                (data_block[22] << 24) | (data_block[23] << 16) |
                (data_block[24] << 8)  | data_block[25]
            )
            info["last_login_time"] = last_login

            # uid_long 位于 offset 38..46
            uid_val = (
                (data_block[38] << 56) | (data_block[39] << 48) |
                (data_block[40] << 40) | (data_block[41] << 32) |
                (data_block[42] << 24) | (data_block[43] << 16) |
                (data_block[44] << 8)  | data_block[45]
            )
            if uid_val > 0:
                info["uid"] = str(uid_val)
    except Exception:
        pass

    # 2. 提取所有合法 TC_STRING 字符串
    strings = []
    pos = 0
    while pos < len(raw_bytes):
        if raw_bytes[pos] == 0x74 and pos + 3 <= len(raw_bytes):
            length = (raw_bytes[pos + 1] << 8) | raw_bytes[pos + 2]
            if 0 < length <= 1024 and pos + 3 + length <= len(raw_bytes):
                try:
                    s = raw_bytes[pos + 3:pos + 3 + length].decode("utf-8")
                    strings.append(s)
                    pos += 3 + length
                    continue
                except UnicodeDecodeError:
                    pass
        pos += 1

    # 3. 字段匹配
    for s in strings:
        # access_token (32 位 hex，通常以 _sh 或 _shp 结尾)
        if re.match(r"^[0-9a-fA-F]{32}(?:_sh[a-zA-Z0-9]*)?$", s):
            info["access_key"] = s
        # 手机号 / 账号 (以 1 开头的 11 位数字)
        elif re.match(r"^1[3-9]\d{9}$", s):
            info["account"] = s
        # 昵称 (含中文字符)
        elif any("\u4e00" <= c <= "\u9fff" for c in s):
            info["username"] = s
        # 登录密码 (6位以上字符，排除系统关键字及 URL)
        elif len(s) >= 6 and re.match(r"^[a-zA-Z0-9_.@!#-]+$", s):
            if not s.startswith("http") and not s.startswith("Ljava/") and s != "null":
                info["password"] = s

    # 兜底 UID 匹配
    if not info["uid"]:
        for s in strings:
            if s.isdigit() and len(s) < 11 and s != "0":
                info["uid"] = s
                break

    return info


CHANNEL_CONFIG_MAP = {
    "Official": {
        "channel_id": "1",
        "account_type": "1",
        "server_name": "官服 (米哈游全平台)",
        "oa_req_key": "",
    },
    "OfficialNew": {
        "channel_id": "1",
        "account_type": "1",
        "server_name": "官服V2",
        "oa_req_key": "",
    },
    "Bilibili": {
        "channel_id": "14",
        "account_type": "2",
        "server_name": "B服 (哔哩哔哩)",
        "oa_req_key": "bilibili",
    },
    "Xiaomi": {
        "channel_id": "11",
        "account_type": "2",
        "server_name": "小米服",
        "oa_req_key": "xiaomi",
    },
    "Huawei": {
        "channel_id": "15",
        "account_type": "2",
        "server_name": "华为服",
        "oa_req_key": "huawei",
    },
    "YYB": {
        "channel_id": "16",
        "account_type": "2",
        "server_name": "应用宝服 (腾讯)",
        "oa_req_key": "yyb",
    },
    "Tencent": {
        "channel_id": "16",
        "account_type": "2",
        "server_name": "应用宝服 (腾讯)",
        "oa_req_key": "yyb",
    },
    "Wegame": {
        "channel_id": "16",
        "account_type": "2",
        "server_name": "Wegame服",
        "oa_req_key": "wegame",
    },
    "Oppo": {
        "channel_id": "18",
        "account_type": "2",
        "server_name": "OPPO服",
        "oa_req_key": "oppo",
    },
    "Vivo": {
        "channel_id": "19",
        "account_type": "2",
        "server_name": "vivo服",
        "oa_req_key": "vivo",
    },
    "UC": {
        "channel_id": "20",
        "account_type": "2",
        "server_name": "九游服",
        "oa_req_key": "uc",
    },
}


def extract_credentials_from_zip(zip_bytes: bytes) -> dict:
    """
    从解密后的 ZIP 数据流中提取账号凭据，支持全渠道服与官服配置自动识别。
    支持解析:
    - 扫码器配置: server_type (Official / Bilibili / Vivo / Oppo / Huawei / Xiaomi / YYB / UC 等)
    - 官服凭据: official_user_*.xml (uid, token, stoken, mid)
    - 腾讯/Wegame: tencent_user_*.xml, wegame_user_*.xml (openid, openkey)
    - B 站凭据: bili_user_*.xml 与加密 login_*.xml / userinfoCache_*.xml
    - 通用备份凭据: 自动提取 combo_token, open_id, combo_id, dispatch / enc_oaserver
    """
    result = {
        "server_type": "Bilibili",
        "server_name": "B服 (哔哩哔哩)",
        "channel_id": "14",
        "account_type": "2",
        "bh_ver": "9.1.0",
        "uid": "",
        "access_key": "",
        "username": "",
        "account": "",
        "password": "",
        "combo_token": "",
        "open_id": "",
        "combo_id": "0",
        "dispatch": "",
        "device_id": "f770fbebc62ee6ef",
    }

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
        namelist = z.namelist()

        # 1. 优先从主配置文件识别目标服别 server_type 与版本
        for name in namelist:
            lower = name.lower()
            if "bh3_login_simulation_preferences.xml" in lower or "preferences.xml" in lower:
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                    m_server = re.search(r'name=["\']server_type["\'][^>]*>([^<]+)<', content)
                    if m_server:
                        st = m_server.group(1).strip()
                        if st in CHANNEL_CONFIG_MAP:
                            result["server_type"] = st
                            cfg = CHANNEL_CONFIG_MAP[st]
                            result["server_name"] = cfg["server_name"]
                            result["channel_id"] = cfg["channel_id"]
                            result["account_type"] = cfg["account_type"]

                    m_ver = re.search(r'name=["\']bh_ver["\'][^>]*>([^<]+)<', content)
                    if m_ver:
                        result["bh_ver"] = m_ver.group(1).strip()

                    m_cuser = re.search(r'name=["\']custom_username["\'][^>]*>([^<]+)<', content)
                    if m_cuser and not result["username"]:
                        result["username"] = m_cuser.group(1).strip()
                except Exception:
                    pass

        # 2. 获取设备 device_id / android_id
        seed_candidates = ["com.bsgamesdk.android.model", "com.bsgamesdk.android", ""]
        for name in namelist:
            lower = name.lower()
            if "scanner_pref.xml" in lower or "config_data.xml" in lower:
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                    m_dev = re.search(r'name=["\'](?:device_id|android_id)["\'][^>]*>([a-zA-Z0-9_-]{12,32})<', content)
                    if m_dev:
                        result["device_id"] = m_dev.group(1).strip()
                except Exception:
                    pass
            elif "trackdatabase.db" in lower:
                try:
                    db_data = z.read(name)
                    aids = _extract_android_ids_from_db(db_data)
                    seed_candidates = aids + seed_candidates
                    if aids and not result.get("device_id"):
                        result["device_id"] = aids[0]
                except Exception:
                    pass

        # 3. 针对官服（Official）：解析 official_user_*.xml
        is_official = result["server_type"].startswith("Official")
        for name in namelist:
            lower = name.lower()
            if "official_user" in lower and lower.endswith(".xml"):
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                    root = ET.fromstring(content)
                    uid_val, token_val, uname_val = "", "", ""
                    for elem in root:
                        attr_name = elem.attrib.get("name", "")
                        val = elem.text or elem.attrib.get("value", "")
                        if attr_name == "uid" and val and val != "0":
                            uid_val = str(val).strip()
                        elif attr_name == "token" and val:
                            token_val = str(val).strip()
                        elif attr_name in ("username", "uname") and val:
                            uname_val = str(val).strip()

                    if uid_val or token_val:
                        if is_official or not result["uid"]:
                            result["server_type"] = "Official"
                            cfg = CHANNEL_CONFIG_MAP["Official"]
                            result["server_name"] = cfg["server_name"]
                            result["channel_id"] = cfg["channel_id"]
                            result["account_type"] = cfg["account_type"]
                            if uid_val:
                                result["uid"] = uid_val
                                result["open_id"] = uid_val
                            if token_val:
                                result["access_key"] = token_val
                                result["combo_token"] = token_val
                            if uname_val and not result["username"]:
                                result["username"] = uname_val
                except Exception:
                    pass

        # 4. 针对腾讯应用宝 / Wegame：解析 tencent_user_*.xml / wegame_user_*.xml
        if result["server_type"] in ("YYB", "Tencent", "Wegame"):
            for name in namelist:
                lower = name.lower()
                if ("tencent_user" in lower or "wegame_user" in lower) and lower.endswith(".xml"):
                    try:
                        content = z.read(name).decode("utf-8", errors="ignore")
                        root = ET.fromstring(content)
                        for elem in root:
                            attr_name = elem.attrib.get("name", "")
                            val = elem.text or elem.attrib.get("value", "")
                            if attr_name == "openid" and val:
                                result["open_id"] = str(val).strip()
                                result["uid"] = str(val).strip()
                            elif attr_name == "openkey" and val:
                                result["access_key"] = str(val).strip()
                            elif attr_name == "username" and val and not result["username"]:
                                result["username"] = str(val).strip()
                    except Exception:
                        pass

        # 5. 针对 B 站渠道服：查找 bili_user_*.xml
        for name in namelist:
            lower = name.lower()
            if "bili_user" in lower:
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                    root = ET.fromstring(content)
                    for elem in root:
                        attr_name = elem.attrib.get("name", "")
                        val = elem.text or elem.attrib.get("value", "")
                        if attr_name == "uid" and val and val != "0":
                            if not result["uid"]:
                                result["uid"] = str(val).strip()
                        elif attr_name in ("username", "uname") and val and not result["username"]:
                            result["username"] = str(val).strip()
                except Exception:
                    pass

        # 6. 解密 B 站 login_*.xml 与 userinfoCache_*.xml
        login_candidates = []
        for name in namelist:
            lower = name.lower()
            if ("login_" in lower or "userinfocache_" in lower) and lower.endswith(".xml"):
                try:
                    xml_content = z.read(name).decode("utf-8", errors="ignore")
                    root = ET.fromstring(xml_content)
                    for elem in root:
                        val = elem.text or ""
                        if len(val) > 100:
                            raw_ser = _decrypt_secure_pref_string(val.strip(), seed_candidates)
                            if raw_ser:
                                parsed = _parse_java_user_parcelable(raw_ser)
                                if parsed["access_key"]:
                                    login_candidates.append(parsed)
                except Exception:
                    pass

        if login_candidates:
            login_candidates.sort(key=lambda x: x.get("last_login_time", 0), reverse=True)
            best = login_candidates[0]
            if not result["access_key"]:
                result["access_key"] = best["access_key"]
            if best["account"] and not result["account"]:
                result["account"] = best["account"]
            if best["password"] and not result["password"]:
                result["password"] = best["password"]
            if best["uid"] and (not result["uid"] or result["uid"] == "0"):
                result["uid"] = best["uid"]
            if best["username"] and not result["username"]:
                result["username"] = best["username"]

        # 7. 备用明文 bili_access_token_*.xml
        if not result["access_key"]:
            for name in namelist:
                lower = name.lower()
                if "bili_access_token" in lower or "access_token" in lower:
                    try:
                        content = z.read(name).decode("utf-8", errors="ignore")
                        root = ET.fromstring(content)
                        for elem in root:
                            attr_name = elem.attrib.get("name", "")
                            val = elem.text or elem.attrib.get("value", "")
                            if val and len(val) >= 32 and re.match(r"^[0-9a-fA-F]{32}(?:_sh[p]?)?$", val):
                                result["access_key"] = val
                                break
                    except Exception:
                        pass

        # 8. 全局扫描直接提取可能已持久化的 combo_token / open_id / combo_id / dispatch
        for name in namelist:
            if name.endswith(".xml") or name.endswith(".json") or name.endswith(".txt"):
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                    if not result["combo_token"]:
                        m_ct = re.search(r'name=["\'](?:combo_token|accountToken)["\'][^>]*>([0-9a-zA-Z_]{20,64})<', content)
                        if m_ct:
                            result["combo_token"] = m_ct.group(1).strip()
                    if not result["open_id"]:
                        m_oi = re.search(r'name=["\'](?:open_id|accountID|openid)["\'][^>]*>([0-9a-zA-Z_]{5,32})<', content)
                        if m_oi:
                            result["open_id"] = m_oi.group(1).strip()
                    if not result["dispatch"]:
                        m_dp = re.search(r'name=["\'](?:enc_oaserver|dispatch)["\'][^>]*>([A-Za-z0-9+/=_-]{20,})<', content)
                        if m_dp:
                            result["dispatch"] = m_dp.group(1).strip()
                except Exception:
                    pass

        # 9. 最终暴力正则兜底
        if not result["uid"] or not result["access_key"]:
            for name in namelist:
                if name.endswith(".xml") or name.endswith(".json") or name.endswith(".txt"):
                    try:
                        content = z.read(name).decode("utf-8", errors="ignore")
                        if not result["uid"]:
                            uid_match = re.search(r'name=["\']uid["\'][^>]*>(\d+)<', content)
                            if uid_match:
                                result["uid"] = uid_match.group(1)
                        if not result["access_key"]:
                            token_match = re.search(r'name=["\'](?:access_token|access_key|token)["\'][^>]*>([0-9a-zA-Z_]{32,64})<', content)
                            if token_match:
                                result["access_key"] = token_match.group(1)
                    except Exception:
                        pass

    # 规范化 UID 格式
    if result["uid"]:
        try:
            result["uid"] = int(result["uid"])
        except Exception:
            pass

    # 若已有 uid 且未设 open_id，默认对其赋值
    if result["uid"] and not result.get("open_id"):
        result["open_id"] = str(result["uid"])

    return result


def parse_scanner_backup(file_path: str, password: str = "") -> dict:
    """
    一体化对外接口：输入备份文件路径和密码，直接解析返回凭据字典
    """
    zip_bytes = decrypt_scanner_backup(file_path, password)
    return extract_credentials_from_zip(zip_bytes)

