import json
import unittest
from unittest.mock import Mock

from app.graph.nodes import literature_retry_prepare_node
from app.graph.routes import (
    route_after_literature_commit,
    route_after_literature_evidence,
)
from tools.literature.evidence_merger import LiteratureEvidenceMerger
from tools.literature.retry_support import accepted_five_metal_sets


def assertion(kind, value, paper_id="openalex:W1"):
    return {
        "kind": kind,
        "value": value,
        "paper_id": paper_id,
        "evidence_id": "E1",
        "assertion_id": f"E1::{kind}",
        "evidence_level": "explicit",
        "inferred": False,
        "evidence": [{"quote": "verbatim evidence"}],
    }


class LiteratureRetryTest(unittest.TestCase):
    def review(self, accepted=0, rejected=0, deferred=0):
        count = accepted + rejected + deferred
        return {
            "status": "review_completed",
            "candidate_count": count,
            "accepted_count": accepted,
            "rejected_count": rejected,
            "deferred_count": deferred,
            "accepted": [],
            "rejected": [
                {
                    "paper_id": f"openalex:W{i}",
                    "doi": f"10.1000/{i}",
                    "title": f"Rejected Paper {i}",
                }
                for i in range(rejected)
            ],
        }

    def state(self, review, round_number=1, assertions=None):
        return {
            "literature_review": review,
            "literature_search_round": round_number,
            "literature_max_search_rounds": 3,
            "accepted_literature_assertions": assertions or [],
            "online_literature_result": {"status": "completed"},
        }

    def test_all_rejected_retries(self):
        self.assertEqual(
            route_after_literature_commit(self.state(self.review(rejected=3))),
            "retry_online",
        )

    def test_mandatory_online_failure_stops_before_extraction(self):
        state = {
            "online_search_policy": {"decision": "online_required"},
            "online_literature_result": {"status": "online_failed"},
        }
        self.assertEqual(
            route_after_literature_evidence(state), "online_failure"
        )

    def test_deferred_does_not_retry(self):
        self.assertEqual(
            route_after_literature_commit(self.state(self.review(deferred=1))),
            "continue",
        )

    def test_maximum_round_does_not_retry(self):
        self.assertEqual(
            route_after_literature_commit(
                self.state(self.review(rejected=2), round_number=3)
            ),
            "continue",
        )

    def test_strict_five_metal_gate(self):
        four = [
            assertion("material_family", "high_entropy_alloy"),
            assertion("element_set", ["Cu", "Fe", "Co", "Ni"]),
        ]
        five = [
            assertion("material_family", "high_entropy_alloy"),
            assertion("element_set", ["Cu", "Fe", "Co", "Ni", "Mn"]),
        ]
        self.assertEqual(accepted_five_metal_sets(four), [])
        self.assertEqual(len(accepted_five_metal_sets(five)), 1)
        self.assertEqual(
            route_after_literature_commit(
                self.state(self.review(accepted=1), assertions=five)
            ),
            "continue",
        )

    def test_task_context_requires_reaction_but_not_product(self):
        claims = [
            assertion("material_family", "high_entropy_alloy"),
            assertion("element_set", ["Cu", "Fe", "Co", "Ni", "Mn"]),
            assertion("reaction", "CO2RR"),
            assertion("product", "CO"),
        ]
        task = {"reaction_family": "CO2RR", "target_product": "CO"}
        self.assertEqual(len(accepted_five_metal_sets(claims, task)), 1)
        claims[-1] = assertion("product", "H2")
        self.assertEqual(len(accepted_five_metal_sets(claims, task)), 1)
        claims = claims[:-2] + [claims[-1]]
        self.assertEqual(accepted_five_metal_sets(claims, task), [])

    def test_missing_product_assertion_does_not_block_c_stage(self):
        paper_id = "crossref:10.1000/no-product"
        claims = [
            assertion("material_family", "high_entropy_alloy", paper_id),
            assertion(
                "element_set", ["Cu", "Fe", "Co", "Ni", "Mn"], paper_id
            ),
            assertion("reaction", "CO2RR", paper_id),
        ]
        papers = [{
            "paper_id": paper_id,
            "abstract": "CuFeCoNiMn is a high entropy alloy for CO2RR.",
            "metadata_verified": True,
            "kimi_cross_verified": True,
        }]
        result = accepted_five_metal_sets(
            claims,
            {"reaction_family": "CO2RR", "target_product": "CO"},
            papers,
        )
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["target_product_required"])

    def test_c_gate_allows_human_accepted_ideal_modeling_hypothesis(self):
        paper_id = "crossref:10.1000/verified"
        claims = [
            assertion("material_family", "high_entropy_alloy", paper_id),
            assertion(
                "element_set", ["Cu", "Fe", "Co", "Ni", "Mn"], paper_id
            ),
            assertion("reaction", "CO2RR", paper_id),
            assertion("product", "CO", paper_id),
        ]
        task = {"reaction_family": "CO2RR", "target_product": "CO"}
        verified = [{
            "paper_id": paper_id,
            "abstract": "CuFeCoNiMn is a high entropy alloy for CO2RR to CO.",
            "metadata_verified": True,
            "metadata_provider": "crossref",
            "kimi_cross_verified": True,
        }]
        self.assertEqual(
            len(accepted_five_metal_sets(claims, task, verified)), 1
        )
        self.assertEqual(
            len(accepted_five_metal_sets(
                claims, task, [{**verified[0], "abstract": ""}]
            )),
            1,
        )
        hypothesis = accepted_five_metal_sets(
            claims,
            task,
            [{**verified[0], "metadata_verified": False,
              "kimi_cross_verified": False}],
        )
        self.assertEqual(len(hypothesis), 1)
        self.assertEqual(
            hypothesis[0]["evidence_use_label"],
            "理想建模假设",
        )
        self.assertFalse(hypothesis[0]["requires_secondary_verification"])

    def test_retry_accumulates_rejected_identities(self):
        result = literature_retry_prepare_node(self.state(self.review(rejected=1)))
        self.assertIn("doi:10.1000/0", result["rejected_literature_identities"])
        self.assertIn("openalex:w0", result["rejected_literature_identities"])
        self.assertEqual(result["literature_search_round"], 2)
        json.dumps(result)

    def test_merger_excludes_rejected_paper(self):
        paper = {
            "paper_id": "openalex:W1",
            "doi": "10.1000/rejected",
            "title": "Rejected paper",
            "abstract": "CO2 reduction high entropy alloy CuFeCoNiMn to CO.",
            "journal": "Journal",
            "year": 2025,
        }
        result = LiteratureEvidenceMerger().merge(
            local_result={"selected": [paper]},
            online_result={"candidates": []},
            question="CO2 reduction to CO",
            task_analysis={"reaction_family": "CO2RR", "target_product": "CO"},
            excluded_identities={"doi:10.1000/rejected"},
        )
        self.assertEqual(result["combined_input_count"], 0)
        self.assertEqual(result["excluded_previous_rejections"], 1)

    def test_merger_preserves_crossref_verification(self):
        local = {
            "paper_id": "local:1",
            "doi": "10.1000/merged",
            "title": "Merged HEA paper",
            "abstract": "CuFeCoNiMn high entropy alloy for CO2RR to CO.",
            "journal": "Journal",
            "year": 2025,
        }
        crossref = {
            **local,
            "paper_id": "crossref:10.1000/merged",
            "source": "Crossref",
            "metadata_verified": True,
            "metadata_provider": "crossref",
            "claim_evidence_available": True,
            "kimi_cross_verified": True,
        }
        result = LiteratureEvidenceMerger().merge(
            local_result={"selected": [local]},
            online_result={"candidates": [crossref]},
            question="CO2RR to CO",
            task_analysis={"reaction_family": "CO2RR", "target_product": "CO"},
        )
        merged = result["selected"][0]
        self.assertTrue(merged["metadata_verified"])
        self.assertEqual(merged["metadata_provider"], "crossref")
        self.assertTrue(merged["claim_evidence_available"])
        self.assertTrue(merged["cross_verified"])
        self.assertTrue(merged["kimi_cross_verified"])


if __name__ == "__main__":
    unittest.main()
