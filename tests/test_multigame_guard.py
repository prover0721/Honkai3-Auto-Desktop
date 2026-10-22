import ast
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
from core.runtime_guard import RuntimeViolation
from games.honkai3.core.task_guard import HonkaiTaskGuard
from games.honkai3.core.ui_vision import UIVision, Template
from games.honkai3.core.popup import PopupHandler
from games.honkai3.core.page import PAGE_MAIN, PAGE_DORM, PageNavigator


class LoginStateScopeTests(unittest.TestCase):
    """登录状态机只允许引用本函数内已绑定的名字。

    2026-10-21 的故障：状态 0 判定引用了 _get_context() 才创建的
    popup_handler/screen，游戏停在登录卡片时会抛 UnboundLocalError，
    表现为「运行后立刻异常终止（部分失败）」。
    """

    def login_function(self):
        base = Path(__file__).resolve().parents[1]
        path = base / 'games' / 'honkai3' / 'runner.py'
        if not path.is_file():
            path = base / 'plugin' / 'runner.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'run_auto_login':
                return node
        self.fail('runner.py 中未找到 run_auto_login')

    def test_state_zero_only_uses_locally_bound_names(self):
        fn = self.login_function()
        assigned = {n.id for n in ast.walk(fn)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        assigned |= {a.arg for a in fn.args.args}
        # 状态 0 判定所在的那一行
        target = [n for n in ast.walk(fn)
                  if isinstance(n, ast.If) and isinstance(n.test, ast.BoolOp)
                  and 'has_popup' in ast.dump(n.test)]
        self.assertTrue(target, '未找到状态 0 判定分支')
        for node in ast.walk(target[0].test):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                self.assertIn(
                    node.id, assigned,
                    f'状态 0 判定引用了未在 run_auto_login 内绑定的名字: {node.id}'
                )


class PopupVisionTests(unittest.TestCase):
    def image_and_vision(self):
        template = np.random.default_rng(17).integers(40, 230, (24, 24, 3), dtype=np.uint8)
        vision = UIVision(template_dirs=[])
        vision.get_template_img = Mock(return_value=template)
        vision.click_point = Mock(return_value=True)
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        screen[490:514, 60:84] = template
        return vision, screen, template

    def test_close_control_can_move_outside_old_upper_right_region(self):
        vision, screen, _ = self.image_and_vision()
        self.assertTrue(PopupHandler(vision)._click_close_x((0, 0, 1280, 720), screen))
        x, y = vision.click_point.call_args[0][1:3]
        self.assertLess(x, 100)
        self.assertGreater(y, 400)

    def test_ambiguous_close_controls_are_not_clicked(self):
        vision, screen, template = self.image_and_vision()
        screen[100:124, 900:924] = template
        self.assertFalse(PopupHandler(vision)._click_close_x((0, 0, 1280, 720), screen))
        vision.click_point.assert_not_called()

    def test_one_template_ambiguity_is_not_overruled_by_another_unique_match(self):
        vision, screen, _ = self.image_and_vision()
        def candidates(frame, template):
            if template.name == 'NOTICE_CLOSE.png':
                return [(72,502,.99), (900,110,.98)]
            if template.name == 'EVENT_PROMO_CLOSE.png':
                return [(72,502,.99)]
            return []
        vision.match_candidates = Mock(side_effect=candidates)
        handler = PopupHandler(vision)
        with patch.object(handler, 'known_popup', return_value=False):
            self.assertTrue(handler.recognizes(screen))
            self.assertIsNone(handler.find_close(screen))
            self.assertFalse(handler.handle((0,0,1280,720), screen))
        vision.click_point.assert_not_called()
        self.assertIsNone(PageNavigator(vision).detect_current_page(screen))

    def test_changed_activity_title_still_uses_verified_close_glyph(self):
        vision, screen, _ = self.image_and_vision()
        handler = PopupHandler(vision)
        with patch.object(handler, 'known_popup', return_value=False):
            self.assertTrue(handler.handle((0,0,1280,720), screen))
        vision.click_point.assert_called_once()

    def test_unknown_page_does_not_trigger_generic_close_search(self):
        vision = Mock()
        vision.exists.return_value = False
        vision.click_template.return_value = False
        self.assertFalse(PopupHandler(vision).handle((0, 0, 1280, 720), np.zeros((720, 1280, 3))))
        vision.click_point.assert_not_called()

    def test_failed_new_capture_never_reuses_old_frame(self):
        self.assertIsNone(PopupHandler(Mock())._grab(lambda: None, np.zeros((3, 3, 3))))

    def test_abyss_overlay_blocks_bridge_even_if_background_icons_match(self):
        vision = Mock()
        vision.exists.side_effect = lambda frame, template: template.name == 'V2_ABYSS_SETTLE.png'
        self.assertIsNone(PageNavigator(vision).detect_current_page(np.zeros((720, 1280, 3))))


class TaskAdapterTests(unittest.TestCase):
    def setUp(self):
        self.evidence = patch.object(HonkaiTaskGuard, 'evidence').start()
        patch('games.honkai3.core.task_guard.time.sleep').start()
        self.addCleanup(patch.stopall)

    def make_guard(self, frames=None):
        self.vision, self.popup, self.nav = Mock(), Mock(), Mock()
        self.vision.exists.return_value = False
        self.popup.recognizes.return_value = False
        self.popup.interrupts.return_value = False
        self.nav.detect_current_page.return_value = PAGE_MAIN
        capture = Mock(side_effect=frames) if frames is not None else Mock(return_value=np.zeros((720, 1280, 3)))
        return HonkaiTaskGuard('missions', (0, 0, 1280, 720), capture, self.nav,
                               self.vision, self.popup, Mock(), lambda: False)

    def test_mid_task_popup_is_processed_before_frame_return(self):
        guard = self.make_guard([np.zeros((720,1280,3)), np.ones((720,1280,3))*100])
        self.popup.recognizes.side_effect = [True, False]
        self.popup.handle.return_value = True
        result = guard.capture()
        self.assertEqual(result.mean(), 100)
        self.popup.handle.assert_called_once()

    def test_task_owned_reward_is_not_consumed_by_popup_cleanup(self):
        from games.honkai3.core.daily_ui import TPL_REWARD_DIALOG
        guard = self.make_guard()
        self.vision.exists.side_effect = lambda frame, marker: marker is TPL_REWARD_DIALOG
        self.popup.recognizes.return_value = True
        self.assertIsNotNone(guard.capture())
        self.popup.handle.assert_not_called()

    def test_external_interrupt_can_take_priority_over_background_reward(self):
        from games.honkai3.core.daily_ui import TPL_REWARD_DIALOG
        guard = self.make_guard([np.zeros((720,1280,3)), np.ones((720,1280,3))*100])
        self.vision.exists.side_effect = lambda frame, marker: frame.mean() == 0 and marker is TPL_REWARD_DIALOG
        self.popup.interrupts.return_value = True
        self.popup.recognizes.side_effect = [True, False]
        self.popup.handle.return_value = True
        self.assertEqual(guard.capture().mean(), 100)
        self.popup.handle.assert_called_once()

    def test_unresolved_popup_stops_and_retains_evidence(self):
        guard = self.make_guard()
        self.popup.recognizes.return_value = True
        self.popup.handle.return_value = False
        with self.assertRaises(RuntimeViolation): guard.capture()
        self.evidence.assert_called_once()
        guard.original_click.assert_not_called()

    def test_popup_loop_is_bounded(self):
        guard = self.make_guard()
        self.popup.recognizes.return_value = True
        self.popup.handle.return_value = True
        with self.assertRaises(RuntimeViolation): guard.capture()
        self.assertEqual(self.popup.handle.call_count, 8)

    def test_unknown_starting_page_stops_without_navigation(self):
        guard = self.make_guard()
        self.nav.detect_current_page.return_value = None
        with self.assertRaises(RuntimeViolation): guard.prepare()
        self.nav.ui_goto.assert_not_called()

    def test_terminal_page_needs_two_observations(self):
        guard = self.make_guard()
        self.assertTrue(guard.finish(True, PAGE_MAIN))
        self.assertEqual(self.nav.detect_current_page.call_count, 2)

    def test_wrong_terminal_page_is_not_success(self):
        guard = self.make_guard()
        self.nav.detect_current_page.return_value = PAGE_DORM
        self.nav.ui_goto.return_value = False
        with self.assertRaises(RuntimeViolation): guard.finish(True, PAGE_MAIN)

    def test_input_wrapper_is_restored_after_task(self):
        guard = self.make_guard()
        original = guard.original_click
        guard.close()
        self.assertIs(self.vision.click_point, original)
