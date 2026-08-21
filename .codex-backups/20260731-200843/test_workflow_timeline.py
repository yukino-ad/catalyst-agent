import unittest

from app.api.workflow_timeline import (
    create_timeline,
    finalize_timeline,
    mark_node_update,
    stage_id_for_review,
    update_stage,
)


class WorkflowTimelineTest(unittest.TestCase):
    def test_initializes_all_display_stages(self):
        timeline = create_timeline()
        self.assertEqual(timeline[0]["stage_id"], "A1")
        self.assertEqual(timeline[-1]["stage_id"], "C12.7")
        self.assertTrue(all(stage["status"] == "pending" for stage in timeline))

    def test_every_stage_has_unified_display_contract(self):
        required = {
            "stage_id",
            "stage_label",
            "status",
            "summary",
            "progress",
            "outputs",
            "next_stage",
            "requires_human_action",
        }
        for stage in create_timeline():
            self.assertTrue(required.issubset(stage), stage["stage_id"])
            self.assertIsInstance(stage["outputs"], dict)

    def test_stage_outputs_are_persisted_on_update(self):
        timeline = update_stage(
            create_timeline(),
            "C6",
            "completed",
            summary="形成能预测完成",
            outputs={"formation_energy_ev_per_atom": -0.0574, "status": "passed"},
        )
        c6 = next(stage for stage in timeline if stage["stage_id"] == "C6")
        self.assertEqual(c6["stage_label"], "预测形成能")
        self.assertEqual(c6["next_stage"], "C7")
        self.assertEqual(c6["outputs"]["status"], "passed")

    def test_candidate_node_updates_c2_and_c3(self):
        timeline = mark_node_update(create_timeline(), "candidate_generation", "three candidates")
        states = {stage["stage_id"]: stage["status"] for stage in timeline}
        self.assertEqual(states["C2"], "completed")
        self.assertEqual(states["C3"], "completed")

    def test_review_maps_to_stage(self):
        self.assertEqual(stage_id_for_review("literature_review_required"), "B6")
        timeline = update_stage(
            create_timeline(),
            "B6",
            "waiting_review",
            requires_human_action=True,
        )
        b6 = next(stage for stage in timeline if stage["stage_id"] == "B6")
        self.assertEqual(b6["status"], "waiting_review")
        self.assertTrue(b6["requires_human_action"])

    def test_later_node_completes_submitted_review_stage(self):
        timeline = update_stage(create_timeline(), "C4", "running")
        timeline = mark_node_update(timeline, "structure_modeling", "modeled")
        states = {stage["stage_id"]: stage["status"] for stage in timeline}
        self.assertEqual(states["C4"], "completed")
        self.assertEqual(states["C5"], "completed")

    def test_skipped_node_is_not_reported_as_completed(self):
        timeline = mark_node_update(
            create_timeline(),
            "dft_execution_options",
            "dft execution options skipped",
            {"status": "dft_execution_options_skipped"},
        )
        c11 = next(stage for stage in timeline if stage["stage_id"] == "C11")
        self.assertEqual(c11["status"], "skipped")

    def test_finalize_closes_submitted_review(self):
        timeline = update_stage(create_timeline(), "C10", "running")
        timeline = finalize_timeline(timeline, reason="Deferred")
        c10 = next(stage for stage in timeline if stage["stage_id"] == "C10")
        self.assertEqual(c10["status"], "completed")


if __name__ == "__main__":
    unittest.main()
