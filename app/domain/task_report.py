from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.api.job_monitor import JobMonitorFacade
from app.api.research_assets import ResearchAssetService
from app.domain.workflow_run_repository import WorkflowRunRepository
from tools.llm_client import LLMError, OpenAICompatibleClient


class TaskReportService:
    """Build a provenance-first report from persisted task-owned records."""

    def __init__(
        self,
        repository: WorkflowRunRepository | None = None,
        assets: ResearchAssetService | None = None,
        jobs: JobMonitorFacade | None = None,
        llm: OpenAICompatibleClient | None = None,
        root: str | Path = "data/reports",
    ) -> None:
        self.repository = repository or WorkflowRunRepository()
        self.assets = assets or ResearchAssetService(runs=self.repository)
        self.jobs = jobs or JobMonitorFacade()
        self.llm = llm or OpenAICompatibleClient()
        self.root = Path(root)

    def generate(self, task_id: str) -> dict[str, Any]:
        task = self.repository.get(task_id)
        if task is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        report = self._build(task)
        directory = self.root / task_id
        directory.mkdir(parents=True, exist_ok=True)
        report["structure_images"] = self._render_structure_images(
            task_id, report["structures"], directory
        )
        report["kimi_recommendations"] = self._kimi_recommendations(report)
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        markdown = self._markdown(report)
        (directory / "report.md").write_text(markdown, encoding="utf-8")
        (directory / "report.html").write_text(
            self._html(report, markdown), encoding="utf-8"
        )
        metadata = self.metadata(task_id)
        self.repository.update(task_id, {"latest_report": metadata})
        return metadata

    def metadata(self, task_id: str) -> dict[str, Any]:
        directory = self.root / task_id
        path = directory / "report.json"
        if not path.is_file():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return {
            "task_id": task_id,
            "generated_at": value.get("generated_at", ""),
            "status": "ready",
            "formats": ["html", "md", "json"],
        }

    def path(self, task_id: str, report_format: str) -> Path:
        if report_format not in {"html", "md", "json"}:
            raise ValueError("Report format must be html, md, or json.")
        path = self.root / task_id / f"report.{report_format}"
        if not path.is_file():
            raise FileNotFoundError("Task report has not been generated.")
        return path

    def _build(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("task_id", ""))
        timeline = [
            {
                "stage_id": item.get("stage_id"),
                "stage_label": item.get("stage_label", item.get("label", "")),
                "status": item.get("status"),
                "summary": item.get("summary", ""),
                "outputs": item.get("outputs", {}),
                "requires_human_action": bool(item.get("requires_human_action", False)),
            }
            for item in task.get("workflow_timeline", [])
            if isinstance(item, dict)
        ]
        try:
            files = self.assets.list_files(task_id)
        except (FileNotFoundError, OSError, ValueError):
            files = []
        try:
            structures = self.assets.list_structures(task_id)
        except (FileNotFoundError, OSError, ValueError):
            structures = []
        try:
            jobs = self.jobs.list_for_task(task_id)
        except (OSError, ValueError, RuntimeError):
            jobs = []
        return {
            "schema_version": "task-report-v1",
            "task_id": task_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "task": {
                "question": task.get("question", ""),
                "workflow_status": task.get("workflow_status", "unknown"),
                "current_stage": task.get("stage", ""),
                "message": task.get("message", ""),
                "warning_count": task.get("warning_count", 0),
                "error_count": task.get("error_count", 0),
            },
            "workflow": timeline,
            "human_reviews": self._safe_value(task.get("review_history", [])),
            "consultations": self._safe_value(task.get("consultation_history", [])),
            "structures": structures,
            "files": [
                {
                    key: item.get(key)
                    for key in ("file_id", "name", "label", "category", "size_bytes")
                }
                for item in files
            ],
            "dft_jobs": jobs,
            "scientific_results": self._safe_value({
                key: task.get(key)
                for key in (
                    "formation_energy_structures",
                    "selected_formation_energy_structures",
                    "stability_screened_structures",
                    "adsorption_source_slabs",
                    "selected_adsorbate",
                    "adsorption_parsed_results",
                    "adsorption_energy_calculation",
                    "adsorption_energy_review",
                )
                if task.get(key) not in (None, "", [], {})
            }),
            "scientific_formulas": {
                "formation_energy": (
                    "E_form = (E_alloy - sum_i n_i * mu_i) / sum_i n_i"
                ),
                "adsorption_energy": (
                    "E_ads = E_slab+adsorbate - E_clean_slab - E_reference"
                ),
                "interpretation": (
                    "CGCNN and delta/Omega are prescreening evidence; a negative adsorption "
                    "energy alone does not establish catalytic activity."
                ),
            },
            "recommendations": [
                "将人工确认且来源一致的形成能加入独立形成能数据集。",
                "将吸附能、吸附物、位点、clean slab 与参考能版本作为一条完整记录保存。",
                "比较不同位点和关键反应中间体，而不是仅凭单个负吸附能判断活性。",
                "对候选进行收敛性、表面构型和实验可合成性复核。",
            ],
            "limitations": [
                "报告仅汇总已持久化记录，不补造缺失结构、能量或收敛结果。",
                "FCC 是起始建模假设，不是实验相结构证明。",
                "模型预测、经验判据和 DFT 结果具有不同证据等级。",
            ],
        }

    @classmethod
    def _safe_value(cls, value: Any, key: str = "") -> Any:
        normalized = key.lower()
        if any(term in normalized for term in (
            "api_key", "secret", "password", "private_key", "ssh_key",
            "token", "potcar_content", "full_text",
        )):
            return "[redacted]"
        if normalized.endswith("_path") or normalized in {
            "path", "record_path", "source_path", "local_result_directory",
            "remote_job_directory",
        }:
            return "[task-owned path hidden]"
        if isinstance(value, dict):
            return {
                str(child_key): cls._safe_value(child, str(child_key))
                for child_key, child in value.items()
            }
        if isinstance(value, list):
            return [cls._safe_value(child, key) for child in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _kimi_recommendations(self, report: dict[str, Any]) -> dict[str, Any]:
        fallback = {
            "source": "local_rules",
            "content": (
                "建议先复核收敛性和能量参考的一致性，再扩展位点与中间体覆盖；"
                "经人工确认的数据应按形成能和吸附能两个独立数据集保存。"
            ),
        }
        if not self.llm.available:
            return fallback
        context = {
            "task": report.get("task", {}),
            "workflow": report.get("workflow", []),
            "dft_jobs": report.get("dft_jobs", []),
            "scientific_formulas": report.get("scientific_formulas", {}),
        }
        try:
            answer = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a senior high-entropy electrocatalysis researcher. Give "
                            "actionable next-study recommendations using only the supplied task "
                            "facts. Clearly label inference and suggestion. Never invent energy, "
                            "structure, convergence, activity, DOI, or experimental validation. "
                            "Keep formation-energy and adsorption-energy datasets separate."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(context, ensure_ascii=False),
                    },
                ],
                max_tokens=1400,
                timeout_seconds=90,
            )
            return {"source": "kimi", "content": answer}
        except LLMError as error:
            return {
                **fallback,
                "source": "local_fallback",
                "error": str(error)[:300],
            }

    def _render_structure_images(
        self,
        task_id: str,
        structures: list[dict[str, Any]],
        directory: Path,
    ) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        image_root = directory / "images"
        try:
            from ase import Atoms
            from ase.visualize.plot import plot_atoms
            from matplotlib import pyplot as plt
        except ImportError:
            return images
        for index, item in enumerate(structures[:20]):
            structure_id = str(item.get("structure_id", ""))
            if not structure_id:
                continue
            try:
                value = self.assets.structure(task_id, structure_id)
                atoms = Atoms(
                    symbols=[atom["element"] for atom in value["atoms"]],
                    positions=[atom["position"] for atom in value["atoms"]],
                    cell=value["lattice"],
                    pbc=True,
                )
                image_root.mkdir(parents=True, exist_ok=True)
                filename = f"structure-{index + 1:02d}-{structure_id}.png"
                path = image_root / filename
                figure, axis = plt.subplots(figsize=(7.2, 5.2), dpi=140)
                axis.set_facecolor("#f5f7fa")
                plot_atoms(atoms, axis, rotation=("10x,20y,0z"), show_unit_cell=2)
                axis.set_axis_off()
                figure.tight_layout()
                figure.savefig(path, bbox_inches="tight", facecolor="#f5f7fa")
                plt.close(figure)
                images.append({
                    "structure_id": structure_id,
                    "label": item.get("label", item.get("name", "")),
                    "structure_state": (
                        "relaxed" if str(item.get("name", "")).upper() == "CONTCAR"
                        else "initial"
                    ),
                    "relative_path": f"images/{filename}",
                })
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                continue
        return images

    @staticmethod
    def _markdown(report: dict[str, Any]) -> str:
        task = report["task"]
        lines = [
            f"# Catalyst Agent 任务报告：{report['task_id']}",
            "",
            f"生成时间：{report['generated_at']}",
            "",
            "## 1. 任务概览",
            "",
            f"- 原始任务：{task.get('question') or '未记录'}",
            f"- 状态：{task.get('workflow_status') or 'unknown'}",
            f"- 当前阶段：{task.get('current_stage') or '未记录'}",
            f"- 说明：{task.get('message') or '无'}",
            "",
            "## 2. 工作流记录",
            "",
        ]
        for stage in report["workflow"]:
            lines.append(
                f"- **{stage['stage_id']} {stage['stage_label']}** | "
                f"{stage['status']} | {stage['summary'] or '无摘要'}"
            )
            outputs = stage.get("outputs") or {}
            if outputs:
                lines.append(
                    f"  - 输出：`{json.dumps(outputs, ensure_ascii=False)}`"
                )
        lines += [
            "",
            "## 3. 结构与文件",
            "",
            f"- 结构数量：{len(report['structures'])}",
            f"- 可追溯文件数量：{len(report['files'])}",
        ]
        for item in report["structures"]:
            lines.append(f"- {item.get('category', '结构')}：{item.get('label', item.get('name'))}")
        lines += ["", "## 4. DFT 作业与解析", ""]
        if report["dft_jobs"]:
            for job in report["dft_jobs"]:
                lines.append(
                    f"- Slurm {job.get('slurm_job_id')} | {job.get('scheduler_state')} | "
                    f"TOTEN={job.get('final_toten_ev', '未获得')} eV | "
                    f"max force={job.get('max_force_ev_ang', '未获得')} eV/Ang"
                )
        else:
            lines.append("- 未获得 task_id 关联的 DFT 作业记录。")
        lines += [
            "",
            "## 5. 科学公式",
            "",
            f"- 形成能：`{report['scientific_formulas']['formation_energy']}`",
            f"- 吸附能：`{report['scientific_formulas']['adsorption_energy']}`",
            f"- 解释边界：{report['scientific_formulas']['interpretation']}",
            "",
            "### 已持久化科学结果",
            "",
            (
                f"`{json.dumps(report['scientific_results'], ensure_ascii=False)}`"
                if report["scientific_results"]
                else "未获得额外的形成能、稳定性或吸附能持久化结果。"
            ),
            "",
            "## 6. 后续科研建议",
            "",
            *[f"- {item}" for item in report["recommendations"]],
            "",
            "### Kimi 科研建议",
            "",
            f"来源：{report['kimi_recommendations']['source']}",
            "",
            report["kimi_recommendations"]["content"],
            "",
            "## 7. 局限与证据边界",
            "",
            *[f"- {item}" for item in report["limitations"]],
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _html(report: dict[str, Any], markdown: str) -> str:
        body = html.escape(markdown)
        images = "".join(
            f'<figure><img src="{html.escape(item["relative_path"])}" alt="{html.escape(str(item["label"]))}"><figcaption>{html.escape(str(item["label"]))} · {html.escape(item["structure_state"])}</figcaption></figure>'
            for item in report.get("structure_images", [])
        )
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Catalyst Agent 报告 {html.escape(report['task_id'])}</title>
<style>body{{font-family:'Microsoft YaHei',sans-serif;max-width:1000px;margin:40px auto;padding:0 24px;color:#172033}}pre{{white-space:pre-wrap;line-height:1.75}}h1{{font-family:KaiTi,serif}}figure{{margin:24px 0;border:1px solid #dbe2ea;padding:12px}}img{{display:block;max-width:100%;margin:auto}}figcaption{{margin-top:8px;color:#607087;font-size:13px}}</style>
</head><body><pre>{body}</pre><h2>结构静态预览</h2>{images or '<p>未获得可渲染的任务结构。</p>'}</body></html>"""
