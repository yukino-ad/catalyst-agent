from __future__ import annotations

import argparse
import sys
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = PROJECT_ROOT / "tests"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Full-graph, interrupt/resume, and public-entrypoint tests belong here.
E2E_MODULES = frozenset({
    "test_graph_candidate_end_to_end",
    "test_graph_stage1",
    "test_main_entrypoint",
})

# Graph-node wiring and multi-service lifecycle tests belong here.
INTEGRATION_MODULES = frozenset({
    "test_a_stage_rag_context",
    "test_graph_adsorption_reaction_planning",
    "test_graph_adsorption_site_generation",
    "test_graph_bulk_dft",
    "test_graph_c_stage_services",
    "test_graph_candidate_nodes",
    "test_graph_candidate_workflow",
    "test_graph_cli",
    "test_graph_cluster_readonly_preflight",
    "test_graph_dft_execution_options",
    "test_graph_dft_input_bundle",
    "test_graph_dft_local_preflight",
    "test_graph_formation_energy",
    "test_graph_remote_execution_plan",
    "test_graph_remote_submission",
    "test_graph_remote_upload",
    "test_graph_slab_generation",
    "test_graph_slab_quality",
    "test_graph_stability_screening",
    "test_graph_structure_modeling",
    "test_graph_submission_recording",
    "test_graph_task_analysis",
    "test_job_operations",
    "test_job_operations_graph",
    "test_graph_adsorbate_structure_generation",
    "test_graph_adsorption_structure_review",
    "test_graph_adsorption_dft",
    "test_adsorption_workflow",
    "test_graph_adsorption_execution",
    "test_adsorption_job_operations",
})


def discover_module_names() -> set[str]:
    return {
        path.stem
        for path in TEST_ROOT.glob("test_*.py")
    }


def classified_modules() -> dict[str, set[str]]:
    all_modules = discover_module_names()
    e2e = set(E2E_MODULES)
    integration = set(INTEGRATION_MODULES)
    fast = all_modules - e2e - integration
    return {
        "fast": fast,
        "integration": integration,
        "e2e": e2e,
        "all": all_modules,
    }


def validate_classification() -> None:
    discovered = discover_module_names()
    overlap = E2E_MODULES & INTEGRATION_MODULES
    unknown = (E2E_MODULES | INTEGRATION_MODULES) - discovered
    if overlap:
        raise RuntimeError(
            "Test modules belong to multiple suites: "
            + ", ".join(sorted(overlap))
        )
    if unknown:
        raise RuntimeError(
            "Classified test modules do not exist: "
            + ", ".join(sorted(unknown))
        )
    groups = classified_modules()
    union = groups["fast"] | groups["integration"] | groups["e2e"]
    if union != discovered:
        raise RuntimeError("Test suite classification does not cover discovery")


def load_suite(name: str) -> unittest.TestSuite:
    validate_classification()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for module in sorted(classified_modules()[name]):
        suite.addTests(loader.loadTestsFromName(f"tests.{module}"))
    return suite


def print_modules(name: str) -> None:
    validate_classification()
    modules = classified_modules()[name]
    print(f"suite: {name}")
    print(f"module_count: {len(modules)}")
    for module in sorted(modules):
        print(f"- {module}")


def run(name: str, verbosity: int) -> bool:
    suite = load_suite(name)
    test_count = suite.countTestCases()
    started = time.perf_counter()
    result = unittest.TextTestRunner(
        verbosity=verbosity,
        stream=sys.stdout,
    ).run(suite)
    elapsed = time.perf_counter() - started
    print("\n" + "=" * 70)
    print("Test suite summary")
    print("=" * 70)
    print(f"suite: {name}")
    print(f"test_count: {test_count}")
    print(f"elapsed_seconds: {elapsed:.3f}")
    print(f"failures: {len(result.failures)}")
    print(f"errors: {len(result.errors)}")
    print(f"skipped: {len(result.skipped)}")
    print(f"successful: {result.wasSuccessful()}")
    return result.wasSuccessful()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Catalyst Agent tests by speed and scope."
    )
    parser.add_argument(
        "suite",
        choices=("fast", "integration", "e2e", "all"),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List classified modules without running tests.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Use compact unittest output.",
    )
    args = parser.parse_args()
    if args.list:
        print_modules(args.suite)
        return
    success = run(args.suite, verbosity=1 if args.quiet else 2)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
