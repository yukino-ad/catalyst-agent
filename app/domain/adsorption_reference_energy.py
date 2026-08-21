from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any


class AdsorptionReferenceEnergyCatalog:
    """Resolve trusted, versioned isolated-intermediate energies."""

    SCHEMA_VERSION = "adsorption-reference-values-v1"
    DEFAULT_CONFIG_PATH = (
        "configs/adsorbates/reference_energy_values_v1.json"
    )

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.config_path = Path(config_path)

    def resolve(self, adsorbate: str) -> dict[str, Any] | None:
        name = str(adsorbate).strip()
        if not name:
            return None

        data = self._load()
        canonical_name = self._canonical_name(
            name,
            data["references"],
        )
        if canonical_name is None:
            return None

        entry = deepcopy(data["references"][canonical_name])
        return {
            "resolved_reference_energy_ev": float(entry["energy_ev"]),
            "requested_adsorbate": name,
            "canonical_adsorbate": canonical_name,
            "structure_label": entry.get("structure_label", ""),
            "energy_field": data["energy_field"],
            "energy_unit": data["energy_unit"],
            "calculation_scope": data["calculation_scope"],
            "source_type": data["provenance"]["source_type"],
            "functional_and_parameters": data["provenance"][
                "functional_and_parameters"
            ],
            "data_version": data["data_version"],
            "config_path": str(self.config_path.resolve()),
        }

    def _load(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            raise FileNotFoundError(
                f"Reference-energy values do not exist: {self.config_path}"
            )
        value = json.loads(self.config_path.read_text(encoding="utf-8"))
        if value.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("Unsupported reference-energy value schema")
        if value.get("status") != "accepted_user_calculation":
            raise ValueError("Reference-energy values are not accepted")
        if value.get("energy_unit") != "eV":
            raise ValueError("Reference-energy values must use eV")
        if not isinstance(value.get("data_version"), str):
            raise ValueError("Reference-energy data_version is required")
        if not isinstance(value.get("provenance"), dict):
            raise TypeError("Reference-energy provenance must be an object")

        references = value.get("references")
        if not isinstance(references, dict):
            raise TypeError("Reference-energy references must be an object")
        aliases: set[str] = set()
        for name, entry in references.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                raise TypeError("Every reference-energy entry is invalid")
            energy = entry.get("energy_ev")
            if (
                isinstance(energy, bool)
                or not isinstance(energy, (int, float))
                or not math.isfinite(float(energy))
            ):
                raise ValueError(f"Reference energy for {name} is invalid")
            entry_aliases = entry.get("aliases", [])
            if not isinstance(entry_aliases, list):
                raise TypeError(f"Aliases for {name} must be a list")
            for alias in entry_aliases:
                text = str(alias).strip()
                if not text or text in references or text in aliases:
                    raise ValueError(f"Reference alias is duplicated: {text}")
                aliases.add(text)
        return value

    @staticmethod
    def _canonical_name(
        requested: str,
        references: dict[str, dict[str, Any]],
    ) -> str | None:
        if requested in references:
            return requested
        for name, entry in references.items():
            if requested in entry.get("aliases", []):
                return name
        return None
