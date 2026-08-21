from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.capability_gate import CapabilityGate
from app.domain.adsorption_reaction_planner import (
    AdsorptionReactionPlanner,
)
from app.domain.adsorption_site_generation import (
    AdsorptionSiteGenerationService,
)
from app.domain.adsorbate_structure_builder import (
    AdsorbateStructureBuilder,
)
from app.domain.adsorption_structure_quality import (
    AdsorptionStructureQualityInspector,
)
from app.domain.adsorption_structure_review import (
    AdsorptionStructureReviewGate,
)
from app.domain.adsorption_dft_input_bundle import (
    AdsorptionVaspInputBundleService,
)
from app.domain.adsorption_energy import (
    AdsorptionEnergyCalculator,
)
from app.domain.adsorption_energy_review import (
    AdsorptionEnergyReviewGate,
)
from app.domain.candidate_constraints import (
    CandidateConstraintBuilder,
)
from app.domain.candidate_evaluator import (
    CandidateEvaluator,
)
from app.domain.candidate_generation import (
    ConstraintDrivenCandidateGenerator,
)
from app.domain.candidate_review import (
    CandidateReviewGate,
)
from app.domain.bulk_dft_input_bundle import (
    BulkFormationVaspBundleService,
)
from app.domain.bulk_dft_input_revision import (
    BulkDFTInputRevisionService,
)
from app.domain.formation_energy import (
    FormationEnergyEvaluator,
)
from app.domain.dft_input_bundle import (
    VaspInputBundleService,
)
from app.domain.dft_input_revision import (
    DFTInputRevisionService,
)
from app.domain.dft_local_preflight import (
    DFTLocalPreflightService,
)
from app.domain.cluster_readonly_preflight import (
    ClusterReadonlyPreflightService,
)
from app.domain.remote_execution_plan import (
    RemoteExecutionPlanService,
)
from app.domain.remote_upload import (
    RemoteUploadService,
)
from app.domain.remote_submission import (
    RemoteSubmissionService,
)
from app.domain.submitted_job_repository import (
    SubmittedJobRepository,
)
from app.domain.reaction_profiles import (
    resolve_c_stage_capability,
)
from app.domain.slab_generation import (
    SlabGenerationService,
)
from app.domain.slab_quality import (
    SlabQualityInspector,
)
from app.domain.slab_review import (
    SlabReviewGate,
)
from app.domain.stability_screening import (
    StabilityScreeningEvaluator,
)
from app.domain.structure_modeling import (
    FCCStructureModeler,
)
from app.domain.task_context import TaskContextBuilder
from app.planner import TaskPlanner
from app.task_analyzer import TaskAnalyzer
from app.task_router import TaskRouter
from tools.cgcnn_service import CGCNNService
from tools.literature.evidence_merger import (
    LiteratureEvidenceMerger,
)
from tools.literature.extraction_service import (
    LiteratureAssertionExtractionService,
)
from tools.literature.extractor import LiteratureExtractor
from tools.literature.local_retriever import (
    LocalLiteratureRetriever,
)
from tools.literature.kimi_crossref_verifier import (
    KimiCrossrefVerifier,
)
from tools.literature.online_retriever import (
    OnlineLiteratureRetriever,
)
from tools.literature.online_search_policy import (
    OnlineSearchPolicy,
)
from tools.literature.review_gate import (
    LiteratureReviewGate,
)
from tools.literature_rag import LiteratureRAG


CStageResolver = Callable[
    [
        dict[str, Any],
        list[dict[str, Any]] | None,
    ],
    dict[str, Any],
]


@dataclass
class GraphServices:
    """Services shared by all LangGraph nodes."""

    # A-stage services.
    analyzer: TaskAnalyzer
    task_context_builder: TaskContextBuilder
    capability_gate: CapabilityGate
    router: TaskRouter
    planner: TaskPlanner

    # B-stage literature services.
    rag: LiteratureRAG
    local_retriever: LocalLiteratureRetriever
    online_policy: OnlineSearchPolicy
    online_retriever: OnlineLiteratureRetriever
    kimi_crossref_verifier: KimiCrossrefVerifier
    evidence_merger: LiteratureEvidenceMerger
    assertion_extraction: LiteratureAssertionExtractionService
    review_gate: LiteratureReviewGate

    # R1 and C-stage domain services.
    c_stage_resolver: CStageResolver
    candidate_constraint_builder: CandidateConstraintBuilder
    candidate_evaluator: CandidateEvaluator
    candidate_generator: ConstraintDrivenCandidateGenerator
    candidate_review_gate: CandidateReviewGate
    structure_modeler: FCCStructureModeler
    cgcnn: CGCNNService
    formation_energy_evaluator: FormationEnergyEvaluator
    stability_screening_evaluator: StabilityScreeningEvaluator
    slab_generation_service: SlabGenerationService
    slab_quality_inspector: SlabQualityInspector
    slab_review_gate: SlabReviewGate
    vasp_input_bundle_service: VaspInputBundleService
    dft_input_revision_service: DFTInputRevisionService
    bulk_dft_input_bundle_service: BulkFormationVaspBundleService
    bulk_dft_input_revision_service: BulkDFTInputRevisionService
    dft_local_preflight_service: DFTLocalPreflightService
    cluster_readonly_preflight_service: (
        ClusterReadonlyPreflightService
    )
    remote_execution_plan_service: (
        RemoteExecutionPlanService
    )
    remote_upload_service: RemoteUploadService
    remote_submission_service: RemoteSubmissionService
    submitted_job_repository: SubmittedJobRepository
    adsorption_reaction_planner: (
        AdsorptionReactionPlanner
    )
    adsorption_site_generation_service: (
        AdsorptionSiteGenerationService
    )
    adsorbate_structure_builder: (
        AdsorbateStructureBuilder
    )
    adsorption_structure_quality_inspector: (
        AdsorptionStructureQualityInspector
    )
    adsorption_structure_review_gate: (
        AdsorptionStructureReviewGate
    )
    adsorption_dft_input_bundle_service: (
        AdsorptionVaspInputBundleService
    )
    adsorption_dft_input_revision_service: (
        DFTInputRevisionService
    )
    adsorption_energy_calculator: (
        AdsorptionEnergyCalculator
    )
    adsorption_energy_review_gate: (
        AdsorptionEnergyReviewGate
    )


def create_services() -> GraphServices:
    """Create the service container used by LangGraph nodes."""

    planner = TaskPlanner()

    analyzer = TaskAnalyzer(
        llm=planner.llm,
    )

    router = TaskRouter(
        llm=planner.llm,
    )

    rag = LiteratureRAG(
        llm=planner.llm,
    )

    constraint_builder = CandidateConstraintBuilder()
    cgcnn = CGCNNService()

    vasp_service = VaspInputBundleService()
    bulk_vasp_service = BulkFormationVaspBundleService()
    adsorption_vasp_service = (
        AdsorptionVaspInputBundleService()
    )

    return GraphServices(
        analyzer=analyzer,
        task_context_builder=TaskContextBuilder(),
        capability_gate=CapabilityGate(),
        router=router,
        planner=planner,
        rag=rag,
        local_retriever=LocalLiteratureRetriever(),
        online_policy=OnlineSearchPolicy(),
        online_retriever=OnlineLiteratureRetriever(),
        kimi_crossref_verifier=KimiCrossrefVerifier(
            llm=planner.llm,
        ),
        evidence_merger=LiteratureEvidenceMerger(),
        assertion_extraction=LiteratureAssertionExtractionService(
            extractor=LiteratureExtractor(llm=planner.llm),
        ),
        review_gate=LiteratureReviewGate(),
        c_stage_resolver=resolve_c_stage_capability,
        candidate_constraint_builder=constraint_builder,
        candidate_evaluator=CandidateEvaluator(),
        candidate_generator=ConstraintDrivenCandidateGenerator(
            constraint_builder=constraint_builder,
        ),
        candidate_review_gate=CandidateReviewGate(
            max_selected=3,
        ),
        structure_modeler=FCCStructureModeler(),
        cgcnn=cgcnn,
        formation_energy_evaluator=(
            FormationEnergyEvaluator(cgcnn=cgcnn)
        ),
        stability_screening_evaluator=(
            StabilityScreeningEvaluator()
        ),
        slab_generation_service=(
            SlabGenerationService()
        ),
        slab_quality_inspector=(
            SlabQualityInspector()
        ),
        slab_review_gate=SlabReviewGate(
            max_approved=3,
        ),
        vasp_input_bundle_service=vasp_service,
        dft_input_revision_service=DFTInputRevisionService(
            bundle_service=vasp_service,
            llm=planner.llm,
        ),
        bulk_dft_input_bundle_service=bulk_vasp_service,
        bulk_dft_input_revision_service=BulkDFTInputRevisionService(
            bundle_service=bulk_vasp_service,
            llm=planner.llm,
        ),
        dft_local_preflight_service=DFTLocalPreflightService(),
        cluster_readonly_preflight_service=(
            ClusterReadonlyPreflightService()
        ),
        remote_execution_plan_service=(
            RemoteExecutionPlanService()
        ),
        remote_upload_service=RemoteUploadService(),
        remote_submission_service=(
            RemoteSubmissionService()
        ),
        submitted_job_repository=(
            SubmittedJobRepository()
        ),
        adsorption_reaction_planner=(
            AdsorptionReactionPlanner()
        ),
        adsorption_site_generation_service=(
            AdsorptionSiteGenerationService()
        ),
        adsorbate_structure_builder=(
            AdsorbateStructureBuilder()
        ),
        adsorption_structure_quality_inspector=(
            AdsorptionStructureQualityInspector()
        ),
        adsorption_structure_review_gate=(
            AdsorptionStructureReviewGate(
                max_approved=15,
            )
        ),
        adsorption_dft_input_bundle_service=(
            adsorption_vasp_service
        ),
        adsorption_dft_input_revision_service=(
            DFTInputRevisionService(
                bundle_service=adsorption_vasp_service,
                llm=planner.llm,
            )
        ),
        adsorption_energy_calculator=(
            AdsorptionEnergyCalculator()
        ),
        adsorption_energy_review_gate=(
            AdsorptionEnergyReviewGate()
        ),
    )
