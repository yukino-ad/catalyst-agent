from __future__ import annotations

from typing import Any, TypedDict


class CatalystState(TypedDict, total=False):
    """All state shared by the catalyst LangGraph nodes."""

    # Basic task information.
    task_id: str
    question: str

    # A-stage task understanding and capability routing.
    task_analysis: dict[str, Any]
    canonical_task_context: dict[str, Any]
    task_context_validation: dict[str, Any]
    direct_c_stage: dict[str, Any]
    external_structure_request: dict[str, Any]
    external_structure_ingestion: dict[str, Any]
    workflow_stop_reason: str
    reaction_profile: dict[str, Any]
    capability: dict[str, Any]
    route: dict[str, Any]
    plan: dict[str, Any]

    # B2-B6 literature evidence workflow.
    local_literature_result: dict[str, Any]
    online_search_policy: dict[str, Any]
    online_literature_result: dict[str, Any]
    kimi_crossref_verification: dict[str, Any]
    merged_literature_result: dict[str, Any]
    literature_assertion_extraction: dict[str, Any]
    accepted_literature_assertions: list[dict[str, Any]]
    literature_evidence_contract: dict[str, Any]
    literature_review: dict[str, Any]
    literature_commit: dict[str, Any]
    literature_search_round: int
    literature_max_search_rounds: int
    literature_search_history: list[dict[str, Any]]
    rejected_literature_identities: list[str]
    literature_retry_plan: dict[str, Any]
    accepted_literature_papers: list[dict[str, Any]]
    accepted_literature_assertion_history: list[dict[str, Any]]
    literature_evidence_gap: dict[str, Any]
    rag_result: dict[str, Any]
    papers: list[dict[str, Any]]
    literature_summary: dict[str, Any]

    # R1: whether this reaction and material family may enter C stage.
    c_stage_capability: dict[str, Any]

    # Optional structured user overrides for C1.
    candidate_user_overrides: dict[str, Any]

    # C1: hard constraints for candidate generation.
    candidate_constraints: dict[str, Any]

    # C2+C3: generated candidates and their soft-score ranking.
    candidate_generation: dict[str, Any]

    # C4: human review result for displayed candidates.
    candidate_review: dict[str, Any]

    # Candidates accepted by the user for later FCC modeling.
    selected_candidates: list[dict[str, Any]]

    # C4.6: user-approved boundary for subsequent theoretical work.
    c_stage_execution_review: dict[str, Any]
    c_stage_execution_mode: str

    # C5: FCC bulk modeling result.
    structure_modeling: dict[str, Any]

    # Flat list of successfully generated C5 bulk structures.
    bulk_structures: list[dict[str, Any]]

    # C6: CGCNN prediction and DFT routing summary.
    formation_energy_evaluation: dict[str, Any]

    # C5 structures enriched with C6 formation-energy fields.
    formation_energy_structures: list[dict[str, Any]]

    # C6 optional temporary-model comparison and approved source.
    formation_energy_comparison: dict[str, Any]
    formation_energy_source_review: dict[str, Any]
    selected_formation_energy_source: str
    selected_formation_energy_structures: list[dict[str, Any]]

    # Structures outside the CGCNN training domain.
    dft_formation_energy_queue: list[dict[str, Any]]

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
    
    # C11 shared execution choices for bulk and slab DFT jobs.
    dft_execution_options: dict[str, Any]
    dft_preflight_jobs: list[dict[str, Any]]
    dft_job_source: str
    	
    # C11.2 local five-file preflight.
    dft_local_preflight: dict[str, Any]
    dft_local_preflight_jobs: list[dict[str, Any]]

    # C11.3 read-only cluster environment preflight.
    cluster_readonly_preflight: dict[str, Any]
    cluster_preflight_jobs: list[dict[str, Any]]

    # C11.4.1 deterministic remote upload plan.
    remote_execution_plan: dict[str, Any]

    # First human gate: remote directory and upload approval.
    remote_upload_review: dict[str, Any]

    # C11.4.2 upload and remote SHA-256 verification.
    remote_upload_result: dict[str, Any]
    remote_verified_jobs: list[dict[str, Any]]

    # Second human gate: explicit sbatch approval.
    remote_submission_review: dict[str, Any]

    # C11.4.3 Slurm submission result.
    remote_submission_result: dict[str, Any]
    submitted_dft_jobs: list[dict[str, Any]]

    # C11.5.1 persisted Slurm job records.
    submission_recording: dict[str, Any]
    persisted_cluster_jobs: list[dict[str, Any]]

    # C11.9 durable linkage between the synchronous and asynchronous graphs.
    workflow_run: dict[str, Any]
    scientific_identity: dict[str, Any]
    formation_energy_backfill: dict[str, Any]
    async_stability_screening: dict[str, Any]
    resume_status: str

    # C12.1 deterministic adsorption-intermediate planning.
    adsorption_user_overrides: dict[str, Any]
    adsorption_literature_suggestions: list[str]
    adsorption_reaction_plan: dict[str, Any]
    adsorption_intermediate_review: dict[str, Any]
    selected_adsorbate: str
    reference_energy_definition: dict[str, Any]
    planned_adsorbates: list[str]

    # C12.2 sites from converged, parsed clean-slab CONTCAR files only.
    adsorption_source_slabs: list[dict[str, Any]]
    adsorption_site_generation: dict[str, Any]
    adsorption_sites: list[dict[str, Any]]

    # C12.3 one-adsorbate structure generation.
    adsorbate_structure_generation: dict[str, Any]
    adsorption_structures: list[dict[str, Any]]

    # C12.4 automatic quality and human review.
    adsorption_structure_quality: dict[str, Any]
    quality_passed_adsorption_structures: list[
        dict[str, Any]
    ]
    adsorption_structure_review: dict[str, Any]
    adsorption_dft_approved_structures: list[
        dict[str, Any]
    ]

    # C12.5 adsorption VASP preview, revision, and finalization.
    adsorption_dft_input_preview: dict[str, Any]
    adsorption_dft_input_review: dict[str, Any]
    adsorption_dft_revision_request: dict[str, str]
    adsorption_dft_revision_plan: dict[str, Any]
    adsorption_dft_revision_validation: dict[str, Any]
    adsorption_dft_revision_history: list[dict[str, Any]]
    adsorption_dft_revision_count: int
    adsorption_dft_input_preparation: dict[str, Any]
    adsorption_dft_jobs: list[dict[str, Any]]

    # C12.6 adsorption DFT submission and result lifecycle.
    adsorption_execution_status: dict[str, Any]
    adsorption_result_monitoring: dict[str, Any]
    adsorption_parsed_results: list[dict[str, Any]]
    adsorption_result_ready: dict[str, Any]

    # C12.7 simplified adsorption-energy calculation and review.
    clean_slab_energies: dict[str, Any]
    reference_energies: dict[str, Any]
    adsorption_energy_calculation: dict[str, Any]
    adsorption_energy_drafts: list[dict[str, Any]]
    adsorption_energy_review: dict[str, Any]
    approved_adsorption_energies: list[dict[str, Any]]
    	
    # C7: formation-energy and delta/Omega screening result.
    stability_screening: dict[str, Any]

    # All structures enriched with C7 screening fields.
    stability_screened_structures: list[dict[str, Any]]

    # Only structures that may enter C8 slab generation.
    slab_eligible_structures: list[dict[str, Any]]

    # Human selection of C7-passed structures allowed to enter DFT.
    c7_dft_upgrade_review: dict[str, Any]
    dft_selected_stability_structures: list[dict[str, Any]]

    # C8: FCC(111) slab generation result.
    slab_generation: dict[str, Any]

    # Successfully generated 48-atom slab structures.
    generated_slabs: list[dict[str, Any]]

    # C9 automatic slab geometry and file-quality inspection.
    slab_quality: dict[str, Any]

    # Slabs that passed every automatic C9 quality criterion.
    quality_passed_slabs: list[dict[str, Any]]

    # C9 human review result.
    slab_review: dict[str, Any]

    # Slabs approved by the user for future DFT preparation.
    dft_approved_slabs: list[dict[str, Any]]

    # C10 five-file VASP preview.
    dft_input_preview: dict[str, Any]

    # C10 human review result.
    dft_input_review: dict[str, Any]

    # C10 controlled natural-language revision state.
    dft_revision_request: dict[str, str]
    dft_revision_plan: dict[str, Any]
    dft_revision_validation: dict[str, Any]
    dft_revision_history: list[dict[str, Any]]
    dft_revision_count: int

    # C10 finalized VASP calculation directories.
    dft_input_preparation: dict[str, Any]

    # Successfully generated DFT jobs.
    dft_jobs: list[dict[str, Any]]

    # Shared execution diagnostics.
    errors: list[dict[str, Any]]
    warnings: list[str]
    status: str
    retry_count: int
