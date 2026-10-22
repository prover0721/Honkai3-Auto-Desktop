# -*- coding: utf-8 -*-
"""
崩坏3 分层页面状态机与图导航系统 (Alas Page Graph System)
实现有向图最短路径搜索、自适应页面跳转与意外弹窗自愈
"""
import time
from collections import deque
from typing import Optional, List, Tuple, Callable, Dict, Callable
import numpy as np

from games.honkai3.core.ui_vision import Template, UIVision
from games.honkai3.core.popup import (
    TPL_MONTHLY_SIGNIN_TAB, TPL_ERRAND_CONFIRM_TITLE, TPL_EVENT_PROMO_TITLE, TPL_EVENT_FLAG, TPL_PROMO_DISMISS_HINT,
    TPL_ABYSS_SETTLE, TPL_ABYSS_DYNAMIC,
    PopupHandler,
)
from games.honkai3.core.daily_ui import (
    TPL_ERRAND_MAP, TPL_EXPEDITION_PAGE, TPL_MATERIAL_PAGE,
    BLOCKING_DIALOGS, claim_reward,
)


# 通用功能键与常驻锚点
# 崩坏3 处于新旧 UI 混合状态: 舰桥/出击已是第二部新 UI, 部分二级页面仍为老 UI。
# 因此返回/主页按钮与页面旗标均采用【多候选模板】: 新 UI 优先, 老 UI 兜底。
TPL_RETURN = Template("V2_RETURN_BUTTON.png", (-0.405, -0.444), threshold=0.75)
TPL_HOME = Template("V2_HOME_BUTTON.png", (-0.341, -0.444), threshold=0.75)
# 老 UI 版本 (HonkaiHelper 原版, 坐标已按 y*16/9 换算到本引擎的高度归一化约定)
TPL_RETURN_OLD = Template("RETURN_BUTTON.png", (-0.444, -0.455), threshold=0.75)
TPL_HOME_OLD = Template("HOME_BUTTON.png", (-0.298, -0.457), threshold=0.75)
TPL_HOME_NEW1 = Template("NEW_HOME_BUTTON.png", (-0.343, -0.448), threshold=0.75)
# 当前录屏中误入活动页后的左上角返回控件；仅在未知页兜底时尝试，不参与主界面判定。
TPL_EVENT_ACTIVITY_BACK = Template("EVENT_ACTIVITY_BACK.png", (-0.414, -0.45), threshold=0.82)
TPL_PART2_FLAG = Template("V4_PART2_FLAG.png", (-0.357, -0.458), threshold=0.88, roi_margin=(0.04, 0.05))
TPL_PART2_BACK = Template("V4_PART2_BACK.png", (-0.467, -0.459), threshold=0.88, roi_margin=(0.025, 0.04))

# 返回/主页多候选点击序列 (依次尝试, 识别到哪个点哪个)
RETURN_CANDIDATES = [TPL_RETURN, TPL_RETURN_OLD]
HOME_CANDIDATES = [TPL_HOME, TPL_HOME_NEW1, TPL_HOME_OLD]
TPL_CONFIRM = Template("CONFIRM_BUTTON.png", (0.0, 0.144), threshold=0.75)
TPL_NEW_ITEM = Template("NEW_ITEM_POPUP.png", (0.289, -0.01), threshold=0.75)

# 主界面 (第二部全新 UI 锚点)
TPL_MAIN_FLAG = Template("MAIN_FLAG.png", (0.281, 0.043), rgb=True, threshold=0.75)
TPL_MAIN_GOTO_BATTLE = Template("V2_MAIN_GOTO_BATTLE.png", (0.422, -0.027), threshold=0.75)
TPL_MAIN_GOTO_DORM = Template("V2_MAIN_GOTO_DORM.png", (0.391, 0.396), threshold=0.75)
TPL_MAIN_GOTO_ARMADA = Template("V2_MAIN_GOTO_ARMADA.png", (0.234, 0.396), threshold=0.75)
TPL_MAIN_GOTO_MISSIONS = Template("V2_MAIN_GOTO_MISSIONS.png", (-0.453, -0.33), threshold=0.75)
TPL_MAIN_GOTO_MAIL = Template("V2_MAIN_GOTO_MAIL.png", (-0.423, -0.048), threshold=0.75)

# 出击与减负
TPL_BATTLE_FLAG = Template("V2_BATTLE_FLAG.png", (-0.203, -0.353), threshold=0.75)
TPL_BATTLE_FLAG_ALT = Template("GOTO_ATTACK.png", (-0.072, -0.359), threshold=0.75)  # 顶部"出击"标签 (实测新UI 0.932)
# 推荐页左下、出击页右下均使用相同文字；不绑定旧卡片的位置或插画。
TPL_BATTLE_GOTO_LITE = Template("V6_MATERIAL_ENTRY_LABEL.png", threshold=0.85)
TPL_RECOMMEND_SELECTED = Template("V7_RECOMMEND_SELECTED.png", (-0.205, -0.356), rgb=True, threshold=0.88, roi_margin=(0.06, 0.05))
TPL_RECOMMEND_TAB = Template("V7_RECOMMEND_TAB.png", (-0.205, -0.356), rgb=True, threshold=0.88, roi_margin=(0.06, 0.05))
TPL_LITE_FLAG = Template("V2_MATL_LITE_BTN.png", (0.398, 0.43), threshold=0.75)
TPL_LITE_FLAG_OLD = Template("LITE_FLAG.png", (-0.001, -0.347), threshold=0.75)
TPL_BATTLE_CHALLENGE_TAB = Template("V2_BATTLE_CHALLENGE_TAB.png", (0.072, -0.35), threshold=0.75)
TPL_BATTLE_GOTO_ARENA = Template("V2_BATTLE_CHALLENGE_TAB.png", (0.072, -0.35), threshold=0.70)
TPL_ARENA_FLAG = Template("V2_ARENA_SWEEP_BTN.png", (0.203, 0.439), threshold=0.75)

# 家园系统
TPL_DORM_FLAG = Template("V2_DORM_STAMINA.png", (-0.35, -0.152), threshold=0.75)
TPL_DORM_FLAG_OLD = Template("DORM_STAMINA.png", (-0.34, -0.105), threshold=0.75)
TPL_DORM_GOTO_ERRANDS = Template("V2_DORM_GOTO_ERRAND.png", (0.242, 0.439), threshold=0.75)
TPL_DORM_GOTO_EXPEDITIONS = Template("V2_DORM_GOTO_EXPEDITION.png", (0.121, 0.439), threshold=0.75)
TPL_ERRANDS_FLAG = Template("V2_ERRAND_DISPATCH.png", (0.267, 0.448), threshold=0.75)
TPL_ERRANDS_FLAG_OLD = Template("ERRANDS_FLAG.png", (-0.077, -0.459), rgb=True, threshold=0.75)
TPL_EXPEDITION_FLAG = Template("V2_EXPEDITION_ONEKEY.png", (0.389, 0.439), threshold=0.75)
TPL_EXPEDITION_FLAG_OLD = Template("EXPEDITION_FLAG.png", (-0.363, -0.325), threshold=0.75)

# 舰团系统
TPL_ARMADA_FLAG = Template("ARMADA_FLAG.png", (0.113, 0.135), threshold=0.75)  # y 坐标已修正 (HH y/W 约定换算)
TPL_ARMADA_GOTO_COMMISSION = Template("ARMADA_GOTO_COMMISSION.png", (-0.113, 0.227), threshold=0.75)
TPL_COMMISSION_FLAG = Template("V2_ARMADA_SUBMIT_BTN.png", (0.22, 0.408), threshold=0.75)
TPL_COMMISSION_FLAG_OLD = Template("COMMISSION_FLAG.png", (-0.392, -0.325), threshold=0.75)
TPL_COMMISSION_GOTO_REWARD = Template("V2_ARMADA_REWARD_TAB.png", (0.413, -0.139), threshold=0.75)
TPL_ARMADA_REWARD_FLAG = Template("ARMADA_REWARD_FLAG.png", (-0.394, -0.184), threshold=0.75)

# 任务系统
TPL_MISSION_FLAG = Template("V2_MISSION_TAB.png", (-0.415, -0.222), threshold=0.75)  # 左侧【作战任务】选中标签 (实测 0.956)
TPL_MISSION_FLAG_ALT = Template("V2_MISSION_CLAIM_ALL.png", (0.418, -0.331), threshold=0.75)
TPL_MISSION_FLAG_OLD = Template("GOTO_BP_MISSIONS.png", (-0.417, -0.304), threshold=0.75)
TPL_MISSION_TAB_INACTIVE = Template("V8_MISSION_TAB_INACTIVE.png", (-0.39, -0.312), rgb=True, threshold=0.88, roi_margin=(0.065, 0.05))

# 邮件系统
TPL_MAIL_FLAG = Template("MAIL_FLAG.png", (-0.456, 0.409), threshold=0.75)  # y 坐标已修正 (HH y/W 约定换算)


class Page:
    """
    页面节点定义 (支持新旧 UI 多旗标: flag 为主模板, alt_flags 为备选模板列表)
    """
    def __init__(self, name: str, flag: Template, alt_flags: Optional[List[Template]] = None):
        self.name = name
        self.flag = flag
        self.alt_flags: List[Template] = alt_flags or []
        self.links: Dict["Page", Template] = {}

    def all_flags(self) -> List[Template]:
        return [self.flag] + self.alt_flags

    def link(self, target: "Page", trigger: Template):
        """建立由当前页面通往 target 页面的单向边"""
        self.links[target] = trigger

    def __repr__(self):
        return f"<Page {self.name}>"


# 1. 实例化各个核心页面节点
# 舰桥在第二部 UI 中已经不再稳定显示旧版 MAIN_FLAG。
# 登录就绪检测一直允许通过新版【出击】入口判断舰桥，但页面导航器此前只认
# MAIN_FLAG，造成“登录判定成功、后续导航却把同一画面判为未知页面”的断层。
# 将舰桥上五个常驻入口全部纳入备选旗标，任一命中即可建立后续页面导航起点。
PAGE_MAIN = Page(
    "main",
    TPL_MAIN_FLAG,
    [
        TPL_MAIN_GOTO_BATTLE,
        TPL_MAIN_GOTO_DORM,
        TPL_MAIN_GOTO_ARMADA,
        TPL_MAIN_GOTO_MISSIONS,
        TPL_MAIN_GOTO_MAIL,
    ],
)
PAGE_BATTLE = Page("battle", TPL_BATTLE_FLAG, [TPL_BATTLE_FLAG_ALT, TPL_BATTLE_GOTO_LITE, TPL_RECOMMEND_SELECTED, TPL_RECOMMEND_TAB])
PAGE_PART2 = Page("second_part", TPL_PART2_FLAG)
PAGE_LITE = Page("lite", TPL_LITE_FLAG, [TPL_LITE_FLAG_OLD])
PAGE_DORM = Page("dorm", TPL_DORM_FLAG, [TPL_DORM_FLAG_OLD])
PAGE_ERRAND = Page("errand", TPL_ERRAND_MAP, [TPL_ERRANDS_FLAG, TPL_ERRANDS_FLAG_OLD])
PAGE_EXPEDITION = Page("expedition", TPL_EXPEDITION_PAGE, [TPL_EXPEDITION_FLAG, TPL_EXPEDITION_FLAG_OLD])
PAGE_MATERIAL = Page("material", TPL_MATERIAL_PAGE)
PAGE_ARMADA = Page("armada", TPL_ARMADA_FLAG)
PAGE_COMMISSION = Page("commission", TPL_COMMISSION_FLAG, [TPL_COMMISSION_FLAG_OLD])
PAGE_ARMADA_REWARD = Page("armada_reward", TPL_ARMADA_REWARD_FLAG)
PAGE_MISSION = Page("mission", TPL_MISSION_FLAG, [TPL_MISSION_FLAG_ALT, TPL_MISSION_FLAG_OLD])
PAGE_BP_REWARDS = Page("bp_rewards", TPL_MISSION_TAB_INACTIVE)
PAGE_MAIL = Page("mail", TPL_MAIL_FLAG)
PAGE_ARENA = Page("arena", TPL_ARENA_FLAG)

ALL_PAGES: List[Page] = [
    PAGE_BP_REWARDS,
    PAGE_PART2,
    PAGE_MATERIAL,
    PAGE_MAIN,
    PAGE_MISSION,
    PAGE_DORM,
    PAGE_ERRAND,
    PAGE_EXPEDITION,
    PAGE_ARMADA,
    PAGE_COMMISSION,
    PAGE_ARMADA_REWARD,
    PAGE_ARENA,
    PAGE_LITE,
    PAGE_MAIL,
    PAGE_BATTLE,
]

# 2. 构建页面有向图 (拓扑连接与双向边)
# 主界面 <-> 出击
PAGE_MAIN.link(PAGE_BATTLE, TPL_MAIN_GOTO_BATTLE)
PAGE_PART2.link(PAGE_MAIN, TPL_PART2_BACK)
PAGE_BATTLE.link(PAGE_MAIN, TPL_HOME)
PAGE_BATTLE.link(PAGE_MAIN, TPL_RETURN)

# 出击 <-> 材料减负
PAGE_BATTLE.link(PAGE_LITE, TPL_BATTLE_GOTO_LITE)
PAGE_BATTLE.link(PAGE_MATERIAL, TPL_BATTLE_GOTO_LITE)
PAGE_LITE.link(PAGE_BATTLE, TPL_RETURN)
PAGE_LITE.link(PAGE_MAIN, TPL_HOME)

# 出击 <-> 记忆战场
PAGE_BATTLE.link(PAGE_ARENA, TPL_BATTLE_GOTO_ARENA)
PAGE_ARENA.link(PAGE_BATTLE, TPL_RETURN)
PAGE_ARENA.link(PAGE_MAIN, TPL_HOME)

# 主界面 <-> 家园
PAGE_MAIN.link(PAGE_DORM, TPL_MAIN_GOTO_DORM)
PAGE_DORM.link(PAGE_MAIN, TPL_RETURN)
PAGE_DORM.link(PAGE_MAIN, TPL_HOME)

# 家园 <-> 打工
PAGE_DORM.link(PAGE_ERRAND, TPL_DORM_GOTO_ERRANDS)
PAGE_ERRAND.link(PAGE_DORM, TPL_RETURN)
PAGE_ERRAND.link(PAGE_MAIN, TPL_HOME)

# 家园 <-> 远征
PAGE_DORM.link(PAGE_EXPEDITION, TPL_DORM_GOTO_EXPEDITIONS)
PAGE_EXPEDITION.link(PAGE_DORM, TPL_RETURN)
PAGE_EXPEDITION.link(PAGE_MAIN, TPL_HOME)

# 主界面 <-> 舰团
PAGE_MAIN.link(PAGE_ARMADA, TPL_MAIN_GOTO_ARMADA)
PAGE_ARMADA.link(PAGE_MAIN, TPL_RETURN)
PAGE_ARMADA.link(PAGE_MAIN, TPL_HOME)

# 舰团 <-> 委托回收
PAGE_ARMADA.link(PAGE_COMMISSION, TPL_ARMADA_GOTO_COMMISSION)
PAGE_COMMISSION.link(PAGE_ARMADA, TPL_RETURN)
PAGE_COMMISSION.link(PAGE_MAIN, TPL_HOME)

# 委托回收 <-> 舰团奖池
PAGE_COMMISSION.link(PAGE_ARMADA_REWARD, TPL_COMMISSION_GOTO_REWARD)
PAGE_ARMADA_REWARD.link(PAGE_COMMISSION, TPL_RETURN)
PAGE_ARMADA_REWARD.link(PAGE_MAIN, TPL_HOME)

# 主界面 <-> 作战任务 (每日使命)
PAGE_MAIN.link(PAGE_MISSION, TPL_MAIN_GOTO_MISSIONS)
PAGE_BP_REWARDS.link(PAGE_MISSION, TPL_MISSION_TAB_INACTIVE)
PAGE_BP_REWARDS.link(PAGE_MAIN, TPL_HOME)
PAGE_MISSION.link(PAGE_MAIN, TPL_RETURN)
PAGE_MISSION.link(PAGE_MAIN, TPL_HOME)

# 主界面 <-> 邮件
PAGE_MAIN.link(PAGE_MAIL, TPL_MAIN_GOTO_MAIL)
PAGE_MAIL.link(PAGE_MAIN, TPL_RETURN)
PAGE_MAIL.link(PAGE_MAIN, TPL_HOME)
PAGE_MATERIAL.link(PAGE_MAIN, TPL_HOME)


class PageNavigator:
    """
    Alas 图导航器：负责执行页面探测、广度优先寻路与状态保持
    """
    def __init__(self, vision: UIVision):
        self.vision = vision

    def detect_current_page(self, screen_bgr: np.ndarray) -> Optional[Page]:
        """扫描并返回当前所处的页面 (支持新旧 UI 多旗标)"""
        if isinstance(self.vision, UIVision) and PopupHandler(self.vision).has_close(screen_bgr):
            return None
        # 日历签到层能透出舰桥入口；覆盖层存在时不能宣布已回主界面。
        if (self.vision.exists(screen_bgr, TPL_ABYSS_SETTLE)
                or self.vision.exists(screen_bgr, TPL_ABYSS_DYNAMIC)
                or self.vision.exists(screen_bgr, TPL_MONTHLY_SIGNIN_TAB)
                or self.vision.exists(screen_bgr, TPL_PROMO_DISMISS_HINT)
                or self.vision.exists(screen_bgr, TPL_ERRAND_CONFIRM_TITLE)
                or self.vision.exists(screen_bgr, TPL_EVENT_PROMO_TITLE)
                or self.vision.exists(screen_bgr, TPL_EVENT_FLAG)):
            return None
        if any(self.vision.exists(screen_bgr, flag) for flag in BLOCKING_DIALOGS):
            return None
        if self.vision.exists(screen_bgr, TPL_PART2_FLAG) and self.vision.exists(screen_bgr, TPL_PART2_BACK):
            return PAGE_PART2
        # 精确标签优先于旧通用图标，避免推荐卡片插画误中家园旗标。
        if (self.vision.exists(screen_bgr, TPL_RECOMMEND_SELECTED)
                or self.vision.exists(screen_bgr, TPL_RECOMMEND_TAB)):
            return PAGE_BATTLE
        # 第二部舰桥会显示多个稳定入口。只凭一个图标就判为舰桥，
        # 容易把活动覆盖层或其他页面上的相似图标误认作主界面。
        main_hits = 0
        for f in PAGE_MAIN.all_flags():
            if self.vision.exists(screen_bgr, f):
                main_hits += 1
                if main_hits >= 2:
                    return PAGE_MAIN

        for page in ALL_PAGES:
            if page in (PAGE_MAIN, PAGE_PART2):
                continue
            for f in page.all_flags():
                if self.vision.exists(screen_bgr, f):
                    return page
        return None

    @staticmethod
    def find_shortest_path(start: Page, target: Page) -> Optional[List[Tuple[Page, Template]]]:
        """BFS 寻找两个页面之间的最短路径转移序列"""
        if start == target:
            return []

        queue = deque([(start, [])])
        visited = {start}

        while queue:
            curr, path = queue.popleft()
            if curr == target:
                return path

            for next_page, trigger in curr.links.items():
                if next_page not in visited:
                    visited.add(next_page)
                    queue.append((next_page, path + [(next_page, trigger)]))

        return None

    def ui_goto(
        self,
        target_page: Page,
        window_rect: Tuple[int, int, int, int],
        capture_func: Callable[[], np.ndarray],
        popup_handler: Optional[Callable[[np.ndarray], bool]] = None,
        log_func=None,
        max_retries: int = 15,
    ) -> bool:
        """
        Alas 核心寻路接口：由当前所处任意页面自动导航至目标页面
        :param target_page: 目标 Page
        :param window_rect: 游戏窗口矩形
        :param capture_func: 获取当前帧图像的回调
        :param popup_handler: 弹窗拦截消解回调
        :param log_func: 日志输出
        :param max_retries: 最多重试步骤
        """
        for step in range(max_retries):
            screen = capture_func()
            if screen is None:
                time.sleep(0.5)
                continue

            # 步骤前检查并处理突发弹窗
            if claim_reward(window_rect, screen, self.vision, log_func):
                time.sleep(0.6)
                continue
            if any(self.vision.exists(screen, flag) for flag in BLOCKING_DIALOGS):
                if log_func:
                    log_func('[!] 远征/减负/奖励确认层尚未处理，停止背景导航。', 'warning')
                return False
            if self.vision.exists(screen, TPL_ERRAND_CONFIRM_TITLE):
                if log_func:
                    log_func("[!] 打工确认弹窗尚未处理，停止页面导航，避免点击弹窗背后的控件。", "warning")
                return False
            if (self.vision.exists(screen, TPL_EVENT_PROMO_TITLE)
                    or self.vision.exists(screen, TPL_EVENT_FLAG)):
                if popup_handler and popup_handler(screen):
                    time.sleep(0.8)
                    continue
                if log_func:
                    log_func('[!] 宣传弹窗仍存在，停止背景导航，等待右上角叉号关闭。', 'warning')
                return False
            if popup_handler and popup_handler(screen):
                time.sleep(0.8)
                continue

            curr_page = self.detect_current_page(screen)
            if curr_page == target_page:
                if log_func:
                    log_func(f"[+] 已成功到达页面: 【{target_page.name}】", "success")
                return True

            if curr_page is None:
                # 前往日常功能时未知帧可能是奖励层或标签选中态。
                # 只等待重新识别，不能点主页再重进造成导航循环。
                if target_page in (PAGE_EXPEDITION, PAGE_BATTLE, PAGE_MATERIAL, PAGE_DORM, PAGE_ERRAND):
                    if log_func:
                        log_func(f"[*] 等待画面识别后继续前往 {target_page.name}，不点击背景主菜单。", "info")
                    time.sleep(0.5)
                    continue
                # 处于未知页面或过渡转场中：优先识别式点击返回/主页, 识别不到则等待画面稳定,
                # 严禁几何盲点 (过场/弹窗画面上盲点极易误触功能按钮)
                if log_func:
                    log_func(f"[*] 页面正在过渡或处于未知界面，尝试识别返回/主页按钮 (重试 {step+1}/{max_retries})...", "info")
                clicked_nav = False
                for cand in [TPL_EVENT_ACTIVITY_BACK] + HOME_CANDIDATES + RETURN_CANDIDATES:
                    if self.vision.click_template(window_rect, screen, cand, log_func=log_func):
                        clicked_nav = True
                        break
                if not clicked_nav and log_func:
                    log_func("[*] 未识别到返回/主页按钮 (新旧UI均无)，等待画面稳定后重试...", "info")
                time.sleep(1.0)
                continue

            # 寻路
            path = self.find_shortest_path(curr_page, target_page)
            if not path:
                # 若找不到路径（可能缺少边），先回主界面
                if log_func:
                    log_func(f"[!] 未找到直达路径，先返回主菜单并重试...", "warning")
                for cand in HOME_CANDIDATES:
                    if self.vision.click_template(window_rect, screen, cand, log_func=log_func):
                        break
                time.sleep(1.2)
                continue

            next_page, trigger = path[0]
            if log_func:
                log_func(f"[*] 页面导航: 【{curr_page.name}】 -> 【{next_page.name}】，触发锚点 [{trigger.name}]", "info")

            clicked = self.vision.click_template(window_rect, screen, trigger, log_func=log_func)
            # 返回主菜单的边允许先返回上一层；下轮重新识别并计算路径。
            if not clicked and trigger in HOME_CANDIDATES + RETURN_CANDIDATES:
                candidates = (HOME_CANDIDATES + RETURN_CANDIDATES
                              if trigger in HOME_CANDIDATES else RETURN_CANDIDATES + HOME_CANDIDATES)
                for candidate in candidates:
                    if candidate is not trigger and self.vision.click_template(
                        window_rect, screen, candidate, log_func=log_func
                    ):
                        clicked = True
                        break
            if not clicked:
                # 记录坐标只是模板搜索的预期位置，不能当作可点击的兜底。
                # 出击页活动卡片会随版本轮换，固定坐标可能进入无关活动。
                if log_func:
                    log_func(
                        f"[!] 当前页面未识别到导航锚点 [{trigger.name}]，停止导航，避免误入其他活动。",
                        "warning",
                    )
                return False
            time.sleep(1.2)

        return False

    def ui_ensure(
        self,
        target_page: Page,
        window_rect: Tuple[int, int, int, int],
        capture_func: Callable[[], np.ndarray],
        popup_handler: Optional[Callable[[np.ndarray], bool]] = None,
        log_func=None,
    ) -> bool:
        """确保当前处于目标页面"""
        screen = capture_func()
        if screen is not None and self.detect_current_page(screen) == target_page:
            return True
        return self.ui_goto(target_page, window_rect, capture_func, popup_handler, log_func)
