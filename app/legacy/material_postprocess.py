"""Screen generated bulk CIFs and build the stable (111) slabs.

This helper runs in the CGCNN environment, which contains pymatgen and ASE.
The formulas and thresholds mirror the two user-supplied scripts.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from itertools import combinations
from pathlib import Path

import numpy as np
from ase.build import make_supercell, surface
from ase.constraints import FixAtoms
from ase.io import read, write
from pymatgen.core import Structure

R = 8.314462618
OMEGA_THRESHOLD = 1.1
DELTA_THRESHOLD = 6.6
ATOMIC_RADIUS = {"Al": 1.43, "Co": 1.25, "Cr": 1.28, "Cu": 1.28, "Fe": 1.26, "Ga": 1.35, "Ge": 1.22, "Mn": 1.39, "Mo": 1.39, "Ni": 1.25, "Ti": 1.47, "Zn": 1.33}
MELTING_POINT = {"Al": 933.47, "Co": 1768.0, "Cr": 2180.0, "Cu": 1357.77, "Fe": 1811.0, "Ga": 302.91, "Ge": 1211.4, "Mn": 1519.0, "Mo": 2896.0, "Ni": 1728.0, "Ti": 1941.0, "Zn": 692.68}
H_MIX = {
    **{("Al", e): v for e, v in {"Co": -19, "Cr": -10, "Cu": -1, "Fe": -11, "Ga": 0, "Ge": -20, "Mn": -19, "Mo": -22, "Ni": -22, "Ti": -30, "Zn": -1}.items()},
    **{("Co", e): v for e, v in {"Cr": 0, "Cu": 6, "Fe": 0, "Ga": 0, "Ge": -10, "Mn": 0, "Mo": -7, "Ni": -4, "Ti": -24, "Zn": 0}.items()},
    **{("Cr", e): v for e, v in {"Cu": 12, "Fe": 1, "Ga": 0, "Ge": -6, "Mn": 0, "Mo": 0, "Ni": 4, "Ti": -7, "Zn": 0}.items()},
    **{("Cu", e): v for e, v in {"Fe": 13, "Ga": 4, "Ge": -1, "Mn": 4, "Mo": -4, "Ni": -4, "Ti": -9, "Zn": 4}.items()},
    **{("Fe", e): v for e, v in {"Ga": 0, "Ge": -17, "Mn": 0, "Mo": -2, "Ni": -2, "Ti": -17, "Zn": 0}.items()},
    **{("Ga", e): v for e, v in {"Ge": -4, "Mn": 0, "Mo": 0, "Ni": 0, "Ti": -10, "Zn": 0}.items()},
    **{("Ge", e): v for e, v in {"Mn": 0, "Mo": 0, "Ni": -4, "Ti": -15, "Zn": 0}.items()},
    **{("Mn", e): v for e, v in {"Mo": -1, "Ni": -4, "Ti": -8, "Zn": 0}.items()},
    **{("Mo", e): v for e, v in {"Ni": -7, "Ti": -16, "Zn": 0}.items()},
    **{("Ni", "Ti"): -35, ("Ni", "Zn"): 4, ("Ti", "Zn"): -2},
}


def pair_hmix(a: str, b: str) -> float:
    return H_MIX.get(tuple(sorted((a, b))), H_MIX.get((b, a)))


def fractions(structure: Structure) -> dict[str, float]:
    comp = structure.composition.get_el_amt_dict()
    total = sum(comp.values())
    return {element: amount / total for element, amount in comp.items()}


def screen(path: Path) -> dict[str, object]:
    try:
        structure = Structure.from_file(str(path))
        fracs = fractions(structure)
        r_avg = sum(fracs[e] * ATOMIC_RADIUS[e] for e in fracs)
        delta = 100 * math.sqrt(sum(x * (1 - ATOMIC_RADIUS[e] / r_avg) ** 2 for e, x in fracs.items()))
        tm = sum(fracs[e] * MELTING_POINT[e] for e in fracs)
        hmix = sum(4 * fracs[a] * fracs[b] * pair_hmix(a, b) for a, b in combinations(fracs, 2))
        smix = -R * sum(x * math.log(x) for x in fracs.values() if x > 0)
        omega = tm * smix / (max(abs(hmix), 1e-12) * 1000)
        delta_pass = delta <= DELTA_THRESHOLD
        omega_pass = omega >= OMEGA_THRESHOLD
        return {
            "cif_path": str(path.resolve()),
            "formula": structure.composition.reduced_formula,
            "delta_percent": delta,
            "omega": omega,
            "delta_pass": delta_pass,
            "omega_pass": omega_pass,
            "passed": delta_pass and omega_pass,
            "reason": "delta_ok;omega_ok" if delta_pass and omega_pass else f"delta={'ok' if delta_pass else 'fail'};omega={'ok' if omega_pass else 'fail'}",
        }
    except Exception as error:
        return {"cif_path": str(path.resolve()), "passed": False, "reason": f"error: {error}"}


def write_poscar_with_constraints(atoms, path: Path) -> None:
    symbols = atoms.get_chemical_symbols()
    order = list(dict.fromkeys(symbols))
    counts = [symbols.count(element) for element in order]
    flags = np.ones((len(atoms), 3), dtype=bool)
    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            flags[constraint.get_indices()] = False
    lines = [" ".join(order), "1.0"]
    lines.extend(" ".join(f"{value:.16f}" for value in vector) for vector in atoms.cell.array)
    lines.extend([" ".join(order), " ".join(map(str, counts)), "Selective dynamics", "Direct"])
    for position, flag in zip(atoms.get_scaled_positions(), flags):
        lines.append(" ".join(f"{value:.16f}" for value in position) + " " + " ".join("T" if x else "F" for x in flag))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_slab(poscar_path: Path, output_root: Path) -> dict[str, object]:
    atoms = read(str(poscar_path), format="vasp")
    slab = make_supercell(surface(atoms, (1, 1, 1), layers=2, vacuum=18.0), np.eye(3, dtype=int))
    z = slab.positions[:, 2]
    unique_z = np.unique(np.round(z, 3))
    unique_z.sort()
    if len(unique_z) > 3:
        slab = slab[z > unique_z[0] + 0.1]
    slab.translate([0, 0, -slab.positions[:, 2].min()])
    thickness = slab.positions[:, 2].max() - slab.positions[:, 2].min()
    cell = slab.cell.array.copy()
    cell[2, 2] = thickness + 18.0
    slab.set_cell(cell, scale_atoms=False)
    z = np.round(slab.positions[:, 2], 3)
    slab.set_constraint(FixAtoms(mask=~np.isclose(z, z.max())))
    cif_dir, poscar_dir = output_root / "cif", output_root / "POSCAR"
    cif_dir.mkdir(parents=True, exist_ok=True)
    poscar_dir.mkdir(parents=True, exist_ok=True)
    cif_path = cif_dir / f"{poscar_path.stem}_slab111.cif"
    slab_path = poscar_dir / f"{poscar_path.stem}_slab111.vasp"
    write(str(cif_path), slab, format="cif")
    write_poscar_with_constraints(slab, slab_path)
    return {"atom_count": len(slab), "vacuum_angstrom": 18.0, "cif_path": str(cif_path.resolve()), "poscar_path": str(slab_path.resolve())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cif", nargs="+", required=True)
    parser.add_argument("--poscar", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--screening-json", required=True)
    args = parser.parse_args()
    if len(args.cif) != len(args.poscar):
        raise ValueError("CIF and POSCAR counts must match.")
    rows = [screen(Path(path)) for path in args.cif]
    output = Path(args.output)
    slabs = []
    for row, poscar_path in zip(rows, args.poscar):
        if row.get("passed"):
            slab = make_slab(Path(poscar_path), output)
            slab["bulk_cif_path"] = row["cif_path"]
            slabs.append(slab)
    Path(args.screening_json).write_text(json.dumps({"screening": rows, "slabs": slabs}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
