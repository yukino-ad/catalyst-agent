from __future__ import annotations

import uuid
from typing import Any


STAGES: dict[str, tuple[str, int]] = {
    "created": ("任务已创建", 2),
    "task_analysis": ("A1 正在理解自然语言任务", 6),
    "external_structure_input": ("正在读取外部结构", 10),
    "capability_gate": ("A2 正在检查 Agent 能力", 10),
    "router": ("A3 正在选择工作流分支", 13),
    "planner": ("A4 正在生成任务计划", 16),
    "literature_evidence": ("B 阶段正在召回和检索文献", 28),
    "literature_assertion_extraction": ("B1 正在抽取和评分科学断言", 38),
    "literature_review": ("B6 等待文献人工审查", 43),
    "literature_commit": ("正在保存文献审查结果", 45),
    "literature_retry_prepare": ("正在准备新一轮文献检索", 25),
    "literature_review_finalize": ("正在汇总文献审查", 48),
    "reviewed_rag": ("正在生成审查后的文献摘要", 50),
    "skip_rag": ("任务无需文献检索", 50),
    "literature_summary": ("B 阶段证据汇总完成", 53),
    "c_stage_preparation": ("C1 正在准备候选约束", 56),
    "candidate_generation": ("C2-C3 正在生成和排序候选", 61),
    "candidate_review": ("C4 等待候选人工选择", 65),
    "c_stage_execution_review": ("等待选择 C 阶段执行范围", 68),
    "structure_modeling": ("C5 正在建立 FCC bulk", 72),
    "formation_energy": ("C6 正在预测形成能", 76),
    "stability_screening": ("C7 正在执行稳定性判据", 80),
    "c7_dft_upgrade_review": ("等待选择进入 DFT 的结构", 82),
    "slab_generation": ("C8 正在构建 (111) slab", 85),
    "slab_quality": ("C9 正在检查 slab 质量", 87),
    "slab_review": ("等待 slab 人工审查", 88),
    "bulk_dft_input_preview": ("正在准备 bulk VASP 输入预览", 88),
    "bulk_dft_input_review": ("等待 bulk VASP 输入审查", 90),
    "dft_input_preview": ("C10 正在准备 slab VASP 输入预览", 90),
    "dft_input_review": ("等待 slab VASP 输入审查", 92),
    "dft_execution_options": ("等待选择 DFT 执行参数", 94),
    "cluster_readonly_preflight": ("远程操作在 F2 中已禁用", 96),
    "submission_record": ("正在保存提交记录", 98),
    "completed": ("工作流已完成", 100),
    "failed": ("工作流运行失败", 100),
}


def stage_details(node: str) -> tuple[str, int]:
    clean = {
        "created": ("任务已创建，等待 Agent 运行", 2),
        "task_analysis": ("A1 正在理解自然语言任务", 6),
        "external_structure_input": ("正在读取外部结构", 10),
        "capability_gate": ("A2 正在检查 Agent 能力", 10),
        "router": ("A3 正在选择工作流分支", 13),
        "planner": ("A4 正在生成任务计划", 16),
        "literature_evidence": ("B1-B4 正在召回和检索文献", 28),
        "literature_assertion_extraction": ("B5 正在提取和评分科学断言", 38),
        "literature_review": ("B6 等待文献人工审查", 43),
        "c_stage_preparation": ("C1 正在准备候选约束", 56),
        "candidate_generation": ("C2-C3 正在生成和排序候选", 61),
        "candidate_review": ("C4 等待候选人工选择", 65),
        "structure_modeling": ("C5 正在建立 FCC bulk", 72),
        "formation_energy": ("C6 正在预测形成能", 76),
        "formation_energy_source_review": ("C6 等待选择形成能来源", 78),
        "stability_screening": ("C7 正在执行稳定性判据", 80),
        "slab_generation": ("C8 正在构建 (111) slab", 85),
        "slab_quality": ("C9 正在检查 slab 质量", 87),
        "dft_input_preview": ("C10 正在准备 slab VASP 输入", 90),
        "cluster_readonly_preflight": ("C11 正在执行集群预检查", 96),
        "submission_record": ("C11 正在保存提交记录", 98),
        "completed": ("工作流已完成", 100),
        "failed": ("工作流运行失败", 100),
    }
    return clean.get(node, STAGES.get(node, (f"正在执行 {node}", 50)))


def safe_interrupt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"type": "unknown", "message": "工作流等待人工操作。"}

    review_type = str(value.get("type", "unknown"))
    safe: dict[str, Any] = {
        "review_id": f"review-{uuid.uuid4().hex}",
        "type": review_type,
        "message": str(value.get("message", "工作流等待人工操作。")),
    }
    for field in (
        "stage_label",
        "total_candidate_count",
        "max_selected",
        "job_count",
        "confirmation_phrase",
        "requires_human_confirmation",
        "recommended_mode",
        "safety_notice",
        "submission_safety",
        "message_zh",
        "submission_safety_zh",
        "passed_count",
        "next_stage",
        "temporary_model_ready",
        "temporary_model_run_id",
    ):
        if field in value:
            safe[field] = value[field]

    for source, target in (
        ("candidates", "candidate_ids"),
        ("bundles", "bundle_ids"),
        ("jobs", "job_ids"),
        ("structures", "structure_ids"),
        ("slabs", "slab_ids"),
        ("calculations", "calculation_ids"),
    ):
        items = value.get(source, [])
        if not isinstance(items, list):
            continue
        safe[target] = [
            _identity(item)
            for item in items[:20]
            if _identity(item)
        ]
        safe[f"{source}_count"] = len(items)

    if review_type == "literature_review_required":
        safe.update({
            "title": "B6 文献与科学断言审查",
            "actions": ["accept", "reject", "defer"],
            "items": [_safe_paper(item) for item in value.get("candidates", [])[:20]],
        })
    elif review_type == "candidate_review_required":
        safe.update({
            "title": "C4 候选材料选择",
            "actions": ["select", "reject", "defer"],
            "max_selected": int(value.get("max_selected", 3)),
            "items": [_safe_candidate(item) for item in value.get("candidates", [])[:20]],
        })
    elif review_type == "c_stage_execution_review_required":
        safe.update({
            "title": "选择 C 阶段执行范围",
            "actions": ["choose_mode"],
            "items": [],
            "options": [_safe_option(item) for item in value.get("options", [])[:10]],
        })
    elif review_type == "formation_energy_source_review_required":
        structures = value.get("structures", [])
        safe.update({
            "title": "C6 形成能来源选择",
            "actions": ["choose_mode"],
            "items": [],
            "options": [_safe_option(item) for item in value.get("options", [])[:10]],
            "temporary_model_ready": bool(value.get("temporary_model_ready", False)),
            "temporary_model_run_id": str(value.get("temporary_model_run_id", ""))[:160],
            "items": [_safe_structure(item) for item in structures[:20]],
        })
    elif review_type == "dft_execution_options_required":
        choices = value.get("choices", value.get("options", []))
        if not choices:
            choices = [
                {"value": "relax_only", "label": "仅弛豫", "description": "使用弛豫 OUTCAR 最终能量。"},
                {"value": "relax_then_static", "label": "弛豫加静态单点", "description": "弛豫完成后追加静态能计算。"},
                {"value": "defer", "label": "暂不提交", "description": "保留五文件并结束当前流程。"},
            ]
        safe.update({
            "title": "C11 DFT 计算方式选择",
            "actions": ["choose_mode"],
            "items": [],
            "job_source": str(value.get("job_source", ""))[:160],
            "job_count": int(value.get("job_count", 0) or 0),
            "jobs": [_safe_job(item) for item in value.get("jobs", [])[:20]],
            "options": [
                {
                    "mode": str(item.get("value", item.get("mode", "")))[:100],
                    "label": str(item.get("label", ""))[:500],
                    "explanation": str(
                        item.get("description", item.get("explanation", ""))
                    )[:2000],
                }
                for item in choices[:10]
                if isinstance(item, dict)
            ],
            "next_stage": "C11 本地与集群只读预检查",
            "safety_notice": (
                "选择计算方式不会直接上传或提交作业；远程上传与 Slurm 提交"
                "仍需经过独立人工确认。"
            ),
        })
    elif review_type == "adsorption_dft_execution_required":
        choices = value.get("choices", [])
        safe.update({
            "title": "C12.6 吸附 DFT 执行选择",
            "actions": ["choose_mode"],
            "items": [],
            "job_count": int(value.get("job_count", 0) or 0),
            "jobs": [_safe_job(item) for item in value.get("jobs", [])[:20]],
            "options": [
                {
                    "mode": str(item.get("value", ""))[:100],
                    "label": str(item.get("label", ""))[:500],
                    "explanation": "仅执行吸附结构弛豫。" if item.get("value") == "relax_only" else "暂不提交，保留输入文件。",
                }
                for item in choices[:10] if isinstance(item, dict)
            ],
            "next_stage": "C12.6 超算上传与提交审查",
        })
    elif review_type == "adsorption_intermediate_review_required":
        candidates = [str(item)[:80] for item in value.get("candidate_adsorbates", [])[:20]]
        safe.update({
            "title": "C12.1 单一吸附中间体选择",
            "actions": ["choose_mode"],
            "items": [],
            "options": [
                {"mode": item, "label": item, "explanation": "本任务仅计算该中间体的单吸附。"}
                for item in candidates
            ],
            "next_stage": "C12.2 吸附位点与结构生成",
        })
    elif review_type == "c7_dft_upgrade_review_required":
        structures = value.get("structures", [])
        safe.update({
            "title": "选择进入 C8 与 DFT 的结构",
            "actions": ["select", "reject", "defer"],
            "max_selected": len(structures),
            "items": [_safe_structure(item) for item in structures[:20]],
        })
    elif review_type == "slab_review_required":
        slabs = value.get("slabs", [])
        safe.update({
            "title": "C9 slab 质量人工审查",
            "actions": ["approve", "reject", "defer"],
            "max_selected": int(value.get("max_approved", len(slabs)) or len(slabs)),
            "items": [_safe_slab(item) for item in slabs[:20]],
        })
    elif review_type == "adsorption_structure_review_required":
        structures = value.get("structures", [])
        safe.update({
            "title": "C12.4 吸附结构人工审查",
            "actions": ["approve", "reject", "defer"],
            "max_selected": int(value.get("maximum_approved", len(structures)) or len(structures)),
            "items": [_safe_adsorption_structure(item) for item in structures[:20]],
        })
    elif review_type in {
        "bulk_dft_input_review_required",
        "dft_input_review_required",
        "adsorption_dft_input_review_required",
    }:
        bundles = value.get("bundles", [])
        safe.update({
            "title": "C10 VASP 输入人工审查",
            "actions": ["approve", "revise", "reject", "defer"],
            "max_selected": len(bundles),
            "required_files": ["POSCAR", "INCAR", "KPOINTS", "POTCAR", "vasp.slurm"],
            "items": [_safe_bundle(item) for item in bundles[:20]],
        })
    elif review_type == "adsorption_energy_review_required":
        calculations = value.get("calculations", [])
        safe.update({
            "title": "C12.7 吸附能人工审查",
            "actions": ["approve", "reject", "defer"],
            "max_selected": len(calculations),
            "items": [_safe_calculation(item) for item in calculations[:20]],
        })
    elif review_type == "result_download_review_required":
        jobs = value.get("jobs", [])
        safe.update({
            "title": "DFT 结果下载确认",
            "actions": ["approve", "defer"],
            "max_selected": len(jobs),
            "items": [_safe_result_job(item) for item in jobs[:20]],
            "next_stage": "下载、解析结果并继续后续工作流",
            "safety_notice": "仅下载列出的只读计算结果；不会修改或删除超算文件。",
        })
    elif review_type in {
        "remote_upload_review_required",
        "remote_submission_review_required",
    }:
        jobs = value.get("jobs", [])
        upload = review_type == "remote_upload_review_required"
        safe.update({
            "title": "C11 远程上传确认" if upload else "C11 Slurm 提交确认",
            "actions": ["approve_remote", "defer"],
            "items": [_safe_remote_job(item) for item in jobs[:20]],
            "plan_digest": str(value.get("plan_digest", ""))[:128],
            "next_stage": "上传并校验远程 SHA-256" if upload else "执行 sbatch 并保存作业编号",
            "safety_notice": (
                "这是有外部副作用的操作。确认短语必须完全一致；只会处理本卡中明确勾选的作业。"
            ),
        })
    return safe


def _identity(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)[:160]
    for key in (
        "candidate_id",
        "bundle_id",
        "job_id",
        "structure_id",
        "slab_id",
        "adsorption_energy_id",
        "evidence_id",
    ):
        if item.get(key):
            return str(item[key])[:160]
    return ""


def _safe_paper(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    assertions = item.get("assertions", [])
    return {
        "evidence_id": str(item.get("evidence_id", ""))[:160],
        "title": str(item.get("title", "未提供标题"))[:1000],
        "year": item.get("year"),
        "journal": str(item.get("journal", ""))[:500],
        "doi": str(item.get("doi", ""))[:500],
        "url": str(item.get("url", ""))[:1000],
        "abstract": str(item.get("abstract", ""))[:6000],
        "source": str(item.get("source", ""))[:200],
        "quality_level": str(item.get("quality_level", "D"))[:10],
        "quality_score": item.get("quality_score", 0),
        "composition_elements": item.get("composition_elements", []),
        "assertions": [
            {
                "assertion_id": str(assertion.get("assertion_id", ""))[:200],
                "kind": str(assertion.get("kind", ""))[:200],
                "value": assertion.get("value"),
                "evidence": [
                    {"quote": str(evidence.get("quote", ""))[:2000]}
                    for evidence in assertion.get("evidence", [])[:5]
                    if isinstance(evidence, dict)
                ],
            }
            for assertion in assertions[:20]
            if isinstance(assertion, dict) and assertion.get("assertion_id")
        ],
    }


def _safe_candidate(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "candidate_id": str(item.get("candidate_id", ""))[:160],
        "rank": item.get("rank"),
        "elements": item.get("elements", []),
        "composition": item.get("composition", {}),
        "total_score": item.get("total_score", 0),
        "scores": item.get("scores", {}),
        "highest_risk_elements": item.get("highest_risk_elements", []),
    }


def _safe_option(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "mode": str(item.get("mode", ""))[:100],
        "label": str(item.get("label", ""))[:500],
        "label_zh": str(item.get("label_zh", ""))[:500],
        "explanation": str(item.get("explanation", ""))[:2000],
        "explanation_zh": str(item.get("explanation_zh", ""))[:2000],
        "runs": item.get("runs", []),
        "disabled": bool(item.get("disabled", False)),
    }


def _safe_structure(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "structure_id": str(item.get("structure_id", ""))[:160],
        "candidate_id": str(item.get("candidate_id", ""))[:160],
        "composition": item.get("composition", {}),
        "formation_energy_ev_per_atom": item.get("formation_energy_ev_per_atom"),
        "pretrained_formation_energy_ev_per_atom": item.get("pretrained_formation_energy_ev_per_atom"),
        "temporary_formation_energy_ev_per_atom": item.get("temporary_formation_energy_ev_per_atom"),
        "prediction_difference_ev_per_atom": item.get("prediction_difference_ev_per_atom"),
        "formation_energy_unit": str(item.get("formation_energy_unit", "eV/atom"))[:30],
        "delta_percent": item.get("delta_percent"),
        "omega": item.get("omega"),
    }


def _safe_adsorption_structure(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    identifier = str(item.get("adsorption_structure_id", ""))[:160]
    return {
        "adsorption_structure_id": identifier,
        "structure_id": identifier,
        "structure_available": bool(identifier),
        "slab_id": str(item.get("slab_id", ""))[:160],
        "adsorbate": str(item.get("adsorbate", ""))[:80],
        "site_id": str(item.get("site_id", ""))[:160],
        "site_type": str(item.get("site_type", ""))[:80],
        "minimum_adsorbate_slab_distance_angstrom": item.get("minimum_adsorbate_slab_distance_angstrom"),
        "remaining_top_vacuum_angstrom": item.get("remaining_top_vacuum_angstrom"),
        "failed_checks": item.get("failed_checks", []),
    }


def _safe_result_job(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "slurm_job_id": str(item.get("slurm_job_id", ""))[:80],
        "job_id": str(item.get("job_id", ""))[:160],
        "scheduler_state": str(item.get("scheduler_state", ""))[:80],
        "vasp_decision": str(item.get("vasp_decision", ""))[:100],
        "remote_job_directory": str(item.get("remote_job_directory", ""))[:1000],
    }


def _safe_job(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "job_id": str(item.get("job_id", ""))[:160],
        "structure_id": str(item.get("structure_id", ""))[:160],
        "slab_id": str(item.get("slab_id", ""))[:160],
        "element_order": item.get("element_order", []),
    }


def _safe_slab(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "slab_id": str(item.get("slab_id", ""))[:160],
        "structure_id": str(item.get("slab_id", ""))[:160],
        "structure_available": bool(item.get("slab_id")),
        "candidate_id": str(item.get("candidate_id", ""))[:160],
        "atom_count": item.get("atom_count"),
        "element_count": item.get("element_count"),
        "minimum_distance_angstrom": item.get("minimum_distance_angstrom"),
        "measured_vacuum_angstrom": item.get("measured_vacuum_angstrom"),
        "fixed_atom_count": item.get("fixed_atom_count"),
        "movable_atom_count": item.get("movable_atom_count"),
        "failed_checks": item.get("failed_checks", []),
    }


def _safe_bundle(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    preview = item.get("preview", {})
    if not isinstance(preview, dict):
        preview = {}
    potcar = preview.get("POTCAR", [])
    slurm = preview.get("vasp.slurm", {})
    if not isinstance(potcar, list):
        potcar = []
    if not isinstance(slurm, dict):
        slurm = {}
    return {
        "bundle_id": str(item.get("bundle_id", ""))[:160],
        "calculation_type": str(item.get("calculation_type", ""))[:160],
        "candidate_id": str(item.get("candidate_id", ""))[:160],
        "structure_id": str(item.get("structure_id", ""))[:160],
        "slab_id": str(item.get("slab_id", ""))[:160],
        "elements": item.get("elements", []),
        "atom_count": item.get("atom_count"),
        "preview_digest": str(item.get("preview_digest", ""))[:128],
        "formal_files_written": bool(item.get("formal_files_written", False)),
        "file_previews": {
            "POSCAR": str(preview.get("POSCAR", ""))[:50000],
            "INCAR": str(preview.get("INCAR", ""))[:20000],
            "KPOINTS": str(preview.get("KPOINTS", ""))[:10000],
            "POTCAR": [
                {
                    "element": str(entry.get("element", ""))[:20],
                    "potential": str(entry.get("potential", ""))[:100],
                }
                for entry in potcar[:20]
                if isinstance(entry, dict)
            ],
            "vasp.slurm": {
                key: slurm.get(key)
                for key in (
                    "job_name",
                    "nodes",
                    "tasks_per_node",
                    "partition",
                    "module_name",
                    "command",
                )
                if slurm.get(key) not in (None, "")
            },
        },
    }


def _safe_calculation(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    calculation = item.get("calculation", {})
    if not isinstance(calculation, dict):
        calculation = {}
    return {
        "adsorption_energy_id": str(item.get("adsorption_energy_id", ""))[:160],
        "adsorption_structure_id": str(item.get("adsorption_structure_id", ""))[:160],
        "candidate_id": str(item.get("candidate_id", ""))[:160],
        "source_clean_slab_id": str(item.get("source_clean_slab_id", ""))[:160],
        "site_type": str(item.get("site_type", ""))[:80],
        "adsorbate": str(item.get("adsorbate", ""))[:80],
        "adsorbed_energy_ev": calculation.get("adsorbed_energy_ev"),
        "clean_slab_energy_ev": calculation.get("clean_slab_energy_ev"),
        "reference_energy_ev": calculation.get("reference_energy_ev"),
        "operation": str(calculation.get("operation", ""))[:160],
        "substitution": str(calculation.get("substitution", ""))[:500],
        "adsorption_energy_ev": item.get("adsorption_energy_ev", calculation.get("adsorption_energy_ev")),
        "energy_unit": str(item.get("energy_unit", "eV"))[:20],
    }


def _safe_remote_job(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    files = item.get("files", [])
    return {
        "job_id": str(item.get("job_id", ""))[:160],
        "remote_job_directory": str(item.get("remote_job_directory", ""))[:1000],
        "remote_hash_verified": bool(item.get("remote_hash_verified", False)),
        "slurm_script": str(item.get("slurm_script", ""))[:100],
        "files": [
            {
                "name": str(entry.get("name", ""))[:100],
                "size_bytes": entry.get("size_bytes"),
                "sha256": str(entry.get("sha256", ""))[:128],
            }
            for entry in files[:10]
            if isinstance(entry, dict)
        ],
    }
