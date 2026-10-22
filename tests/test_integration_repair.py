"""Offline integration regressions: no desktop or network access."""
import unittest
from unittest.mock import Mock, patch
import numpy as np
from core.runtime_guard import RuntimeViolation
from games.honkai3 import runner
from games.honkai3.core.task_guard import HonkaiTaskGuard
from games.honkai3.core.page import PageNavigator, PAGE_DORM, PAGE_ERRAND, PAGE_MAIN
from games.honkai3.core.daily_ui import TPL_EXPEDITION_DIALOG, TPL_SWEEP_DIALOG, TPL_REWARD_DIALOG
from games.honkai3.core.popup import PopupHandler, TPL_ERRAND_CONFIRM_TITLE
from games.honkai3.core.ui_vision import UIVision

class IntegrationRepairTests(unittest.TestCase):
    def guard(self, task, marker):
        v, pop, nav = Mock(), Mock(), Mock()
        v.exists.side_effect = lambda frame, tpl: tpl is marker
        pop.interrupts.return_value = False
        pop.recognizes.return_value = False
        nav.detect_current_page.return_value = None
        g = HonkaiTaskGuard(task, (0,0,1280,720), lambda: np.zeros((720,1280,3)), nav, v, pop, Mock(), lambda:False)
        self.addCleanup(g.close)
        return g

    @patch.object(HonkaiTaskGuard, 'evidence')
    def test_supported_task_owned_dialog_can_resume(self, evidence):
        for task, marker in [('expedition',TPL_EXPEDITION_DIALOG), ('expedition',TPL_REWARD_DIALOG),
                             ('daily_sweep',TPL_SWEEP_DIALOG), ('daily_sweep',TPL_REWARD_DIALOG),
                             ('dorm_errand',TPL_ERRAND_CONFIRM_TITLE)]:
            with self.subTest(task=task, marker=marker.name):
                self.guard(task,marker).prepare()
        evidence.assert_not_called()

    @patch.object(HonkaiTaskGuard, 'evidence')
    def test_other_task_cannot_resume_foreign_confirmation(self, evidence):
        with self.assertRaises(RuntimeViolation):
            self.guard('missions',TPL_EXPEDITION_DIALOG).prepare()

    @patch('games.honkai3.core.page.time.sleep')
    def test_unknown_dorm_transition_waits_without_return_click(self, sleep):
        for target in (PAGE_DORM,PAGE_ERRAND):
            v=Mock(); v.exists.return_value=False
            n=PageNavigator(v); n.detect_current_page=Mock(side_effect=[None,target])
            self.assertTrue(n.ui_goto(target,(0,0,1280,720),lambda:np.zeros((720,1280,3)),max_retries=2))
            v.click_template.assert_not_called()

    def test_close_search_shared_for_same_frame_but_new_capture_rechecks(self):
        v=UIVision(template_dirs=[]); v.match_candidates=Mock(return_value=[])
        frame=np.zeros((720,1280,3))
        self.assertFalse(PopupHandler(v).has_close(frame))
        self.assertFalse(PopupHandler(v).has_close(frame))
        self.assertEqual(v.match_candidates.call_count,3)
        self.assertFalse(PopupHandler(v).has_close(frame.copy()))
        self.assertEqual(v.match_candidates.call_count,6)

    def login_patches(self, at_main=False):
        from contextlib import ExitStack
        stack=ExitStack(); self.addCleanup(stack.close)
        def stub(name, **kw): return stack.enter_context(patch(name,**kw))
        prefix='games.honkai3.'
        stub(prefix+'runner.detect_bh3_version',return_value='9.1.0')
        stub(prefix+'runner.qr_scanner.find_bh3_window',return_value=(0,0,1280,720))
        stub(prefix+'runner.qr_scanner.capture_screen_or_window',return_value=np.zeros((720,1280,3)))
        v=Mock(); v.exists.return_value=False
        stub(prefix+'core.ui_vision.UIVision',return_value=v)
        n=Mock(); n.detect_current_page.return_value=PAGE_MAIN if at_main else None
        stub(prefix+'core.page.PageNavigator',return_value=n)
        pop=Mock(); pop.has_close.return_value=False
        stub(prefix+'core.popup.PopupHandler',return_value=pop)
        return stub

    def test_login_card_first_frame_has_no_unbound_local(self):
        stub=self.login_patches()
        stub('games.honkai3.runner.qr_scanner.decode_qr_code',return_value='qr')
        stub('games.honkai3.runner.qr_scanner.parse_qr_payload',return_value={'ticket':'test'})
        self.assertFalse(runner.run_auto_login({'account_type':'1','bh_ver':'9.1.0'},Mock(),lambda:False))

    def test_already_logged_in_context_failure_is_not_success(self):
        stub=self.login_patches(at_main=True)
        stub('games.honkai3.runner._get_context',return_value=(None,)*5)
        self.assertFalse(runner.run_auto_login({'account_type':'1','bh_ver':'9.1.0'},Mock(),lambda:False))

    def test_authorized_login_context_failure_is_not_success(self):
        stub=self.login_patches()
        for name,value in [('decode_qr_code','qr'),('parse_qr_payload',{'ticket':'test'}),('wait_and_click_enter_game',True)]:
            stub('games.honkai3.runner.qr_scanner.'+name,return_value=value)
        for name in ('scan_qrcode','confirm_qrcode'):
            stub('games.honkai3.runner.mihoyo_api.'+name,return_value={'retcode':0})
        stub('games.honkai3.runner._get_context',return_value=(None,)*5)
        self.assertFalse(runner.run_auto_login({'account_type':'1','bh_ver':'9.1.0','open_id':'test','combo_token':'test'},Mock(),lambda:False))

    def test_visual_cache_reuses_only_identical_frame_and_rule(self):
        v=UIVision(template_dirs=[])
        v._match_uncached=Mock(return_value=(10,10,.99))
        from games.honkai3.core.ui_vision import Template
        frame=np.zeros((20,20,3)); tpl=Template('test.png')
        v.match(frame,tpl); v.match(frame,tpl)
        self.assertEqual(v._match_uncached.call_count,1)
        v.match(frame,tpl,threshold=.95)
        v.match(frame.copy(),tpl)
        self.assertEqual(v._match_uncached.call_count,3)
        self.assertLessEqual(len(v._frame_match_cache),2)
