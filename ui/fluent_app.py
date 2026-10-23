# -*- coding: utf-8 -*-
"""
Windows 11 原生 Fluent 风格二游自动化总控界面
基于 PySide6 + PySide6-Fluent-Widgets 构建
"""
import os
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, CheckBox, ComboBox,
    FluentIcon as FIF, FluentWindow, InfoBar, InfoBarPosition,
    LineEdit, MSFluentWindow, NavigationItemPosition, PasswordLineEdit,
    PlainTextEdit, PrimaryPushButton, PushButton, SimpleCardWidget,
    SmoothScrollArea, SpinBox, SubtitleLabel, SwitchButton, Theme, TitleLabel,
    isDarkTheme, setTheme, setThemeColor
)

from core.plugin_manager import GamePlugin, plugin_manager
from core.task_runner import (
    GameTaskWorker, SequentialPipelineWorker, honkai3_automation_running,
    honkai3_automation_paused, pause_honkai3_automation,
    resume_honkai3_automation,
)
from ui.theme_manager import ThemeMode, theme_manager


class LazyInterface(QWidget):
    """按需/延迟加载包装器，大幅削减主窗口冷启动耗时，在用户切换或空闲时无感初始化"""

    def __init__(self, factory, object_name: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(object_name)
        self.factory = factory
        self.real_widget = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._loaded = False

    def ensure_loaded(self):
        if not self._loaded:
            self._loaded = True
            self.real_widget = self.factory()
            self._layout.addWidget(self.real_widget)

    def showEvent(self, event):
        self.ensure_loaded()
        super().showEvent(event)


class GameInterface(SmoothScrollArea):
    """单个游戏分区页面 (Fluent 原生开阔舒适布局，60fps 平滑惯性滚动)"""

    def __init__(self, plugin: GamePlugin, parent=None):
        super().__init__(parent=parent)
        self.plugin = plugin
        self.worker: Optional[GameTaskWorker] = None
        self.pause_btn: Optional[PushButton] = None
        self.pause_shortcut: Optional[QShortcut] = None
        self.setObjectName(f"game_interface_{plugin.id}")

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("SmoothScrollArea, QScrollArea { border: none; background: transparent; }")

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.main_layout = QVBoxLayout(self.container)
        self.main_layout.setContentsMargins(36, 28, 36, 28)
        self.main_layout.setSpacing(22)

        self._init_header()
        self._init_task_cards()
        self._init_config_card()
        self._init_log_console()

        self.setWidget(self.container)

        if self.plugin.id == "honkai3":
            self.pause_timer = QTimer(self)
            self.pause_timer.setInterval(500)
            self.pause_timer.timeout.connect(self._refresh_pause_control)
            self.pause_timer.start()
        

    def showEvent(self, event):
        super().showEvent(event)
        

    def _init_header(self):
        """初始化顶部标题与控制栏 (双层紧凑结构，根除过宽横向溢出)"""
        header_widget = QWidget()
        h_main_layout = QVBoxLayout(header_widget)
        h_main_layout.setContentsMargins(0, 0, 0, 0)
        h_main_layout.setSpacing(10)

        # 第一行：标题 + 描述 + 运行状态指示
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        title = TitleLabel(self.plugin.name)
        info_layout.addWidget(title)

        env_badge = CaptionLabel(f"环境: {self.plugin.env}  |  {self.plugin.description}")
        env_badge.setWordWrap(True)
        env_badge.setStyleSheet("color: #888888;")
        info_layout.addWidget(env_badge)
        top_row.addLayout(info_layout, stretch=1)

        

        self.status_label = CaptionLabel("状态: 空闲")
        self.status_label.setStyleSheet("color: #0088ff; font-weight: bold; padding: 4px 10px; background: rgba(0, 136, 255, 0.08); border-radius: 6px;")
        top_row.addWidget(self.status_label, alignment=Qt.AlignRight | Qt.AlignVCenter)
        h_main_layout.addLayout(top_row)

        # 第二行：功能按键工具栏 (紧凑排布)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)

        # 启动游戏客户端按钮与快速登录B站按钮
        if self.plugin.id == "honkai3":
            self.launch_game_btn = PushButton("启动游戏", self, FIF.APPLICATION)
            self.launch_game_btn.clicked.connect(self._launch_game_client)
            btn_row.addWidget(self.launch_game_btn)

            self.bili_login_btn = PushButton("登录 B 站", self, FIF.PEOPLE)
            self.bili_login_btn.clicked.connect(self._open_bili_login_dialog)
            btn_row.addWidget(self.bili_login_btn)
        

        btn_row.addStretch()

        # 运行按钮
        self.run_btn = PrimaryPushButton("运行任务", self, FIF.PLAY)
        self.run_btn.clicked.connect(self.start_tasks)
        btn_row.addWidget(self.run_btn)

        # 暂停/继续快捷键
        if self.plugin.id == "honkai3":
            self.pause_btn = PushButton("暂停 (F9)", self, FIF.PAUSE)
            self.pause_btn.setEnabled(False)
            self.pause_btn.clicked.connect(self.toggle_pause_tasks)
            btn_row.addWidget(self.pause_btn)

            self.pause_shortcut = QShortcut(QKeySequence("F9"), self)
            self.pause_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            self.pause_shortcut.activated.connect(self.toggle_pause_tasks)

        # 停止按钮
        self.stop_btn = PushButton("终止", self, FIF.CLOSE)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_tasks)
        btn_row.addWidget(self.stop_btn)

        h_main_layout.addLayout(btn_row)
        self.main_layout.addWidget(header_widget)

    def _open_bili_login_dialog(self):
        """打开 B 站官方风格可视化登录弹窗"""
        try:
            from ui.bili_login_dialog import BiliLoginDialog
            dlg = BiliLoginDialog(self)
            dlg.login_success.connect(self._on_bili_login_success)
            dlg.exec()
        except Exception as e:
            InfoBar.error(title="打开登录窗口失败", content=str(e), parent=self)

    def _on_bili_login_success(self, data: dict):
        """账号授权/导入成功后的联动回调"""
        uid = data.get("uid", "")
        access_key = data.get("access_key", "")
        uname = data.get("uname", "")
        server_name = data.get("server_name") or data.get("server_type") or "B服"

        if "uid" in self.config_inputs:
            self.config_inputs["uid"].setText(str(uid))
        if "access_key" in self.config_inputs:
            self.config_inputs["access_key"].setText(str(access_key))

        self.plugin.config["uid"] = uid
        self.plugin.config["access_key"] = access_key
        self.plugin.config["uname"] = uname
        if data.get("server_type"):
            self.plugin.config["server_type"] = data["server_type"]
        if data.get("server_name"):
            self.plugin.config["server_name"] = data["server_name"]
        if data.get("channel_id"):
            self.plugin.config["channel_id"] = data["channel_id"]
        if data.get("account_type"):
            self.plugin.config["account_type"] = data["account_type"]
        if data.get("dispatch"):
            self.plugin.config["dispatch"] = data["dispatch"]

        if data.get("combo_token"):
            self.plugin.config["combo_token"] = data["combo_token"]
            self.plugin.config["open_id"] = data.get("open_id", "")
            self.plugin.config["combo_id"] = data.get("combo_id", "")
        self.plugin.save_config()

        if hasattr(self, "bili_status_badge"):
            self.bili_status_badge.setText(f"✅ [{server_name}] 已绑定: {uname} (UID: {uid})")
            self.bili_status_badge.setStyleSheet("color: #22c55e; font-weight: bold;")

        InfoBar.success(
            title="账号授权成功！",
            content=f"已成功绑定【{server_name}】账号: {uname} (UID: {uid})，免扫码自动登舰已就绪！",
            orient=Qt.Horizontal,
            position=InfoBarPosition.TOP,
            duration=4000,
            parent=self
        )
        self.append_log(f"[√] 成功绑定【{server_name}】账号: {uname} (UID: {uid})，米哈游免扫码授权就绪！", "success")

    def _launch_game_client(self):
        """直接拉起本地游戏客户端"""
        game_path = self.plugin.config.get("game_path")
        if not game_path and "game_path" in self.config_inputs:
            game_path = self.config_inputs["game_path"].text().strip()

        try:
            from games.honkai3.runner import launch_game
            ok, msg = launch_game(game_path)
            if ok:
                InfoBar.success(
                    title="已启动游戏",
                    content=f"{msg}，正在为您自动衔接扫码登舰...",
                    orient=Qt.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=3500,
                    parent=self
                )
                self.append_log(f"[+] {msg}，1.5 秒后自动启动扫码登舰任务...", "success")
                QTimer.singleShot(1500, self.start_tasks)
            else:
                InfoBar.error(
                    title="启动失败",
                    content=msg,
                    orient=Qt.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=4000,
                    parent=self
                )
                self.append_log(f"[错误] {msg}", "error")
        except Exception as e:
            InfoBar.error(title="启动异常", content=str(e), parent=self)

            else:

    def _init_task_cards(self):
        """初始化自动化任务开关列表 (精美微胶囊悬浮条目与极淡柔光分隔)"""
        self.task_switches: Dict[str, SwitchButton] = {}
        self.exclusive_switches: Dict[str, SwitchButton] = {}
        self.exclusive_status_lbls: Dict[str, CaptionLabel] = {}
        self.current_exclusive_task_id: Optional[str] = None

        # 检查是否有明确的分组配置
        sections = getattr(self.plugin, "sections", [])
        if not sections:
            # 默认单一板块
            sections = [{"id": "daily", "name": "日常任务"}]
            grouped_tasks = {"daily": self.plugin.tasks}
        else:
            grouped_tasks = {sec["id"]: [] for sec in sections}
            for task in self.plugin.tasks:
                sec_id = task.get("section", sections[0]["id"])
                if sec_id not in grouped_tasks:
                    grouped_tasks[sec_id] = []
                grouped_tasks[sec_id].append(task)

        for sec_idx, sec in enumerate(sections):
            sec_id = sec["id"]
            sec_name = sec.get("name", "任务队列")
            tasks = grouped_tasks.get(sec_id, [])
            if not tasks:
                continue

            is_exclusive_sec = (sec_id in ("event", "opsi", "campaign", "war_archives"))

            sec_header = QWidget()
            sh_layout = QHBoxLayout(sec_header)
            sh_layout.setContentsMargins(0, 0, 0, 0)
            sh_layout.addWidget(SubtitleLabel(sec_name))

            if is_exclusive_sec:
                # 独占特遣板块：展示提示徽章，绝不展示全选/反选
                hint_badge = CaptionLabel("💡 独占执行模式 · 拨动开关即自动启动 (单任务防抢占)")
                hint_badge.setStyleSheet("color: #0284c7; font-weight: 500; padding: 2px 8px; background: rgba(2, 132, 199, 0.08); border-radius: 4px;")
                sh_layout.addWidget(hint_badge)
                sh_layout.addStretch()
            else:
                # 常规日常队列：展示一键推荐与全选/反选
                sh_layout.addStretch()
                if self.plugin.id == "honkai3" and sec_idx == 0:
                    btn_rec = PushButton("推荐任务", self, FIF.COMPLETED)
                    btn_rec.clicked.connect(self._apply_honkai_recommended_tasks)
                    sh_layout.addWidget(btn_rec)

                btn_select_sec = PushButton("全选 / 反选", self, FIF.CHECKBOX)
                btn_select_sec.clicked.connect(lambda checked=False, s_id=sec_id: self._toggle_section_tasks(s_id))
                sh_layout.addWidget(btn_select_sec)

            self.main_layout.addWidget(sec_header)

            tasks_container = CardWidget(self)
            t_layout = QVBoxLayout(tasks_container)
            t_layout.setContentsMargins(8, 6, 8, 6)
            t_layout.setSpacing(4)

            for i, task in enumerate(tasks):
                row = QWidget()
                row.setObjectName("task_item_row")
                row.setStyleSheet(
                    "QWidget#task_item_row {"
                    "    border-radius: 6px;"
                    "    background-color: transparent;"
                    "}"
                    "QWidget#task_item_row:hover {"
                    "    background-color: rgba(0, 0, 0, 0.035);"
                    "}"
                )
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(16, 12, 16, 12)

                t_info = QVBoxLayout()
                t_info.setSpacing(2)
                name_lbl = BodyLabel(task.get("name", task.get("id")))
                name_lbl.setStyleSheet("font-weight: 600;")
                desc_lbl = CaptionLabel(task.get("desc", ""))
                desc_lbl.setWordWrap(True)
                desc_lbl.setStyleSheet("color: #777777;")
                t_info.addWidget(name_lbl)
                t_info.addWidget(desc_lbl)
                row_layout.addLayout(t_info, stretch=1)

                task_id = task.get("id")

                if is_exclusive_sec:
                    # 独占即时执行控件组
                    ctrl_box = QHBoxLayout()
                    ctrl_box.setSpacing(10)
                    ctrl_box.setContentsMargins(0, 0, 0, 0)

                    status_indicator = CaptionLabel("⚪ 空闲")
                    status_indicator.setStyleSheet("color: #888888; font-weight: bold; min-width: 60px;")
                    ctrl_box.addWidget(status_indicator, alignment=Qt.AlignRight | Qt.AlignVCenter)
                    self.exclusive_status_lbls[task_id] = status_indicator

                    switch = SwitchButton(self)
                    switch.setOnText("")
                    switch.setOffText("")
                    switch.setText("")
                    if hasattr(switch, "label") and switch.label:
                        switch.label.hide()
                    switch.checkedChanged.connect(lambda checked, tid=task_id: self._on_exclusive_task_toggled(tid, checked))
                    ctrl_box.addWidget(switch, alignment=Qt.AlignRight | Qt.AlignVCenter)
                    self.exclusive_switches[task_id] = switch

                    row_layout.addLayout(ctrl_box)
                else:
                    # 常规日常配置开关
                    switch = SwitchButton(self)
                    switch.setOnText("")
                    switch.setOffText("")
                    switch.setText("")
                    if hasattr(switch, "label") and switch.label:
                        switch.label.hide()
                    row_layout.addWidget(switch, alignment=Qt.AlignRight | Qt.AlignVCenter)
                    self.task_switches[task_id] = switch
                    enabled = task.get("enabled", True)
                    if enabled:
                        switch.setChecked(True)
                    switch.checkedChanged.connect(lambda checked, tid=task_id: self._on_task_toggled(tid, checked))

                t_layout.addWidget(row)

                if i < len(tasks) - 1:
                    # 告别生硬粗黑的 3D QFrame.HLine，改用超轻柔 1px 细线分隔，高颜值呼吸感
                    line = QFrame()
                    line.setFixedHeight(1)
                    line.setStyleSheet("border: none; background-color: rgba(128, 128, 128, 0.12); min-height: 1px; max-height: 1px;")
                    t_layout.addWidget(line)

            self.main_layout.addWidget(tasks_container)

    def _apply_honkai_recommended_tasks(self):
        """应用崩坏3官方推荐日常方案 (全部日常开启，关闭退出游戏)"""
        recommended_on = {
            "auto_login", "handle_popups", "daily_sweep", "arena_sweep",
            "dorm_errand", "expedition", "armada", "missions", "mail"
        }
        for t in self.plugin.tasks:
            tid = t.get("id")
            should_enable = tid in recommended_on
            t["enabled"] = should_enable
            if tid in self.task_switches:
                self.task_switches[tid].setChecked(should_enable)
        self.plugin.save_manifest()
        InfoBar.success(
            title="推荐配置已应用",
            content="已为您勾选：免密登录 + 签到弹窗 + 材料减负 + 战场快速通关 + 家园打工 + 远征体力 + 舰团委托 + 600历练值宝箱 + 邮件！",
            orient=Qt.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3500,
            parent=self
        )

    def _toggle_section_tasks(self, section_id: str):
        """切换特定板块内的全选/反选"""
        sec_tasks = [t for t in self.plugin.tasks if t.get("section", "daily") == section_id or (section_id == "daily" and "section" not in t)]
        any_disabled = any(not t.get("enabled", True) for t in sec_tasks if t.get("id") != "auto_close")
        for t in sec_tasks:
            if t.get("id") == "auto_close" and any_disabled:
                continue
            t["enabled"] = any_disabled
            tid = t.get("id")
            if tid in self.task_switches:
                self.task_switches[tid].setChecked(any_disabled)
        self.plugin.save_manifest()

    def _toggle_all_tasks(self):
        """切换全局全选/全不选"""
        any_disabled = any(not t.get("enabled", True) for t in self.plugin.tasks if t.get("id") != "auto_close")
        for t in self.plugin.tasks:
            if t.get("id") == "auto_close" and any_disabled:
                continue
            t["enabled"] = any_disabled
            tid = t.get("id")
            if tid in self.task_switches:
                self.task_switches[tid].setChecked(any_disabled)
        self.plugin.save_manifest()

    def _on_task_toggled(self, task_id: str, checked: bool):
        for t in self.plugin.tasks:
            if t.get("id") == task_id:
                t["enabled"] = checked
                break
        self.plugin.save_manifest()

    def _on_exclusive_task_toggled(self, task_id: str, checked: bool):
        """独占任务开关触发：打开即执行，关闭即停止，严格单任务互斥防抢占"""
        if checked:
            if self.worker and self.worker.isRunning():
                if self.current_exclusive_task_id == task_id:
                    return
                InfoBar.warning(
                    title="任务互斥保护",
                    content="当前已有自动化任务正在运行中，已自动阻止并发抢占。",
                    parent=self,
                    duration=3000
                )
                sw = self.exclusive_switches.get(task_id)
                if sw:
                    sw.blockSignals(True)
                    sw.setChecked(False)
                    sw.blockSignals(False)
                return

            self.current_exclusive_task_id = task_id
            self.run_btn.setEnabled(False)

            # 互斥锁定其他所有独占任务开关
            for tid, sw in self.exclusive_switches.items():
                if tid != task_id:
                    sw.setEnabled(False)
                    lbl = self.exclusive_status_lbls.get(tid)
                    if lbl:
                        lbl.setText("🔒 互斥锁定")
                        lbl.setStyleSheet("color: #a8a29e; font-weight: bold; min-width: 60px;")
                else:
                    lbl = self.exclusive_status_lbls.get(tid)
                    if lbl:
                        lbl.setText("🟢 运行中")
                        lbl.setStyleSheet("color: #22c55e; font-weight: bold; min-width: 60px;")

            self._start_single_task(task_id)
        else:
            if self.current_exclusive_task_id == task_id:
                lbl = self.exclusive_status_lbls.get(task_id)
                if lbl:
                    lbl.setText("⚪ 空闲")
                    lbl.setStyleSheet("color: #888888; font-weight: bold; min-width: 60px;")
                sw = self.exclusive_switches.get(task_id)
                if sw:
                    sw.setEnabled(False)

                self.status_label.setText("状态: 空闲 (已手动停止)")
                self.status_label.setStyleSheet("color: #0088ff; font-weight: bold; padding: 4px 10px; background: rgba(0, 136, 255, 0.08); border-radius: 6px;")
                self.append_log(f"用户主动关闭【{task_id}】，已发送终止信号...", "warning")
                self.stop_tasks()
    def _start_single_task(self, task_id: str):
        """拉起单个独占任务执行器 (单任务防抢占模式)"""
        if self.worker and self.worker.isRunning():
            return

        task_name = task_id
        for t in self.plugin.tasks:
            if t.get("id") == task_id:
                task_name = t.get("name", task_id)
                break

        self.log_console.clear()
        self.append_log(f"正在拉起【{task_name}】独占自动化任务 (单任务防抢占模式)...", "info")
        self.status_label.setText(f"状态: 独占运行中 ({task_name})")
        self.status_label.setStyleSheet("color: #ff9900; font-weight: bold;")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        if self.pause_btn:
            self.pause_btn.setEnabled(False)

        self.worker = GameTaskWorker(self.plugin.id, task_ids=[task_id])
        self.worker.signals.log_emitted.connect(lambda gid, txt, lvl: self.append_log(txt, lvl))
        self.worker.signals.game_finished.connect(self._on_worker_finished)
        self.worker.start()

    def _reset_exclusive_ui(self):
        """恢复所有独占任务开关与状态标签至初始就绪状态"""
        self.current_exclusive_task_id = None
        for tid, sw in self.exclusive_switches.items():
            sw.blockSignals(True)
            sw.setChecked(False)
            sw.setEnabled(True)
            if hasattr(sw, "label") and sw.label:
                sw.label.hide()
            sw.blockSignals(False)
            lbl = self.exclusive_status_lbls.get(tid)
            if lbl:
                lbl.setText("⚪ 空闲")
                lbl.setStyleSheet("color: #888888; font-weight: bold; min-width: 60px;")

    def _init_config_card(self):
        """初始化游戏游戏配置表单"""
        sec_title = SubtitleLabel("游戏配置")
        self.main_layout.addWidget(sec_title)

        card = CardWidget(self)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 16, 20, 16)
        c_layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.config_inputs = {}

        if self.plugin.id == "honkai3":
            # 游戏可执行文件路径 (BH3.exe)
            path_layout = QHBoxLayout()
            path_input = LineEdit(self)
            cur_path = self.plugin.config.get("game_path", "")
            if not cur_path:
                try:
                    from games.honkai3.runner import detect_bh3_path
                    cur_path = detect_bh3_path() or ""
                except Exception:
                    cur_path = ""
            path_input.setText(cur_path)
            path_input.setPlaceholderText("选择或自动检索本地 BH3.exe 路径")
            self.config_inputs["game_path"] = path_input
            path_layout.addWidget(path_input)

            btn_browse = PushButton("浏览...", self, FIF.FOLDER)
            btn_browse.clicked.connect(self._browse_bh3_path)
            path_layout.addWidget(btn_browse)

            btn_detect = PushButton("自动检索", self, FIF.SEARCH)
            btn_detect.clicked.connect(self._detect_bh3_path)
            path_layout.addWidget(btn_detect)

            form.addRow("游戏主程序 (BH3.exe):", path_layout)

            # 崩坏3 账号状态提示与可视化登录入口
            status_box = QHBoxLayout()
            server_name = self.plugin.config.get("server_name") or self.plugin.config.get("server_type") or "B服"
            has_auth = bool((self.plugin.config.get("uid") and self.plugin.config.get("access_key")) or self.plugin.config.get("combo_token"))
            uname = self.plugin.config.get("uname") or f"UID_{self.plugin.config.get('uid')}"
            status_text = f"✅ [{server_name}] 已绑定: {uname} (UID: {self.plugin.config.get('uid')})" if has_auth else "⚠️ 尚未绑定 (点击右侧登录/导入)"
            color = "#22c55e" if has_auth else "#eab308"
            self.bili_status_badge = CaptionLabel(status_text)
            self.bili_status_badge.setStyleSheet(f"color: {color}; font-weight: bold;")
            status_box.addWidget(self.bili_status_badge)

            btn_open_login = PrimaryPushButton("🔑 账号授权 / 导入备份", self, FIF.PEOPLE)
            btn_open_login.clicked.connect(self._open_bili_login_dialog)
            status_box.addWidget(btn_open_login)
            form.addRow("游戏账号授权:", status_box)

            # 崩坏3专属配置
            self.config_inputs["uid"] = LineEdit(self)
            self.config_inputs["uid"].setText(str(self.plugin.config.get("uid", "")))
            self.config_inputs["uid"].setPlaceholderText("B 站 UID")
            form.addRow("B 站 UID:", self.config_inputs["uid"])

            self.config_inputs["access_key"] = PasswordLineEdit(self)
            self.config_inputs["access_key"].setText(str(self.plugin.config.get("access_key", "")))
            self.config_inputs["access_key"].setPlaceholderText("B 站 access_key")
            form.addRow("B 站 access_key:", self.config_inputs["access_key"])

            self.config_inputs["bh_ver"] = LineEdit(self)
            self.config_inputs["bh_ver"].setText(str(self.plugin.config.get("bh_ver", "9.0.0")))
            form.addRow("游戏客户端版本:", self.config_inputs["bh_ver"])

            # 校验凭证按钮
            token_btn_box = QHBoxLayout()
            btn_verify = PushButton("核验 B 站与米哈游凭证", self, FIF.ACCEPT)
            btn_verify.clicked.connect(self._verify_honkai_token)
            token_btn_box.addWidget(btn_verify)
            form.addRow("", token_btn_box)

        else:
            for k, v in self.plugin.config.items():
                inp = LineEdit(self)
                inp.setText(str(v))
                form.addRow(f"{k}:", inp)
                self.config_inputs[k] = inp

        c_layout.addLayout(form)

        # 保存配置按钮
        btn_save = PrimaryPushButton("保存当前分区配置", self, FIF.SAVE)
        btn_save.clicked.connect(self._save_game_config)
        c_layout.addWidget(btn_save)

        self.main_layout.addWidget(card)

    def _verify_honkai_token(self):
        uid = self.config_inputs["uid"].text().strip()
        key = self.config_inputs["access_key"].text().strip()
        if not uid or not key:
            InfoBar.warning(
                title="提示",
                content="请先填写 UID 与 access_key！",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        try:
            from games.honkai3 import mihoyo_api
            res = mihoyo_api.verify_bili_account(uid, key)
            if res.get("retcode") == 0:
                data_combo = res.get("data", {})
                if data_combo.get("combo_token"):
                    self.plugin.config["combo_token"] = data_combo["combo_token"]
                    self.plugin.config["open_id"] = data_combo.get("open_id", "")
                    self.plugin.config["combo_id"] = data_combo.get("combo_id", "")
                    self.plugin.config["uid"] = int(uid) if str(uid).isdigit() else uid
                    self.plugin.config["access_key"] = key
                    self.plugin.save_config()

                if hasattr(self, "bili_status_badge"):
                    self.bili_status_badge.setText(f"✅ B站授权状态: 已绑定 (UID: {uid})")
                    self.bili_status_badge.setStyleSheet("color: #22c55e; font-weight: bold;")

                InfoBar.success(
                    title="验证成功",
                    content="B站与米哈游协议对接成功！凭据有效已持久化保存！",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3500,
                    parent=self
                )
            else:
                err_msg = res.get('message', res)
                tip = ""
                if "渠道" in str(err_msg) or res.get("retcode") == -107:
                    tip = "\n提示: 米哈游 B 服要求使用 B 站游戏中心客户端专属凭据。请在【登录 B 站账号】中使用【账号密码登录】（拖动滑块验证）或【导入扫码器】！"
                InfoBar.error(
                    title="验证未通过",
                    content=f"米哈游返回: {err_msg}{tip}",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self
                )
        except Exception as e:
            InfoBar.error(
                title="验证异常",
                content=str(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )

    def _browse_bh3_path(self):
        """打开文件对话框选择 BH3.exe"""
        cur = self.config_inputs.get("game_path", {}).text() if "game_path" in self.config_inputs else ""
        start_dir = os.path.dirname(cur) if cur and os.path.isdir(os.path.dirname(cur)) else "C:\\"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择崩坏3游戏主程序 (BH3.exe)",
            start_dir,
            "游戏主程序 (BH3.exe);;所有可执行文件 (*.exe);;所有文件 (*.*)"
        )
        if file_path:
            normed = os.path.normpath(file_path)
            if "game_path" in self.config_inputs:
                self.config_inputs["game_path"].setText(normed)
            self.plugin.config["game_path"] = normed
            self.plugin.save_config()
            InfoBar.success(
                title="路径已更新",
                content=f"已选定游戏文件: {normed}",
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )

    def _detect_bh3_path(self):
        """自动从系统注册表检索 BH3.exe 路径"""
        try:
            from games.honkai3.runner import detect_bh3_path
            detected = detect_bh3_path()
            if detected:
                if "game_path" in self.config_inputs:
                    self.config_inputs["game_path"].setText(detected)
                self.plugin.config["game_path"] = detected
                self.plugin.save_config()
                InfoBar.success(
                    title="自动定位成功",
                    content=f"已检索到本地崩坏3: {detected}",
                    orient=Qt.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=3500,
                    parent=self
                )
            else:
                InfoBar.warning(
                    title="未检索到",
                    content="未能从注册表自动定位，请点击【浏览...】手动指定！",
                    orient=Qt.Horizontal,
                    position=InfoBarPosition.TOP,
                    duration=3500,
                    parent=self
                )
        except Exception as e:
            InfoBar.error(title="检索异常", content=str(e), parent=self)

    def _save_game_config(self):
        for k, inp in self.config_inputs.items():
            if isinstance(inp, SpinBox):
                self.plugin.config[k] = inp.value()
            elif hasattr(inp, "text"):
                val = inp.text().strip()
                if k == "uid" and val.isdigit():
                    self.plugin.config[k] = int(val)
                else:
                    self.plugin.config[k] = val
        self.plugin.save_config()
        InfoBar.success(
            title="成功",
            content="配置已成功保存至本地 config.json！",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self
        )

    def _init_log_console(self):
        """初始化终端控制台 (全宽开阔视窗 + 复制/清空工具栏)"""
        sec_header = QWidget()
        sh_layout = QHBoxLayout(sec_header)
        sh_layout.setContentsMargins(0, 0, 0, 0)
        sh_layout.addWidget(SubtitleLabel("实时运行日志 (Live Console)"))

        sh_layout.addStretch()

        btn_copy = PushButton("复制日志", self, FIF.COPY)
        btn_copy.clicked.connect(self._copy_log)
        sh_layout.addWidget(btn_copy)

        btn_clear = PushButton("清空控制台", self, FIF.DELETE)
        def _on_clear_clicked():
            self.log_console.clear()
            import gc
            gc.collect()
        btn_clear.clicked.connect(_on_clear_clicked)
        sh_layout.addWidget(btn_clear)

        self.main_layout.addWidget(sec_header)

        self.log_console = PlainTextEdit(self)
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumBlockCount(1000)  # 严格限制内存与文档规模，淘汰老日志，杜绝长期运行导致的排版与重绘卡顿
        self.log_console.setMinimumHeight(260)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        self.log_console.setFont(font)

        # 初始主题与响应主题切换信号
        self.set_console_theme(isDarkTheme())
        theme_manager.theme_changed.connect(self.set_console_theme)

        self.main_layout.addWidget(self.log_console)

    def _copy_log(self):
        """复制控制台日志文本到剪贴板"""
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.log_console.toPlainText())
            InfoBar.success(
                title="已复制",
                content="控制台日志已成功复制到系统剪贴板！",
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )

    def set_console_theme(self, is_dark: bool):
        """根据主题模式自适应控制台底色与文字对比度"""
        if is_dark:
            self.log_console.setStyleSheet(
                "PlainTextEdit {"
                "  background-color: #121214;"
                "  color: #38ef7d;"
                "  border: 1px solid rgba(255, 255, 255, 0.1);"
                "  border-radius: 8px;"
                "  padding: 10px;"
                "}"
            )
        else:
            self.log_console.setStyleSheet(
                "PlainTextEdit {"
                "  background-color: #f8fafc;"
                "  color: #0f172a;"
                "  border: 1px solid rgba(0, 0, 0, 0.12);"
                "  border-radius: 8px;"
                "  padding: 10px;"
                "}"
            )

    def append_log(self, text: str, level: str = "info"):
        prefix = ""
        if level == "error":
            prefix = "[ERROR] "
        elif level == "warning":
            prefix = "[WARN]  "
        elif level == "success":
            prefix = "[OK]    "
        self.log_console.appendPlainText(f"{prefix}{text}")
        self.log_console.ensureCursorVisible()

    def start_tasks(self):
        if self.worker and self.worker.isRunning():
            return

        self.log_console.clear()
        self.append_log(f"正在拉起【{self.plugin.name}】后台调度任务...", "info")
        self.status_label.setText("状态: 运行中...")
        self.status_label.setStyleSheet("color: #ff9900; font-weight: bold; padding: 4px 10px; background: rgba(255, 153, 0, 0.1); border-radius: 6px;")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        if self.pause_btn:
            self.pause_btn.setText("暂停 (F9)")
            self.pause_btn.setEnabled(False)

        # 准确收集界面上勾选启用的常规日常任务 (排除独占特遣板块)
        selected_task_ids = []
        for t in self.plugin.tasks:
            sec = t.get("section", "daily")
            if sec in ("event", "opsi", "campaign", "war_archives"):
                continue  # 活动、大世界、主线困难与作战档案采用独立即时开关，不参与日常批量队列
            tid = t.get("id")
            sw = self.task_switches.get(tid)
            if (sw and sw.isChecked()) or (not sw and t.get("enabled", True)):
                selected_task_ids.append(tid)

        if not selected_task_ids:
            self.append_log("当前日常任务队列未启用任何任务，请在列表开启所需任务！", "warning")
            self.status_label.setText("状态: 空闲")
            self.status_label.setStyleSheet("color: #0088ff; font-weight: bold; padding: 4px 10px; background: rgba(0, 136, 255, 0.08); border-radius: 6px;")
            self.run_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        # 在常规日常批量执行期间，锁定所有独占任务开关，防止并发争抢
        for tid, sw in self.exclusive_switches.items():
            sw.setEnabled(False)
            lbl = self.exclusive_status_lbls.get(tid)
            if lbl:
                lbl.setText("🔒 互斥锁定")
                lbl.setStyleSheet("color: #a8a29e; font-weight: bold; min-width: 60px;")

        self.worker = GameTaskWorker(self.plugin.id, task_ids=selected_task_ids)
        self.worker.signals.log_emitted.connect(lambda gid, txt, lvl: self.append_log(txt, lvl))
        self.worker.signals.game_finished.connect(self._on_worker_finished)
        self.worker.start()

    def stop_tasks(self):
        if self.worker and self.worker.isRunning():
            self.append_log("正在发送终止信号...", "warning")
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            if self.pause_btn:
                self.pause_btn.setEnabled(False)
    def toggle_pause_tasks(self):
        """控制崩坏3分区和全局流水线启动的所有崩坏3执行器。"""
        if self.plugin.id != "honkai3" or not honkai3_automation_running():
            return

        if honkai3_automation_paused():
            if resume_honkai3_automation():
                self.status_label.setText("状态: 运行中...")
                self.status_label.setStyleSheet("color: #ff9900; font-weight: bold; padding: 4px 10px; background: rgba(255, 153, 0, 0.1); border-radius: 6px;")
                self.append_log("[继续] 崩坏3自动化已恢复。", "success")
                if self.pause_btn:
                    self.pause_btn.setText("暂停 (F9)")
            else:
                self.append_log("[!] 无法恢复自动化子进程，请使用终止后重新运行。", "error")
        else:
            if pause_honkai3_automation():
                self.status_label.setText("状态: 已暂停")
                self.status_label.setStyleSheet("color: #d97706; font-weight: bold; padding: 4px 10px; background: rgba(217, 119, 6, 0.1); border-radius: 6px;")
                self.append_log("[暂停] 崩坏3自动化已暂停；游戏保持运行。", "warning")
                if self.pause_btn:
                    self.pause_btn.setText("继续 (F9)")
            else:
                self.append_log("[!] 自动化子进程尚未就绪，暂时无法暂停。", "warning")

    def _refresh_pause_control(self):
        """同步崩坏3分区按钮与全局流水线的实际进程状态 (带脏检查，杜绝多余重绘)。"""
        if not self.pause_btn:
            return
        running = honkai3_automation_running()
        paused = running and honkai3_automation_paused()
        if self.pause_btn.isEnabled() != running:
            self.pause_btn.setEnabled(running)
        target_text = "继续 (F9)" if paused else "暂停 (F9)"
        if self.pause_btn.text() != target_text:
            self.pause_btn.setText(target_text)
        if paused:
            if self.status_label.text() != "状态: 已暂停":
                self.status_label.setText("状态: 已暂停")
                self.status_label.setStyleSheet("color: #d97706; font-weight: bold; padding: 4px 10px; background: rgba(217, 119, 6, 0.1); border-radius: 6px;")
        elif running:
            if self.status_label.text() != "状态: 运行中...":
                self.status_label.setText("状态: 运行中...")
                self.status_label.setStyleSheet("color: #ff9900; font-weight: bold; padding: 4px 10px; background: rgba(255, 153, 0, 0.1); border-radius: 6px;")

    def _on_worker_finished(self, game_id: str, success: bool, summary: str):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self.pause_btn:
            self.pause_btn.setText("暂停 (F9)")
            self.pause_btn.setEnabled(False)
        finished_task_id = self.current_exclusive_task_id
        self._reset_exclusive_ui()
        is_user_cancelled = (summary == "用户已终止")
        if not success and finished_task_id:
            lbl = self.exclusive_status_lbls.get(finished_task_id)
            if lbl:
                if is_user_cancelled:
                    lbl.setText("⚪ 空闲")
                    lbl.setStyleSheet("color: #888888; font-weight: bold; min-width: 60px;")
                else:
                    lbl.setText("🔴 执行失败")
                    lbl.setStyleSheet("color: #ef4444; font-weight: bold; min-width: 60px;")
        if success:
            if finished_task_id == "hard_campaign_3_stars":
                self.status_label.setText("状态: 主线困难本次流程完成（详情见日志）")
            elif finished_task_id:
                task_name = finished_task_id
                for t in self.plugin.tasks:
                    if t.get("id") == finished_task_id:
                        task_name = t.get("name", finished_task_id)
                        break
                self.status_label.setText(f"状态: 【{task_name}】执行完成")
            else:
                self.status_label.setText(f"状态: {summary}")
            self.status_label.setStyleSheet("color: #22c55e; font-weight: bold; padding: 4px 10px; background: rgba(34, 197, 94, 0.1); border-radius: 6px;")
        elif is_user_cancelled:
            self.status_label.setText("状态: 空闲 (已手动停止)")
            self.status_label.setStyleSheet("color: #0088ff; font-weight: bold; padding: 4px 10px; background: rgba(0, 136, 255, 0.08); border-radius: 6px;")
        else:
            self.status_label.setText(f"状态: 异常终止 ({summary})")
            self.status_label.setStyleSheet("color: #ef4444; font-weight: bold; padding: 4px 10px; background: rgba(239, 68, 68, 0.1); border-radius: 6px;")


class PipelineInterface(SmoothScrollArea):
    """全局串行一条龙调度页面 (Fluent 原生开阔舒适布局，60fps 平滑惯性滚动)"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("pipeline_interface")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("SmoothScrollArea, QScrollArea { border: none; background: transparent; }")

        self.worker: Optional[SequentialPipelineWorker] = None

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(16)

        # 标题栏
        layout.addWidget(TitleLabel("全局二游日常【一条龙】串行调度"))
        desc = CaptionLabel("按顺序依次拉起已勾选的游戏；前一个游戏完成并关闭释放内存后，自动拉起下一个游戏，避免同时争抢显存与键鼠焦点。")
        desc.setStyleSheet("color: #888888;")
        layout.addWidget(desc)

        # 游戏勾选卡片
        card = CardWidget(self)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 16, 20, 16)
        c_layout.setSpacing(12)

        c_layout.addWidget(SubtitleLabel("执行顺序队列 (勾选参与一条龙的游戏)"))

        self.game_checkboxes: Dict[str, CheckBox] = {}
        for plugin in plugin_manager.get_all_plugins():
            cb = CheckBox(f"{plugin.name} ({plugin.env})", self)
            cb.setChecked(True)
            c_layout.addWidget(cb)
            self.game_checkboxes[plugin.id] = cb

        layout.addWidget(card)

        # 控制按钮
        btn_box = QHBoxLayout()
        self.btn_run = PrimaryPushButton("启动全局一条龙流水线", self, FIF.PLAY)
        self.btn_run.clicked.connect(self.start_pipeline)
        btn_box.addWidget(self.btn_run)

        self.btn_stop = PushButton("终止流水线", self, FIF.CLOSE)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_pipeline)
        btn_box.addWidget(self.btn_stop)
        btn_box.addStretch()

        layout.addLayout(btn_box)

        # 控制台
        c_header = QWidget()
        ch_layout = QHBoxLayout(c_header)
        ch_layout.setContentsMargins(0, 0, 0, 0)
        ch_layout.addWidget(SubtitleLabel("全局流水线控制台 (Live Console)"))
        ch_layout.addStretch()

        btn_copy = PushButton("复制日志", self, FIF.COPY)
        btn_copy.clicked.connect(self._copy_log)
        ch_layout.addWidget(btn_copy)

        btn_clear = PushButton("清空控制台", self, FIF.DELETE)
        def _on_clear_clicked():
            self.log_console.clear()
            import gc
            gc.collect()
        btn_clear.clicked.connect(_on_clear_clicked)
        ch_layout.addWidget(btn_clear)

        layout.addWidget(c_header)

        self.log_console = PlainTextEdit(self)
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumBlockCount(1000)  # 严格限制内存与文档规模
        self.log_console.setMinimumHeight(280)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        self.log_console.setFont(font)

        self.set_console_theme(isDarkTheme())
        theme_manager.theme_changed.connect(self.set_console_theme)

        layout.addWidget(self.log_console)

        self.setWidget(container)

    def _copy_log(self):
        """复制控制台日志文本到剪贴板"""
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.log_console.toPlainText())
            InfoBar.success(
                title="已复制",
                content="全局流水线日志已成功复制到系统剪贴板！",
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )

    def set_console_theme(self, is_dark: bool):
        """根据主题模式自适应控制台底色与文字对比度"""
        if is_dark:
            self.log_console.setStyleSheet(
                "PlainTextEdit {"
                "  background-color: #121214;"
                "  color: #38ef7d;"
                "  border: 1px solid rgba(255, 255, 255, 0.1);"
                "  border-radius: 8px;"
                "  padding: 10px;"
                "}"
            )
        else:
            self.log_console.setStyleSheet(
                "PlainTextEdit {"
                "  background-color: #f8fafc;"
                "  color: #0f172a;"
                "  border: 1px solid rgba(0, 0, 0, 0.12);"
                "  border-radius: 8px;"
                "  padding: 10px;"
                "}"
            )

    def start_pipeline(self):
        selected_games = [
            gid for gid, cb in self.game_checkboxes.items() if cb.isChecked()
        ]
        if not selected_games:
            InfoBar.warning(
                title="提示",
                content="请至少勾选一个要执行的游戏分区！",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        self.log_console.clear()
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.worker = SequentialPipelineWorker(selected_games)
        self.worker.signals.log_emitted.connect(lambda gid, txt, lvl: self.log_console.appendPlainText(f"[{gid}] {txt}"))
        self.worker.signals.game_finished.connect(self._on_finished)
        self.worker.start()

    def stop_pipeline(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.btn_stop.setEnabled(False)

    def _on_finished(self, game_id, success, summary):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        import gc
        gc.collect()


class SettingsInterface(SmoothScrollArea):
    """设置与扩展新游戏管理页面 (已升级 Fluent 60fps 平滑惯性滚动)"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("settings_interface")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("SmoothScrollArea, QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("系统设置"))

        # 1. 界面外观与主题设置卡片 (置顶第一项)
        theme_card = CardWidget(self)
        t_layout = QVBoxLayout(theme_card)
        t_layout.setContentsMargins(20, 16, 20, 16)
        t_layout.setSpacing(12)

        t_layout.addWidget(SubtitleLabel("主题切换"))
        desc_label = CaptionLabel("选择界面主题风格，支持纯白背景、暗黑背景或跟随 Windows 系统外观")
        desc_label.setStyleSheet("color: #888888;")
        t_layout.addWidget(desc_label)

        # 模式下拉选择 (黑 / 白 / 跟随系统)
        self.theme_combo = ComboBox(self)
        self.theme_options = [
            ("☀️ 亮色模式 (白)", ThemeMode.LIGHT),
            ("🌙 暗色模式 (黑)", ThemeMode.DARK),
            ("💻 跟随系统外观", ThemeMode.SYSTEM),
        ]
        for label, _ in self.theme_options:
            self.theme_combo.addItem(label)

        cur_mode = theme_manager.current_mode
        idx_to_select = 0
        for i, (_, mode_val) in enumerate(self.theme_options):
            if mode_val == cur_mode:
                idx_to_select = i
                break
        self.theme_combo.setCurrentIndex(idx_to_select)

        self.current_theme_label = CaptionLabel(f"当前生效主题: {self.theme_options[idx_to_select][0]}")
        self.current_theme_label.setStyleSheet("color: #0088ff; font-weight: bold;")

        def on_theme_changed(index):
            selected_mode = self.theme_options[index][1]
            theme_manager.check_and_apply(selected_mode)
            self.current_theme_label.setText(f"当前生效主题: {self.theme_options[index][0]}")
            InfoBar.success(
                title="主题已切换",
                content=f"已切换为: {self.theme_options[index][0]}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )

        self.theme_combo.currentIndexChanged.connect(on_theme_changed)
        t_layout.addWidget(self.theme_combo)
        t_layout.addWidget(self.current_theme_label)

        # 快捷切换按钮排
        quick_btn_box = QHBoxLayout()
        quick_btn_box.setSpacing(10)

        btn_quick_light = PushButton("白色背景 (亮色)", self, FIF.BRUSH)
        btn_quick_light.clicked.connect(lambda: self.theme_combo.setCurrentIndex(0))
        quick_btn_box.addWidget(btn_quick_light)

        btn_quick_dark = PushButton("黑色背景 (暗色)", self, FIF.BRIGHTNESS)
        btn_quick_dark.clicked.connect(lambda: self.theme_combo.setCurrentIndex(1))
        quick_btn_box.addWidget(btn_quick_dark)

        btn_quick_sys = PushButton("跟随系统", self, FIF.APPLICATION)
        btn_quick_sys.clicked.connect(lambda: self.theme_combo.setCurrentIndex(2))
        quick_btn_box.addWidget(btn_quick_sys)

        quick_btn_box.addStretch()
        t_layout.addLayout(quick_btn_box)

        layout.addWidget(theme_card)

        # 2. 扩展新游戏指南卡片
        guide_card = CardWidget(self)
        g_layout = QVBoxLayout(guide_card)
        g_layout.setContentsMargins(20, 16, 20, 16)
        g_layout.setSpacing(10)

        g_layout.addWidget(SubtitleLabel("如何添加新游戏分区？（热插拔机制）"))
        info = CaptionLabel(
            "本平台采用完全解耦的插件化架构。只需将 games/_template 模板文件夹复制一份，\n"
            "重命名为你想要的游戏（如 genshin / zzz），修改 manifest.json 中的任务名称与 runner.py，\n"
            "重启或刷新平台后，左侧导航栏将全自动生成该游戏的分区页面，无需更改平台本体任何代码！"
        )
        info.setStyleSheet("color: #aaaaaa; line-height: 1.5;")
        g_layout.addWidget(info)

        btn_open_folder = PrimaryPushButton("在文件资源管理器中打开 games 目录", self, FIF.FOLDER)
        btn_open_folder.clicked.connect(self._open_games_folder)
        g_layout.addWidget(btn_open_folder)

        layout.addWidget(guide_card)

        layout.addStretch()
        self.setWidget(container)

    def _open_games_folder(self):
        games_path = Path(__file__).parent.parent / "games"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(games_path.resolve())))


class MainWindow(FluentWindow):
    """总控平台 Fluent 主窗口"""

    def __init__(self):
        super().__init__()
        self.resize(1220, 820)
        self.setMinimumSize(1000, 640)
        self.center_on_screen()

        # 应用已保存的主题 (默认亮色白色背景，或根据偏好自适应)
        theme_manager.check_and_apply()

        self.hBoxLayout.setContentsMargins(0, 48, 0, 0)
        self.widgetLayout.setContentsMargins(0, 0, 0, 0)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor("#f5f5f5", "#202020")
        self.navigationInterface.setExpandWidth(220)
        self.navigationInterface.setMinimumExpandWidth(800)
        self.navigationInterface.setCollapsible(False)
        self.navigationInterface.expand(useAni=False)
        self.navigationInterface.setMenuButtonVisible(False)
        self.navigationInterface.setReturnButtonVisible(False)
        self._init_navigation()
        self._apply_codex_theme(isDarkTheme())
        theme_manager.theme_changed.connect(self._apply_codex_theme)

        # 启动每分钟定时器，在自适应模式下平滑切换
        self.time_timer = QTimer(self)
        self.time_timer.setInterval(60 * 1000)
        self.time_timer.timeout.connect(self._check_time_theme)
        self.time_timer.start()

        # 在窗口呈现后利用空闲时间逐步预热未激活页面，确保后续切换零卡顿
        QTimer.singleShot(1500, self._prewarm_interfaces)

    def _apply_codex_theme(self, dark):
        """Neutral surfaces and readable controls shared by every lazy page."""
        foreground = "#ececec" if dark else "#252525"
        surface = "#262626" if dark else "#ffffff"
        sidebar = "#202020" if dark else "#f5f5f5"
        border = "#3b3b3b" if dark else "#e8e8e8"
        hover = "#343434" if dark else "#ededed"
        accent = "#ececec" if dark else "#252525"
        setThemeColor(QColor(accent))
        self.setCustomBackgroundColor("#f5f5f5", "#202020")
        self.stackedWidget.setStyleSheet(
            f"StackedWidget {{ background: {surface}; border: none; border-left: 1px solid {border}; border-radius: 0px; }}"
        )
        self.navigationInterface.setStyleSheet(
            f"NavigationInterface, NavigationPanel {{ background: {sidebar}; border: none; }}"
        )
        self.setStyleSheet(f"""
            MainWindow {{ background: {sidebar}; }}
            QWidget {{ font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"; }}
            TitleLabel {{ font-size: 26px; font-weight: 600; color: {foreground}; }}
            SubtitleLabel {{ font-size: 16px; font-weight: 600; color: {foreground}; }}
            BodyLabel {{ font-size: 14px; color: {foreground}; }}
            CaptionLabel {{ font-size: 12px; }}
            CardWidget, SimpleCardWidget {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
            PushButton {{ background: transparent; border: 1px solid {border}; border-radius: 8px; padding: 7px 12px; color: {foreground}; font-size: 13px; }}
            PushButton:hover {{ background: {hover}; }}
            PushButton:disabled {{ color: #909090; background: transparent; }}
            PrimaryPushButton {{ background: {accent}; border: none; border-radius: 8px; padding: 7px 16px; color: {sidebar}; font-size: 13px; font-weight: 600; }}
            PrimaryPushButton:hover {{ background: {'#d0d0d0' if dark else '#454545'}; }}
            PrimaryPushButton:disabled {{ background: {hover}; color: #909090; }}
            LineEdit, PasswordLineEdit, ComboBox, SpinBox {{ border-radius: 7px; }}
        """)

    def showEvent(self, event):
        super().showEvent(event)
        self.setWindowTitle("崩坏3 全自动管家")

    def center_on_screen(self):
        """将窗口自适应居中显示在当前活动屏幕的可视工作区（自动避开任务栏）"""
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        w = min(self.width(), geo.width())
        h = min(self.height(), geo.height())
        self.resize(w, h)
        cx = geo.x() + max(0, (geo.width() - w) // 2)
        cy = geo.y() + max(0, (geo.height() - h) // 2)
        self.move(cx, cy)

    def _check_time_theme(self):
        if theme_manager.current_mode == ThemeMode.TIME_AUTO:
            theme_manager.check_and_apply()

    def _prewarm_interfaces(self):
        """利用系统空闲时间分步预加载非激活页面，确保后续切换零等待"""
        for lazy in self.lazy_interfaces:
            if not lazy._loaded:
                lazy.ensure_loaded()
                break  # 每次事件循环只预热一个，避免阻塞
        if any(not lazy._loaded for lazy in self.lazy_interfaces):
            QTimer.singleShot(300, self._prewarm_interfaces)

    def _init_navigation(self):
        plugins = plugin_manager.get_all_plugins()

        # 图标映射字典
        icon_map = {
            "honkai3": FIF.GAME,
            
        }

        self.lazy_interfaces: List[LazyInterface] = []

        # 1. 动态为每个游戏添加分区页面（统一采用 LazyInterface 懒加载，窗口骨架秒开无等待）
        for i, plugin in enumerate(plugins):
            obj_name = f"game_interface_{plugin.id}"
            icon = icon_map.get(plugin.id, FIF.APPLICATION)
            p = plugin
            interface = LazyInterface(lambda p=p: GameInterface(p, self), obj_name, self)
            self.lazy_interfaces.append(interface)

            self.addSubInterface(
                interface=interface,
                icon=icon,
                text=plugin.name,
                position=NavigationItemPosition.TOP
            )

        # 2. 添加全局一条龙页面 (按需懒加载)
        self.pipeline_interface = LazyInterface(lambda: PipelineInterface(self), "pipeline_interface", self)
        self.lazy_interfaces.append(self.pipeline_interface)
        self.addSubInterface(
            interface=self.pipeline_interface,
            icon=FIF.SYNC,
            text="全局一条龙",
            position=NavigationItemPosition.TOP
        )

        # 3. 添加左下角设置按钮 (齿轮图标，按需懒加载)
        self.settings_interface = LazyInterface(lambda: SettingsInterface(self), "settings_interface", self)
        self.lazy_interfaces.append(self.settings_interface)
        self.addSubInterface(
            interface=self.settings_interface,
            icon=FIF.SETTING,
            text="设置",
            position=NavigationItemPosition.BOTTOM
        )

    def closeEvent(self, event):
        """
        极速关闭退出管线：
        1. 瞬间隐藏窗口，实现 0.01 秒内的零延迟视觉关闭；
        2. 快速停止各游戏与全局一条龙的后台 Worker 线程及子进程树；
        3. 停用全部常驻高频定时器；
        4. 采用 os._exit(0) 绕过长期运行后对数十万对象的耗时 GC 析构，实现操作系统级秒退。
        """
        try:
            # 1. 立即从用户屏幕隐藏主窗口，消除视觉假死与卡顿滞留
            self.hide()
            event.accept()

            # 2. 停用常驻定时器
            if hasattr(self, 'time_timer') and self.time_timer.isActive():
                self.time_timer.stop()

            # 3. 停止所有已加载分区的后台工作线程与定时器
            for lazy in getattr(self, 'lazy_interfaces', []):
                widget = getattr(lazy, 'real_widget', getattr(lazy, '_widget', None))
                if getattr(lazy, '_loaded', False) and widget:
                    # 停用分区定时器
                    if hasattr(widget, 'pause_timer') and widget.pause_timer.isActive():
                        widget.pause_timer.stop()
                    
                    # 停止工作线程
                    if hasattr(widget, 'worker') and widget.worker and widget.worker.isRunning():
                        try:
                            widget.worker.stop()
                        except Exception:
                            pass

            # 4. 彻底清理  或崩坏3 可能残留的子进程
            

        except Exception:
            pass
        finally:
            # 5. 直接内核级快速退出，彻底规避 PySide/C++ 析构和海量 Python GC 遍历卡顿
            import os
            os._exit(0)


def launch_app():
    # 设置 Windows 独立任务栏进程模型 ID，确保任务栏使用专属图标而非 Python 默认图标
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GameHub.AnimeAutomation.DesktopApp.1.0")
    except Exception:
        pass

    app = QApplication(sys.argv)

    # 优先加载 assets/app_icon.ico 作为全局窗口与任务栏图标
    icon_path = Path(__file__).parent.parent / "assets" / "app_icon.ico"
    if icon_path.is_file():
        from PySide6.QtGui import QIcon
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)

    w = MainWindow()
    if icon_path.is_file():
        from PySide6.QtGui import QIcon
        w.setWindowIcon(QIcon(str(icon_path)))
    w.show()
    ret = app.exec()
    import os
    os._exit(ret)


if __name__ == "__main__":
    launch_app()

