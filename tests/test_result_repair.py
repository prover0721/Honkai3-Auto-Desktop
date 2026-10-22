"""Result propagation and pause ordering, with all input mocked."""
import unittest
from unittest.mock import Mock, patch
from contextlib import contextmanager
import numpy as np
from core.runtime_guard import RuntimeViolation
from games.honkai3.core.task_guard import HonkaiTaskGuard
from games.honkai3.core.page import PAGE_MISSION, PAGE_ERRAND, PAGE_EXPEDITION
from games.honkai3.tasks.task_dorm import run_dorm_task
from games.honkai3.tasks.task_expedition import run_expedition_task
from games.honkai3.tasks.task_mission import run_mission_task
from games.honkai3 import runner

class ResultRepairTests(unittest.TestCase):
    def setup_task(self):
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        v,n=Mock(),Mock(); v.exists.return_value=False
        n.ui_goto.return_value=True; n.detect_current_page.return_value=PAGE_MISSION
        return frame,v,n

    @patch('games.honkai3.tasks.task_dorm.time.sleep')
    def test_missing_dispatch_is_not_success(self,sleep):
        f,v,n=self.setup_task()
        self.assertFalse(run_dorm_task((0,0,1280,720),lambda:f,n,v))

    @patch('games.honkai3.tasks.task_dorm.time.sleep')
    def test_already_dispatched_in_errand_page_succeeds(self, sleep):
        f, v, n = self.setup_task()
        n.detect_current_page.return_value = PAGE_ERRAND
        self.assertTrue(run_dorm_task((0, 0, 1280, 720), lambda: f, n, v))

    @patch('games.honkai3.tasks.task_expedition.time.sleep')
    def test_already_dispatched_in_expedition_page_succeeds(self, sleep):
        f, v, n = self.setup_task()
        n.detect_current_page.return_value = PAGE_EXPEDITION
        self.assertTrue(run_expedition_task((0, 0, 1280, 720), lambda: f, n, v))

    @patch('games.honkai3.tasks.task_dorm.time.sleep')
    def test_gold_click_failure_stops_dorm(self,sleep):
        f,v,n=self.setup_task()
        v.exists.side_effect=lambda frame,t:t.name=='V2_DORM_GOLD.png'
        v.click_template.return_value=False
        self.assertFalse(run_dorm_task((0,0,1280,720),lambda:f,n,v))
        self.assertEqual(n.ui_goto.call_count,1)

    @patch('games.honkai3.tasks.task_mission.time.sleep')
    @patch('games.honkai3.tasks.task_mission.stage_is_reached',return_value=True)
    def test_chest_click_failure_is_not_success(self,reached,sleep):
        f,v,n=self.setup_task(); v.match.return_value=(100,100,.99)
        v.click_template.return_value=False
        self.assertFalse(run_mission_task((0,0,1280,720),lambda:f,n,v))
        self.assertEqual(n.ui_goto.call_count,1)

    @patch('games.honkai3.tasks.task_mission.time.sleep')
    def test_wrong_mission_page_is_not_hidden_by_return_home(self,sleep):
        f,v,n=self.setup_task(); n.detect_current_page.side_effect=[PAGE_MISSION,None]
        self.assertFalse(run_mission_task((0,0,1280,720),lambda:f,n,v))
        self.assertEqual(n.ui_goto.call_count,1)

    @patch.object(HonkaiTaskGuard,'evidence')
    def test_pause_wait_precedes_freshness_check(self,evidence):
        f,v,n=self.setup_task(); pop=Mock()
        g=HonkaiTaskGuard('missions',(0,0,1280,720),lambda:f,n,v,pop,Mock(),lambda:False)
        self.addCleanup(g.close)
        now=[0.]; g.runtime.clock=lambda:now[0]; g.runtime.observe(f)
        @contextmanager
        def resumed_after_long_pause():
            now[0]=30.
            yield
        with patch('games.honkai3.core.pause_gate.input_permit',resumed_after_long_pause):
            with self.assertRaises(RuntimeViolation): v.click_point((0,0,1280,720),10,10)
        g.original_click.assert_not_called()

    def test_merged_task_recovers_expedition_before_dorm(self):
        f,v,n=self.setup_task()
        v.exists.side_effect=lambda frame,t:t.name=='V3_EXPEDITION_DISPATCH_TITLE.png'
        order=[]
        with patch('games.honkai3.tasks.task_expedition.run_expedition_task',side_effect=lambda *a:order.append('expedition') or True), patch('games.honkai3.tasks.task_dorm.run_dorm_task',side_effect=lambda *a:order.append('dorm') or True):
            self.assertTrue(runner._dispatch_guarded_task('daily_errand',(0,0,1280,720),lambda:f,n,v,Mock(),Mock(),lambda:False))
        self.assertEqual(order,['expedition','dorm'])

    def test_merged_task_recovery_failure_never_starts_dorm(self):
        f,v,n=self.setup_task(); v.exists.return_value=True
        with patch('games.honkai3.tasks.task_expedition.run_expedition_task',return_value=False), patch('games.honkai3.tasks.task_dorm.run_dorm_task') as dorm:
            self.assertFalse(runner._dispatch_guarded_task('daily_errand',(0,0,1280,720),lambda:f,n,v,Mock(),Mock(),lambda:False))
            dorm.assert_not_called()
