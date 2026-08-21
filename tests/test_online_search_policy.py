import unittest

from tools.literature.online_search_policy import (
    OnlineSearchPolicy,
)


def make_paper(
    paper_id: str,
    title: str,
    doi: str,
    quality_level: str = "A",
    reaction_direct: bool = True,
    product_direct: bool = True,
    source: str = "OpenAlex",
    year: int = 2025,
):
    return {
        "paper_id": paper_id,
        "title": title,
        "doi": doi,
        "source": source,
        "year": year,
        "evidence_quality": {
            "quality_level": (
                quality_level
            ),
            "reaction_direct": (
                reaction_direct
            ),
            "product_direct": (
                product_direct
            ),
        },
    }


class OnlineSearchPolicyTest(
    unittest.TestCase
):
    def setUp(self):
        self.policy = OnlineSearchPolicy(
            minimum_real_papers=5,
            minimum_unique_papers=3,
            minimum_a_level_papers=2,
            minimum_reaction_direct_papers=2,
            recent_year_window=5,
        )

        self.task = {
            "reaction_family": "CO2RR",
            "target_product": "CO",
        }

    def test_sparse_local_results_trigger_online(self):
        local_result = {
            "selected": [
                make_paper(
                    "openalex:1",
                    "CO2 reduction paper",
                    "10.1000/one",
                )
            ]
        }

        result = self.policy.evaluate(
            local_result=local_result,
            task_analysis=self.task,
            question=(
                "设计用于 CO2 还原生成 CO "
                "的催化剂"
            ),
        )

        self.assertTrue(
            result["use_online_search"]
        )
        self.assertEqual(
            result["decision"],
            "online_supplement",
        )
        self.assertEqual(
            result["metrics"][
                "real_paper_count"
            ],
            1,
        )

    def test_sufficient_local_results_skip_online_search(self):
        papers = [
            make_paper(
                f"openalex:{index}",
                f"CO2 reduction paper {index}",
                f"10.1000/{index}",
            )
            for index in range(1, 6)
        ]

        local_result = {
            "selected": papers,
        }

        result = self.policy.evaluate(
            local_result=local_result,
            task_analysis=self.task,
            question="CO2 reduction catalyst",
        )

        self.assertFalse(
            result["use_online_search"]
        )
        self.assertEqual(
            result["decision"],
            "local_sufficient",
        )
        self.assertEqual(
            result["metrics"][
                "real_paper_count"
            ],
            5,
        )

    def test_samples_do_not_count_as_real_papers(self):
        papers = [
            make_paper(
                paper_id=f"sample:{index}",
                title=f"Sample paper {index}",
                doi="",
                source="sample",
            )
            for index in range(1, 6)
        ]

        result = self.policy.evaluate(
            local_result={
                "selected": papers,
            },
            task_analysis=self.task,
            question="CO2 reduction catalyst",
        )

        self.assertTrue(
            result["use_online_search"]
        )
        self.assertEqual(
            result["metrics"][
                "development_sample_count"
            ],
            5,
        )
        self.assertEqual(
            result["metrics"][
                "real_paper_count"
            ],
            0,
        )

    def test_duplicate_doi_reduces_unique_count(self):
        papers = [
            make_paper(
                "openalex:1",
                "First title",
                "https://doi.org/10.1000/same",
            ),
            make_paper(
                "openalex:2",
                "Second title",
                "10.1000/same",
            ),
            make_paper(
                "openalex:3",
                "Third title",
                "10.1000/third",
            ),
            make_paper(
                "openalex:4",
                "Fourth title",
                "10.1000/fourth",
            ),
            make_paper(
                "openalex:5",
                "Fifth title",
                "10.1000/fifth",
            ),
        ]

        result = self.policy.evaluate(
            local_result={
                "selected": papers,
            },
            task_analysis=self.task,
            question="CO2 reduction catalyst",
        )

        self.assertEqual(
            result["metrics"][
                "real_paper_count"
            ],
            5,
        )
        self.assertEqual(
            result["metrics"][
                "unique_real_paper_count"
            ],
            4,
        )
        self.assertEqual(
            result["metrics"][
                "potential_duplicate_count"
            ],
            1,
        )

    def test_normalized_title_detects_duplicate(self):
        papers = [
            make_paper(
                "openalex:1",
                (
                    "High-Entropy Alloys for "
                    "CO<sub>2</sub> Reduction"
                ),
                "",
            ),
            make_paper(
                "openalex:2",
                (
                    "High Entropy Alloys for "
                    "CO2 Reduction"
                ),
                "",
            ),
        ]

        result = self.policy.evaluate(
            local_result={
                "selected": papers,
            },
            task_analysis=self.task,
            question="CO2 reduction",
        )

        self.assertEqual(
            result["metrics"][
                "unique_real_paper_count"
            ],
            1,
        )

    def test_latest_request_forces_online_search(self):
        papers = [
            make_paper(
                f"openalex:{index}",
                f"Paper {index}",
                f"10.1000/{index}",
            )
            for index in range(1, 6)
        ]

        result = self.policy.evaluate(
            local_result={
                "selected": papers,
            },
            task_analysis=self.task,
            question=(
                "检索最新的 CO2 还原研究进展"
            ),
        )

        self.assertTrue(
            result["use_online_search"]
        )
        self.assertIn(
            "用户明确要求最新、近期或联网文献",
            result["reasons"],
        )

    def test_local_only_request_forbids_online(self):
        result = self.policy.evaluate(
            local_result={
                "selected": [],
            },
            task_analysis=self.task,
            question=(
                "不要联网，只用本地文献分析 "
                "CO2 还原"
            ),
        )

        self.assertFalse(
            result["use_online_search"]
        )
        self.assertEqual(
            result["decision"],
            "online_forbidden_by_user",
        )
        self.assertTrue(
            result["reasons"]
        )

    def test_product_match_is_only_a_mention_metric(self):
        paper = make_paper(
            "openalex:1",
            "CO adsorption study",
            "10.1000/co",
            product_direct=True,
        )

        result = self.policy.evaluate(
            local_result={
                "selected": [paper],
            },
            task_analysis=self.task,
            question="CO2 reduction to CO",
        )

        self.assertEqual(
            result["metrics"][
                "product_mention_count"
            ],
            1,
        )
        self.assertTrue(
            any(
                "词法上提到目标产物"
                in warning
                for warning
                in result["warnings"]
            )
        )


if __name__ == "__main__":
    unittest.main()
