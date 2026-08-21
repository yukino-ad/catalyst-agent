from __future__ import annotations

from typing import Any


LOW_RISK_REVIEW_TYPES = {
    "literature_review_required",
    "candidate_review_required",
    "c_stage_execution_review_required",
    "formation_energy_source_review_required",
    "c7_dft_upgrade_review_required",
    "slab_review_required",
    "bulk_dft_input_review_required",
    "dft_input_review_required",
    "adsorption_dft_input_review_required",
    "adsorption_energy_review_required",
    "dft_execution_options_required",
    "remote_upload_review_required",
    "remote_submission_review_required",
    "result_download_review_required",
    "adsorption_intermediate_review_required",
    "adsorption_structure_review_required",
    "adsorption_dft_execution_required",
}


def validate_review_decision(
    review: dict[str, Any],
    review_type: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    if review_type not in LOW_RISK_REVIEW_TYPES:
        raise ValueError("This review type is not enabled in F3 yet.")
    if review_type in {
        "remote_upload_review_required",
        "remote_submission_review_required",
    }:
        return _remote_operation_decision(review, review_type, decision)
    if review_type == "result_download_review_required":
        known = _known_ids(review.get("items", []), "slurm_job_id")
        normalized = _classify(decision, known, ("approve", "reject", "defer"))
        _require_complete_classification(normalized, known)
        approved = normalized["approve"]
        expected = str(review.get("confirmation_phrase", ""))
        confirmation = str(decision.get("confirmation_text", ""))
        if approved and confirmation != expected:
            raise ValueError("Download confirmation phrase does not match.")
        return {
            "action": "approve_download" if approved else "defer",
            "approved_slurm_job_ids": approved,
            "confirmation_text": confirmation if approved else "",
            "note": _note(decision),
        }
    if review_type in {
        "c_stage_execution_review_required",
        "formation_energy_source_review_required",
        "dft_execution_options_required",
        "adsorption_dft_execution_required",
        "adsorption_intermediate_review_required",
    }:
        allowed = {
            str(item.get("mode", ""))
            for item in review.get("options", [])
            if isinstance(item, dict)
        }
        mode = str(decision.get("mode", "")).strip()
        if mode not in allowed:
            raise ValueError("Unknown execution mode.")
        if (
            review_type == "formation_energy_source_review_required"
            and mode == "temporary_trained"
            and review.get("temporary_model_ready") is not True
        ):
            raise ValueError("Temporary CGCNN training has not completed.")
        if review_type == "adsorption_intermediate_review_required":
            return {"selected_adsorbate": mode, "note": _note(decision)}
        return {"mode": mode, "note": _note(decision)}

    if review_type == "literature_review_required":
        known = _known_ids(review.get("items", []), "evidence_id")
        normalized = _classify(decision, known, ("accept", "reject", "defer"))
        _require_complete_classification(normalized, known)
        accepted_evidence_ids = set(normalized["accept"])
        assertion_ids = {
            str(assertion.get("assertion_id", "")).strip()
            for item in review.get("items", [])
            if isinstance(item, dict)
            and str(item.get("evidence_id", "")).strip() in accepted_evidence_ids
            for assertion in item.get("assertions", [])
            if isinstance(assertion, dict) and assertion.get("assertion_id")
        }
        assertion_decision = decision.get("assertions", {})
        if not isinstance(assertion_decision, dict):
            assertion_decision = {}
        normalized["assertions"] = _filter_classification(
            assertion_decision, assertion_ids, ("accept", "reject", "defer")
        )
        normalized["note"] = _note(decision)
        return normalized

    if review_type == "candidate_review_required":
        id_field, primary = "candidate_id", "select"
    elif review_type == "c7_dft_upgrade_review_required":
        id_field, primary = "structure_id", "select"
    elif review_type == "slab_review_required":
        id_field, primary = "slab_id", "approve"
    elif review_type == "adsorption_structure_review_required":
        id_field, primary = "adsorption_structure_id", "approve"
    elif review_type in {"bulk_dft_input_review_required", "dft_input_review_required", "adsorption_dft_input_review_required"}:
        id_field, primary = "bundle_id", "approve"
    else:
        id_field, primary = "adsorption_energy_id", "approve"
    known = _known_ids(review.get("items", []), id_field)
    normalized = _classify(decision, known, (primary, "reject", "defer"))
    revision_requests: dict[str, str] = {}
    if id_field == "bundle_id":
        revision_requests = _revision_requests(decision, known)
    if revision_requests:
        classified = {
            identifier
            for identifiers in normalized.values()
            for identifier in identifiers
        }
        conflicts = classified & set(revision_requests)
        if conflicts:
            raise ValueError(
                "A VASP bundle cannot be both revised and classified: "
                f"{sorted(conflicts)}"
            )
        _require_complete_classification(
            normalized,
            known - set(revision_requests),
        )
        normalized["action"] = "revise"
        normalized["revision_requests"] = revision_requests
    else:
        if str(decision.get("action", "finalize")).strip() == "revise":
            raise ValueError("A revision action requires revision_requests.")
        _require_complete_classification(normalized, known)
        if id_field == "bundle_id":
            normalized["action"] = "finalize"
    max_selected = int(review.get("max_selected", len(known)) or len(known))
    if len(normalized[primary]) > max_selected:
        raise ValueError(f"At most {max_selected} items may be selected.")
    if id_field == "bundle_id":
        confirmations = decision.get("file_confirmations", {})
        if not isinstance(confirmations, dict):
            raise ValueError("file_confirmations must be a dictionary.")
        required = review.get("required_files", [])
        for bundle_id in normalized["approve"]:
            values = confirmations.get(bundle_id, {})
            if not isinstance(values, dict) or any(values.get(name) is not True for name in required):
                raise ValueError(f"All five files must be confirmed for {bundle_id}.")
        normalized["file_confirmations"] = confirmations
    normalized["note"] = _note(decision)
    return normalized


def _known_ids(items: Any, field: str) -> set[str]:
    if not isinstance(items, list):
        return set()
    return {
        str(item.get(field, "")).strip()
        for item in items
        if isinstance(item, dict) and item.get(field)
    }


def _classify(
    decision: dict[str, Any],
    known: set[str],
    fields: tuple[str, str, str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    seen: set[str] = set()
    for field in fields:
        raw = decision.get(field, [])
        values = [raw] if isinstance(raw, str) else raw
        if not isinstance(values, list):
            raise ValueError(f"{field} must be a list of identifiers.")
        identifiers = [str(value).strip() for value in values if str(value).strip()]
        unknown = set(identifiers) - known
        if unknown:
            raise ValueError(f"Unknown review identifiers: {sorted(unknown)}")
        conflict = set(identifiers) & seen
        if conflict:
            raise ValueError(f"Identifiers have conflicting decisions: {sorted(conflict)}")
        seen.update(identifiers)
        result[field] = list(dict.fromkeys(identifiers))
    return result


def _filter_classification(
    decision: dict[str, Any],
    allowed: set[str],
    fields: tuple[str, str, str],
) -> dict[str, list[str]]:
    """Keep only assertions belonging to papers accepted in this review."""
    filtered: dict[str, Any] = {}
    for field in fields:
        raw = decision.get(field, [])
        values = [raw] if isinstance(raw, str) else raw
        if not isinstance(values, list):
            raise ValueError(f"{field} must be a list of identifiers.")
        filtered[field] = [
            str(value).strip()
            for value in values
            if str(value).strip() in allowed
        ]
    return _classify(filtered, allowed, fields)


def _require_complete_classification(
    decision: dict[str, list[str]],
    known: set[str],
) -> None:
    decided = {
        identifier
        for identifiers in decision.values()
        for identifier in identifiers
    }
    missing = known - decided
    if missing:
        raise ValueError(
            "Every review item requires an explicit decision; "
            f"missing: {sorted(missing)}"
        )


def _revision_requests(
    decision: dict[str, Any],
    known: set[str],
) -> dict[str, str]:
    raw = decision.get("revision_requests", {})
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("revision_requests must be a dictionary.")
    result: dict[str, str] = {}
    for identifier, request in raw.items():
        bundle_id = str(identifier).strip()
        text = str(request).strip()
        if bundle_id not in known:
            raise ValueError(f"Unknown review identifiers: {[bundle_id]}")
        if not text:
            raise ValueError(f"Revision request for {bundle_id} is empty.")
        if len(text) > 4000:
            raise ValueError(f"Revision request for {bundle_id} is too long.")
        result[bundle_id] = text
    return result


def _note(decision: dict[str, Any]) -> str:
    return str(decision.get("note", "")).strip()[:2000]


def _remote_operation_decision(
    review: dict[str, Any],
    review_type: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    action = str(decision.get("action", "defer")).strip()
    approve_action = (
        "approve_upload"
        if review_type == "remote_upload_review_required"
        else "approve_submission"
    )
    if action not in {approve_action, "defer"}:
        raise ValueError("Unsupported remote operation decision.")
    if action == "defer":
        return {
            "action": "defer",
            "approved_job_ids": [],
            "plan_digest": str(review.get("plan_digest", "")),
            "confirmation_text": "",
            "note": _note(decision),
        }

    known = _known_ids(review.get("items", []), "job_id")
    approved = decision.get("approved_job_ids", [])
    if not isinstance(approved, list):
        raise ValueError("approved_job_ids must be a list.")
    approved_ids = [str(value).strip() for value in approved if str(value).strip()]
    if not approved_ids:
        raise ValueError("At least one job must be approved.")
    if len(approved_ids) != len(set(approved_ids)):
        raise ValueError("approved_job_ids contains duplicates.")
    unknown = set(approved_ids) - known
    if unknown:
        raise ValueError(f"Unknown review identifiers: {sorted(unknown)}")

    expected = str(review.get("confirmation_phrase", ""))
    confirmation = str(decision.get("confirmation_text", ""))
    if not expected or confirmation != expected:
        raise ValueError("Confirmation phrase does not match exactly.")
    return {
        "action": approve_action,
        "approved_job_ids": approved_ids,
        "plan_digest": str(review.get("plan_digest", "")),
        "confirmation_text": confirmation,
        "note": _note(decision),
    }
