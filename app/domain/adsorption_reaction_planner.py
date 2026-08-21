from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class AdsorptionReactionPlanner:
    """Build a reviewable adsorption plan from a reaction profile."""

    SCHEMA_VERSION = "c12.1"
    DEFAULT_CONFIG_PATH = (
        "configs/reactions/adsorption_profiles_v1.json"
    )
    DEFAULT_REFERENCE_CONFIG_PATH = (
        "configs/adsorbates/reference_energy_schemes_v1.json"
    )

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        reference_config_path: str | Path = DEFAULT_REFERENCE_CONFIG_PATH,
    ) -> None:
        self.config_path = Path(config_path)
        self.reference_config_path = Path(reference_config_path)

    def plan(
        self,
        task_analysis: dict[str, Any],
        reaction_profile: dict[str, Any] | None = None,
        user_overrides: dict[str, Any] | None = None,
        literature_suggestions: list[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(task_analysis, dict):
            raise TypeError(
                "task_analysis must be a dictionary"
            )

        reaction_profile = reaction_profile or {}
        user_overrides = user_overrides or {}
        literature_suggestions = literature_suggestions or []

        if not isinstance(reaction_profile, dict):
            raise TypeError(
                "reaction_profile must be a dictionary"
            )

        if not isinstance(user_overrides, dict):
            raise TypeError(
                "user_overrides must be a dictionary"
            )

        if not isinstance(literature_suggestions, list):
            raise TypeError(
                "literature_suggestions must be a list"
            )

        reaction_id = str(
            task_analysis.get(
                "reaction_id",
                reaction_profile.get(
                    "reaction_id",
                    "UNKNOWN",
                ),
            )
            or "UNKNOWN"
        ).strip()

        config = self._load_config()
        profiles = config["profiles"]
        profile = profiles.get(reaction_id)

        if profile is None:
            return self._unsupported_result(
                reaction_id=reaction_id,
                data_version=config["data_version"],
            )

        primary = self._string_list(
            profile.get(
                "primary_adsorbates",
                [],
            )
        )
        competitive = self._string_list(
            profile.get(
                "competitive_adsorbates",
                [],
            )
        )
        configured_suggestions = self._string_list(
            profile.get(
                "suggested_adsorbates",
                [],
            )
        )

        required_by_user = self._string_list(
            user_overrides.get(
                "required_adsorbates",
                [],
            )
        )
        excluded_by_user = set(
            self._string_list(
                user_overrides.get(
                    "excluded_adsorbates",
                    [],
                )
            )
        )

        primary = [
            value
            for value in primary
            if value not in excluded_by_user
        ]
        competitive = [
            value
            for value in competitive
            if value not in excluded_by_user
        ]

        formal_adsorbates = self._unique(
            [
                *primary,
                *competitive,
                *required_by_user,
            ]
        )

        suggestions = self._unique(
            [
                *configured_suggestions,
                *self._string_list(
                    literature_suggestions
                ),
            ]
        )

        suggestions = [
            value
            for value in suggestions
            if value not in formal_adsorbates
            and value not in excluded_by_user
        ]

        source_records = []

        for adsorbate in primary:
            source_records.append({
                "adsorbate": adsorbate,
                "role": "primary",
                "source": "reaction_profile",
                "approved_for_site_generation": True,
            })

        for adsorbate in competitive:
            source_records.append({
                "adsorbate": adsorbate,
                "role": "competitive",
                "source": "reaction_profile",
                "approved_for_site_generation": True,
            })

        for adsorbate in required_by_user:
            source_records.append({
                "adsorbate": adsorbate,
                "role": "user_required",
                "source": "user_override",
                "approved_for_site_generation": True,
            })

        for adsorbate in suggestions:
            source_records.append({
                "adsorbate": adsorbate,
                "role": "suggested",
                "source": "profile_or_literature_suggestion",
                "approved_for_site_generation": False,
            })

        warnings = self._string_list(
            profile.get("notes", [])
        )

        support_level = str(
            profile.get(
                "support_level",
                "unsupported",
            )
        )

        if support_level == "human_review_required":
            warnings.append(
                "This reaction requires scientific review "
                "before formal adsorption calculations."
            )

        if suggestions:
            warnings.append(
                "Suggested adsorbates are not included in "
                "the formal site-generation queue."
            )

        target_product = (
            task_analysis.get("target_product")
            or reaction_profile.get("target_product")
            or profile.get("target_product")
        )

        reference_config = self._load_reference_config()
        reference_definitions = {
            adsorbate: deepcopy(
                reference_config["adsorbates"].get(
                    adsorbate,
                    {
                        "reference_scheme": "manual",
                        "reference_expression": None,
                        "required_components": [],
                        "manual_reference_required": True,
                    },
                )
            )
            for adsorbate in formal_adsorbates
        }

        ready = False

        if not formal_adsorbates:
            status = (
                "adsorption_reaction_plan_waiting_for_review"
            )
            reason = (
                "No formal adsorbates are approved. "
                "Select a target product or provide "
                "required_adsorbates."
            )
        else:
            status = "adsorption_intermediate_selection_required"
            reason = (
                "Select exactly one adsorption intermediate before "
                "site generation."
            )

        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage": "c12.1",
            "status": status,
            "reaction_id": reaction_id,
            "reaction_family": profile.get(
                "reaction_family",
                reaction_profile.get(
                    "reaction_family",
                    "UNKNOWN",
                ),
            ),
            "target_product": target_product,
            "support_level": support_level,
            "primary_adsorbates": primary,
            "competitive_adsorbates": competitive,
            "user_required_adsorbates": (
                required_by_user
            ),
            "formal_adsorbates": formal_adsorbates,
            "candidate_adsorbates": formal_adsorbates,
            "selected_adsorbate": None,
            "selected_adsorbate_count": 0,
            "suggested_adsorbates": suggestions,
            "excluded_adsorbates": sorted(
                excluded_by_user
            ),
            "adsorbate_sources": source_records,
            "descriptor_targets": self._string_list(
                profile.get(
                    "descriptor_targets",
                    [],
                )
            ),
            "reference_strategy": profile.get(
                "reference_strategy",
            ),
            "reference_energy_definitions": reference_definitions,
            "reference_data_version": reference_config["data_version"],
            "requires_clean_slab_energy": bool(
                profile.get(
                    "requires_clean_slab_energy",
                    True,
                )
            ),
            "requires_gas_phase_references": bool(
                profile.get(
                    "requires_gas_phase_references",
                    True,
                )
            ),
            "ready_for_site_generation": ready,
            "requires_human_confirmation": True,
            "activity_prediction_performed": False,
            "structure_generation_performed": False,
            "remote_operation_performed": False,
            "profile_data_version": config[
                "data_version"
            ],
            "profile_config_path": str(
                self.config_path.resolve()
            ),
            "reason": reason,
            "warnings": self._unique(warnings),
            "next_stage": (
                "c12.1_single_intermediate_review"
                if formal_adsorbates
                else "human_reaction_plan_review"
            ),
        }

    def _load_reference_config(self) -> dict[str, Any]:
        if not self.reference_config_path.is_file():
            raise FileNotFoundError(
                "Reference-energy configuration does not exist: "
                f"{self.reference_config_path}"
            )
        value = json.loads(
            self.reference_config_path.read_text(encoding="utf-8")
        )
        if value.get("schema_version") != "adsorption-reference-energy-v1":
            raise ValueError("Unsupported reference-energy schema")
        if not isinstance(value.get("data_version"), str):
            raise ValueError("Reference-energy data_version is required")
        if not isinstance(value.get("adsorbates"), dict):
            raise TypeError("Reference-energy adsorbates must be an object")
        return value

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            raise FileNotFoundError(
                "Adsorption reaction profile does not "
                f"exist: {self.config_path}"
            )

        value = json.loads(
            self.config_path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(value, dict):
            raise TypeError(
                "Adsorption profile must contain "
                "a JSON object"
            )

        if (
            value.get("schema_version")
            != "adsorption-reaction-profile-v1"
        ):
            raise ValueError(
                "Unsupported adsorption profile schema"
            )

        if value.get("status") != "accepted":
            raise ValueError(
                "Adsorption profile is not accepted"
            )

        data_version = value.get("data_version")
        if not isinstance(data_version, str) or not data_version:
            raise ValueError(
                "Adsorption profile data_version is required"
            )

        profiles = value.get("profiles")
        if not isinstance(profiles, dict):
            raise TypeError(
                "Adsorption profiles must be a dictionary"
            )

        for reaction_id, profile in profiles.items():
            if not isinstance(reaction_id, str):
                raise TypeError(
                    "Reaction profile IDs must be strings"
                )

            if not isinstance(profile, dict):
                raise TypeError(
                    f"Profile {reaction_id} must be an object"
                )

            self._validate_profile(
                reaction_id,
                profile,
            )

        return deepcopy(value)

    def _validate_profile(
        self,
        reaction_id: str,
        profile: dict[str, Any],
    ) -> None:
        required = {
            "reaction_family",
            "target_product",
            "support_level",
            "primary_adsorbates",
            "competitive_adsorbates",
            "descriptor_targets",
            "reference_strategy",
            "requires_clean_slab_energy",
            "requires_gas_phase_references",
        }

        missing = sorted(
            required - set(profile)
        )

        if missing:
            raise ValueError(
                f"Profile {reaction_id} is missing: "
                + ", ".join(missing)
            )

        for field in (
            "primary_adsorbates",
            "competitive_adsorbates",
            "descriptor_targets",
        ):
            if not isinstance(
                profile.get(field),
                list,
            ):
                raise TypeError(
                    f"{reaction_id}.{field} must be a list"
                )

    def _unsupported_result(
        self,
        reaction_id: str,
        data_version: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage": "c12.1",
            "status": (
                "adsorption_reaction_unsupported"
            ),
            "reaction_id": reaction_id,
            "reaction_family": "UNKNOWN",
            "target_product": None,
            "support_level": "unsupported",
            "primary_adsorbates": [],
            "competitive_adsorbates": [],
            "user_required_adsorbates": [],
            "formal_adsorbates": [],
            "suggested_adsorbates": [],
            "excluded_adsorbates": [],
            "adsorbate_sources": [],
            "descriptor_targets": [],
            "reference_strategy": None,
            "requires_clean_slab_energy": True,
            "requires_gas_phase_references": True,
            "ready_for_site_generation": False,
            "requires_human_confirmation": True,
            "activity_prediction_performed": False,
            "structure_generation_performed": False,
            "remote_operation_performed": False,
            "profile_data_version": data_version,
            "profile_config_path": str(
                self.config_path.resolve()
            ),
            "reason": (
                "No accepted adsorption profile exists "
                f"for reaction {reaction_id}."
            ),
            "warnings": [
                "C12 must not reuse another reaction's "
                "adsorbates automatically."
            ],
            "next_stage": (
                "human_reaction_profile_definition"
            ),
        }

    @staticmethod
    def _string_list(
        values: Any,
    ) -> list[str]:
        if not isinstance(values, list):
            raise TypeError(
                "Adsorbate values must be a list"
            )

        result = []

        for value in values:
            text = str(value).strip()

            if text and text not in result:
                result.append(text)

        return result

    @staticmethod
    def _unique(
        values: list[str],
    ) -> list[str]:
        result = []

        for value in values:
            if value and value not in result:
                result.append(value)

        return result
