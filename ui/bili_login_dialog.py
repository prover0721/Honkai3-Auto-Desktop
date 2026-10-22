# -*- coding: utf-8 -*-
"""
B 站账号可视化登录对话框 (纯手机扫码与扫码器导入专属版)
支持：
1. 手机 B 站 App 扫码登录 (TV/App OAuth 移动端专属授权，免滑块、免密码、一扫即过)
2. 导入《崩坏3外置扫码器》备份凭证 (.zip)
登录成功后自动调用米哈游 API 核验并保存凭据
"""
from io import BytesIO
import os
from typing import Optional
import qrcode
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QStackedWidget
)
from qfluentwidgets import (
    CaptionLabel, FluentIcon as FIF, LineEdit, PasswordLineEdit,
    PrimaryPushButton, PushButton, SegmentedWidget
)

from games.honkai3 import bili_sdk, mihoyo_api


class QrPollThread(QThread):
    """后台轮询 B 站 TV/App OAuth 扫码登录状态"""
    status_signal = Signal(str)   # 提示文字
    success_signal = Signal(dict) # 成功数据
    expired_signal = Signal()     # 二维码过期

    def __init__(self, auth_code: str):
        super().__init__()
        self.auth_code = auth_code
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                res_data = bili_sdk.poll_tv_qrcode(self.auth_code)
                code = res_data.get("code")
                if code == 0:
                    data = res_data.get("data", {})
                    self.success_signal.emit(data)
                    return
                elif code == 86039:
                    self.status_signal.emit("等待手机扫码中，扫码后请在手机上点击【确认授权】...")
                elif code == 86090:
                    self.status_signal.emit("已扫码，请在手机上点击【确认授权】")
                elif code == 86038:
                    self.status_signal.emit("二维码已过期，请刷新")
                    self.expired_signal.emit()
                    return
                else:
                    msg = res_data.get("message", "")
                    if msg:
                        self.status_signal.emit(f"等待手机扫码确认中... ({msg})")
            except Exception:
                pass
            self.msleep(1500)


class BiliLoginDialog(QDialog):
    """B 站账号授权登录对话框"""
    login_success = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle("B 站账号授权登录 (手机扫码)")
        self.setFixedSize(460, 560)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowSystemMenuHint)

        self.qr_thread: Optional[QrPollThread] = None
        self.current_qrcode_key = ""

        self._init_ui()
        QTimer.singleShot(150, self._fetch_new_qr)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 24, 32, 24)
        main_layout.setSpacing(14)

        # 头部标题 (仿 bilibili 游戏视觉)
        header = QWidget()
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(4)

        bili_title = QLabel("bilibili 游戏")
        bili_title.setStyleSheet("color: #00aeec; font-size: 24px; font-weight: bold;")
        bili_title.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(bili_title)

        sub_title = CaptionLabel("手机 B 站 App 扫码获取《崩坏3》免扫码自动登舰授权")
        sub_title.setAlignment(Qt.AlignCenter)
        sub_title.setStyleSheet("color: #888888;")
        h_layout.addWidget(sub_title)

        main_layout.addWidget(header)

        # 选项卡切换 (仅保留手机扫码授权与导入扫码器凭据)
        self.pivot = SegmentedWidget(self)
        self.pivot.addItem("qr_login", "📸 手机扫码授权", onClick=lambda: self.stack.setCurrentIndex(0))
        self.pivot.addItem("import_login", "📦 导入扫码器", onClick=lambda: self.stack.setCurrentIndex(1))
        self.pivot.setCurrentItem("qr_login")
        main_layout.addWidget(self.pivot, alignment=Qt.AlignCenter)

        # 堆叠窗口容器
        self.stack = QStackedWidget(self)
        self._init_qr_page()
        self._init_import_page()
        main_layout.addWidget(self.stack)

        self.status_label = CaptionLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def _init_qr_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        self.qr_label = QLabel(self)
        self.qr_label.setFixedSize(190, 190)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet(
            "QLabel { background: white; border: 1px solid #e2e8f0; border-radius: 8px; }"
        )

        qr_box = QHBoxLayout()
        qr_box.addStretch()
        qr_box.addWidget(self.qr_label)
        qr_box.addStretch()
        layout.addLayout(qr_box)

        self.qr_tip_label = CaptionLabel("正在请求 B 站授权二维码...")
        self.qr_tip_label.setAlignment(Qt.AlignCenter)
        self.qr_tip_label.setStyleSheet("color: #0088ff; font-weight: bold;")
        layout.addWidget(self.qr_tip_label)

        self.btn_refresh_qr = PushButton("刷新二维码", self, FIF.SYNC)
        self.btn_refresh_qr.clicked.connect(self._fetch_new_qr)
        layout.addWidget(self.btn_refresh_qr, alignment=Qt.AlignCenter)

        hint = CaptionLabel(
            "🛡️ 采用 B 站官方 TV/App OAuth 移动端专属授权协议\n"
            "手机一键确认即可颁发专属凭证，免密码、免滑动拼图"
        )
        hint.setStyleSheet("color: #999999; line-height: 1.4;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        layout.addStretch()
        self.stack.addWidget(page)

    def _init_import_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        tip = CaptionLabel(
            "💡 如果您此前在手机端或模拟器使用过《崩坏3外置扫码器.apk》，\n"
            "可以在该 App【设置 -> 备份与恢复】中导出备份文件（.zip）。\n"
            "选择导出的备份文件即可一秒解析并绑定凭据！"
        )
        tip.setStyleSheet("color: #64748b; line-height: 1.5;")
        tip.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip)

        path_box = QHBoxLayout()
        self.import_path_input = LineEdit(self)
        self.import_path_input.setPlaceholderText("选择 scanner-backup-*.zip 备份文件路径")
        self.import_path_input.setClearButtonEnabled(True)
        path_box.addWidget(self.import_path_input)

        btn_browse_backup = PushButton("浏览文件...", self, FIF.FOLDER)
        btn_browse_backup.clicked.connect(self._browse_backup_file)
        path_box.addWidget(btn_browse_backup)
        layout.addLayout(path_box)

        btn_auto_find = PushButton("🔍 自动检索常用目录备份", self, FIF.SEARCH)
        btn_auto_find.clicked.connect(self._auto_find_backup_file)
        layout.addWidget(btn_auto_find)

        pwd_box = QVBoxLayout()
        pwd_tip = CaptionLabel("备份解密密码 (若导出时未设密码可留空)：")
        pwd_tip.setStyleSheet("color: #888888;")
        pwd_box.addWidget(pwd_tip)
        self.import_pwd_input = PasswordLineEdit(self)
        self.import_pwd_input.setPlaceholderText("留空或输入导出备份时设置的密码")
        pwd_box.addWidget(self.import_pwd_input)
        layout.addLayout(pwd_box)

        self.btn_do_import = PrimaryPushButton("🚀 立即解析并绑定凭据", self, FIF.ACCEPT)
        self.btn_do_import.setStyleSheet(
            "PrimaryPushButton { background-color: #00aeec; border-color: #00aeec; font-size: 15px; font-weight: bold; height: 38px; }"
            "PrimaryPushButton:hover { background-color: #00bbee; border-color: #00bbee; }"
            "PrimaryPushButton:pressed { background-color: #0099cc; border-color: #0099cc; }"
        )
        self.btn_do_import.clicked.connect(self._do_import_backup)
        layout.addWidget(self.btn_do_import)

        layout.addStretch()
        self.stack.addWidget(page)

    def _browse_backup_file(self):
        start_dir = os.path.dirname(os.path.abspath(__file__))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择《崩坏3外置扫码器》备份文件",
            start_dir,
            "备份文件 (*.zip);;所有文件 (*.*)"
        )
        if path:
            self.import_path_input.setText(os.path.normpath(path))

    def _auto_find_backup_file(self):
        search_dirs = [
            os.getcwd(),
            os.path.dirname(os.getcwd()),
            os.path.expanduser("~/Downloads")
        ]
        found = []
        for d in search_dirs:
            if os.path.isdir(d):
                try:
                    for f in os.listdir(d):
                        if f.startswith("scanner-backup") and f.endswith(".zip"):
                            found.append(os.path.join(d, f))
                except Exception:
                    pass
        if found:
            self.import_path_input.setText(os.path.normpath(found[0]))
            self.status_label.setText(f"✅ 已自动定位备份文件: {os.path.basename(found[0])}")
            self.status_label.setStyleSheet("color: #22c55e; font-weight: bold;")
        else:
            self.status_label.setText("未在常用目录发现 scanner-backup-*.zip，请点击【浏览文件...】手动选择！")
            self.status_label.setStyleSheet("color: #ff9900; font-weight: bold;")

    def _do_import_backup(self):
        file_path = self.import_path_input.text().strip()
        pwd = self.import_pwd_input.text().strip()
        if not file_path or not os.path.isfile(file_path):
            self.status_label.setText("⚠️ 请先选择有效的扫码器备份文件 (.zip)！")
            self.status_label.setStyleSheet("color: #ff9900; font-weight: bold;")
            return

        self.status_label.setText("正在解密并提取扫码器凭据...")
        self.status_label.setStyleSheet("color: #0088ff; font-weight: bold;")

        try:
            from games.honkai3.scanner_importer import parse_scanner_backup
            creds = parse_scanner_backup(file_path, pwd)
            uid = creds.get("uid")
            access_key = creds.get("access_key")
            uname = creds.get("username") or f"UID_{uid}"
            server_name = creds.get("server_name") or creds.get("server_type") or "B服"
            server_type = creds.get("server_type", "Bilibili")
            channel_id = str(creds.get("channel_id", "14"))
            account_type = str(creds.get("account_type", "2"))
            combo_token = creds.get("combo_token", "")
            open_id = creds.get("open_id", "")
            combo_id = creds.get("combo_id", "")
            dispatch = creds.get("dispatch", "")

            if not uid and not open_id:
                self.status_label.setText("❌ 未能在备份文件中提取到有效 UID 或账号标识！")
                self.status_label.setStyleSheet("color: #e11d48; font-weight: bold;")
                return

            self.status_label.setText(f"🎉 成功提取【{server_name}】UID: {uid or open_id}！")
            self.status_label.setStyleSheet("color: #22c55e; font-weight: bold;")

            result = {
                "uid": uid or open_id,
                "access_key": str(access_key or ""),
                "uname": uname,
                "account": creds.get("account", ""),
                "server_type": server_type,
                "server_name": server_name,
                "channel_id": channel_id,
                "account_type": account_type,
                "combo_token": combo_token,
                "open_id": str(open_id or uid),
                "combo_id": combo_id,
                "dispatch": dispatch
            }

            if account_type == "1" or combo_token:
                self.login_success.emit(result)
                self.accept()
                return

            if access_key and channel_id == "14":
                self._finish_and_verify(uid, access_key, uname, "外置扫码器导入", extra_result=result)
            else:
                self.login_success.emit(result)
                self.accept()
        except Exception as e:
            self.status_label.setText(f"❌ 导入解析失败: {e}")
            self.status_label.setStyleSheet("color: #e11d48; font-weight: bold;")

    def _fetch_new_qr(self):
        """生成 B 站 TV/App OAuth 扫码二维码 (直接获取专属 access_key)"""
        if self.qr_thread and self.qr_thread.isRunning():
            self.qr_thread.stop()
            self.qr_thread.wait()

        self.qr_tip_label.setText("正在生成专属移动端授权二维码...")
        try:
            res = bili_sdk.fetch_tv_qrcode()
            if res.get("code") == 0:
                url = res["url"]
                self.current_qrcode_key = res["auth_code"]

                qr = qrcode.QRCode(box_size=5, border=1)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
                buf = BytesIO()
                img.save(buf, format="PNG")
                qimg = QImage.fromData(buf.getvalue())
                self.qr_label.setPixmap(QPixmap.fromImage(qimg).scaled(180, 180, Qt.KeepAspectRatio))

                self.qr_tip_label.setText("请打开手机【哔哩哔哩 App】扫一扫并在手机上确认授权")

                self.qr_thread = QrPollThread(self.current_qrcode_key)
                self.qr_thread.status_signal.connect(lambda txt: self.qr_tip_label.setText(txt))
                self.qr_thread.expired_signal.connect(lambda: self.qr_tip_label.setText("二维码已失效，请点击刷新"))
                self.qr_thread.success_signal.connect(self._on_qr_login_success)
                self.qr_thread.start()
            else:
                msg = res.get("message", "获取二维码失败")
                self.qr_tip_label.setText(f"获取二维码失败: {msg}，请重试")
        except Exception as e:
            self.qr_tip_label.setText(f"网络异常: {e}")

    def _on_qr_login_success(self, data: dict):
        """扫码登录成功回调 (直接提取专属 access_key 与 UID)"""
        self.qr_tip_label.setText("🎉 扫码授权成功！正在同步凭证...")
        real_uid = data.get("mid") or 0
        access_key = data.get("access_token") or ""
        uname = f"B站用户_{real_uid}"

        if real_uid and access_key:
            try:
                u_res = bili_sdk.get_user_info(real_uid, access_key)
                if u_res.get("code") == 0 and "data" in u_res:
                    uname = u_res["data"].get("uname", uname)
            except Exception:
                pass

        self.qr_tip_label.setText(f"🎉 扫码授权成功！已提取 UID: {real_uid}")
        self._finish_and_verify(
            uid=real_uid,
            access_key=access_key,
            uname=uname
        )

    def _finish_and_verify(self, uid, access_key, uname, account="", extra_result=None):
        try:
            clean_uid = int(uid) if str(uid).isdigit() else uid
            mi_res = mihoyo_api.verify_bili_account(clean_uid, access_key)
            result = {
                "uid": clean_uid,
                "access_key": str(access_key),
                "uname": uname,
                "account": account,
                "server_type": "Bilibili",
                "server_name": "B服",
                "channel_id": "14",
                "account_type": "2"
            }
            if extra_result:
                result.update(extra_result)

            if mi_res.get("retcode") == 0:
                data_combo = mi_res.get("data", {})
                result["combo_token"] = data_combo.get("combo_token", "")
                result["open_id"] = data_combo.get("open_id", "")
                result["combo_id"] = data_combo.get("combo_id", "")
                self.login_success.emit(result)
                self.accept()
                return

            msg = mi_res.get("message", "核验未通过")
            if "渠道" in msg or mi_res.get("retcode") == -107:
                self.status_label.setText(
                    f"⚠️ UID: {clean_uid} 凭证米哈游核验未通过 (渠道错误: {msg})！\n"
                    f"💡 请点击【刷新二维码】重新扫码授权"
                )
                self.status_label.setStyleSheet("color: #e11d48; font-weight: bold;")
                return

            if mi_res.get("retcode") != 0:
                self.status_label.setText(f"❌ 米哈游凭证核验未通过: {msg} (retcode: {mi_res.get('retcode')})")
                self.status_label.setStyleSheet("color: #e11d48; font-weight: bold;")
                return

            self.login_success.emit(result)
            self.accept()
        except Exception as e:
            self.status_label.setText(f"❌ 凭证处理异常: {e}")
            self.status_label.setStyleSheet("color: #e11d48; font-weight: bold;")
            clean_uid = int(uid) if str(uid).isdigit() else uid
            result = {
                "uid": clean_uid,
                "access_key": str(access_key),
                "uname": uname,
                "account": account
            }
            if extra_result:
                result.update(extra_result)
            self.login_success.emit(result)
            self.accept()

    def closeEvent(self, event):
        if self.qr_thread and self.qr_thread.isRunning():
            self.qr_thread.stop()
            self.qr_thread.wait()
        event.accept()
        super().closeEvent(event)

    def reject(self):
        if self.qr_thread and self.qr_thread.isRunning():
            self.qr_thread.stop()
            self.qr_thread.wait()
        super().reject()
