import copy
import unittest

from tools.literature.evidence_merger import (
    LiteratureEvidenceMerger,
)


def make_paper(
    paper_id,
    title,
    doi="",
    abstract="",
    journal="",
    source="OpenAlex",
    year=2025,
):
    return {
        "paper_id": paper_id,
        "title": title,
        "doi": doi,
        "abstract": abstract,
        "journal": journal,
        "source": source,
        "year": year,
        "url": "",
        "summary": "",
        "assertions": [],
    }


class LiteratureEvidenceMergerTest(
    unittest.TestCase
):
    def setUp(self):
        self.merger = LiteratureEvidenceMerger()

        self.task = {
            "reaction_family": "CO2RR",
            "target_product": "CO",
        }

        self.question = (
            "设计用于 CO2 还原生成 CO "
            "的高熵催化剂"
        )

    def test_same_doi_is_deduplicated(self):
        local = make_paper(
            "openalex:W1",
            "CO2 reduction catalyst",
            doi="https://doi.org/10.1000/same",
            abstract=(
                "CO2 reduction produces CO."
            ),
            journal="Example Journal",
        )

        online = make_paper(
            "openalex:W2",
            "A different metadata title",
            doi="10.1000/same",
            abstract=(
                "CO2 reduction produces CO."
            ),
            journal="Example Journal",
        )

        result = self.merger.merge(
            local_result={"selected": [local]},
            online_result={
                "candidates": [online]
            },
            question=self.question,
            task_analysis=self.task,
        )

        self.assertEqual(
            result["combined_input_count"],
            2,
        )
        self.assertEqual(
            result["unique_count"],
            1,
        )
        self.assertEqual(
            result["duplicate_count"],
            1,
        )

    def test_same_openalex_id_is_deduplicated(self):
        local = make_paper(
            "openalex:W123",
            "Local title",
        )

        online = make_paper(
            "https://openalex.org/W123",
            "Online title",
        )

        result = self.merger.merge(
            local_result={"selected": [local]},
            online_result={
                "candidates": [online]
            },
            question=self.question,
            task_analysis=self.task,
        )

        self.assertEqual(
            result["unique_count"],
            1,
        )

    def test_formal_version_is_preferred(self):
        preprint = make_paper(
            "openalex:PREPRINT",
            (
                "High-Entropy Alloys for "
                "CO<sub>2</sub> Reduction"
            ),
            doi="10.1000/preprint",
            abstract=(
                "CO2 reduction produces CO."
            ),
            journal="ChemRxiv",
            source="ChemRxiv",
        )

        formal = make_paper(
            "openalex:FORMAL",
            (
                "High Entropy Alloys for "
                "CO2 Reduction"
            ),
            doi="10.1000/formal",
            abstract="",
            journal="ACS Catalysis",
            source="OpenAlex",
        )

        result = self.merger.merge(
            local_result={
                "selected": [preprint]
            },
            online_result={
                "candidates": [formal]
            },
            question=self.question,
            task_analysis=self.task,
        )

        paper = result["selected"][0]

        self.assertEqual(
            result["unique_count"],
            1,
        )
        self.assertEqual(
            paper["doi"],
            "10.1000/formal",
        )
        self.assertEqual(
            paper["journal"],
            "ACS Catalysis",
        )
        self.assertTrue(
            paper["abstract"]
        )
        self.assertTrue(
            paper["version_info"][
                "has_preprint_version"
            ]
        )
        self.assertTrue(
            paper["version_info"][
                "has_formal_version"
            ]
        )

    def test_direct_paper_ranks_before_indirect(self):
        direct = make_paper(
            "openalex:DIRECT",
            (
                "High entropy alloy for "
                "CO2 reduction to CO"
            ),
            doi="10.1000/direct",
            abstract=(
                "This work studies CO2 reduction "
                "and selective CO production."
            ),
            journal="Example Journal",
            year=2025,
        )

        indirect = make_paper(
            "openalex:INDIRECT",
            "General alloy synthesis",
            doi="10.1000/indirect",
            abstract=(
                "This work studies metallic "
                "alloy preparation."
            ),
            journal="Example Journal",
            year=2025,
        )

        result = self.merger.merge(
            local_result={
                "selected": [indirect]
            },
            online_result={
                "candidates": [direct]
            },
            question=self.question,
            task_analysis=self.task,
            final_count=2,
        )

        self.assertEqual(
            result["selected"][0][
                "paper_id"
            ],
            "openalex:DIRECT",
        )

    def test_selected_papers_receive_evidence_ids(self):
        paper = make_paper(
            "openalex:W1",
            "CO2 reduction to CO",
            doi="10.1000/one",
            abstract=(
                "CO2 reduction produces CO."
            ),
            journal="Example Journal",
        )

        result = self.merger.merge(
            local_result={"selected": [paper]},
            online_result={"candidates": []},
            question=self.question,
            task_analysis=self.task,
        )

        selected = result["selected"][0]

        self.assertEqual(
            selected["evidence_id"],
            "E1",
        )
        self.assertEqual(
            selected["merged_rank"],
            1,
        )
        self.assertIn(
            "merged_ranking_scores",
            selected,
        )
        self.assertIn(
            "evidence_quality",
            selected,
        )

    def test_d_level_record_is_rejected(self):
        weak = make_paper(
            paper_id="",
            title="Unrelated note",
            doi="",
            abstract="",
            journal="",
            source="",
            year=None,
        )

        result = self.merger.merge(
            local_result={"selected": []},
            online_result={
                "candidates": [weak]
            },
            question=self.question,
            task_analysis=self.task,
        )

        self.assertEqual(
            result["selected_count"],
            0,
        )
        self.assertEqual(
            len(result["rejected"]),
            1,
        )
        self.assertEqual(
            result["rejected"][0][
                "evidence_quality"
            ]["quality_level"],
            "D",
        )

    def test_inputs_are_not_modified(self):
        paper = make_paper(
            "openalex:W1",
            "CO2 reduction to CO",
            doi="10.1000/one",
            abstract=(
                "CO2 reduction produces CO."
            ),
            journal="Example Journal",
        )

        local_result = {
            "selected": [paper]
        }
        original = copy.deepcopy(local_result)

        self.merger.merge(
            local_result=local_result,
            online_result={"candidates": []},
            question=self.question,
            task_analysis=self.task,
        )

        self.assertEqual(
            local_result,
            original,
        )

    def test_invalid_final_count_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "final_count",
        ):
            self.merger.merge(
                local_result={"selected": []},
                online_result={
                    "candidates": []
                },
                question=self.question,
                task_analysis=self.task,
                final_count=0,
            )

    def test_target_reaction_mismatch_is_audited_and_not_selected(self):
        oer = make_paper(
            "crossref:10.1000/oer",
            "FeCoNiCrMo high-entropy alloy for oxygen evolution reaction",
            doi="10.1000/oer",
            abstract=(
                "The FeCoNiCrMo high-entropy alloy demonstrates an OER "
                "current density of 100 mA cm-2."
            ),
            journal="Example Journal",
        )
        result = self.merger.merge(
            local_result={"selected": []},
            online_result={"candidates": [oer]},
            question=self.question,
            task_analysis=self.task,
        )

        self.assertEqual(result["selected_count"], 0)
        self.assertEqual(result["task_mismatch_rejected_count"], 1)
        self.assertEqual(
            result["task_mismatch_rejected"][0]["paper_id"],
            "crossref:10.1000/oer",
        )

    def test_missing_target_product_does_not_block_reaction_match(self):
        co2rr = make_paper(
            "crossref:10.1000/co2rr",
            "CuFeCoNiMn high-entropy alloy for CO2 reduction",
            doi="10.1000/co2rr",
            abstract=(
                "The CuFeCoNiMn high-entropy alloy demonstrates a CO2RR "
                "current density of 100 mA cm-2."
            ),
            journal="Example Journal",
        )
        result = self.merger.merge(
            local_result={"selected": []},
            online_result={"candidates": [co2rr]},
            question=self.question,
            task_analysis=self.task,
        )

        self.assertEqual(result["selected_count"], 1)
        self.assertFalse(result["target_product_required"])

    def test_four_metal_hea_is_retained_for_claim_extraction(self):
        four_metal = make_paper(
            "crossref:10.1000/four",
            "Cu-Mn-Ni-Zn high-entropy alloy for CO2 reduction",
            doi="10.1000/four",
            abstract=(
                "The Cu-Mn-Ni-Zn high-entropy alloy demonstrates CO2RR "
                "activity at 100 mA cm-2."
            ),
            journal="Example Journal",
        )
        result = self.merger.merge(
            local_result={"selected": []},
            online_result={"candidates": [four_metal]},
            question=self.question,
            task_analysis=self.task,
        )

        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(
            result["selected"][0]["evidence_quality"][
                "composition_element_count"
            ],
            4,
        )


if __name__ == "__main__":
    unittest.main()
