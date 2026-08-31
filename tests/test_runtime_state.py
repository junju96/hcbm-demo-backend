import unittest

from app.services.action_sequence_client import ActionSequenceRuntime


def _plan(*states):
    return {
        "vehicle_summary": [
            {
                "vid": "ZD01",
                "stages": [
                    {"stage_seq": 1, "actions": [{"action_id": f"a{i}", "state": s} for i, s in enumerate(states)]}
                ],
            }
        ]
    }


class TestRuntimeReinfer(unittest.TestCase):
    """init_state_from_plan 的指纹重推断规则。"""

    def setUp(self):
        self.rt = ActionSequenceRuntime()

    def test_stale_done_recovers_when_plan_rewritten(self):
        """旧版本锁定的 DONE：plan 被重写为全 SCHEDULED 后应恢复。"""
        self.rt.init_state_from_plan("p1", _plan("DONE", "DONE"))
        self.assertEqual(self.rt.get_state("p1")["state"], "DONE")
        self.rt.init_state_from_plan("p1", _plan("SCHEDULED", "SCHEDULED"))
        self.assertEqual(self.rt.get_state("p1")["state"], "SCHEDULED")

    def test_active_not_reverted_when_actions_unchanged(self):
        """开始后 DS 行动状态未推进：ACTIVE 不被冲回 SCHEDULED。"""
        self.rt.init_state_from_plan("p1", _plan("SCHEDULED", "SCHEDULED"))
        ok, _ = self.rt.transit("p1", "ACTIVE")
        self.assertTrue(ok)
        self.rt.init_state_from_plan("p1", _plan("SCHEDULED", "SCHEDULED"))
        self.assertEqual(self.rt.get_state("p1")["state"], "ACTIVE")

    def test_active_kept_while_actions_progressing(self):
        """行动中行动状态部分推进（非全 DONE）：保持 ACTIVE。"""
        self.rt.init_state_from_plan("p1", _plan("SCHEDULED", "SCHEDULED"))
        self.rt.transit("p1", "ACTIVE")
        self.rt.init_state_from_plan("p1", _plan("ACTIVE", "SCHEDULED"))
        self.assertEqual(self.rt.get_state("p1")["state"], "ACTIVE")

    def test_active_completes_to_done(self):
        """行动全部 DONE：ACTIVE 自动收敛为 DONE。"""
        self.rt.init_state_from_plan("p1", _plan("SCHEDULED", "SCHEDULED"))
        self.rt.transit("p1", "ACTIVE")
        self.rt.init_state_from_plan("p1", _plan("DONE", "DONE"))
        self.assertEqual(self.rt.get_state("p1")["state"], "DONE")

    def test_paused_kept_while_actions_not_all_done(self):
        """暂停中行动状态未全部完成：保持 PAUSED。"""
        self.rt.init_state_from_plan("p1", _plan("SCHEDULED", "SCHEDULED"))
        self.rt.transit("p1", "ACTIVE")
        self.rt.transit("p1", "PAUSED")
        self.rt.init_state_from_plan("p1", _plan("ACTIVE", "SCHEDULED"))
        self.assertEqual(self.rt.get_state("p1")["state"], "PAUSED")


if __name__ == "__main__":
    unittest.main()
