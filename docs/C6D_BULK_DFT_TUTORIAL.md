# C6D：Bulk DFT 输入包教程

## 0. C6D 的作用和边界

C6 已经把超出 CGCNN 数据域的 bulk 结构放入
`dft_formation_energy_queue`。C6D 负责把这些 32 原子 FCC bulk 结构转换为
可提交 VASP 的五文件计算包：

```text
POSCAR + INCAR + KPOINTS + POTCAR + vasp.slurm
```

C6D 包含与 C10 相同的三层保护：

```text
完整预览 -> 人工确认或自然语言修订 -> 再次完整预览 -> 正式落盘
```

本阶段不连接超算、不提交任务、不生成虚假的 DFT 形成能。C6D 完成后，
含 DFT 待算结构的任务停止在“输入包准备完成”；后续 C11-C16 得到真实形成能并
回写 `formation_energy_structures` 后，才进入 C7。

参考脚本只用于 bulk INCAR、KPOINTS 和 Slurm 参数。C5 已生成的 POSCAR 必须
逐字节保留，C6D 不执行参考脚本中的原子重新排序，也不修改任何坐标。

## 1. 确认环境和文件

在 PowerShell 中执行：

```powershell
cd "C:\Users\chenheli\Documents\agent开发\catalyst-agent"

Test-Path ".\app\domain\dft_input_bundle.py"
Test-Path ".\app\domain\dft_input_revision.py"
Test-Path ".\database\PBE"
Test-Path "C:\Users\chenheli\Desktop\学习专用\GitHubCGCNN\cgcnn-master\cgcnn-master\Cu-HEA-bulk-2-10500\DFT-Formation-400\generate_vasp_formation_400.py"
```

四项必须都是 `True`。不要复制或改写 `database\PBE` 中的 POTCAR。

## 2. 新建 bulk 专用配置

新建 `configs/dft/vasp_bulk_formation_v1.json`，完整内容如下：

```json
{
  "schema_version": "vasp-bulk-formation-v1",
  "calculation_type": "bulk_formation_relax",
  "incar": {
    "LWAVE": "F",
    "LCHARG": "F",
    "ENCUT": 400,
    "ALGO": "Fast",
    "NELM": 200,
    "NELMDL": -4,
    "NELMIN": 6,
    "EDIFF": "1.0E-5",
    "LREAL": "Auto",
    "NSW": 800,
    "EDIFFG": -0.03,
    "IBRION": 2,
    "ISIF": 2,
    "ISMEAR": 1,
    "SIGMA": 0.02,
    "LORBIT": 11,
    "ENAUG": 800.0,
    "NCORE": 4
  },
  "kpoints": [
    "Automatic Mesh",
    "0",
    "Gamma",
    "1  1  1",
    "0  0  0"
  ],
  "magnetic_elements": ["Fe", "Co", "Ni", "Mn"],
  "magmom_per_atom": 0.5,
  "potcar_mapping": {
    "Al": "Al",
    "Co": "Co_pv",
    "Cr": "Cr_pv",
    "Cu": "Cu_pv",
    "Fe": "Fe_pv",
    "Ga": "Ga_d",
    "Ge": "Ge_d",
    "Mn": "Mn_pv",
    "Mo": "Mo_pv",
    "Ni": "Ni_pv",
    "Ti": "Ti_pv",
    "Zn": "Zn",
    "Ag": "Ag",
    "Pd": "Pd",
    "Pt": "Pt",
    "Au": "Au"
  },
  "slurm": {
    "nodes": 1,
    "tasks_per_node": 32,
    "partition": "xahcnormal",
    "environment_script": "/work/home/chenheli/apprepo/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc/scripts/env.sh",
    "command": "srun --mpi=pmi2 vasp_std"
  }
}
```

说明：参考脚本把 Co 映射为 `Co`，而当前 C10 和现有 PBE 约定使用 `Co_pv`。
这里保持全项目 POTCAR 口径一致，采用 `Co_pv`。以后计算单质参考能时也必须使用
同一 POTCAR 映射，否则 DFT 形成能没有可比性。

检查 JSON：

```powershell
python -m json.tool ".\configs\dft\vasp_bulk_formation_v1.json" > $null
```

没有报错即通过。

## 3. 添加 bulk 五文件领域服务

新建 `app/domain/bulk_dft_input_bundle.py`：

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.dft_input_bundle import VaspInputBundleService


class BulkFormationVaspBundleService(VaspInputBundleService):
    """Preview and finalize 32-atom bulk formation-energy jobs."""

    MAX_STRUCTURES = 3

    def __init__(
        self,
        output_root: str | Path = "data/dft_formation_inputs",
        config_path: str | Path = "configs/dft/vasp_bulk_formation_v1.json",
        pbe_root: str | Path = "database/PBE",
    ) -> None:
        super().__init__(output_root, config_path, pbe_root)

    def preview(
        self,
        dft_queue: list[dict[str, Any]],
        task_id: str,
    ) -> dict[str, Any]:
        if not isinstance(dft_queue, list):
            raise TypeError("dft_queue must be a list")
        if len(dft_queue) > self.MAX_STRUCTURES:
            raise ValueError("C6D can process at most 3 bulk structures")
        if not dft_queue:
            return {
                "schema_version": "c6d.0",
                "stage": "c6d_preview",
                "status": "bulk_dft_input_preview_skipped",
                "bundle_count": 0,
                "bundles": [],
            }

        clean_task_id = self._safe_id(task_id)
        config = self._load_config()
        bundles = [
            self._preview_one(item, clean_task_id, config)
            for item in dft_queue
        ]
        return {
            "schema_version": "c6d.0",
            "stage": "c6d_preview",
            "status": "bulk_dft_input_preview_completed",
            "task_id": clean_task_id,
            "bundle_count": len(bundles),
            "bundles": bundles,
            "formal_files_written": False,
            "requires_human_confirmation": True,
            "next_stage": "c6d_review",
        }

    def _preview_one(
        self,
        record: dict[str, Any],
        task_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_record(record)
        structure_id = str(record["structure_id"]).strip()
        bundle_id = self._safe_id(f"{structure_id}_bulk_formation")
        source = Path(str(record["poscar_path"])).resolve()
        poscar_text = source.read_text(encoding="utf-8")
        elements, counts = self._poscar_species(poscar_text)

        if len(elements) != 5:
            raise ValueError("C6D expects exactly five elements")
        if sum(counts) != 32:
            raise ValueError("C6D expects exactly 32 atoms")

        incar_text = self._build_bulk_incar(
            system_name=bundle_id,
            elements=elements,
            atom_count=sum(counts),
            config=config,
        )
        kpoints_text = "\n".join(config["kpoints"]) + "\n"
        slurm_text = self._build_slurm(bundle_id, config)
        potcar_plan = self._potcar_plan(elements, config)
        digest = self._preview_digest(
            poscar_text,
            incar_text,
            kpoints_text,
            slurm_text,
            potcar_plan,
        )

        return {
            "schema_version": "c6d.0",
            "calculation_type": "bulk_formation_relax",
            "bundle_id": bundle_id,
            "task_id": task_id,
            "structure_id": structure_id,
            "candidate_id": record.get("candidate_id"),
            "source_poscar_path": str(source),
            "elements": elements,
            "counts": counts,
            "atom_count": sum(counts),
            "preview": {
                "POSCAR": poscar_text,
                "INCAR": incar_text,
                "KPOINTS": kpoints_text,
                "POTCAR": potcar_plan,
                "vasp.slurm": {
                    "job_name": bundle_id,
                    "nodes": config["slurm"]["nodes"],
                    "tasks_per_node": config["slurm"]["tasks_per_node"],
                    "partition": config["slurm"]["partition"],
                    "environment_script": config["slurm"]["environment_script"],
                    "command": config["slurm"]["command"],
                    "full_text": slurm_text,
                },
            },
            "preview_digest": digest,
            "preview_version": 1,
            "formal_files_written": False,
            "requires_human_confirmation": True,
            "poscar_immutable": True,
        }

    def _finalize_one(self, bundle: dict[str, Any]) -> dict[str, Any]:
        # Reuse C10 atomic writing while translating slab identity to bulk identity.
        compatible = dict(bundle)
        compatible["slab_id"] = bundle["structure_id"]
        result = super()._finalize_one(compatible)
        result.pop("slab_id", None)
        result.update({
            "schema_version": "c6d.0",
            "calculation_type": "bulk_formation_relax",
            "structure_id": bundle["structure_id"],
            "status": "bulk_dft_input_files_created",
        })
        return result

    @staticmethod
    def _build_bulk_incar(
        system_name: str,
        elements: list[str],
        atom_count: int,
        config: dict[str, Any],
    ) -> str:
        lines = [f"SYSTEM = {system_name}", ""]
        lines.extend(
            f"{key:<8}= {value}"
            for key, value in config["incar"].items()
        )
        magnetic = set(config["magnetic_elements"])
        if magnetic.intersection(elements):
            lines.extend([
                "",
                "ISPIN   = 2",
                f"MAGMOM  = {atom_count}*{config['magmom_per_atom']}",
            ])
        else:
            lines.extend(["", "ISPIN   = 1"])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _validate_record(record: dict[str, Any]) -> None:
        if not isinstance(record, dict):
            raise TypeError("Every C6D queue item must be a dictionary")
        if record.get("job_type") != "formation_energy_dft":
            raise ValueError("C6D only accepts formation_energy_dft records")
        if record.get("status") != "waiting_for_supercomputer":
            raise ValueError("C6D record is not waiting for supercomputer")
        if not str(record.get("structure_id", "")).strip():
            raise ValueError("structure_id is required")
        source = Path(str(record.get("poscar_path", "")))
        if not source.is_file():
            raise FileNotFoundError(f"Bulk POSCAR does not exist: {source}")
```

注意：POSCAR 仅调用 `read_text()`，不会调用 ASE/pymatgen 重写结构。

## 4. 添加 C6D 修订服务

新建 `app/domain/bulk_dft_input_revision.py`：

```python
from __future__ import annotations

from typing import Any

from app.domain.dft_input_revision import DFTInputRevisionService


class BulkDFTInputRevisionService(DFTInputRevisionService):
    """C6D facade over the validated C10 revision engine."""

    def parse_requests(
        self,
        revision_requests: dict[str, str],
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        result = super().parse_requests(revision_requests, preview)
        result.update({
            "schema_version": "c6d-revision-v1",
            "status": "bulk_dft_revision_plan_ready",
        })
        return result

    def apply(
        self,
        preview: dict[str, Any],
        plan: dict[str, Any],
        revision_count: int = 0,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result = super().apply(
            preview, plan, revision_count, history
        )
        result["preview"]["schema_version"] = "c6d.1"
        result["validation"].update({
            "schema_version": "c6d-revision-v1",
            "status": "bulk_dft_revision_accepted",
        })
        return result
```

该服务继承 C10 的白名单、安全字符、POTCAR 存在性、摘要哈希和 POSCAR 不可变
检查。最多允许五轮修订。

## 5. 注册服务

打开 `app/graph/services.py`，在 import 区加入：

```python
from app.domain.bulk_dft_input_bundle import BulkFormationVaspBundleService
from app.domain.bulk_dft_input_revision import BulkDFTInputRevisionService
```

在 `GraphServices` 最后加入：

```python
bulk_dft_input_bundle_service: BulkFormationVaspBundleService
bulk_dft_input_revision_service: BulkDFTInputRevisionService
```

在 `create_services()` 中，紧邻 `vasp_service = VaspInputBundleService()` 加入：

```python
bulk_vasp_service = BulkFormationVaspBundleService()
```

在 `return GraphServices(...)` 中加入：

```python
bulk_dft_input_bundle_service=bulk_vasp_service,
bulk_dft_input_revision_service=BulkDFTInputRevisionService(
    bundle_service=bulk_vasp_service,
    llm=planner.llm,
),
```

## 6. 扩展 LangGraph State

打开 `app/graph/state.py`，放在 `dft_formation_energy_queue` 后面：

```python
    # C6D bulk formation-energy VASP preview and review.
    bulk_dft_input_preview: dict[str, Any]
    bulk_dft_input_review: dict[str, Any]
    bulk_dft_revision_request: dict[str, str]
    bulk_dft_revision_plan: dict[str, Any]
    bulk_dft_revision_validation: dict[str, Any]
    bulk_dft_revision_history: list[dict[str, Any]]
    bulk_dft_revision_count: int
    bulk_dft_input_preparation: dict[str, Any]
    bulk_dft_jobs: list[dict[str, Any]]
```

这些字段必须与 C10 字段分开，防止 bulk 和 slab 的预览或版本历史相互覆盖。

## 7. 添加路由函数

打开 `app/graph/routes.py`，加入：

```python
def route_after_formation_energy(
    state: CatalystState,
) -> Literal["bulk_dft", "stability"]:
    if state.get("dft_formation_energy_queue"):
        return "bulk_dft"
    return "stability"


def route_after_bulk_dft_review(
    state: CatalystState,
) -> Literal["revise", "finalize"]:
    review = state.get("bulk_dft_input_review", {})
    if review.get("action") == "revise":
        return "revise"
    return "finalize"
```

这采用保守策略：只要有一个候选等待真实 DFT，整批任务先完成 C6D 并暂停，不让
CGCNN 候选独自越过 C7。后续如果需要并行候选分支，再改成 `Send` fan-out。

## 8. 添加五个 C6D 节点

打开 `app/graph/nodes.py`，在 `formation_energy_node` 后加入：

```python
def bulk_dft_input_preview_node(state: CatalystState) -> dict[str, Any]:
    try:
        result = services.bulk_dft_input_bundle_service.preview(
            state.get("dft_formation_energy_queue", []),
            str(state.get("task_id", "")),
        )
        return {
            "bulk_dft_input_preview": result,
            "status": result["status"],
        }
    except Exception as error:
        return {
            "bulk_dft_input_preview": {
                "schema_version": "c6d.0",
                "status": "bulk_dft_input_preview_failed",
                "bundles": [],
                "reason": str(error),
            },
            "status": "bulk_dft_input_preview_failed",
            "errors": _append_error(state, "bulk_dft_input_preview", error),
        }


def bulk_dft_input_review_node(state: CatalystState) -> dict[str, Any]:
    preview = state.get("bulk_dft_input_preview", {})
    bundles = preview.get("bundles", [])
    if not bundles:
        return {
            "bulk_dft_input_review": {
                "action": "finalize",
                "approve": [],
                "reject": [],
                "defer": [],
                "file_confirmations": {},
            },
            "status": "bulk_dft_input_review_skipped",
        }

    decision = interrupt({
        "type": "bulk_dft_input_review_required",
        "stage_label": "C6D",
        "message": "请逐项审查 bulk 形成能的五个 VASP 文件。",
        "bundles": bundles,
        "revision_count": state.get("bulk_dft_revision_count", 0),
        "revision_validation": state.get(
            "bulk_dft_revision_validation", {}
        ),
    })
    return {
        "bulk_dft_input_review": decision,
        "bulk_dft_revision_request": decision.get(
            "revision_requests", {}
        ),
        "status": "bulk_dft_input_review_completed",
    }


def bulk_dft_revision_plan_node(state: CatalystState) -> dict[str, Any]:
    try:
        result = services.bulk_dft_input_revision_service.parse_requests(
            state.get("bulk_dft_revision_request", {}),
            state.get("bulk_dft_input_preview", {}),
        )
        return {
            "bulk_dft_revision_plan": result,
            "bulk_dft_revision_validation": {},
            "status": "bulk_dft_revision_plan_ready",
        }
    except Exception as error:
        return {
            "bulk_dft_revision_plan": {},
            "bulk_dft_revision_validation": {
                "status": "bulk_dft_revision_rejected",
                "reason": str(error),
                "poscar_unchanged": True,
            },
            "status": "bulk_dft_revision_rejected",
            "errors": _append_error(state, "bulk_dft_revision_plan", error),
        }


def bulk_dft_revision_apply_node(state: CatalystState) -> dict[str, Any]:
    plan = state.get("bulk_dft_revision_plan", {})
    if not plan:
        return {"status": "bulk_dft_revision_rejected"}
    try:
        result = services.bulk_dft_input_revision_service.apply(
            state.get("bulk_dft_input_preview", {}),
            plan,
            int(state.get("bulk_dft_revision_count", 0)),
            state.get("bulk_dft_revision_history", []),
        )
        return {
            "bulk_dft_input_preview": result["preview"],
            "bulk_dft_revision_validation": result["validation"],
            "bulk_dft_revision_history": result["history"],
            "bulk_dft_revision_count": result["revision_count"],
            "bulk_dft_input_review": {},
            "status": "bulk_dft_revision_accepted",
        }
    except Exception as error:
        return {
            "bulk_dft_revision_validation": {
                "status": "bulk_dft_revision_rejected",
                "reason": str(error),
                "poscar_unchanged": True,
            },
            "status": "bulk_dft_revision_rejected",
            "errors": _append_error(state, "bulk_dft_revision_apply", error),
        }


def bulk_dft_input_finalize_node(state: CatalystState) -> dict[str, Any]:
    try:
        result = services.bulk_dft_input_bundle_service.finalize(
            state.get("bulk_dft_input_preview", {}),
            state.get("bulk_dft_input_review", {}),
        )
        # Rename generic C10 status to the C6D boundary.
        if result.get("status") == "dft_input_preparation_completed":
            result["status"] = "bulk_dft_input_preparation_completed"
        result["schema_version"] = "c6d.0"
        result["stage"] = "c6d_finalize"
        result["next_stage"] = "c11_bulk_cluster_preflight"
        return {
            "bulk_dft_input_preparation": result,
            "bulk_dft_jobs": result.get("jobs", []),
            "status": result["status"],
        }
    except Exception as error:
        return {
            "bulk_dft_input_preparation": {
                "schema_version": "c6d.0",
                "status": "bulk_dft_input_preparation_failed",
                "jobs": [],
                "failures": [{
                    "error_type": type(error).__name__,
                    "message": str(error),
                }],
            },
            "bulk_dft_jobs": [],
            "status": "bulk_dft_input_preparation_failed",
            "errors": _append_error(state, "bulk_dft_input_finalize", error),
        }
```

## 9. 把节点接入 workflow

打开 `app/graph/workflow.py`。

在 nodes import 中加入：

```python
    bulk_dft_input_finalize_node,
    bulk_dft_input_preview_node,
    bulk_dft_input_review_node,
    bulk_dft_revision_apply_node,
    bulk_dft_revision_plan_node,
```

在 routes import 中加入：

```python
    route_after_bulk_dft_review,
    route_after_formation_energy,
```

在 `build_graph()` 注册：

```python
    builder.add_node("bulk_dft_input_preview", bulk_dft_input_preview_node)
    builder.add_node("bulk_dft_input_review", bulk_dft_input_review_node)
    builder.add_node("bulk_dft_revision_plan", bulk_dft_revision_plan_node)
    builder.add_node("bulk_dft_revision_apply", bulk_dft_revision_apply_node)
    builder.add_node("bulk_dft_input_finalize", bulk_dft_input_finalize_node)
```

删除原来的固定边：

```python
builder.add_edge("formation_energy", "stability_screening")
```

替换为：

```python
    builder.add_conditional_edges(
        "formation_energy",
        route_after_formation_energy,
        {
            "bulk_dft": "bulk_dft_input_preview",
            "stability": "stability_screening",
        },
    )

    builder.add_edge("bulk_dft_input_preview", "bulk_dft_input_review")

    builder.add_conditional_edges(
        "bulk_dft_input_review",
        route_after_bulk_dft_review,
        {
            "revise": "bulk_dft_revision_plan",
            "finalize": "bulk_dft_input_finalize",
        },
    )

    builder.add_edge("bulk_dft_revision_plan", "bulk_dft_revision_apply")
    builder.add_edge("bulk_dft_revision_apply", "bulk_dft_input_review")

    # C11 尚未实现；C6D 目前以五文件准备完成为边界。
    builder.add_edge("bulk_dft_input_finalize", END)
```

## 10. 复用 CLI 五文件审查

打开 `app/graph/cli.py`。

在 `collect_dft_input_review_decision()` 开头加入：

```python
    stage_label = str(request.get("stage_label", "C10"))
```

把函数中两处固定的 `C10 revision count` 和 `C10 审查备注` 改成
`f"{stage_label} ..."`。然后在 `resume_interrupts()` 中加入：

```python
        elif interrupt_type == "bulk_dft_input_review_required":
            decision = collect_dft_input_review_decision(interrupt_value)
```

在最终输出函数中加入摘要：

```python
    c6d = result.get("bulk_dft_input_preparation", {})
    print_section(
        "C6D bulk DFT 输入文件",
        {
            "status": c6d.get("status"),
            "prepared_job_count": c6d.get("prepared_job_count", 0),
            "failure_count": c6d.get("failure_count", 0),
            "jobs": [
                {
                    "job_id": job.get("job_id"),
                    "structure_id": job.get("structure_id"),
                    "job_dir": job.get("job_dir"),
                    "element_order": job.get("element_order"),
                    "potcar_order": job.get("potcar_order"),
                    "preview_digest": job.get("preview_digest"),
                }
                for job in c6d.get("jobs", [])
            ],
        },
    )
```

## 11. 添加领域测试

新建 `tests/test_bulk_dft_input_bundle.py`。建议至少覆盖：

```python
import json
import tempfile
import unittest
from pathlib import Path

from app.domain.bulk_dft_input_bundle import BulkFormationVaspBundleService


class BulkFormationVaspBundleServiceTest(unittest.TestCase):
    ELEMENTS = ["Au", "Ag", "Pt", "Pd", "Cu"]
    COUNTS = [7, 7, 6, 6, 6]
    MAPPING = {
        "Au": "Au",
        "Ag": "Ag",
        "Pt": "Pt",
        "Pd": "Pd",
        "Cu": "Cu_pv",
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output_root = self.root / "output"
        self.pbe_root = self.root / "PBE"
        self.config_path = self.root / "bulk.json"
        self.poscar_path = self.root / "bulk.vasp"
        self._write_config()
        self._write_potcars()
        self._write_poscar(self.COUNTS)
        self.service = BulkFormationVaspBundleService(
            output_root=self.output_root,
            config_path=self.config_path,
            pbe_root=self.pbe_root,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def queue_item(self) -> dict:
        return {
            "job_type": "formation_energy_dft",
            "status": "waiting_for_supercomputer",
            "structure_id": "noble-bulk-01",
            "candidate_id": "C1",
            "elements": self.ELEMENTS,
            "composition": dict(zip(self.ELEMENTS, self.COUNTS)),
            "poscar_path": str(self.poscar_path),
        }

    @staticmethod
    def confirmations(bundle_id: str) -> dict:
        return {
            "action": "finalize",
            "approve": [bundle_id],
            "reject": [],
            "defer": [],
            "file_confirmations": {
                bundle_id: {
                    "POSCAR": True,
                    "INCAR": True,
                    "KPOINTS": True,
                    "POTCAR": True,
                    "vasp.slurm": True,
                }
            },
        }

    def test_empty_queue_is_skipped(self):
        result = self.service.preview([], "test")
        self.assertEqual(result["status"], "bulk_dft_input_preview_skipped")

    def test_wrong_atom_count_is_rejected(self):
        self._write_poscar([7, 7, 6, 6, 5])
        with self.assertRaisesRegex(ValueError, "32 atoms"):
            self.service.preview([self.queue_item()], "test")

    def test_poscar_text_is_preserved(self):
        source = self.poscar_path.read_text(encoding="utf-8")
        result = self.service.preview([self.queue_item()], "test")
        self.assertEqual(
            result["bundles"][0]["preview"]["POSCAR"],
            source,
        )

    def test_noble_metal_potcars_follow_poscar_order(self):
        result = self.service.preview([self.queue_item()], "test")
        plan = result["bundles"][0]["preview"]["POTCAR"]
        self.assertEqual(
            [item["element"] for item in plan],
            self.ELEMENTS,
        )
        self.assertEqual(
            [item["potential"] for item in plan],
            [self.MAPPING[element] for element in self.ELEMENTS],
        )

    def test_finalize_creates_exactly_five_files(self):
        preview = self.service.preview([self.queue_item()], "test")
        bundle_id = preview["bundles"][0]["bundle_id"]
        result = self.service.finalize(
            preview,
            self.confirmations(bundle_id),
        )
        self.assertEqual(
            result["status"],
            "dft_input_preparation_completed",
        )
        job = result["jobs"][0]
        files = sorted(
            path.name
            for path in Path(job["job_dir"]).iterdir()
            if path.is_file()
        )
        self.assertEqual(
            files,
            sorted(BulkFormationVaspBundleService.FILE_NAMES),
        )
        self.assertEqual(job["status"], "bulk_dft_input_files_created")

    def test_result_is_json_serializable(self):
        result = self.service.preview([self.queue_item()], "test")
        self.assertIn(
            "bulk_dft_input_preview_completed",
            json.dumps(result, ensure_ascii=False),
        )

    def _write_config(self):
        value = {
            "incar": {
                "LWAVE": "F",
                "LCHARG": "F",
                "ENCUT": 400,
                "NELM": 200,
                "NSW": 800,
                "EDIFFG": -0.03,
            },
            "kpoints": [
                "Automatic Mesh",
                "0",
                "Gamma",
                "1  1  1",
                "0  0  0",
            ],
            "magnetic_elements": ["Fe", "Co", "Ni", "Mn"],
            "magmom_per_atom": 0.5,
            "potcar_mapping": self.MAPPING,
            "slurm": {
                "nodes": 1,
                "tasks_per_node": 32,
                "partition": "normal",
                "environment_script": "/safe/vasp/env.sh",
                "command": "srun vasp_std",
            },
        }
        self.config_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_potcars(self):
        for element, potential in self.MAPPING.items():
            directory = self.pbe_root / potential
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "POTCAR").write_bytes(
                f"POTCAR-{element}-{potential}\n".encode("ascii")
            )

    def _write_poscar(self, counts: list[int]):
        coordinate_count = sum(counts)
        lines = [
            "C6D test bulk",
            "1.0",
            "4.0 0.0 0.0",
            "0.0 4.0 0.0",
            "0.0 0.0 4.0",
            " ".join(self.ELEMENTS),
            " ".join(str(value) for value in counts),
            "Selective dynamics",
            "Direct",
        ]
        for index in range(coordinate_count):
            value = index / max(coordinate_count, 1)
            lines.append(
                f"{value:.8f} {value:.8f} {value:.8f} T T T"
            )
        self.poscar_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    unittest.main()
```

## 12. 添加路由和节点测试

在新的 `tests/test_graph_bulk_dft.py` 中至少验证：

```python
import unittest

from app.graph.routes import (
    route_after_bulk_dft_review,
    route_after_formation_energy,
)


class GraphBulkDFTRouteTest(unittest.TestCase):
    def test_dft_queue_enters_c6d(self):
        self.assertEqual(
            route_after_formation_energy({
                "dft_formation_energy_queue": [{"structure_id": "S1"}]
            }),
            "bulk_dft",
        )

    def test_empty_queue_enters_c7(self):
        self.assertEqual(
            route_after_formation_energy({
                "dft_formation_energy_queue": []
            }),
            "stability",
        )

    def test_revision_loops_back(self):
        self.assertEqual(
            route_after_bulk_dft_review({
                "bulk_dft_input_review": {"action": "revise"}
            }),
            "revise",
        )


if __name__ == "__main__":
    unittest.main()
```

还应模仿 `tests/test_graph_dft_input_bundle.py` 对五个新节点进行 mock 测试。

## 13. 分层运行检查

先检查语法：

```powershell
python -m py_compile `
  ".\app\domain\bulk_dft_input_bundle.py" `
  ".\app\domain\bulk_dft_input_revision.py" `
  ".\app\graph\services.py" `
  ".\app\graph\state.py" `
  ".\app\graph\routes.py" `
  ".\app\graph\nodes.py" `
  ".\app\graph\workflow.py" `
  ".\app\graph\cli.py"
```

运行 C6/C6D/C10 聚焦测试：

```powershell
python -m unittest `
  tests.test_formation_energy `
  tests.test_graph_formation_energy `
  tests.test_bulk_dft_input_bundle `
  tests.test_graph_bulk_dft `
  tests.test_dft_input_bundle `
  tests.test_dft_input_revision `
  tests.test_graph_dft_input_bundle `
  tests.test_graph_cli -v
```

最后运行全量测试：

```powershell
python -m unittest discover -s tests -v
```

## 14. 手工运行行为

```powershell
python -m app.main --cli "设计用于 CO2 还原生成 CO 的高熵催化剂"
```

当所选候选含 Au/Ag/Pt/Pd 时，预期流程为：

```text
C5 生成 32 原子 bulk
-> C6 标记 waiting_for_dft
-> C6D 展示五文件
-> 输入 m 可修改 INCAR/KPOINTS/POTCAR/受限 Slurm 参数
-> POSCAR 或坐标修改被拒绝
-> 再次展示完整五文件
-> 五项确认后正式生成目录
-> 流程结束，等待未来 C11
```

默认输出目录：

```text
data/dft_formation_inputs/<task_id>/<structure_id>_bulk_formation/
```

确认其中恰好包含：

```text
POSCAR
INCAR
KPOINTS
POTCAR
vasp.slurm
```

## 15. C6D 完成判据

C6D 只有同时满足以下条件才算完成：

1. CGCNN 域外结构自动进入 C6D，域内结构仍直接进入 C7。
2. bulk POSCAR 与 C5 原文件逐字节一致。
3. INCAR/KPOINTS 与参考脚本参数一致。
4. Au、Ag、Pt、Pd POTCAR 能按 POSCAR 元素顺序规划和拼接。
5. 自然语言修订不允许修改 POSCAR。
6. 修订后强制重新检查五文件。
7. 未确认时不写正式文件。
8. 正式目录只有五个文件且不覆盖旧目录。
9. C6D 不提交超算、不制造形成能、不提前进入 C7。
10. 聚焦测试和全量测试全部通过。

完成后下一阶段是 C11：先为 bulk DFT 输入包建立本地与远程超算预检查，随后才允许
人工确认上传和提交。
