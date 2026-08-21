from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


class StructureBuilder:
    """Build 32-atom FCC HEA structures using the rules from Cu-HEA-FCC-8.0-fix.py."""

    LATTICE_CONSTANTS = {
        "Fe": 3.615, "Co": 3.615, "Ni": 3.615, "Cu": 3.615,
        "Cr": 3.615, "Mn": 3.885, "Mo": 3.885, "Ti": 4.095,
        "Al": 4.095, "Zn": 3.885, "Ga": 3.885, "Ge": 3.615,
        "Au": 4.095, "Ag": 4.095, "Pt": 3.885, "Pd": 3.885,
    }
    SUPPORTED_ELEMENTS = set(LATTICE_CONSTANTS)
    P_ELEMENTS = {"Al", "Zn", "Ga", "Ge"}
    CLUSTER_SENSITIVE = {"Mo", "Ti", "Mn"}
    NOBLE_ELEMENTS = {"Au", "Ag", "Pt", "Pd"}

    def __init__(self, output_dir: str | Path = "data/structures") -> None:
        self.output_dir = Path(output_dir)

    def generate(
        self,
        selected_elements: Sequence[str],
        num_structures: int = 1,
        generation_mode: str = "fixed_cu",
        start_index: int = 1,
        seed: int = 42,
        min_distance: float = 1.8,
        composition: dict[str, int] | None = None,
        unique_only: bool = True,
        write_cif: bool = True,
        write_poscar: bool = True,
        **_: Any,
    ) -> dict[str, Any]:
        elements = self._validate_elements(selected_elements, generation_mode)
        if num_structures <= 0:
            raise ValueError("num_structures 必须大于 0。")

        if composition is None:
            if generation_mode == "composition_driven":
                raise ValueError(
                    "composition_driven 模式必须提供 composition。"
                )

            counts = self._default_composition(
                elements,
                generation_mode,
            )
        else:
            counts = dict(composition)
        self._validate_composition(elements, counts)
        fractional_coords = self._fcc_2x2x2_coords()
        lattice_a0 = sum(self.LATTICE_CONSTANTS[e] * counts[e] for e in elements) / 32
        supercell_a = 2.0 * lattice_a0
        neighbor_list = self._neighbor_list(fractional_coords, supercell_a)
        minimum_distance = supercell_a * math.sqrt(0.125)
        if minimum_distance < min_distance:
            raise ValueError(
                f"最小原子间距 {minimum_distance:.3f} A 小于阈值 {min_distance:.3f} A。"
            )

        cif_dir = self.output_dir / "cif"
        poscar_dir = self.output_dir / "POSCAR"
        manifest_dir = self.output_dir / "manifests"
        for directory in (cif_dir, poscar_dir, manifest_dir):
            directory.mkdir(parents=True, exist_ok=True)

        rng = random.Random(seed)
        generated: list[dict[str, Any]] = []
        seen: set[str] = set()
        attempts = 0
        max_attempts = max(1000, num_structures * 5000)

        while len(generated) < num_structures and attempts < max_attempts:
            attempts += 1
            symbols = [element for element in elements for _ in range(counts[element])]
            rng.shuffle(symbols)
            if not self._local_rules_ok(symbols, neighbor_list):
                continue

            signature = self._signature(symbols, supercell_a)
            if unique_only and signature in seen:
                continue
            seen.add(signature)

            index = start_index + len(generated)
            composition_text = "_".join(f"{e}{counts[e]}" for e in sorted(elements))
            prefix = (
                "Cu_HEA_FCC"
                if "Cu" in elements
                else "HEA_FCC"
            )
            stem = (
                f"{prefix}_{index:05d}_"
                f"{composition_text}_{signature[:8]}"
            )
            cif_path = cif_dir / f"{stem}.cif"
            poscar_path = poscar_dir / f"{stem}.vasp"
            if write_cif:
                self._write_cif(cif_path, symbols, fractional_coords, supercell_a, counts)
            if write_poscar:
                self._write_poscar(poscar_path, symbols, fractional_coords, supercell_a)

            generated.append(
                {
                    "id": index,
                    "formula": "".join(f"{e}{counts[e]}" for e in sorted(elements)),
                    "elements": elements,
                    "counts": counts,
                    "lattice_constant_a0": round(lattice_a0, 6),
                    "supercell_a": round(supercell_a, 6),
                    "minimum_distance": round(minimum_distance, 6),
                    "cif_path": str(cif_path.resolve()) if write_cif else None,
                    "poscar_path": str(poscar_path.resolve()) if write_poscar else None,
                    "signature": signature,
                }
            )

        manifest = {
            "success": len(generated) == num_structures,
            "requested_count": num_structures,
            "generated_count": len(generated),
            "attempts": attempts,
            "parameters": {
                "selected_elements": elements,
                "generation_mode": generation_mode,
                "seed": seed,
                "min_distance": min_distance,
                "composition": counts,
            },
            "results": generated,
        }
        manifest_path = manifest_dir / f"manifest_{start_index}_{seed}.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["manifest_path"] = str(manifest_path.resolve())
        return manifest

    def _validate_elements(
        self,
        selected: Sequence[str],
        mode: str,
    ) -> list[str]:
        elements = list(dict.fromkeys(
            str(element).strip().capitalize()
            for element in selected
            if str(element).strip()
        ))

        unsupported = sorted(
            set(elements) - self.SUPPORTED_ELEMENTS
        )
        if unsupported:
            raise ValueError(
                "建模器缺少以下元素的晶格参数："
                + ", ".join(unsupported)
            )

        supported_modes = {
            "fixed_cu",
            "composition_driven",
        }
        if mode not in supported_modes:
            raise ValueError(
                f"不支持的建模模式：{mode}"
            )

        if len(elements) != 5:
            raise ValueError(
                "当前 FCC 建模要求恰好包含 5 种元素。"
            )

        if mode == "fixed_cu" and "Cu" not in elements:
            raise ValueError(
                "fixed_cu 模式要求候选中包含 Cu。"
            )

        if len(set(elements) & self.P_ELEMENTS) > 1:
            raise ValueError(
                "一个候选最多包含一种 p 区元素："
                "Al、Zn、Ga 或 Ge。"
            )

        return elements

    def _default_composition(self, elements: list[str], mode: str) -> dict[str, int]:
        if mode != "fixed_cu":
            raise ValueError(f"不支持的建模模式: {mode}")
        counts = {"Cu": 8}
        non_cu = [e for e in elements if e != "Cu"]
        if set(elements) & self.NOBLE_ELEMENTS:
            counts.update({e: 6 for e in non_cu})
            return counts
        p_elements = [e for e in non_cu if e in self.P_ELEMENTS]
        if p_elements:
            counts[p_elements[0]] = 3
            counts.update({e: 7 for e in non_cu if e not in p_elements})
        else:
            counts.update({e: 6 for e in non_cu})
        return counts

    def _validate_composition(self, elements: list[str], counts: dict[str, int]) -> None:
        if set(counts) != set(elements):
            raise ValueError("composition 的元素必须与 selected_elements 完全一致。")
        if any(not isinstance(value, int) or value <= 0 for value in counts.values()):
            raise ValueError("composition 中的原子数必须是正整数。")
        if sum(counts.values()) != 32:
            raise ValueError("2x2x2 FCC 超胞的 composition 原子总数必须等于 32。")

    @staticmethod
    def _fcc_2x2x2_coords() -> list[tuple[float, float, float]]:
        basis = ((0, 0, 0), (0.5, 0.5, 0), (0.5, 0, 0.5), (0, 0.5, 0.5))
        return [
            ((i + x) / 2, (j + y) / 2, (k + z) / 2)
            for i in range(2) for j in range(2) for k in range(2)
            for x, y, z in basis
        ]

    @staticmethod
    def _neighbor_list(coords: list[tuple[float, float, float]], cell: float) -> list[list[int]]:
        neighbors = [[] for _ in coords]
        for i in range(len(coords)):
            for j in range(i + 1, len(coords)):
                delta = [coords[i][axis] - coords[j][axis] for axis in range(3)]
                delta = [value - round(value) for value in delta]
                distance = cell * math.sqrt(sum(value * value for value in delta))
                if distance < 2.9:
                    neighbors[i].append(j)
                    neighbors[j].append(i)
        return neighbors

    def _local_rules_ok(self, symbols: list[str], neighbors: list[list[int]]) -> bool:
        for i, element in enumerate(symbols):
            nearby = [symbols[j] for j in neighbors[i]]
            if nearby.count(element) > 3:
                return False
            if element in self.P_ELEMENTS and sum(e in self.P_ELEMENTS for e in nearby) > 2:
                return False
            if element in self.CLUSTER_SENSITIVE and sum(e in self.CLUSTER_SENSITIVE for e in nearby) > 4:
                return False
        return True

    @staticmethod
    def _signature(symbols: list[str], cell: float) -> str:
        payload = f"{cell:.8f}|" + ",".join(symbols)
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    @staticmethod
    def _write_poscar(path: Path, symbols: list[str], coords: list[tuple[float, float, float]], cell: float) -> None:
        counts = Counter(symbols)
        order = ["Cu"] + sorted(e for e in counts if e != "Cu") if "Cu" in counts else sorted(counts)
        lines = ["HEA_FCC_2x2x2", "1.0", f"{cell:.10f} 0 0", f"0 {cell:.10f} 0", f"0 0 {cell:.10f}"]
        lines.extend((" ".join(order), " ".join(str(counts[e]) for e in order), "Direct"))
        for element in order:
            lines.extend(f"{x:.10f} {y:.10f} {z:.10f}" for symbol, (x, y, z) in zip(symbols, coords) if symbol == element)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _write_cif(path: Path, symbols: list[str], coords: list[tuple[float, float, float]], cell: float, counts: dict[str, int]) -> None:
        formula = " ".join(f"{e}{counts[e]}" for e in sorted(counts))
        lines = [
            "data_HEA_FCC_2x2x2", f'_chemical_formula_sum "{formula}"',
            "_symmetry_space_group_name_H-M 'P1'", "_symmetry_Int_Tables_number 1",
            f"_cell_length_a {cell:.6f}", f"_cell_length_b {cell:.6f}", f"_cell_length_c {cell:.6f}",
            "_cell_angle_alpha 90", "_cell_angle_beta 90", "_cell_angle_gamma 90", "",
            "loop_", "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x",
            "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
        ]
        lines.extend(f"{e}{i + 1:02d} {e} {x:.6f} {y:.6f} {z:.6f} 1.0" for i, (e, (x, y, z)) in enumerate(zip(symbols, coords)))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
