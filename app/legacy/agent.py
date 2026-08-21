from __future__ import annotations

from typing import Any

from app.planner import TaskPlanner
from app.task_router import TaskRouter
from tools.candidate_generator import CandidateGenerator
from tools.cgcnn_service import CGCNNService
from tools.literature_search import LiteratureSearchTool
from tools.literature_rag import LiteratureRAG
from tools.ovito_service import OvitoService
from app.legacy.postprocess_service import PostprocessService
from tools.structure_builder import StructureBuilder


class CatalystAgent:
    """Generate, predict, and visualize compatible HEA candidates."""

    def __init__(self, output_dir: str = "data/structures") -> None:
        self.planner = TaskPlanner()
        self.router = TaskRouter(llm=self.planner.llm)
        self.literature_tool = LiteratureSearchTool()
        self.literature_rag = LiteratureRAG(llm=self.planner.llm)
        self.candidate_generator = CandidateGenerator()
        self.structure_builder = StructureBuilder(output_dir=output_dir)
        self.cgcnn = CGCNNService()
        self.ovito = OvitoService()
        self.postprocess = PostprocessService()

    def run(
        self,
        question: str,
        selected_candidate: dict[str, Any] | None = None,
        build_params: dict[str, Any] | None = None,
        build_structure: bool = True,
        train_cgcnn: bool = False,
        cgcnn_epochs: int = 60,
        predict_properties: bool = True,
        candidate_count: int = 1,
        open_ovito: bool = False,
        run_postprocess: bool = True,
    ) -> dict[str, Any]:
        if not 1 <= candidate_count <= 3:
            raise ValueError("candidate_count 必须在 1 到 3 之间。")

        route = self.router.route(question)
        plan = self.planner.plan(question)
        if route["use_rag"]:
            rag_question = route.get("rag_query") or question
            rag_plan = dict(plan)
            rag_plan["keywords"] = list(dict.fromkeys([
                *plan.get("keywords", []), *route.get("rag_focus", [])
            ]))
            rag_result = self.literature_rag.run(rag_question, rag_plan)
        else:
            rag_result = {
                "evidence": [],
                "synthesis": {
                    "answer": f"入口路由决定跳过 RAG：{route['rag_reason']}",
                    "citations": [],
                    "mode": "router_skipped",
                },
            }
        papers = rag_result["evidence"]
        evidence_element_sets = [
            paper.get("elements", []) for paper in papers if paper.get("elements")
        ]
        candidates = self.candidate_generator.generate(
            top_k=max(6, candidate_count),
            evidence_element_sets=evidence_element_sets,
        )
        selected_candidates = [selected_candidate] if selected_candidate else candidates[:candidate_count]

        training_result = self.cgcnn.train(epochs=cgcnn_epochs) if train_cgcnn else None
        candidate_results: list[dict[str, Any]] = []
        all_structures: list[dict[str, Any]] = []
        property_predictions: list[dict[str, Any]] = []
        cgcnn_error = None
        ovito_result = None
        ovito_error = None
        postprocess_result = None
        postprocess_error = None

        if build_structure:
            params = {
                "num_structures": 1,
                "generation_mode": "fixed_cu",
                "seed": 42,
                "min_distance": 1.8,
            }
            params.update(build_params or {})
            structures_per_candidate = int(params.pop("structures_per_candidate", params.pop("num_structures", 1)))
            if structures_per_candidate <= 0:
                raise ValueError("每个候选的结构数量必须大于 0。")

            for candidate_index, candidate in enumerate(selected_candidates):
                start_index = 1 + candidate_index * structures_per_candidate
                candidate_params = dict(params)
                candidate_params.update(
                    {
                        "num_structures": structures_per_candidate,
                        "start_index": start_index,
                        "seed": int(params.get("seed", 42)) + candidate_index,
                        "generation_mode": candidate.get("generation_mode", "fixed_cu"),
                        "composition": candidate.get("composition"),
                    }
                )
                structure_result = self.structure_builder.generate(
                    selected_elements=candidate["elements"], **candidate_params
                )
                for structure in structure_result["results"]:
                    structure["candidate_formula"] = candidate["formula"]
                    structure["candidate_rank"] = candidate_index + 1
                    all_structures.append(structure)
                candidate_results.append(
                    {"candidate": candidate, "structure_result": structure_result}
                )

            if predict_properties and all_structures:
                try:
                    property_predictions = self.cgcnn.predict(
                        [structure["cif_path"] for structure in all_structures]
                    )
                    for structure, prediction in zip(all_structures, property_predictions):
                        structure["formation_energy_per_atom"] = prediction["formation_energy_per_atom"]
                        structure["formation_energy_unit"] = prediction["unit"]
                except (FileNotFoundError, RuntimeError) as error:
                    cgcnn_error = str(error)

            if run_postprocess and all_structures:
                try:
                    postprocess_result = self.postprocess.screen_and_cleave(
                        [structure["cif_path"] for structure in all_structures],
                        [structure["poscar_path"] for structure in all_structures],
                    )
                    screening_by_path = {
                        row["cif_path"]: row for row in postprocess_result["screening"]
                    }
                    for structure in all_structures:
                        structure["stability_screening"] = screening_by_path.get(
                            str(__import__("pathlib").Path(structure["cif_path"]).resolve())
                        )
                except (ValueError, RuntimeError, OSError) as error:
                    postprocess_error = str(error)

            if open_ovito and all_structures:
                try:
                    ovito_result = self.ovito.open_structures(
                        [structure["poscar_path"] for structure in all_structures]
                    )
                except (FileNotFoundError, OSError) as error:
                    ovito_error = str(error)

        result = {
            "route": route,
            "plan": plan,
            "papers": papers,
            "rag_answer": rag_result["synthesis"],
            "candidates": candidates,
            "selected_candidates": selected_candidates,
            "candidate_results": candidate_results,
            "structures": all_structures,
            "cgcnn_training": training_result,
            "property_predictions": property_predictions,
            "cgcnn_error": cgcnn_error,
            "ovito_result": ovito_result,
            "ovito_error": ovito_error,
            "postprocess_result": postprocess_result,
            "postprocess_error": postprocess_error,
        }
        result["text"] = self.format_result(result)
        return result

    @staticmethod
    def format_result(result: dict[str, Any]) -> str:
        plan = result["plan"]
        lines = [
            "任务分析结果：",
            f"入口决策：{'使用 RAG' if result['route']['use_rag'] else '跳过 RAG'}（{result['route']['rag_reason']}）",
            f"目标反应：{plan['reaction']}",
            f"目标产物：{plan['product']}",
            "",
            "候选高熵催化剂：",
        ]
        for index, candidate in enumerate(result["selected_candidates"], 1):
            lines.append(
                f"{index}. {candidate['formula']}，评分：{candidate['score']}，"
                f"配比：{candidate['composition']}"
            )

        structures = result.get("structures", [])
        if structures:
            lines.extend(("", f"共生成 {len(structures)} 个结构："))
            for structure in structures:
                lines.append(
                    f"- 候选 {structure['candidate_rank']} {structure['candidate_formula']} / "
                    f"{structure['formula']}"
                )
                lines.append(f"  CIF：{structure['cif_path']}")
                lines.append(f"  POSCAR：{structure['poscar_path']}")
                if "formation_energy_per_atom" in structure:
                    lines.append(
                        f"  CGCNN 预测形成能：{structure['formation_energy_per_atom']:.6f} "
                        f"{structure['formation_energy_unit']}"
                    )
                screening = structure.get("stability_screening")
                if screening:
                    lines.append(
                        f"  固溶体判据：{'通过' if screening['passed'] else '未通过'}；"
                        f"delta={screening.get('delta_percent', 0):.4f}%，"
                        f"Omega={screening.get('omega', 0):.4f}"
                    )

        postprocess = result.get("postprocess_result")
        if postprocess:
            lines.extend(("", f"通过判据：{sum(row['passed'] for row in postprocess['screening'])} / {len(postprocess['screening'])}"))
            lines.append(f"生成 (111) slab：{len(postprocess['slabs'])} 个")
            for slab in postprocess["slabs"]:
                lines.append(
                    f"- slab：{slab['atom_count']} 原子，真空层 {slab['vacuum_angstrom']:.1f} Å"
                )
                lines.append(f"  CIF：{slab['cif_path']}")
                lines.append(f"  POSCAR：{slab['poscar_path']}")

        ovito = result.get("ovito_result")
        if ovito:
            lines.extend(
                (
                    "",
                    f"OVITO 已打开 {ovito['opened_count']} 个 POSCAR。",
                    "OVITO 仅展示第一个 POSCAR，其余结构继续完成预测和后处理。" if ovito["truncated"] else "",
                )
            )
        if result.get("ovito_error"):
            lines.extend(("", f"OVITO 启动失败：{result['ovito_error']}"))
        if result.get("cgcnn_error"):
            lines.extend(("", f"CGCNN 预测失败：{result['cgcnn_error']}"))
        if result.get("postprocess_error"):
            lines.extend(("", f"稳定性筛选/切面失败：{result['postprocess_error']}"))
        return "\n".join(line for line in lines if line != "")
