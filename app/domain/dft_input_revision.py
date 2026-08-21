from __future__ import annotations

import copy
import re
from typing import Any

from app.domain.dft_input_bundle import VaspInputBundleService
from tools.llm_client import OpenAICompatibleClient


class DFTInputRevisionError(ValueError):
    """Raised when a requested C10 revision is unsafe or unsupported."""


class DFTInputRevisionService:
    """Translate, validate, and apply controlled VASP input revisions."""

    MAX_REVISIONS = 5
    ALLOWED_SECTIONS = {"INCAR", "KPOINTS", "POTCAR", "vasp.slurm"}
    EXTRA_INCAR_KEYS = {"ISPIN", "MAGMOM"}
    KPOINTS_KEYS = {"mesh", "center", "shift"}
    SLURM_KEYS = {"job_name", "nodes", "tasks_per_node", "partition"}
    UNSAFE_TEXT = re.compile(r"[\r\n;`]|&&|\|\||\$\(")
    INCAR_NUMERIC_RANGES = {
        "ENCUT": (100.0, 2000.0), "EDIFF": (1e-12, 1.0),
        "EDIFFG": (-10.0, 10.0), "NELM": (1.0, 2000.0),
        "NELMIN": (1.0, 2000.0), "NELMDL": (-2000.0, 2000.0),
        "NSW": (0.0, 100000.0), "IBRION": (-1.0, 44.0),
        "ISIF": (0.0, 8.0), "ISMEAR": (-5.0, 5.0),
        "SIGMA": (0.0, 10.0), "ISPIN": (1.0, 2.0),
    }

    def __init__(
        self,
        bundle_service: VaspInputBundleService,
        llm: OpenAICompatibleClient | None = None,
    ) -> None:
        self.bundle_service = bundle_service
        self.llm = llm or OpenAICompatibleClient()

    def parse_requests(
        self,
        revision_requests: dict[str, str],
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        """Use the LLM only to translate natural language into JSON."""

        if not isinstance(revision_requests, dict) or not revision_requests:
            raise DFTInputRevisionError("No DFT revision request was supplied")
        if not self.llm.available:
            raise DFTInputRevisionError("LLM is unavailable for revision parsing")

        known_ids = {
            str(bundle.get("bundle_id", ""))
            for bundle in preview.get("bundles", [])
        }
        plans = []
        for bundle_id, request in revision_requests.items():
            if bundle_id not in known_ids:
                raise DFTInputRevisionError(f"Unknown bundle ID: {bundle_id}")
            request = str(request).strip()
            if not request:
                raise DFTInputRevisionError(
                    f"Revision request for {bundle_id} is empty"
                )
            if len(request) > 4000:
                raise DFTInputRevisionError(
                    f"Revision request for {bundle_id} is too long"
                )
            if re.search(r"poscar|原子坐标|坐标", request, re.IGNORECASE):
                raise DFTInputRevisionError(
                    "POSCAR and atomic coordinates cannot be modified"
                )

            value = self.llm.chat_json([
                {
                    "role": "system",
                    "content": (
                        "You translate VASP input revision requests into JSON. "
                        "Do not invent values. Return exactly an object with a "
                        "changes object. Allowed sections are INCAR, KPOINTS, "
                        "POTCAR, and vasp.slurm. KPOINTS keys: mesh, center, "
                        "shift. POTCAR maps element symbols to potential folder "
                        "names. Never emit POSCAR changes. Example: "
                        '{"changes":{"INCAR":{"ENCUT":500},'
                        '"KPOINTS":{"mesh":[3,3,1]}}}'
                    ),
                },
                {"role": "user", "content": request},
            ])
            plans.append({
                "bundle_id": bundle_id,
                "request": request,
                "changes": value.get("changes", value),
            })

        return {
            "schema_version": "c10-revision-v1",
            "status": "dft_revision_plan_ready",
            "plans": plans,
        }

    def apply(
        self,
        preview: dict[str, Any],
        plan: dict[str, Any],
        revision_count: int = 0,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Apply validated changes while preserving POSCAR exactly."""

        if revision_count >= self.MAX_REVISIONS:
            raise DFTInputRevisionError(
                f"Maximum revision count ({self.MAX_REVISIONS}) reached"
            )

        revised = copy.deepcopy(preview)
        bundles = {
            bundle["bundle_id"]: bundle
            for bundle in revised.get("bundles", [])
        }
        changes_log = []

        for item in plan.get("plans", []):
            bundle_id = str(item.get("bundle_id", ""))
            if bundle_id not in bundles:
                raise DFTInputRevisionError(f"Unknown bundle ID: {bundle_id}")
            changes = item.get("changes", {})
            self._validate_changes(changes)

            bundle = bundles[bundle_id]
            old_poscar = bundle["preview"]["POSCAR"]
            old_digest = bundle["preview_digest"]
            diff = self._apply_bundle_changes(bundle, changes)

            if bundle["preview"]["POSCAR"] != old_poscar:
                raise DFTInputRevisionError("POSCAR is immutable in C10 revisions")

            current = bundle["preview"]
            new_digest = self.bundle_service._preview_digest(
                poscar_text=current["POSCAR"],
                incar_text=current["INCAR"],
                kpoints_text=current["KPOINTS"],
                slurm_text=current["vasp.slurm"]["full_text"],
                potcar_plan=current["POTCAR"],
            )
            bundle["preview_digest"] = new_digest
            bundle["preview_version"] = int(
                bundle.get("preview_version", 1)
            ) + 1
            changes_log.append({
                "bundle_id": bundle_id,
                "request": item.get("request", ""),
                "version": bundle["preview_version"],
                "old_digest": old_digest,
                "new_digest": new_digest,
                "changes": diff,
                "poscar_unchanged": True,
            })

        new_history = list(history or []) + changes_log
        revised["schema_version"] = "c10.1"
        revised["revision_count"] = revision_count + 1
        revised["revision_history"] = new_history
        revised["requires_human_confirmation"] = True

        return {
            "preview": revised,
            "validation": {
                "schema_version": "c10-revision-v1",
                "status": "dft_revision_accepted",
                "revision_count": revision_count + 1,
                "changes": changes_log,
                "poscar_unchanged": True,
                "requires_full_review": True,
            },
            "history": new_history,
            "revision_count": revision_count + 1,
        }

    def _validate_changes(self, changes: Any) -> None:
        if not isinstance(changes, dict) or not changes:
            raise DFTInputRevisionError("Revision changes must be a non-empty object")
        for raw_section, values in changes.items():
            section = str(raw_section)
            if section.upper() == "POSCAR":
                raise DFTInputRevisionError(
                    "POSCAR and atomic coordinates cannot be modified"
                )
            if section not in self.ALLOWED_SECTIONS:
                raise DFTInputRevisionError(f"Unsupported section: {section}")
            if not isinstance(values, dict) or not values:
                raise DFTInputRevisionError(f"{section} changes must be an object")

        config = self.bundle_service._load_config()
        incar_allowed = set(config["incar"]) | self.EXTRA_INCAR_KEYS
        unknown_incar = set(changes.get("INCAR", {})) - incar_allowed
        if unknown_incar:
            raise DFTInputRevisionError(
                "Unsupported INCAR keys: " + ", ".join(sorted(unknown_incar))
            )
        self._validate_incar(changes.get("INCAR", {}))
        unknown_kpoints = set(changes.get("KPOINTS", {})) - self.KPOINTS_KEYS
        if unknown_kpoints:
            raise DFTInputRevisionError(
                "Unsupported KPOINTS keys: " + ", ".join(sorted(unknown_kpoints))
            )
        unknown_slurm = set(changes.get("vasp.slurm", {})) - self.SLURM_KEYS
        if unknown_slurm:
            raise DFTInputRevisionError(
                "Unsupported vasp.slurm keys: " + ", ".join(sorted(unknown_slurm))
            )

    def _apply_bundle_changes(
        self,
        bundle: dict[str, Any],
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        preview = bundle["preview"]
        diff: dict[str, Any] = {}

        if "INCAR" in changes:
            old_values = self._parse_incar(preview["INCAR"])
            new_values = dict(old_values)
            new_values.update(changes["INCAR"])
            preview["INCAR"] = self._render_incar(new_values)
            diff["INCAR"] = self._changed_values(old_values, new_values)

        if "KPOINTS" in changes:
            old_values = self._parse_kpoints(preview["KPOINTS"])
            new_values = dict(old_values)
            new_values.update(changes["KPOINTS"])
            self._validate_kpoints(new_values)
            preview["KPOINTS"] = self._render_kpoints(new_values)
            diff["KPOINTS"] = self._changed_values(old_values, new_values)

        if "POTCAR" in changes:
            requested = changes["POTCAR"]
            unknown_elements = set(requested) - set(bundle["elements"])
            if unknown_elements:
                raise DFTInputRevisionError(
                    "POTCAR elements are not in POSCAR: "
                    + ", ".join(sorted(unknown_elements))
                )
            for element, potential in requested.items():
                if not isinstance(potential, str) or not re.fullmatch(
                    r"[A-Za-z0-9_.+-]+", potential
                ):
                    raise DFTInputRevisionError(
                        f"Unsafe POTCAR potential for {element}"
                    )
            config = self.bundle_service._load_config()
            mapping = dict(config["potcar_mapping"])
            old_mapping = {
                item["element"]: item["potential"]
                for item in preview["POTCAR"]
            }
            mapping.update(requested)
            config["potcar_mapping"] = mapping
            preview["POTCAR"] = self.bundle_service._potcar_plan(
                bundle["elements"], config
            )
            diff["POTCAR"] = self._changed_values(
                old_mapping,
                {item["element"]: item["potential"] for item in preview["POTCAR"]},
            )

        if "vasp.slurm" in changes:
            old_values = {
                key: value
                for key, value in preview["vasp.slurm"].items()
                if key != "full_text"
            }
            new_values = dict(old_values)
            new_values.update(changes["vasp.slurm"])
            self._validate_slurm(new_values)
            config = self.bundle_service._load_config()
            config["slurm"].update({
                key: value
                for key, value in new_values.items()
                if key != "job_name"
            })
            preview["vasp.slurm"] = {
                **new_values,
                "full_text": self.bundle_service._build_slurm(
                    str(new_values["job_name"]), config
                ),
            }
            diff["vasp.slurm"] = self._changed_values(old_values, new_values)

        return diff

    @staticmethod
    def _parse_incar(text: str) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    @staticmethod
    def _render_incar(values: dict[str, Any]) -> str:
        system = values.get("SYSTEM", "revised-system")
        lines = [f"SYSTEM = {system}", ""]
        lines.extend(
            f"{key:<8}= {value}"
            for key, value in values.items()
            if key != "SYSTEM"
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _parse_kpoints(text: str) -> dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 5:
            raise DFTInputRevisionError("KPOINTS preview is incomplete")
        return {
            "center": lines[2],
            "mesh": [int(value) for value in lines[3].split()],
            "shift": [float(value) for value in lines[4].split()],
        }

    @staticmethod
    def _render_kpoints(values: dict[str, Any]) -> str:
        mesh = "  ".join(str(value) for value in values["mesh"])
        shift = "  ".join(str(value) for value in values["shift"])
        return f"Automatic Mesh\n0\n{values['center']}\n{mesh}\n{shift}\n"

    @staticmethod
    def _validate_kpoints(values: dict[str, Any]) -> None:
        if values.get("center") not in {"Gamma", "Monkhorst-Pack"}:
            raise DFTInputRevisionError("KPOINTS center must be Gamma or Monkhorst-Pack")
        mesh = values.get("mesh")
        shift = values.get("shift")
        if not isinstance(mesh, list) or len(mesh) != 3 or not all(
            type(value) is int and value > 0 for value in mesh
        ):
            raise DFTInputRevisionError("KPOINTS mesh must contain three positive integers")
        if not isinstance(shift, list) or len(shift) != 3 or not all(
            type(value) in {int, float} for value in shift
        ):
            raise DFTInputRevisionError("KPOINTS shift must contain three numbers")

    def _validate_slurm(self, values: dict[str, Any]) -> None:
        for key in ("nodes", "tasks_per_node"):
            if type(values.get(key)) is not int or values[key] <= 0:
                raise DFTInputRevisionError(f"{key} must be a positive integer")
        for key in ("job_name", "partition"):
            value = str(values.get(key, ""))
            if not value or self.UNSAFE_TEXT.search(value):
                raise DFTInputRevisionError(f"Unsafe vasp.slurm value for {key}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(values["job_name"])):
            raise DFTInputRevisionError("Slurm job_name contains unsupported characters")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(values["partition"])):
            raise DFTInputRevisionError("Slurm partition contains unsupported characters")

    def _validate_incar(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if not isinstance(value, (str, int, float, bool)):
                raise DFTInputRevisionError(
                    f"INCAR value for {key} must be a scalar"
                )
            if self.UNSAFE_TEXT.search(str(value)):
                raise DFTInputRevisionError(
                    f"Unsafe INCAR value for {key}"
                )
            if key in self.INCAR_NUMERIC_RANGES:
                if isinstance(value, bool):
                    raise DFTInputRevisionError(f"INCAR value for {key} must be numeric")
                try:
                    number = float(value)
                except (TypeError, ValueError) as error:
                    raise DFTInputRevisionError(f"INCAR value for {key} must be numeric") from error
                minimum, maximum = self.INCAR_NUMERIC_RANGES[key]
                if not minimum <= number <= maximum:
                    raise DFTInputRevisionError(f"INCAR value for {key} is outside the allowed range")

    @staticmethod
    def _changed_values(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
        return {
            key: {"before": old.get(key), "after": value}
            for key, value in new.items()
            if old.get(key) != value
        }
