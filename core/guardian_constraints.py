"""Task-scoped, rule-based Alas constraints; all recovery actions are bounded."""
from dataclasses import dataclass
from types import MethodType
import math
import time


class GuardianViolation(RuntimeError):
    pass


def stage_key(name):
    name = str(name).lower()
    if name.startswith('campaign_'):
        name = name[len('campaign_'):]
    return name.replace('_', '-')


@dataclass(frozen=True)
class CampaignIntent:
    manage_fleets: bool = True
    target_fleet: int = None
    force_single_fleet: bool = False
    no_submarine: bool = False
    auto_advice_empty_fleet: bool = True
    priority_mobs_for_3_stars: bool = True


@dataclass(frozen=True)
class StageObservation:
    stage: str
    mode: str
    stars: bool
    progress: float
    folder: str = None

    @property
    def complete(self):
        return self.stars and math.isfinite(self.progress) and self.progress > 0.95


class CognitiveGuardian:
    MAX_FRAMES = 20
    MAX_CLICKS = 3
    FRAME_DELAY = 0.25

    def __init__(self, runner, intent):
        self.runner, self.intent = runner, intent
        self.expected = self.observation = None
        self.expected_folder = None

    @classmethod
    def apply_to_campaign(cls, runner, **options):
        intent = CampaignIntent(**options)
        if intent.target_fleet is not None and intent.target_fleet not in range(1, 7):
            raise ValueError('target_fleet must be between 1 and 6')
        existing = getattr(runner, '_cognitive_guardian', None)
        if existing is not None:
            if existing.intent != intent:
                raise GuardianViolation('同一执行器不能挂载冲突的任务约束')
            return existing
        guard = cls(runner, intent)
        original_load = runner.load_campaign

        def load_campaign(_runner, *args, **kwargs):
            name = args[0] if args else kwargs.get('name')
            folder = args[1] if len(args) > 1 else kwargs.get('folder', 'campaign_main')
            # Native Alas caches by name only: multiple archives reuse a1/d1.
            if (getattr(_runner, 'name', None) == name
                    and getattr(_runner, 'folder', folder) != folder):
                _runner.name = None
            result = original_load(*args, **kwargs)
            guard._attach(_runner.campaign)
            return result

        runner.load_campaign = MethodType(load_campaign, runner)
        runner._cognitive_guardian = guard
        campaign = vars(runner).get('campaign')
        if campaign is not None:
            guard._attach(campaign)
        return guard

    def begin_stage(self, stage, mode, folder=None):
        self.expected = (stage_key(stage), mode)
        self.expected_folder = folder
        self.observation = None

    def stage_complete(self, stage, mode):
        observed = self.observation
        return bool(observed and (observed.stage, observed.mode) == (stage_key(stage), mode)
                    and (self.expected_folder is None or observed.folder == self.expected_folder)
                    and observed.complete)

    def _attach(self, campaign):
        existing = getattr(campaign, '_cognitive_guardian', None)
        if existing is self:
            return
        if existing is not None:
            raise GuardianViolation('关卡实例已由其他任务守卫管理')
        original_info = campaign.map_get_info
        original_appear = campaign.appear
        original_preparation = campaign.handle_map_preparation

        def appear(_campaign, button, offset=0, interval=0, similarity=0.85, threshold=10):
            result = original_appear(button, offset=offset, interval=interval,
                                     similarity=similarity, threshold=threshold)
            if result:
                return result
            from module.map.assets import MAP_PREPARATION_HARD
            # Keep the actual template and native animation/progress checks.
            if button is MAP_PREPARATION_HARD and _campaign.config.Campaign_Mode == 'hard':
                return original_appear(button, offset=(40, 40), interval=interval,
                                       similarity=similarity, threshold=threshold)
            return result

        def map_get_info(_campaign):
            result = original_info()
            current = (stage_key(_campaign.config.Campaign_Name), _campaign.config.Campaign_Mode)
            if self.expected is None or current != self.expected:
                raise GuardianViolation(f'当前关卡 {current} 与任务目标 {self.expected} 不一致')
            folder = getattr(_campaign.config, 'Campaign_Event', None)
            if self.expected_folder is not None and folder != self.expected_folder:
                raise GuardianViolation(f'当前关卡目录 {folder} 与任务目标 {self.expected_folder} 不一致')
            progress = float(_campaign.map_clear_percentage)
            if not math.isfinite(progress) or not 0 <= progress <= 1.05:
                raise GuardianViolation('无法确认当前关卡通关进度')
            self.observation = StageObservation(*current, bool(_campaign.map_is_3_stars), progress, folder)
            # Native map_get_info recalculates this flag, so enforce afterwards.
            if self.intent.priority_mobs_for_3_stars:
                _campaign.config.MAP_CLEAR_ALL_THIS_TIME = not self.observation.stars
            if self.intent.force_single_fleet:
                _campaign.config.FLEET_2 = 0
            if self.intent.no_submarine:
                _campaign.config.SUBMARINE = 0
            return result

        def preparation(_campaign):
            result = original_preparation()
            if result:
                _campaign.map_fleet_checked = False
            return result

        def fleet_preparation(_campaign):
            _campaign.map_fleet_checked = False
            self._prepare_fleets(_campaign)
            _campaign.map_fleet_checked = True
            return True

        campaign.appear = MethodType(appear, campaign)
        campaign.map_get_info = MethodType(map_get_info, campaign)
        campaign.handle_map_preparation = MethodType(preparation, campaign)
        if self.intent.manage_fleets:
            campaign.fleet_preparation = MethodType(fleet_preparation, campaign)
        campaign._cognitive_guardian = self

    def _poll(self, main, label, ready, action):
        clicks = 0
        for frame in range(self.MAX_FRAMES):
            main.device.screenshot()
            if ready():
                return
            if frame % 6 == 0 and clicks < self.MAX_CLICKS:
                action()
                clicks += 1
            time.sleep(self.FRAME_DELAY)
        raise GuardianViolation(f'{label}未得到确认，已停止（最多 {self.MAX_CLICKS} 次操作）')

    def _clear(self, main, operator, label):
        if not operator.allow():
            if operator.in_use():
                raise GuardianViolation(f'{label}存在但无法撤下')
            return

        def action():
            if not main.handle_popup_confirm(str(operator._clear)):
                main.device.click(operator._clear)

        self._poll(main, label, lambda: operator.allow() and not operator.in_use(), action)

    def _select(self, main, operator, target):
        self._poll(main, '打开舰队选择', operator.bar_opened,
                   lambda: main.device.click(operator._choose))
        if operator.selected() != [target]:
            main.device.click(operator.get_button(target))
            self._poll(main, '关闭舰队选择', lambda: not operator.bar_opened(),
                       lambda: main.device.click(operator._choose))
            self._poll(main, '重新核验舰队选择', operator.bar_opened,
                       lambda: main.device.click(operator._choose))
        if operator.selected() != [target]:
            raise GuardianViolation(f'未能确认只选择第 {target} 舰队')
        self._poll(main, '收起舰队选择', lambda: not operator.bar_opened(),
                   lambda: main.device.click(operator._choose))
        if not operator.in_use():
            raise GuardianViolation('目标舰队为空，禁止出击')

    def _advice(self, main, operator, label):
        if not operator.is_hard():
            raise GuardianViolation(f'无法确认{label}的困难编队条件')
        self._poll(main, f'{label}推荐编队',
                   lambda: operator.in_use() and operator.is_hard_satisfied() is True,
                   lambda: main.device.click(operator._advice))

    def _prepare_fleets(self, main):
        from module.map.map_fleet_preparation import FleetOperator
        from module.map import assets as a
        from module.handler import assets as h
        if self.observation is None or self.expected != (self.observation.stage, self.observation.mode):
            raise GuardianViolation('缺少当前关卡观察，禁止直接出击')
        if main.appear(a.FLEET_1_CLEAR, offset=FleetOperator.OFFSET):
            for name in ('AUTO_SEARCH_SET_MOB', 'AUTO_SEARCH_SET_BOSS', 'AUTO_SEARCH_SET_ALL', 'AUTO_SEARCH_SET_STANDBY'):
                getattr(h, name).load_offset(a.FLEET_1_CLEAR)
        if main.appear(a.SUBMARINE_CLEAR, offset=FleetOperator.OFFSET):
            for name in ('AUTO_SEARCH_SET_SUB_AUTO', 'AUTO_SEARCH_SET_SUB_STANDBY'):
                getattr(h, name).load_offset(a.SUBMARINE_CLEAR)
        shifted = a.FLEET_1_CLEAR.button[1] - a.FLEET_1_CLEAR.area[1] < -10

        def operator(prefix):
            in_use = a.FLEET_2_IN_USE_W15 if prefix == 'FLEET_2' and shifted else getattr(a, prefix + '_IN_USE')
            return FleetOperator(choose=getattr(a, prefix + '_CHOOSE'), advice=getattr(a, prefix + '_ADVICE'),
                                 bar=getattr(a, prefix + '_BAR'), clear=getattr(a, prefix + '_CLEAR'),
                                 in_use=in_use, hard_satisfied=getattr(a, prefix + '_HARD_SATIESFIED'), main=main)

        first, second, sub = [operator(p) for p in ('FLEET_1', 'FLEET_2', 'SUBMARINE')]
        main.map_is_hard_mode = self.expected[1] == 'hard'
        # W15/W16 subclasses normally inspect an additional support slot in
        # fleet_preparation. Our replacement must retain that inspection.
        if hasattr(main, 'use_support_fleet'):
            empty_support = main.appear(a.FLEET_SUPPORT_EMPTY, offset=(5, 5))
            main.use_support_fleet = not empty_support
            submarine_support = self.expected[0].startswith('16-') and self.intent.no_submarine
            if not empty_support and (self.intent.force_single_fleet or submarine_support):
                raise GuardianViolation('支援舰队未确认清空，与仅指定舰队/禁用潜艇要求冲突，请先手动撤下支援')
        if self.intent.no_submarine:
            self._clear(main, sub, '潜艇')
        if self.intent.force_single_fleet:
            self._clear(main, second, '第二舰队')
        if self.intent.target_fleet is not None:
            self._select(main, first, self.intent.target_fleet)
        if self.intent.auto_advice_empty_fleet and main.map_is_hard_mode:
            self._advice(main, first, '第一舰队')
            if not self.intent.force_single_fleet and second.is_hard():
                self._advice(main, second, '第二舰队')
        main.device.screenshot()
        if not first.in_use():
            raise GuardianViolation('第一舰队为空，禁止出击')
        if self.intent.force_single_fleet and second.in_use():
            raise GuardianViolation('第二舰队仍在编队中，禁止出击')
        if self.intent.no_submarine and sub.in_use():
            raise GuardianViolation('潜艇仍在编队中，禁止出击')
        if main.map_is_hard_mode:
            if first.is_hard_satisfied() is not True:
                raise GuardianViolation('第一舰队困难条件未得到确认')
            if second.is_hard() and second.is_hard_satisfied() is not True:
                raise GuardianViolation('第二舰队困难条件未得到确认')
