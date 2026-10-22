"""Offline safety checks for Honkai3 navigation and input decisions."""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

from games.honkai3 import runner
from games.honkai3.core.page import PAGE_MAIN, PageNavigator
from games.honkai3.core.popup import PopupHandler
from games.honkai3.core.ui_vision import Template, UIVision
from games.honkai3.tasks.task_armada import run_armada_task
from games.honkai3.tasks.task_dorm import run_dorm_task, finish_errand_dispatch
from games.honkai3.tasks.task_expedition import run_expedition_task
from games.honkai3.tasks.task_mission import run_mission_task


class Honkai3SafetyTests(unittest.TestCase):
    def test_unreached_chest_icon_is_not_eligible(self):
        from games.honkai3.core.daily_ui import stage_is_reached
        self.assertFalse(stage_is_reached(np.zeros((720,1280,3),dtype=np.uint8), (100,100,.99)))

    @patch('games.honkai3.core.daily_ui.time.sleep', return_value=None)
    def test_stuck_dispatch_is_clicked_only_once_and_fails(self, _sleep):
        from games.honkai3.core.daily_ui import confirm_and_wait, TPL_EXPEDITION_DIALOG, TPL_EXPEDITION_SEND
        from games.honkai3.core.page import PAGE_EXPEDITION
        vision = MagicMock()
        vision.exists.return_value = True
        vision.click_template.return_value = True
        self.assertFalse(confirm_and_wait((0,0,1280,720),lambda:np.zeros((720,1280,3)),MagicMock(),vision,
                         TPL_EXPEDITION_DIALOG,TPL_EXPEDITION_SEND,PAGE_EXPEDITION))
        self.assertEqual(vision.click_template.call_count,1)

    @patch('games.honkai3.core.daily_ui.time.sleep', return_value=None)
    def test_dispatch_waits_for_correct_page(self, _sleep):
        from games.honkai3.core.daily_ui import confirm_and_wait, TPL_EXPEDITION_DIALOG, TPL_EXPEDITION_SEND
        from games.honkai3.core.page import PAGE_EXPEDITION
        screens = iter([1,2])
        vision = MagicMock()
        vision.exists.side_effect=lambda s,t:s==1 and t is TPL_EXPEDITION_DIALOG
        vision.click_template.return_value=True
        nav=MagicMock()
        nav.detect_current_page.return_value=PAGE_EXPEDITION
        self.assertTrue(confirm_and_wait((0,0,1280,720),lambda:next(screens),nav,vision,
                        TPL_EXPEDITION_DIALOG,TPL_EXPEDITION_SEND,PAGE_EXPEDITION))
        self.assertEqual(vision.click_template.call_count,1)

    @patch("games.honkai3.core.popup.time.sleep", return_value=None)
    def test_monthly_signin_claim_does_not_click_after_page_changes(self, _sleep):
        signin = np.zeros((720, 1280, 3), dtype=np.uint8)
        main = np.ones_like(signin)
        vision = MagicMock()
        vision.exists.side_effect = lambda screen, template: screen is signin and template.name in {
            "V3_MONTHLY_SIGNIN_TAB.png", "V3_MONTHLY_SIGNIN_CLAIM.png"
        }
        vision.click_template.return_value = True
        handler = PopupHandler(vision)
        self.assertTrue(handler.handle((0, 0, 1280, 720), signin, capture_func=lambda: signin))
        self.assertFalse(handler.handle((0, 0, 1280, 720), signin, capture_func=lambda: main))
        self.assertEqual(vision.click_template.call_count, 1)
        self.assertEqual(vision.click_template.call_args.args[2].name, "V3_MONTHLY_SIGNIN_CLAIM.png")
        vision.click_pos.assert_not_called()

    @patch("games.honkai3.core.popup.time.sleep", return_value=None)
    def test_monthly_signin_requires_recognized_close_x(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision = MagicMock()
        vision.exists.side_effect = lambda _screen, template: template.name == "V3_MONTHLY_SIGNIN_TAB.png"
        vision.match.return_value = None
        handler = PopupHandler(vision)
        self.assertFalse(handler.handle((0, 0, 1280, 720), screen, capture_func=lambda: None))
        self.assertFalse(handler.handle((0, 0, 1280, 720), screen, capture_func=lambda: screen))
        vision.click_template.assert_not_called()

    def test_close_x_clicks_exact_validated_match_without_second_search(self):
        vision = MagicMock()
        vision.match.return_value = (1000, 100, 0.96)
        vision.click_point.return_value = True
        handler = PopupHandler(vision)
        self.assertTrue(handler._click_close_x((0, 0, 1280, 720), np.zeros((720, 1280, 3))))
        vision.click_point.assert_called_once_with((0, 0, 1280, 720), 1000, 100, jitter=0)
        vision.click_template.assert_not_called()

    def test_close_x_rejects_content_area_match(self):
        vision = MagicMock()
        vision.match.return_value = (600, 450, 0.99)
        self.assertFalse(PopupHandler(vision)._click_close_x((0, 0, 1280, 720), np.zeros((720, 1280, 3))))
        vision.click_point.assert_not_called()
        vision.click_template.assert_not_called()

    def test_event_overlay_blocks_reward_clicks_when_close_missing(self):
        vision = MagicMock()
        vision.exists.side_effect = lambda _s, t: t.name in {'POPUP_EVENT_FLAG.png', 'MONTHLY_CARD_CLAIM.png'}
        vision.match.return_value = None
        self.assertFalse(PopupHandler(vision).handle((0, 0, 1280, 720), np.zeros((720, 1280, 3))))
        vision.click_template.assert_not_called()
        vision.click_point.assert_not_called()

    def test_monthly_signin_overlay_blocks_bridge_anchors(self):
        vision = MagicMock()
        vision.exists.side_effect = lambda _screen, template: template.name in {
            "V3_MONTHLY_SIGNIN_TAB.png", "MAIN_FLAG.png", "V2_MAIN_GOTO_BATTLE.png"
        }
        self.assertIsNone(PageNavigator(vision).detect_current_page(np.zeros((720, 1280, 3), dtype=np.uint8)))

    def test_main_page_requires_two_independent_anchors(self):
        vision = MagicMock()
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision.exists.side_effect = lambda _screen, template: template.name == "MAIN_FLAG.png"
        self.assertIsNone(PageNavigator(vision).detect_current_page(screen))

        vision.exists.side_effect = lambda _screen, template: template.name in {
            "MAIN_FLAG.png", "V2_MAIN_GOTO_BATTLE.png"
        }
        self.assertIs(PageNavigator(vision).detect_current_page(screen), PAGE_MAIN)

    @patch("games.honkai3.core.popup.time.sleep", return_value=None)
    def test_event_promo_requires_title_and_close_and_clicks_close_x(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision = MagicMock()
        vision.exists.side_effect = lambda _screen, template: template.name in {
            "EVENT_PROMO_TITLE.png", "EVENT_PROMO_CLOSE.png"
        }
        vision.click_template.return_value = False

        handled = PopupHandler(vision).handle((0, 0, 1280, 720), screen)

        self.assertFalse(handled)
        vision.click_pos.assert_not_called()
        self.assertEqual(vision.click_template.call_args.args[2].name, "EVENT_PROMO_CLOSE.png")

    @patch("games.honkai3.core.page.time.sleep", return_value=None)
    def test_unknown_event_page_uses_recognized_back_control_to_reach_main(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision = MagicMock()
        vision.exists.return_value = False
        vision.click_template.side_effect = lambda _rect, _screen, template, **_kwargs: (
            template.name == "EVENT_ACTIVITY_BACK.png"
        )
        navigator = PageNavigator(vision)
        navigator.detect_current_page = MagicMock(side_effect=[None, PAGE_MAIN])

        result = navigator.ui_goto(PAGE_MAIN, (0, 0, 1280, 720), lambda: screen)

        self.assertTrue(result)
        self.assertTrue(any(
            call.args[2].name == "EVENT_ACTIVITY_BACK.png"
            for call in vision.click_template.call_args_list
        ))

    @patch("games.honkai3.runner.time.sleep", return_value=None)
    def test_bridge_gate_closes_promo_returns_from_event_and_only_then_opens(self, _sleep):
        screens = {
            "promo": np.full((720, 1280, 3), 1, dtype=np.uint8),
            "event": np.full((720, 1280, 3), 2, dtype=np.uint8),
            "main": np.full((720, 1280, 3), 3, dtype=np.uint8),
        }
        state = {"name": "promo"}
        vision = MagicMock()
        vision.exists.side_effect = lambda screen, template: (
            state["name"] == "promo" and template.name in {
                "EVENT_PROMO_TITLE.png", "EVENT_PROMO_CLOSE.png"
            }
        )

        def click_template(_rect, screen, template, **_kwargs):
            if template.name == "EVENT_ACTIVITY_BACK.png" and state["name"] == "event":
                state["name"] = "main"
                return True
            return False

        vision.click_template.side_effect = click_template
        navigator = MagicMock()
        navigator.detect_current_page.side_effect = lambda _screen: (
            PAGE_MAIN if state["name"] == "main" else None
        )
        popup_handler = MagicMock()
        popup_handler.handle_all_clear.side_effect = lambda *_args, **_kwargs: state.update(name="event")

        def capture():
            return screens[state["name"]]

        result = runner.wait_until_bridge_ready(
            (0, 0, 1280, 720), capture, navigator, vision, popup_handler, max_wait=3
        )

        self.assertTrue(result)
        self.assertEqual(state["name"], "main")
        popup_handler.handle_all_clear.assert_called_once()
        self.assertTrue(any("EVENT_ACTIVITY_BACK.png" == call.args[2].name
                            for call in vision.click_template.call_args_list))

    @patch("games.honkai3.runner.time.sleep", return_value=None)
    @patch("games.honkai3.runner.time.time", side_effect=[0.0, 5.0, 5.0, 10.0])
    def test_unknown_bridge_state_never_uses_coordinate_fallback_clicks(self, _time, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision = MagicMock()
        vision.exists.return_value = False
        vision.click_template.return_value = False
        navigator = MagicMock()
        navigator.detect_current_page.return_value = None
        popup_handler = MagicMock()

        result = runner.wait_until_bridge_ready(
            (0, 0, 1280, 720), lambda: screen, navigator, vision, popup_handler, max_wait=10
        )

        self.assertFalse(result)
        vision.click_point.assert_not_called()

    def test_fullscreen_roi_fallback_uses_screen_origin(self):
        rng = np.random.default_rng(42)
        screen = rng.integers(0, 40, (720, 1280, 3), dtype=np.uint8)
        sample = rng.integers(0, 255, (20, 20, 3), dtype=np.uint8)
        screen[100:120, 100:120] = sample
        vision = UIVision([])
        vision.get_template_img = MagicMock(return_value=sample)

        match = vision.match(screen, Template("sample.png", record_pos=(2.0, 2.0)))

        self.assertIsNotNone(match)
        self.assertEqual(match[:2], (110, 110))

    def test_daily_context_rejects_non_16_by_9_capture(self):
        messages = []
        with patch.object(runner.qr_scanner, "find_bh3_window", return_value=(0, 0, 1024, 768)), \
             patch.object(runner.qr_scanner, "capture_screen_or_window", return_value=Image.new("RGB", (1024, 768))), \
             patch("games.honkai3.core.ui_vision.activate_game_window", return_value=True):
            result = runner._get_context(lambda message, level: messages.append(message))

        self.assertEqual(result, (None, None, None, None, None))
        self.assertTrue(any("16:9" in message for message in messages))

    def test_daily_context_accepts_user_screenshot_ratio(self):
        with patch.object(runner.qr_scanner, "find_bh3_window", return_value=(0, 0, 2559, 1438)), \
             patch.object(runner.qr_scanner, "capture_screen_or_window", return_value=Image.new("RGB", (2559, 1438))), \
             patch("games.honkai3.core.ui_vision.activate_game_window", return_value=True):
            result = runner._get_context(lambda *_: None)

        self.assertEqual(len(result), 5)
        self.assertIsNotNone(result[0])

    @patch("games.honkai3.tasks.task_expedition.time.sleep", return_value=None)
    def test_expedition_missing_button_never_clicks_coordinates(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        navigator = MagicMock()
        navigator.ui_goto.return_value = True
        from games.honkai3.core.page import PAGE_EXPEDITION, PAGE_MAIN
        navigator.detect_current_page.return_value = PAGE_EXPEDITION
        vision = MagicMock()
        vision.exists.return_value = False

        self.assertTrue(run_expedition_task((0, 0, 1280, 720), lambda: screen, navigator, vision))
        vision.click_point.assert_not_called()
        vision.click_pos.assert_not_called()
        navigator.ui_goto.assert_called_once()

    @patch("games.honkai3.tasks.task_expedition.time.sleep", return_value=None)
    def test_expedition_deviated_page_stops_safely(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        navigator = MagicMock()
        navigator.ui_goto.return_value = False
        navigator.detect_current_page.return_value = None
        vision = MagicMock()
        vision.exists.return_value = False

        self.assertFalse(run_expedition_task((0, 0, 1280, 720), lambda: screen, navigator, vision))
        vision.click_point.assert_not_called()
        vision.click_pos.assert_not_called()

    def test_selected_sortie_material_card_identifies_battle_page(self):
        from games.honkai3.core.page import PageNavigator, PAGE_BATTLE, TPL_BATTLE_GOTO_LITE
        vision = MagicMock()
        vision.exists.side_effect = lambda _s, t: t is TPL_BATTLE_GOTO_LITE
        self.assertIs(PageNavigator(vision).detect_current_page(np.zeros((720, 1280, 3))), PAGE_BATTLE)

    def test_promo_without_x_never_enters_other_claim_branch(self):
        from games.honkai3.core.popup import PopupHandler, TPL_EVENT_PROMO_TITLE, TPL_POPUP_CLAIM
        vision = MagicMock()
        vision.exists.side_effect = lambda _s, t: t in (TPL_EVENT_PROMO_TITLE, TPL_POPUP_CLAIM)
        self.assertFalse(PopupHandler(vision).handle((0, 0, 1280, 720), np.zeros((720, 1280, 3))))
        vision.click_template.assert_not_called()
        vision.click_pos.assert_not_called()

    def test_claim_reward_dialog_blocks_material_background(self):
        from games.honkai3.core.daily_ui import TPL_REWARD_CLAIM_DIALOG
        from games.honkai3.core.page import PageNavigator, TPL_MATERIAL_PAGE
        vision = MagicMock()
        vision.exists.side_effect = lambda _s, t: t in (TPL_REWARD_CLAIM_DIALOG, TPL_MATERIAL_PAGE)
        self.assertIsNone(PageNavigator(vision).detect_current_page(np.zeros((720, 1280, 3))))

    @patch('games.honkai3.core.popup.time.sleep', return_value=None)
    def test_abyss_popup_is_clicked_once_only_while_present(self, _sleep):
        from games.honkai3.core.popup import PopupHandler, TPL_ABYSS_SETTLE
        vision = MagicMock()
        vision.exists.side_effect = lambda _s, t: t is TPL_ABYSS_SETTLE
        vision.click_template.return_value = True
        handler = PopupHandler(vision)
        screen = np.zeros((720, 1280, 3))
        self.assertTrue(handler.handle((0, 0, 1280, 720), screen))
        self.assertFalse(handler.handle((0, 0, 1280, 720), screen))
        vision.click_template.assert_called_once_with((0, 0, 1280, 720), screen, TPL_ABYSS_SETTLE, log_func=None)

    def test_absent_abyss_popup_never_triggers_abyss_click(self):
        from games.honkai3.core.popup import PopupHandler, TPL_ABYSS_SETTLE
        vision = MagicMock()
        vision.exists.return_value = False
        vision.click_template.return_value = False
        self.assertFalse(PopupHandler(vision).handle((0, 0, 1280, 720), np.zeros((720, 1280, 3))))
        self.assertFalse(any(c.args[2] is TPL_ABYSS_SETTLE for c in vision.click_template.call_args_list))
        vision.click_point.assert_not_called()
        vision.click_pos.assert_not_called()

    @patch('games.honkai3.core.page.time.sleep', return_value=None)
    def test_unknown_daily_destination_never_clicks_home(self, _sleep):
        from games.honkai3.core.page import PageNavigator, PAGE_BATTLE
        vision = MagicMock()
        vision.exists.return_value = False
        self.assertFalse(PageNavigator(vision).ui_goto(
            PAGE_BATTLE, (0, 0, 1280, 720), lambda: np.zeros((720, 1280, 3)), max_retries=2))
        vision.click_template.assert_not_called()

    @patch("games.honkai3.tasks.task_expedition.time.sleep", return_value=None)
    def test_expedition_confirms_reward_before_onekey_dispatch_and_home(self, _sleep):
        from games.honkai3.core.daily_ui import (
            TPL_EXPEDITION_DIALOG, TPL_EXPEDITION_SEND,
            TPL_REWARD_DIALOG, TPL_REWARD_CONFIRM,
        )
        from games.honkai3.core.page import PAGE_EXPEDITION, PAGE_MAIN
        from games.honkai3.tasks.task_expedition import TPL_EXPEDITION_FINISH, TPL_EXPEDITION_ONEKEY

        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        state = {"page": "expedition"}
        clicks = []
        navigator = MagicMock()
        navigator.ui_goto.return_value = True
        navigator.detect_current_page.side_effect = lambda _screen: (
            PAGE_EXPEDITION if state["page"] in {"expedition", "reward", "after_reward", "dispatch", "done"}
            else None
        )
        vision = MagicMock()

        def exists(_screen, template):
            name = template.name
            return (
                (name == TPL_EXPEDITION_DIALOG.name and state["page"] == "dispatch")
                or (name == TPL_REWARD_DIALOG.name and state["page"] == "reward")
                or (name == TPL_EXPEDITION_FINISH.name and state["page"] == "expedition")
                or (name == TPL_EXPEDITION_ONEKEY.name and state["page"] == "after_reward")
            )

        def click(_rect, _screen, template, **_kwargs):
            clicks.append(template.name)
            transitions = {
                TPL_EXPEDITION_FINISH.name: "reward",
                TPL_REWARD_CONFIRM.name: "after_reward",
                TPL_EXPEDITION_ONEKEY.name: "dispatch",
                TPL_EXPEDITION_SEND.name: "done",
            }
            state["page"] = transitions.get(template.name, state["page"])
            return True

        vision.exists.side_effect = exists
        vision.click_template.side_effect = click

        result = run_expedition_task((0, 0, 1280, 720), lambda: screen, navigator, vision)

        self.assertTrue(result)
        self.assertEqual(clicks, [
            TPL_EXPEDITION_FINISH.name,
            TPL_REWARD_CONFIRM.name,
            TPL_EXPEDITION_ONEKEY.name,
            TPL_EXPEDITION_SEND.name,
        ])
        self.assertEqual(navigator.ui_goto.call_args_list[-1].args[0], PAGE_MAIN)

    @patch("games.honkai3.tasks.task_expedition.time.sleep", return_value=None)
    def test_expedition_stops_if_reward_confirm_cannot_be_clicked(self, _sleep):
        from games.honkai3.core.daily_ui import TPL_REWARD_CONFIRM, TPL_REWARD_DIALOG
        from games.honkai3.core.page import PAGE_EXPEDITION, PAGE_MAIN
        from games.honkai3.tasks.task_expedition import TPL_EXPEDITION_FINISH, TPL_EXPEDITION_ONEKEY

        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        state = {"page": "expedition"}
        navigator = MagicMock()
        navigator.ui_goto.return_value = True
        navigator.detect_current_page.return_value = PAGE_EXPEDITION
        vision = MagicMock()

        def exists(_screen, template):
            return (
                (template.name == TPL_EXPEDITION_FINISH.name and state["page"] == "expedition")
                or (template.name == TPL_REWARD_DIALOG.name and state["page"] == "reward")
            )

        def click(_rect, _screen, template, **_kwargs):
            if template.name == TPL_EXPEDITION_FINISH.name:
                state["page"] = "reward"
                return True
            if template.name == TPL_REWARD_CONFIRM.name:
                return False
            return True

        vision.exists.side_effect = exists
        vision.click_template.side_effect = click

        self.assertFalse(run_expedition_task((0, 0, 1280, 720), lambda: screen, navigator, vision))
        self.assertFalse(any(call.args[0] is PAGE_MAIN for call in navigator.ui_goto.call_args_list))
        self.assertFalse(any(
            call.args[2].name == TPL_EXPEDITION_ONEKEY.name
            for call in vision.click_template.call_args_list
        ))

    @patch("games.honkai3.tasks.task_sweep.time.sleep", return_value=None)
    def test_sweep_returns_home_without_claiming_missions_early(self, _sleep):
        from games.honkai3.core.daily_ui import TPL_SWEEP_DIALOG, TPL_SWEEP_CONFIRM
        from games.honkai3.core.page import (
            PAGE_MAIN, PAGE_BATTLE, PAGE_MATERIAL, TPL_BATTLE_FLAG_ALT,
            TPL_BATTLE_GOTO_LITE,
        )
        from games.honkai3.tasks.task_sweep import TPL_MATL_LITE, run_sweep_task

        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        state = {"page": PAGE_MAIN}
        navigator = MagicMock()
        actions = []

        def goto(page, *_args, **_kwargs):
            navigator.ui_goto_calls.append(page)
            actions.append(("goto", page))
            state["page"] = page
            return True

        navigator.ui_goto_calls = []
        navigator.ui_goto.side_effect = goto
        navigator.detect_current_page.side_effect = lambda _screen: state["page"]
        vision = MagicMock()

        def exists(_screen, template):
            if template.name == 'V7_RECOMMEND_SELECTED.png':
                return state.get("sortie_tab_active", False)
            if template.name == 'V7_RECOMMEND_TAB.png':
                return state["page"] == PAGE_BATTLE and not state.get("sortie_tab_active", False)
            if template.name == TPL_SWEEP_DIALOG.name:
                return state["page"] == "sweep_dialog"
            if template.name == TPL_BATTLE_GOTO_LITE.name:
                return state.get("sortie_tab_active", False)
            if template.name == TPL_BATTLE_FLAG_ALT.name:
                return state["page"] == PAGE_BATTLE and not state.get("sortie_tab_active", False)
            return False

        def click(_rect, _screen, template, **_kwargs):
            actions.append(("click", template.name))
            if template.name == 'V7_RECOMMEND_TAB.png':
                state["sortie_tab_active"] = True
            if template.name == TPL_MATL_LITE.name:
                state["page"] = "sweep_dialog"
            elif template.name == TPL_SWEEP_CONFIRM.name:
                state["page"] = PAGE_MATERIAL
            return True

        vision.exists.side_effect = exists
        vision.click_template.side_effect = click

        result = run_sweep_task((0, 0, 1280, 720), lambda: screen, navigator, vision)

        self.assertTrue(result)
        self.assertEqual(navigator.ui_goto_calls, [PAGE_BATTLE, PAGE_MATERIAL, PAGE_MAIN])
        self.assertLess(actions.index(("click", 'V7_RECOMMEND_TAB.png')),
                        actions.index(("goto", PAGE_MATERIAL)))
        self.assertLess(actions.index(("goto", PAGE_MATERIAL)),
                        actions.index(("click", TPL_MATL_LITE.name)))

    @patch("games.honkai3.tasks.task_armada.time.sleep", return_value=None)
    def test_armada_missing_button_never_clicks_coordinates(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        navigator = MagicMock()
        navigator.ui_goto.return_value = True
        vision = MagicMock()
        vision.exists.return_value = False

        self.assertTrue(run_armada_task((0, 0, 1280, 720), lambda: screen, navigator, vision))
        vision.click_point.assert_not_called()
        vision.click_pos.assert_not_called()
        self.assertEqual(navigator.ui_goto.call_args.args[0], PAGE_MAIN)

    @patch("games.honkai3.tasks.task_mission.time.sleep", return_value=None)
    def test_mission_chests_only_click_templates_that_match(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        screen[96:104, 30:60] = (255, 255, 0)
        navigator = MagicMock()
        navigator.ui_goto.return_value = True
        # Import the shared page singleton used by the task module.
        from games.honkai3.core.page import PAGE_MISSION
        navigator.detect_current_page.return_value = PAGE_MISSION

        vision = MagicMock()
        vision.exists.return_value = False
        vision.match.side_effect = lambda _screen, template: (
            (100, 100, 0.97) if template.name == "DAILY_REWARD_100.png" else None
        )
        vision.click_template.return_value = True

        logs = []
        result = run_mission_task(
            (0, 0, 1280, 720), lambda: screen, navigator, vision,
            log_func=lambda message, level: logs.append((message, level)),
        )

        self.assertTrue(result)
        chest_clicks = [
            call.args[2].name for call in vision.click_template.call_args_list
            if call.args[2].name.startswith("DAILY_REWARD_")
        ]
        self.assertEqual(chest_clicks, ["DAILY_REWARD_100.png"])
        self.assertFalse(vision.click_pos.called)
        self.assertTrue(any("是否达到600历练值以游戏内进度为准" in text for text, _ in logs))

    @patch("games.honkai3.tasks.task_mission.time.sleep", return_value=None)
    def test_mission_wrong_page_aborts_before_any_reward_click(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        navigator = MagicMock()
        navigator.ui_goto.return_value = True
        from games.honkai3.core.page import PAGE_MAIN
        navigator.detect_current_page.return_value = PAGE_MAIN
        vision = MagicMock()

        result = run_mission_task((0, 0, 1280, 720), lambda: screen, navigator, vision)

        self.assertFalse(result)
        vision.click_template.assert_not_called()
        vision.click_pos.assert_not_called()

    @patch("games.honkai3.tasks.task_dorm.time.sleep", return_value=None)
    def test_dorm_reward_not_ready_is_a_safe_skip_and_dispatch_continues(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        navigator = MagicMock()
        navigator.ui_goto.return_value = True
        vision = MagicMock()
        pending = {"value": False}
        vision.exists.side_effect = lambda _screen, template: (
            pending["value"] if template.name == "V3_ERRAND_CONFIRM_TITLE.png"
            else template.name == "V2_ERRAND_DISPATCH.png"
        )
        def click(_rect, _screen, template, **_kwargs):
            if template.name == "V2_ERRAND_DISPATCH.png":
                pending["value"] = True
            elif template.name == "QUICK_ERRAND_CONFIRM.png":
                pending["value"] = False
            return True
        vision.click_template.side_effect = click
        logs = []

        result = run_dorm_task(
            (0, 0, 1280, 720), lambda: screen, navigator, vision,
            log_func=lambda message, level: logs.append((message, level)),
        )

        self.assertTrue(result)
        clicked_templates = [call.args[2].name for call in vision.click_template.call_args_list]
        self.assertNotIn("V2_ERRAND_CLAIM.png", clicked_templates)
        self.assertIn("V2_ERRAND_DISPATCH.png", clicked_templates)
        self.assertIn("QUICK_ERRAND_CONFIRM.png", clicked_templates)
        self.assertFalse(pending["value"])
        self.assertTrue(any("尚未到完成时间" in text for text, _ in logs))

    @patch("games.honkai3.tasks.task_dorm.time.sleep", return_value=None)
    def test_errand_confirmation_persists_after_click_fails_instead_of_completing(self, _sleep):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision = MagicMock()
        vision.exists.return_value = True
        vision.click_template.return_value = True
        self.assertFalse(finish_errand_dispatch((0, 0, 1280, 720), lambda: screen, vision))
        # 已发送确认但画面未变化时不连点，也不宣称完成。
        vision.click_template.assert_called_once()

    def test_errand_dialog_blocks_navigation_to_background_controls(self):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        vision = MagicMock()
        vision.exists.side_effect = lambda _screen, template: template.name == "V3_ERRAND_CONFIRM_TITLE.png"
        nav = PageNavigator(vision)
        self.assertIsNone(nav.detect_current_page(screen))
        self.assertFalse(nav.ui_goto(PAGE_MAIN, (0, 0, 1280, 720), lambda: screen))
        vision.click_template.assert_not_called()

    def test_dispatch_returns_v9_seed_offline(self):
        from games.honkai3 import mihoyo_api
        disp = mihoyo_api.get_game_dispatch("9.0.0")
        self.assertTrue(mihoyo_api._is_valid_dispatch(disp))
        self.assertEqual(len(disp), len(mihoyo_api._KNOWN_DISPATCH_V9))

    def test_dispatch_fallback_on_network_error(self):
        from games.honkai3 import mihoyo_api
        with patch("requests.get", side_effect=Exception("Offline")):
            disp = mihoyo_api.get_game_dispatch("9.9.9")
            self.assertEqual(disp, "")

    def test_find_account_login_button_on_blank(self):
        from games.honkai3 import qr_scanner
        blank = Image.new("RGB", (1024, 575), (0, 0, 0))
        self.assertIsNone(qr_scanner.find_account_login_button(blank))

    def test_find_dialog_confirm_button_on_blank(self):
        from games.honkai3 import qr_scanner
        blank = Image.new("RGB", (1024, 575), (0, 0, 0))
        self.assertIsNone(qr_scanner.find_dialog_confirm_button(blank))

    def test_fetch_tv_qrcode_mock_success(self):
        from games.honkai3 import bili_sdk
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "url": "https://passport.bilibili.com/x/passport-tv-login/h5/qrcode/auth?auth_code=test1234",
                "auth_code": "test1234"
            }
        }
        with patch("requests.post", return_value=mock_resp):
            res = bili_sdk.fetch_tv_qrcode()
            self.assertEqual(res["code"], 0)
            self.assertEqual(res["auth_code"], "test1234")
            self.assertTrue(res["url"].startswith("http"))

    def test_poll_tv_qrcode_mock_flow(self):
        from games.honkai3 import bili_sdk
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "access_token": "mock_tv_access_token_12345",
                "mid": 247659774,
                "refresh_token": "mock_refresh_token",
                "expires_in": 2592000
            }
        }
        with patch("requests.post", return_value=mock_resp):
            res = bili_sdk.poll_tv_qrcode("test1234")
            self.assertEqual(res["code"], 0)
            data = res.get("data", {})
            self.assertEqual(data.get("access_token"), "mock_tv_access_token_12345")
            self.assertEqual(data.get("mid"), 247659774)

    def test_find_qr_toggle_button_on_user_screenshot(self):
        from pathlib import Path
        from games.honkai3 import qr_scanner
        user_img_path = Path("C:/Users/40432/.gemini/antigravity/brain/6c9158f3-6fa0-4d08-ab0c-e9a35f00713c/.user_uploaded/media_1791815338852_85cbdc71.png")
        if user_img_path.is_file():
            img = Image.open(user_img_path)
            pos = qr_scanner.find_qr_toggle_button(img)
            self.assertIsNotNone(pos)
            self.assertEqual(pos, (353, 152))

    def test_dorm_and_armada_anchors_hit_button_center(self):
        from pathlib import Path
        import cv2
        from games.honkai3.core.page import (
            PageNavigator, PAGE_MAIN, PAGE_DORM, PAGE_ARMADA,
            TPL_MAIN_GOTO_DORM, TPL_MAIN_GOTO_ARMADA
        )
        # Check normalized coordinates are centered on button, not on bottom border
        self.assertAlmostEqual(TPL_MAIN_GOTO_DORM.record_pos[0], 0.391, places=2)
        self.assertAlmostEqual(TPL_MAIN_GOTO_DORM.record_pos[1], 0.396, places=2)
        self.assertAlmostEqual(TPL_MAIN_GOTO_ARMADA.record_pos[0], 0.234, places=2)
        self.assertAlmostEqual(TPL_MAIN_GOTO_ARMADA.record_pos[1], 0.396, places=2)

        # Check against diagnostic frame if present
        diag_path = Path(__file__).resolve().parents[1] / "diagnostics" / "1792573107307943700.png"
        if diag_path.is_file():
            frame = cv2.imread(str(diag_path))
            vision = UIVision()
            match_d = vision.match(frame, TPL_MAIN_GOTO_DORM)
            self.assertIsNotNone(match_d)
            self.assertTrue(2260 <= match_d[0] <= 2300, f"Dorm click x {match_d[0]} not in button center")
            self.assertTrue(1270 <= match_d[1] <= 1310, f"Dorm click y {match_d[1]} not in button center")

            match_a = vision.match(frame, TPL_MAIN_GOTO_ARMADA)
            self.assertIsNotNone(match_a)
            self.assertTrue(1860 <= match_a[0] <= 1900, f"Armada click x {match_a[0]} not in button center")
            self.assertTrue(1270 <= match_a[1] <= 1310, f"Armada click y {match_a[1]} not in button center")


if __name__ == "__main__":
    unittest.main()



