"""Integrated, offline Phase 2 audit and evidence-package construction."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from scene_grammar_kit.assisted import (
    load_annotation,
    load_construction_config,
    validate_assisted_input,
)
from scene_grammar_kit.demo.runner import compare_scene_builds
from scene_grammar_kit.geometry.serialization import (
    atomic_write_bytes,
    atomic_write_text,
)
from scene_grammar_kit.grammar import (
    grammar_to_canonical_json,
    load_grammar,
    validate_grammar,
)
from scene_grammar_kit.paths import OutputDirectoryError, create_output_directory
from scene_grammar_kit.phase2_acceptance.models import (
    PHASE2_ACCEPTANCE_POLICY_VERSION,
    AcceptanceStatus,
    Phase2AcceptanceCheck,
    Phase2AcceptanceReport,
    Phase2CaseAcceptance,
    Phase2EvidenceRow,
)
from scene_grammar_kit.phase2_acceptance.persistence import (
    artifact_index,
    artifact_to_data,
    attribution_to_markdown,
    canonical_json,
    evidence_row_to_data,
    evidence_to_csv,
    evidence_to_markdown,
    report_to_data,
    report_to_markdown,
)
from scene_grammar_kit.real_cases import (
    build_open_images_cases,
    refresh_review_figures,
)
from scene_grammar_kit.real_cases.open_images import (
    ALLOWED_IMAGE_LICENSES,
    OPEN_IMAGES_ANNOTATION_LICENSE,
)

CASE_ORDER = ("canonical_success", "moderate_case", "limitation_case")
REPRODUCTION_COMMAND = (
    "python -m scene_grammar_kit phase2-acceptance "
    "--cases inputs/real_cases --results results/real_cases "
    "--output results/phase2_acceptance --verify-determinism"
)
NEXT_STEP = "public release validation and broader evaluation"
HERO_SUBTITLE = (
    "Annotation-assisted coarse proxy; not automatic or photorealistic reconstruction."
)
EXPECTED_IDENTITIES = {
    "canonical_success": {
        "image_id": "736a482693c18962",
        "title": "Statens Hus, Leikanger",
        "author": "Kulturnett Sogn og Fjordane",
        "license_url": "https://creativecommons.org/licenses/by/2.0/",
        "outcome": "success",
        "primary": "repeat",
        "accepted": 1,
        "fallback": 0,
    },
    "moderate_case": {
        "image_id": "40992cf7a7bbf20e",
        "title": "Komotini-Demokratias Avenue and Parking",
        "author": "Sir Adavis",
        "license_url": "https://creativecommons.org/licenses/by/2.0/",
        "outcome": "success",
        "primary": "repeat",
        "accepted": 1,
        "fallback": 0,
    },
    "limitation_case": {
        "image_id": "692c5c6be088dbf8",
        "title": "Ugliest building in Turku, original",
        "author": "Henry Hagnäs",
        "license_url": "https://creativecommons.org/licenses/by/2.0/",
        "outcome": "degraded_success",
        "primary": "split_only",
        "accepted": 0,
        "fallback": 0,
    },
}
EXPECTED_PROTOCOL_FILES = (
    "README.md",
    "scope.md",
    "system.md",
    "metrics.md",
)
EXPECTED_PHASE2_DOCS = (
    "phase2_annotation_contract.md",
    "phase2_annotation_review.md",
    "phase2_coarse_lifting.md",
    "phase2_split_induction.md",
    "phase2_repeat_induction.md",
    "phase2_constructor.md",
    "phase2_real_cases.md",
    "phase2_acceptance.md",
)
OUTPUT_PATHS = (
    "README.md",
    "phase2_acceptance.json",
    "phase2_acceptance.md",
    "phase2_evidence_summary.json",
    "phase2_evidence_summary.csv",
    "phase2_evidence_summary.md",
    "artifact_index.json",
    "attribution.json",
    "ATTRIBUTION.md",
    "phase2_regression_manifest.json",
    "review/canonical_success.png",
    "review/moderate_case.png",
    "review/limitation_case.png",
    "review/three_case_overview.png",
    "review/overview_candidate.png",
)


class Phase2AcceptanceError(RuntimeError):
    """A persistence or invocation error outside individual audit checks."""


@dataclass(frozen=True, slots=True)
class Phase2AcceptanceResult:
    output_directory: Path
    report: Phase2AcceptanceReport
    evidence_rows: tuple[Phase2EvidenceRow, ...]
    attribution_records: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _CaseAudit:
    acceptance: Phase2CaseAcceptance
    evidence: Phase2EvidenceRow
    attribution: dict[str, Any]
    manifest: dict[str, Any]
    annotation: dict[str, Any]
    constructor: dict[str, Any]
    real_report: dict[str, Any]


def run_phase2_acceptance(
    cases_directory: Path,
    results_directory: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
    verify_determinism: bool = False,
    regression_manifest_path: Path | None = None,
) -> Phase2AcceptanceResult:
    """Audit the frozen workflow and atomically package all Phase 2 evidence."""
    repository = Path(__file__).resolve().parents[3]
    cases_root = Path(cases_directory).expanduser().resolve()
    results_root = Path(results_directory).expanduser().resolve()
    output_requested = Path(output_directory).expanduser().resolve()
    regression_path = (
        repository / "tests" / "fixtures" / "phase2" / "phase2_regression_manifest.json"
        if regression_manifest_path is None
        else Path(regression_manifest_path).expanduser().resolve()
    )
    try:
        output = create_output_directory(
            output_requested,
            allow_nonempty=overwrite,
        )
    except OutputDirectoryError as exc:
        raise Phase2AcceptanceError(str(exc)) from exc
    final_report = output / "phase2_acceptance.json"
    if overwrite and final_report.is_file():
        final_report.unlink()

    checks: list[Phase2AcceptanceCheck] = []
    checks.extend(_repository_checks(repository))
    regression = _load_regression(regression_path, checks)
    checks.append(_case_set_check(cases_root))
    checks.append(_result_set_check(results_root))
    audits: list[_CaseAudit] = []
    for case_key in CASE_ORDER:
        try:
            audit, case_checks = _audit_case(
                case_key,
                cases_root / case_key,
                results_root / case_key,
                results_root,
                regression,
            )
            audits.append(audit)
            checks.extend(case_checks)
        except Exception as exc:
            checks.append(
                _check(
                    f"CASE_{case_key.upper()}_LOAD",
                    f"Load and audit {case_key}.",
                    False,
                    f"Case audit failed: {exc}",
                    case_key=case_key,
                )
            )
    checks.extend(_summary_checks(results_root, audits))
    checks.append(_regression_check(regression, audits))

    review_checks = _copy_review_images(results_root, output)
    checks.extend(review_checks)
    hero_ok, hero_detail = _build_and_verify_hero(cases_root, results_root, output)
    checks.append(
        _check(
            "OVERVIEW_CANDIDATE",
            "The deterministic 2400×1350 overview candidate is complete.",
            hero_ok,
            hero_detail,
            paths=("review/overview_candidate.png",),
        )
    )
    checks.extend(
        _determinism_checks(
            cases_root,
            results_root,
            output,
            verify_determinism=verify_determinism,
        )
    )

    evidence_rows = tuple(audit.evidence for audit in audits)
    attribution_records = tuple(audit.attribution for audit in audits)
    checks.append(_evidence_model_check(evidence_rows))
    checks.append(_attribution_model_check(attribution_records))

    _write_supporting_artifacts(
        output,
        evidence_rows,
        attribution_records,
        regression_path,
    )
    checks.append(_portable_paths_check(output))
    cases = tuple(audit.acceptance for audit in audits)
    report = _make_report(checks, cases)
    atomic_write_text(
        report_to_markdown(report, evidence_rows),
        output / "phase2_acceptance.md",
        overwrite=True,
        create_parents=True,
    )
    atomic_write_text(
        _readme(report),
        output / "README.md",
        overwrite=True,
        create_parents=True,
    )
    index = artifact_index(output, included=OUTPUT_PATHS)
    atomic_write_text(
        canonical_json([artifact_to_data(item) for item in index]),
        output / "artifact_index.json",
        overwrite=True,
        create_parents=True,
    )
    # The structured PASS/FAIL report is intentionally the final write.
    atomic_write_text(
        canonical_json(report_to_data(report)),
        final_report,
        overwrite=True,
        create_parents=True,
    )
    return Phase2AcceptanceResult(
        output_directory=output,
        report=report,
        evidence_rows=evidence_rows,
        attribution_records=attribution_records,
    )


def _repository_checks(repository: Path) -> list[Phase2AcceptanceCheck]:
    protocol = repository / "protocols" / "evaluation_v0_1"
    missing = [
        name for name in EXPECTED_PROTOCOL_FILES if not (protocol / name).is_file()
    ]
    checks = [
        _check(
            "PROTOCOL_FILES",
            "The versioned evaluation protocol is complete.",
            not missing,
            "All protocol files found."
            if not missing
            else "Missing: " + ", ".join(missing),
            paths=tuple(
                f"protocols/evaluation_v0_1/{name}" for name in EXPECTED_PROTOCOL_FILES
            ),
        )
    ]
    docs = repository / "docs"
    missing_docs = [
        name for name in EXPECTED_PHASE2_DOCS if not (docs / name).is_file()
    ]
    checks.append(
        _check(
            "PHASE2_DOCUMENTATION",
            "All required Phase 2 documentation exists.",
            not missing_docs,
            "All required documents found."
            if not missing_docs
            else "Missing: " + ", ".join(missing_docs),
            paths=tuple(f"docs/{name}" for name in EXPECTED_PHASE2_DOCS),
        )
    )
    forbidden_extensions = tuple(
        path.relative_to(repository).as_posix()
        for suffix in ("*.cpp", "*.cu", "*.cuh")
        for path in repository.glob(f"src/**/{suffix}")
    )
    forbidden_imports = []
    pattern = re.compile(r"^\s*(?:import|from)\s+(torch|tensorflow|tkinter|PyQt)", re.M)
    for path in repository.glob("src/**/*.py"):
        if pattern.search(path.read_text(encoding="utf-8")):
            forbidden_imports.append(path.relative_to(repository).as_posix())
    forbidden = sorted((*forbidden_extensions, *forbidden_imports))
    checks.append(
        _check(
            "FORBIDDEN_FUNCTIONALITY",
            "Repository source introduces no neural, GUI, C++, or CUDA dependency.",
            not forbidden,
            "No forbidden implementation found."
            if not forbidden
            else "Found: " + ", ".join(forbidden),
        )
    )
    controlled_ok, controlled_output_detail = _controlled_outputs_are_complete(
        repository
    )
    checks.append(
        _check(
            "CONTROLLED_EVALUATION_COMPLETE",
            "The 12 controlled definitions and metric outputs are complete.",
            controlled_ok,
            controlled_output_detail,
        )
    )
    return checks


def _controlled_outputs_are_complete(repository: Path) -> tuple[bool, str]:
    case_files = sorted(
        (repository / "evaluation" / "benchmark_v0_1" / "cases").glob("*.json")
    )
    try:
        results = json.loads(
            (
                repository / "results" / "evaluation" / "controlled_results.json"
            ).read_text(encoding="utf-8")
        )
        summary = json.loads(
            (
                repository / "results" / "evaluation" / "controlled_summary.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return False, f"Could not load controlled evidence: {exc}"
    complete = (
        len(case_files) == 12
        and isinstance(results, list)
        and len(results) == 12
        and summary.get("valid_grammar_rate", {}).get("denominator") == 12
    )
    return (
        complete,
        "12 case definitions and 12 result rows are present."
        if complete
        else "Controlled definitions, results, or summary counts are incomplete.",
    )


def _load_regression(
    path: Path,
    checks: list[Phase2AcceptanceCheck],
) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        valid = (
            data.get("phase2_acceptance_policy_version")
            == PHASE2_ACCEPTANCE_POLICY_VERSION
            and data.get("case_order") == list(CASE_ORDER)
            and isinstance(data.get("cases"), list)
        )
        checks.append(
            _check(
                "REGRESSION_MANIFEST_LOAD",
                "The Phase 2 regression manifest is present and versioned.",
                valid,
                "Regression manifest loaded."
                if valid
                else "Regression manifest structure or version is invalid.",
                paths=("tests/fixtures/phase2/phase2_regression_manifest.json",),
            )
        )
        return data if valid else {}
    except (OSError, ValueError) as exc:
        checks.append(
            _check(
                "REGRESSION_MANIFEST_LOAD",
                "The Phase 2 regression manifest is present and versioned.",
                False,
                f"Could not load regression manifest: {exc}",
                paths=("tests/fixtures/phase2/phase2_regression_manifest.json",),
            )
        )
        return {}


def _case_set_check(cases_root: Path) -> Phase2AcceptanceCheck:
    if not cases_root.is_dir():
        return _check(
            "CASE_SET",
            "Exactly the three frozen case directories are present.",
            False,
            f"Cases directory does not exist: {cases_root.name}",
        )
    actual = sorted(item.name for item in cases_root.iterdir() if item.is_dir())
    roles = []
    for key in actual:
        path = cases_root / key / "case_manifest.json"
        try:
            roles.append(json.loads(path.read_text(encoding="utf-8"))["case_role"])
        except Exception:
            roles.append(f"<invalid:{key}>")
    valid = (
        actual == sorted(CASE_ORDER)
        and len(set(roles)) == 3
        and set(roles) == set(CASE_ORDER)
    )
    return _check(
        "CASE_SET",
        "Exactly the three frozen case directories and unique roles are present.",
        valid,
        f"directories={actual}; roles={roles}",
        paths=tuple(f"inputs/real_cases/{key}" for key in CASE_ORDER),
    )


def _result_set_check(results_root: Path) -> Phase2AcceptanceCheck:
    if not results_root.is_dir():
        return _check(
            "RESULT_SET",
            "Exactly the three frozen result bundles are present.",
            False,
            f"Results directory does not exist: {results_root.name}",
        )
    actual = sorted(
        item.name
        for item in results_root.iterdir()
        if item.is_dir() and item.name not in {"archive", "review"}
    )
    valid = actual == sorted(CASE_ORDER)
    return _check(
        "RESULT_SET",
        "Exactly the three active frozen result bundles are present.",
        valid,
        f"result_bundles={actual}",
        paths=tuple(f"results/real_cases/{key}" for key in CASE_ORDER),
    )


def _audit_case(
    case_key: str,
    input_root: Path,
    result_root: Path,
    results_root: Path,
    regression: dict[str, Any],
) -> tuple[_CaseAudit, list[Phase2AcceptanceCheck]]:
    checks: list[Phase2AcceptanceCheck] = []
    manifest = _json(input_root / "case_manifest.json")
    annotation_data = _json(input_root / manifest["annotation_path"])
    constructor = _json(result_root / "construction_report.json")
    real_report = _json(result_root / "real_case_report.json")
    expected = EXPECTED_IDENTITIES[case_key]
    identity_ok = all(
        (
            manifest.get("case_role") == case_key,
            manifest.get("image_id") == expected["image_id"],
            manifest.get("title") == expected["title"],
            manifest.get("author") == expected["author"],
            manifest.get("license_url") == expected["license_url"],
        )
    )
    checks.append(
        _check(
            "FROZEN_IDENTITY",
            "The selected Open Images identity matches the Phase 2 freeze.",
            identity_ok,
            (
                f"id={manifest.get('image_id')}; title={manifest.get('title')}; "
                f"author={manifest.get('author')}"
            ),
            case_key=case_key,
            paths=(f"inputs/real_cases/{case_key}/case_manifest.json",),
        )
    )
    source = input_root / manifest["source_image_path"]
    source_hash = _sha256_file(source)
    source_ok = (
        source_hash
        == manifest.get("source_image_sha256")
        == annotation_data.get("source_image", {}).get("sha256")
        == constructor.get("source_image_sha256")
    )
    checks.append(
        _check(
            "SOURCE_HASH",
            "Frozen source bytes match every recorded SHA-256.",
            source_ok,
            f"sha256={source_hash}",
            case_key=case_key,
            paths=(f"inputs/real_cases/{case_key}/{source.name}",),
        )
    )
    attribution_ok = all(
        (
            manifest.get("dataset_name") == "Open Images",
            manifest.get("dataset_version") == "V7",
            manifest.get("split") == "validation",
            bool(manifest.get("original_landing_page")),
            bool(manifest.get("original_url")),
            bool(manifest.get("author")),
            manifest.get("license_url") in ALLOWED_IMAGE_LICENSES,
            manifest.get("annotation_license_url") == OPEN_IMAGES_ANNOTATION_LICENSE,
        )
    )
    checks.append(
        _check(
            "ATTRIBUTION_COMPLETE",
            "Dataset, author, landing page, image license, and annotation license are complete.",
            attribution_ok,
            (
                f"dataset={manifest.get('dataset_name')} "
                f"{manifest.get('dataset_version')}; "
                f"license={manifest.get('license_url')}; "
                f"annotation_license={manifest.get('annotation_license_url')}"
            ),
            case_key=case_key,
            paths=(f"inputs/real_cases/{case_key}/case_manifest.json",),
        )
    )
    official_ok = str(manifest.get("official_mirror_url", "")).startswith(
        "https://open-images-dataset.s3.amazonaws.com/validation/"
    )
    checks.append(
        _check(
            "OFFICIAL_SOURCE",
            "The frozen image records the official CVDF Open Images source.",
            official_ok,
            manifest.get("official_mirror_url", "missing"),
            case_key=case_key,
        )
    )
    provenance_ok = all(
        isinstance(manifest.get(field), list) and bool(manifest[field])
        for field in (
            "dataset_supplied_information",
            "researcher_supplied_information",
            "scene_grammar_kit_derived_information",
        )
    )
    checks.append(
        _check(
            "ANNOTATION_PROVENANCE",
            "Dataset-, project-, and SceneGrammarKit-supplied information is separated.",
            provenance_ok,
            "All three provenance partitions are populated."
            if provenance_ok
            else "One or more provenance partitions are absent.",
            case_key=case_key,
        )
    )
    annotation = load_annotation(input_root / manifest["annotation_path"])
    config = load_construction_config(input_root / manifest["construction_config_path"])
    validation = validate_assisted_input(annotation, config)
    disclosure_text = "\n".join(
        [annotation.description]
        + list(annotation.annotation_notes)
        + list(manifest.get("factual_notes", []))
    ).casefold()
    disclosure_ok = (
        "annotation assistance" in disclosure_text
        or "annotation-assisted" in disclosure_text
    ) and not _positive_forbidden_claim(manifest, annotation_data)
    checks.append(
        _check(
            "ASSISTED_DISCLOSURE",
            "Annotation assistance is disclosed without automatic or metric-depth claims.",
            disclosure_ok,
            "Disclosure is explicit and no prohibited positive claim was found."
            if disclosure_ok
            else "Assisted disclosure is missing or prohibited wording was found.",
            case_key=case_key,
        )
    )
    checks.append(
        _check(
            "ASSISTED_INPUT_VALID",
            "The frozen annotation and construction configuration validate.",
            validation.is_valid,
            (
                "Annotation/configuration validation passed."
                if validation.is_valid
                else ", ".join(item.code for item in validation.diagnostics)
            ),
            case_key=case_key,
            paths=(
                f"inputs/real_cases/{case_key}/{manifest['annotation_path']}",
                f"inputs/real_cases/{case_key}/{manifest['construction_config_path']}",
            ),
        )
    )
    provenance_ok, provenance_detail = _constructor_provenance(
        source,
        result_root,
        constructor,
    )
    checks.append(
        _check(
            "CONSTRUCTOR_PROVENANCE",
            "Grammar, render, edit, source, and selected grammar family are traceable.",
            provenance_ok,
            provenance_detail,
            case_key=case_key,
            paths=(
                f"results/real_cases/{case_key}/construction_report.json",
                f"results/real_cases/{case_key}/primary/grammar.json",
                f"results/real_cases/{case_key}/primary/render.png",
            ),
        )
    )
    outcome_ok = (
        manifest.get("expected_outcome") == expected["outcome"]
        and real_report.get("outcome") == expected["outcome"]
        and constructor.get("success") is True
        and constructor.get("primary_grammar_type") == expected["primary"]
        and constructor.get("accepted_repeat_group_count") == expected["accepted"]
        and constructor.get("fallback_repeat_group_count") == expected["fallback"]
    )
    checks.append(
        _check(
            "EXPECTED_OUTCOME",
            "The constructor outcome and repeat decision match the frozen role.",
            outcome_ok,
            (
                f"outcome={real_report.get('outcome')}; "
                f"primary={constructor.get('primary_grammar_type')}; "
                f"accepted={constructor.get('accepted_repeat_group_count')}; "
                f"fallback={constructor.get('fallback_repeat_group_count')}"
            ),
            case_key=case_key,
        )
    )
    case_ok, case_detail = _case_specific_check(
        case_key,
        manifest,
        annotation_data,
        constructor,
        real_report,
    )
    checks.append(
        _check(
            "ROLE_REQUIREMENTS",
            "Role-specific success, fallback, or limitation requirements hold.",
            case_ok,
            case_detail,
            case_key=case_key,
        )
    )
    reopen_ok, reopen_detail = _reopen_artifacts(result_root)
    checks.append(
        _check(
            "ARTIFACT_REOPEN",
            "The primary GLB and semantic render reopen successfully.",
            reopen_ok,
            reopen_detail,
            case_key=case_key,
            paths=(
                f"results/real_cases/{case_key}/primary/scene.glb",
                f"results/real_cases/{case_key}/primary/render.png",
            ),
        )
    )
    regression_ok, regression_detail = _case_regression_check(
        case_key,
        input_root,
        result_root,
        manifest,
        constructor,
        real_report,
        results_root,
        regression,
    )
    checks.append(
        _check(
            "CASE_REGRESSION",
            "Frozen case values match the tracked Phase 2 regression manifest.",
            regression_ok,
            regression_detail,
            case_key=case_key,
        )
    )
    split_summary = _grammar_summary(constructor, "split_only")
    repeat_summary = _grammar_summary(constructor, "repeat")
    lifted = _json(result_root / "lifting" / "lifted_observations.json")
    source_ref = annotation_data["source_image"]
    edit = constructor["edit_decision"]
    limitation_code = (
        "axis_aligned_proxy_curvature_loss" if case_key == "limitation_case" else ""
    )
    evidence = Phase2EvidenceRow(
        case_key=case_key,
        open_images_id=manifest["image_id"],
        case_role=manifest["case_role"],
        constructor_status="success" if constructor["success"] else "failure",
        source_width=source_ref["pixel_width"],
        source_height=source_ref["pixel_height"],
        supplied_region_count=len(annotation_data["regions"]),
        supplied_instance_count=len(annotation_data["instances"]),
        supplied_repeat_group_count=len(annotation_data["repeat_groups"]),
        lifted_observation_count=len(lifted["observations"]),
        split_symbolic_node_count=split_summary["symbolic_node_count"],
        split_terminal_count=split_summary["terminal_node_count"],
        split_grammar_bytes=split_summary["canonical_byte_size"],
        repeat_symbolic_node_count=repeat_summary["symbolic_node_count"],
        repeat_terminal_count=repeat_summary["terminal_node_count"],
        repeat_grammar_bytes=repeat_summary["canonical_byte_size"],
        accepted_repeat_groups=constructor["accepted_repeat_group_count"],
        fallback_repeat_groups=constructor["fallback_repeat_group_count"],
        primary_grammar=constructor["primary_grammar_type"],
        primary_primitive_count=real_report["primary_primitive_count"],
        default_edit_type=edit["operation_type"] or "",
        default_edit_status="applied" if edit["applied"] else "skipped",
        warning_count=len(constructor["construction_warnings"]),
        limitation_code=limitation_code,
        source_license=manifest["license_url"],
    )
    status = (
        AcceptanceStatus.PASS
        if all(item.status is AcceptanceStatus.PASS for item in checks)
        else AcceptanceStatus.FAIL
    )
    case_acceptance = Phase2CaseAcceptance(
        case_key=case_key,
        image_id=manifest["image_id"],
        expected_outcome=manifest["expected_outcome"],
        observed_outcome=real_report["outcome"],
        constructor_status="success" if constructor["success"] else "failure",
        primary_grammar=constructor["primary_grammar_type"],
        accepted_repeat_groups=constructor["accepted_repeat_group_count"],
        fallback_repeat_groups=constructor["fallback_repeat_group_count"],
        status=status,
    )
    attribution = {
        "annotation_license_url": manifest["annotation_license_url"],
        "asset_paths": [
            f"review/{case_key}.png",
            "review/three_case_overview.png",
            "review/overview_candidate.png",
        ],
        "author": manifest["author"],
        "case_key": case_key,
        "dataset_name": manifest["dataset_name"],
        "dataset_version": manifest["dataset_version"],
        "image_id": manifest["image_id"],
        "license_name": "Creative Commons Attribution 2.0",
        "license_url": manifest["license_url"],
        "original_landing_page": manifest["original_landing_page"],
        "title": manifest["title"],
    }
    return (
        _CaseAudit(
            case_acceptance,
            evidence,
            attribution,
            manifest,
            annotation_data,
            constructor,
            real_report,
        ),
        checks,
    )


def _constructor_provenance(
    source: Path,
    result_root: Path,
    report: dict[str, Any],
) -> tuple[bool, str]:
    try:
        primary = result_root / "primary" / "grammar.json"
        grammar = load_grammar(primary)
        canonical = grammar_to_canonical_json(grammar).encode("utf-8")
        grammar_hash = hashlib.sha256(canonical).hexdigest()
        selected = result_root / report["primary_grammar_type"] / "grammar.json"
        render = _json(result_root / "primary" / "render.json")
        edit_before = result_root / "edit" / "grammar_before.json"
        edit_report = _json(result_root / "edit" / "edit_report.json")
        copied_source = result_root / "input" / "source_image.jpg"
        facts = (
            primary.read_bytes() == canonical,
            grammar_hash == report["primary_grammar_sha256"],
            primary.read_bytes() == selected.read_bytes(),
            validate_grammar(grammar).is_valid,
            render["executed_scene_grammar_sha256"] == grammar_hash,
            edit_before.read_bytes() == primary.read_bytes(),
            edit_report["original_grammar_sha256"] == grammar_hash,
            copied_source.read_bytes() == source.read_bytes(),
            (result_root / "review" / "annotation_overlay.png").is_file(),
            (result_root / "edit" / "after.png").is_file(),
        )
        return all(facts), (
            f"primary_sha256={grammar_hash}; selected_family="
            f"{report['primary_grammar_type']}; checks={sum(facts)}/{len(facts)}"
        )
    except Exception as exc:
        return False, f"Provenance verification failed: {exc}"


def _case_specific_check(
    case_key: str,
    manifest: dict[str, Any],
    annotation: dict[str, Any],
    constructor: dict[str, Any],
    real_report: dict[str, Any],
) -> tuple[bool, str]:
    edit = constructor["edit_decision"]
    if case_key == "canonical_success":
        reason = edit.get("reason", "").casefold()
        ok = all(
            (
                edit.get("applied") is True,
                edit.get("operation_type") == "set_repeat_count",
                "not claimed as observed or inferred" in reason,
                constructor["primary_grammar_type"] == "repeat",
                constructor["accepted_repeat_group_count"] == 1,
                constructor["fallback_repeat_group_count"] == 0,
            )
        )
        return (
            ok,
            "Accepted one supplied repeat and applied a disclosed repeat-count variation.",
        )
    if case_key == "moderate_case":
        reason = edit.get("reason", "").casefold()
        ok = all(
            (
                len(annotation["instances"]) == 5,
                manifest.get("primary_camera") == "isometric",
                edit.get("operation_type") == "set_repeat_count",
                edit.get("applied") is True,
                "not claimed as observed or inferred" in reason,
                constructor["primary_grammar_type"] == "repeat",
                constructor["accepted_repeat_group_count"] == 1,
                constructor["fallback_repeat_group_count"] == 0,
            )
        )
        return (
            ok,
            "Five supplied parked-car boxes form one accepted repeat; count edit succeeds.",
        )
    limitation = (real_report.get("limitation") or "").casefold()
    challenges = " ".join(manifest["known_representation_challenges"]).casefold()
    ok = all(
        (
            real_report.get("outcome") == "degraded_success",
            "axis-aligned" in limitation,
            "curvature" in limitation,
            "does not preserve" in limitation,
            "axis-aligned" in challenges,
            edit.get("operation_type") == "set_split_child_weight",
            edit.get("applied") is True,
            real_report.get("constructor_success") is True,
        )
    )
    return (
        ok,
        "Curvature loss is explicit; degraded result and edit remain constructor-generated.",
    )


def _reopen_artifacts(result_root: Path) -> tuple[bool, str]:
    try:
        with Image.open(result_root / "primary" / "render.png") as image:
            image.verify()
        import trimesh

        scene = trimesh.load(
            result_root / "primary" / "scene.glb",
            file_type="glb",
            force="scene",
            process=False,
        )
        geometry_count = len(scene.geometry)
        return geometry_count > 0, f"PNG verified; GLB geometry_count={geometry_count}."
    except Exception as exc:
        return False, f"Artifact reopen failed: {exc}"


def _case_regression_check(
    case_key: str,
    input_root: Path,
    result_root: Path,
    manifest: dict[str, Any],
    constructor: dict[str, Any],
    real_report: dict[str, Any],
    results_root: Path,
    regression: dict[str, Any],
) -> tuple[bool, str]:
    locked = {
        item["case_key"]: item
        for item in regression.get("cases", [])
        if isinstance(item, dict) and "case_key" in item
    }.get(case_key)
    if locked is None:
        return False, "Case is absent from the regression manifest."
    actual = {
        "accepted_repeat_groups": constructor["accepted_repeat_group_count"],
        "annotation_sha256": constructor["annotation_sha256"],
        "case_key": case_key,
        "construction_config_sha256": constructor["construction_config_sha256"],
        "constructor_report_sha256": _sha256_file(
            result_root / "construction_report.json"
        ),
        "expected_outcome": real_report["outcome"],
        "fallback_repeat_groups": constructor["fallback_repeat_group_count"],
        "image_id": manifest["image_id"],
        "primary_grammar_sha256": constructor["primary_grammar_sha256"],
        "review_panel_sha256": _sha256_file(
            results_root / "review" / f"{case_key}.png"
        ),
        "source_image_sha256": _sha256_file(input_root / manifest["source_image_path"]),
    }
    return (
        actual == locked,
        "All locked values match." if actual == locked else "Locked values differ.",
    )


def _summary_checks(
    results_root: Path,
    audits: list[_CaseAudit],
) -> list[Phase2AcceptanceCheck]:
    try:
        summary = _json(results_root / "real_case_summary.json")
        with (results_root / "real_case_summary.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            csv_rows = list(csv.DictReader(handle))
        markdown = (results_root / "real_case_summary.md").read_text(encoding="utf-8")
        json_keys = [item["case_key"] for item in summary["cases"]]
        csv_keys = [item["case_key"] for item in csv_rows]
        positions = [markdown.index(key) for key in CASE_ORDER]
        row_ok = (
            summary["case_order"] == list(CASE_ORDER)
            and json_keys == list(CASE_ORDER)
            and csv_keys == list(CASE_ORDER)
            and len(audits) == 3
            and positions == sorted(positions)
        )
        values_ok = all(
            summary["cases"][index]["outcome"] == audit.real_report["outcome"]
            and csv_rows[index]["outcome"] == audit.real_report["outcome"]
            and csv_rows[index]["image_id"] == audit.manifest["image_id"]
            for index, audit in enumerate(audits)
        )
        unsupported = re.search(
            r"\b(mean|p-value|percentage|ranking|average)\b",
            (results_root / "real_case_summary.md").read_text(encoding="utf-8"),
            re.I,
        )
    except Exception as exc:
        return [
            _check(
                "CROSS_CASE_SUMMARIES",
                "Batch 2.7 JSON, CSV, and Markdown summaries agree.",
                False,
                f"Summary audit failed: {exc}",
            )
        ]
    return [
        _check(
            "CROSS_CASE_SUMMARIES",
            "Batch 2.7 JSON, CSV, and Markdown summaries contain exactly three ordered rows.",
            row_ok and values_ok,
            f"row_order={json_keys}; values_agree={values_ok}",
            paths=(
                "results/real_cases/real_case_summary.json",
                "results/real_cases/real_case_summary.csv",
                "results/real_cases/real_case_summary.md",
            ),
        ),
        _check(
            "DESCRIPTIVE_ONLY",
            "The real-case summary contains no unsupported three-case statistic or ranking.",
            unsupported is None,
            "No unsupported aggregate language found."
            if unsupported is None
            else f"Unsupported term: {unsupported.group(0)}",
        ),
    ]


def _regression_check(
    regression: dict[str, Any],
    audits: list[_CaseAudit],
) -> Phase2AcceptanceCheck:
    identities = regression.get("evidence_summary_row_identities", [])
    actual = [
        {"case_key": audit.evidence.case_key, "image_id": audit.evidence.open_images_id}
        for audit in audits
    ]
    ok = (
        regression.get("case_order") == list(CASE_ORDER)
        and identities == actual
        and len(regression.get("cases", [])) == 3
    )
    return _check(
        "REGRESSION_MANIFEST",
        "Regression manifest locks all cases and evidence-row identities.",
        ok,
        "Case order and row identities match."
        if ok
        else "Regression identities differ.",
        paths=("tests/fixtures/phase2/phase2_regression_manifest.json",),
    )


def _copy_review_images(
    results_root: Path,
    output: Path,
) -> list[Phase2AcceptanceCheck]:
    checks = []
    for name in (*CASE_ORDER, "three_case_overview"):
        source = results_root / "review" / f"{name}.png"
        target = output / "review" / f"{name}.png"
        try:
            atomic_write_bytes(
                source.read_bytes(),
                target,
                overwrite=True,
                create_parents=True,
            )
            ok = target.read_bytes() == source.read_bytes()
            detail = f"sha256={_sha256_file(target)}"
        except OSError as exc:
            ok = False
            detail = f"Copy failed: {exc}"
        checks.append(
            _check(
                "REVIEW_BYTE_COPY",
                "Batch 2.7 review image is preserved byte-for-byte.",
                ok,
                detail,
                case_key=name if name in CASE_ORDER else None,
                paths=(f"review/{name}.png",),
            )
        )
    return checks


def _build_and_verify_hero(
    cases_root: Path,
    results_root: Path,
    output: Path,
) -> tuple[bool, str]:
    try:
        first = _hero_image(cases_root, results_root)
        second = _hero_image(cases_root, results_root)
        first_bytes = _png_bytes(first)
        second_bytes = _png_bytes(second)
        target = output / "review" / "overview_candidate.png"
        atomic_write_bytes(
            first_bytes,
            target,
            overwrite=True,
            create_parents=True,
        )
        with Image.open(target) as reopened:
            pixels = reopened.convert("RGBA").tobytes()
            size = reopened.size
        ok = (
            size == (2400, 1350)
            and first_bytes == second_bytes
            and pixels == second.convert("RGBA").tobytes()
        )
        return ok, (
            f"size={size[0]}x{size[1]}; byte_deterministic="
            f"{first_bytes == second_bytes}; annotation-assisted label embedded"
        )
    except Exception as exc:
        return False, f"Hero construction failed: {exc}"


def _hero_image(cases_root: Path, results_root: Path) -> Image.Image:
    canvas = Image.new("RGB", (2400, 1350), "#f4f1ea")
    draw = ImageDraw.Draw(canvas)
    title_font = _hero_font(38, bold=True)
    label_font = _hero_font(22, bold=True)
    small_font = _hero_font(17)
    draw.rectangle((0, 0, 2400, 155), fill="#17233d")
    draw.text(
        (30, 18),
        "Annotation-assisted SceneGrammarKit:",
        fill="white",
        font=title_font,
    )
    draw.text(
        (30, 66),
        "from one image to an editable proxy grammar",
        fill="white",
        font=title_font,
    )
    draw.text(
        (32, 119),
        HERO_SUBTITLE,
        fill="#d7e1f2",
        font=small_font,
    )
    canonical_input = cases_root / "canonical_success"
    canonical_result = results_root / "canonical_success"
    top = (
        ("Single input image", canonical_input / "source.jpg"),
        (
            "Supplied structure",
            canonical_result / "review" / "presentation_overlay.png",
        ),
        ("Relevant generated grammar", None),
        (
            "Executable structured-scene proxy",
            canonical_result / "primary" / "render.png",
        ),
        ("Explicit edit | Windows: 5 → 6", canonical_result / "edit" / "after.png"),
    )
    for index, (label, path) in enumerate(top):
        x0 = index * 480
        draw.multiline_text(
            (x0 + 20, 170),
            label.replace(" structured-scene ", "\nstructured-scene "),
            fill="#17233d",
            font=label_font,
            spacing=2,
        )
        if path is None:
            _draw_grammar_card(draw, canonical_result, (x0 + 20, 232, x0 + 460, 752))
        else:
            with Image.open(path) as opened:
                fitted = ImageOps.contain(
                    ImageOps.exif_transpose(opened).convert("RGB"),
                    (440, 510),
                )
            canvas.paste(
                fitted,
                (
                    x0 + 20 + (440 - fitted.width) // 2,
                    232 + (510 - fitted.height) // 2,
                ),
            )
    draw.text(
        (505, 752),
        "Supplied repeat band: 5 windows",
        fill="#8c2638",
        font=_hero_font(18, bold=True),
    )
    draw.line((1950, 736, 2328, 736), fill="#d1495b", width=8)
    draw.line((1950, 724, 1950, 744), fill="#d1495b", width=8)
    draw.line((2328, 724, 2328, 744), fill="#d1495b", width=8)
    _draw_proxy_legend(draw, "facade", (1460, 620))
    draw.rectangle((0, 790, 2400, 845), fill="#d9e2ee")
    draw.text(
        (28, 805),
        "Supporting cases",
        fill="#17233d",
        font=label_font,
    )
    _draw_support_case(
        canvas,
        draw,
        bounds=(20, 860, 1180, 1255),
        title="Structured-street success",
        source=cases_root / "moderate_case" / "source.jpg",
        proxy=results_root / "moderate_case" / "primary" / "render.png",
        badge="Repeat accepted",
        edit_label="Cars: 5 → 6",
        legend="street",
    )
    _draw_support_case(
        canvas,
        draw,
        bounds=(1220, 860, 2380, 1255),
        title="Curved-facade limitation",
        source=cases_root / "limitation_case" / "source.jpg",
        proxy=results_root / "limitation_case" / "primary" / "render.png",
        badge="Axis-aligned limitation",
        edit_label="",
        legend=None,
    )
    manifests = tuple(
        _json(cases_root / key / "case_manifest.json") for key in CASE_ORDER
    )
    draw.rectangle((0, 1265, 2400, 1350), fill="#17233d")
    draw.text(
        (24, 1278),
        "  ·  ".join(
            f"Open Images {item['image_id']} — {item['author']} · CC BY 2.0"
            for item in manifests
        ),
        fill="white",
        font=small_font,
    )
    draw.text(
        (24, 1315),
        "Annotation-assisted inputs; proxy geometry is coarse and axis-aligned.",
        fill="#d7e1f2",
        font=small_font,
    )
    return canvas


def _draw_grammar_card(
    draw: ImageDraw.ImageDraw,
    result_root: Path,
    bounds: tuple[int, int, int, int],
) -> None:
    grammar = _json(result_root / "primary" / "grammar.json")
    lines = semantic_grammar_excerpt(grammar)
    x0, y0, x1, y1 = bounds
    draw.rounded_rectangle(
        bounds, radius=14, fill="#edf2f8", outline="#55739d", width=3
    )
    mono = _hero_font(18)
    small = _hero_font(14)
    y = y0 + 22
    for line in lines:
        draw.text((x0 + 24, y), line, fill="#17233d", font=mono)
        y += 38
    draw.line((x0 + 24, y + 4, x1 - 24, y + 4), fill="#9aabc2", width=2)
    draw.text(
        (x0 + 24, y + 18),
        "Semantic excerpt; generated wrapper/filler nodes omitted.",
        fill="#43536d",
        font=small,
    )


def semantic_grammar_excerpt(grammar: dict[str, Any]) -> tuple[str, ...]:
    """Create a semantic excerpt while validating every displayed saved value."""
    root = grammar["root"]
    repeat = _first_repeat(root)
    terminals = tuple(_terminal_nodes(root))
    by_id = {item["node_id"]: item for item in terminals}
    facade_base = by_id["induced_region_facade_base"]
    parapet = by_id["induced_region_parapet"]
    sky = by_id["induced_region_sky"]
    foreground = by_id["induced_region_foreground_ground"]
    element = repeat["element"]
    if root.get("axis") != "z" or repeat.get("axis") != "x":
        raise ValueError("saved canonical grammar has unexpected displayed axes")
    return (
        "Scene",
        "└─ split(z): depth zones",
        f"   ├─ Foreground ({foreground['geometry']})",
        "   ├─ Facade layout",
        "   │  └─ split(y)",
        f"   │     ├─ Facade base ({facade_base['geometry']})",
        "   │     ├─ Window band",
        (
            "   │     │  └─ repeat("
            f"{repeat['axis']}, n={repeat['count']}, spacing={repeat['spacing']})"
        ),
        (
            f"   │     │     └─ {element['semantic_class'].title()} "
            f"({element['geometry']})"
        ),
        f"   │     └─ Parapet ({parapet['geometry']})",
        f"   └─ Sky ({sky['geometry']})",
    )


def _terminal_nodes(node: dict[str, Any]):
    if node.get("type") == "terminal":
        yield node
    for child in node.get("children", []):
        yield from _terminal_nodes(child["node"])
    element = node.get("element")
    if isinstance(element, dict):
        yield from _terminal_nodes(element)


def _hero_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        (
            Path("C:/Windows/Fonts/arialbd.ttf")
            if bold
            else Path("C:/Windows/Fonts/arial.ttf")
        ),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
            if bold
            else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        ),
    )
    font_path = next((path for path in candidates if path.is_file()), None)
    if font_path is None:
        raise OSError("a Unicode TrueType font is required for report figures")
    return ImageFont.truetype(font_path, size)


def _draw_proxy_legend(
    draw: ImageDraw.ImageDraw,
    kind: str,
    origin: tuple[int, int],
) -> None:
    from scene_grammar_kit.rendering.palette import resolve_palette

    entries = (
        (
            ("Upper facade", "facade"),
            ("Repeated windows", "window"),
            ("Lower facade", "facade"),
        )
        if kind == "facade"
        else (
            ("Building", "building"),
            ("Parking", "parking"),
            ("Road", "road"),
            ("Sidewalk", "sidewalk"),
            ("Curb", "curb"),
            ("Cars", "car"),
        )
    )
    palette = resolve_palette(tuple(item[1] for item in entries))
    x, y = origin
    columns = 2 if len(entries) > 3 else 1
    rows = (len(entries) + columns - 1) // columns
    width = 430 if columns == 2 else 355
    height = 30 + rows * 27
    draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill="#17233d")
    for index, (label, semantic) in enumerate(entries):
        column, row = index // rows, index % rows
        px, py = x + 12 + column * 208, y + 12 + row * 27
        draw.rectangle((px, py, px + 19, py + 16), fill=palette[semantic][:3])
        draw.text((px + 27, py - 1), label, fill="white", font=_hero_font(12))


def _draw_support_case(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    bounds: tuple[int, int, int, int],
    title: str,
    source: Path,
    proxy: Path,
    badge: str,
    edit_label: str,
    legend: str | None,
) -> None:
    x0, y0, x1, y1 = bounds
    draw.rounded_rectangle(bounds, radius=14, fill="white", outline="#c9d2df", width=2)
    draw.text((x0 + 18, y0 + 14), title, fill="#17233d", font=_hero_font(22, bold=True))
    badge_box = draw.textbbox((0, 0), badge, font=_hero_font(17, bold=True))
    badge_width = badge_box[2] - badge_box[0] + 30
    draw.rounded_rectangle(
        (x1 - badge_width - 18, y0 + 12, x1 - 18, y0 + 47),
        radius=16,
        fill="#e8eef6" if legend else "#fff0dc",
    )
    draw.text(
        (x1 - badge_width - 3, y0 + 19),
        badge,
        fill="#244d78" if legend else "#8b4c12",
        font=_hero_font(17, bold=True),
    )
    for index, path in enumerate((source, proxy)):
        with Image.open(path) as opened:
            fitted = ImageOps.contain(
                ImageOps.exif_transpose(opened).convert("RGB"),
                (530, 275),
            )
        px = x0 + 20 + index * 565 + (530 - fitted.width) // 2
        py = y0 + 72 + (275 - fitted.height) // 2
        canvas.paste(fitted, (px, py))
        draw.rectangle(
            (px, py, px + fitted.width, py + fitted.height), outline="#17233d", width=2
        )
    draw.text(
        (x0 + 22, y1 - 34), "Source", fill="#43536d", font=_hero_font(16, bold=True)
    )
    if edit_label:
        draw.text(
            (x1 - 245, y1 - 38),
            edit_label,
            fill="#8c2638",
            font=_hero_font(20, bold=True),
        )
        draw.line((x1 - 515, y1 - 28, x1 - 265, y1 - 28), fill="#d1495b", width=6)
    if legend:
        _draw_proxy_legend(draw, legend, (x0 + 700, y0 + 190))


def _first_repeat(node: dict[str, Any]) -> dict[str, Any]:
    if node.get("type") == "repeat":
        return node
    for child in node.get("children", []):
        found = _first_repeat(child["node"])
        if found:
            return found
    element = node.get("element")
    if isinstance(element, dict):
        found = _first_repeat(element)
        if found:
            return found
    return {}


def _path_to_first_repeat(
    node: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    if node.get("type") == "repeat":
        return (node,)
    for child in node.get("children", []):
        path = _path_to_first_repeat(child["node"])
        if path:
            return (node, *path)
    element = node.get("element")
    if isinstance(element, dict):
        path = _path_to_first_repeat(element)
        if path:
            return (node, *path)
    return ()


def _png_bytes(image: Image.Image) -> bytes:
    import io

    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _determinism_checks(
    cases_root: Path,
    results_root: Path,
    output: Path,
    *,
    verify_determinism: bool,
) -> list[Phase2AcceptanceCheck]:
    codes = (
        ("DETERMINISM_SOURCE", "Frozen source bytes are stable."),
        ("DETERMINISM_MANIFESTS", "Canonical case manifests are stable."),
        ("DETERMINISM_ANNOTATION_CONFIG", "Annotations and configurations are stable."),
        ("DETERMINISM_CONSTRUCTOR_REPORTS", "Constructor reports are stable."),
        ("DETERMINISM_GRAMMARS_PRIMITIVES", "Grammar and primitive bytes are stable."),
        (
            "DETERMINISM_PNG_PIXELS",
            "Platform-neutral decoded PNG pixels are stable.",
        ),
        ("DETERMINISM_PNG_BYTES", "Same-environment PNG bytes are stable."),
        ("DETERMINISM_GLB_BYTES", "GLB bytes are stable."),
        ("DETERMINISM_GLB_STRUCTURES", "Reopened GLB structures are equivalent."),
        ("DETERMINISM_CASE_REPORTS", "Real-case reports are stable."),
        (
            "DETERMINISM_REVIEW_PANELS",
            "Review panels are stable within one environment.",
        ),
    )
    if not verify_determinism:
        return [
            Phase2AcceptanceCheck(
                code,
                description,
                AcceptanceStatus.SKIP,
                True,
                "Determinism verification was not requested.",
            )
            for code, description in codes
        ]
    temporary = Path(
        tempfile.mkdtemp(prefix=".phase2-real-cases-verify-", dir=output.parent)
    ).resolve()
    try:
        rebuilt = temporary / "real_cases"
        rebuilt_summary = build_open_images_cases(
            rebuilt,
            input_directory=cases_root,
            verify_determinism=True,
        )
        compare = compare_scene_builds(results_root, rebuilt)
        unstable = {f"{key}/runtime_report.json" for key in CASE_ORDER} | {
            f"{key}/artifact_index.json" for key in CASE_ORDER
        }
        json_mismatch = [
            item
            for item in compare.canonical_json_mismatches
            if item not in unstable and _is_active_case_artifact(item)
        ]
        png_pixel_mismatch = [
            item
            for item in compare.png_pixel_mismatches
            if _is_platform_neutral_png(item)
        ]
        glb_byte_mismatch = [
            item
            for item in compare.glb_byte_mismatches
            if _is_active_case_artifact(item)
        ]
        glb_structure_mismatch = [
            item
            for item in compare.glb_structure_mismatches
            if _is_active_case_artifact(item)
        ]
        source_equal = _relative_bytes_equal(
            results_root,
            rebuilt,
            tuple(f"{key}/input/source_image.jpg" for key in CASE_ORDER),
        )
        manifests_equal = _relative_bytes_equal(
            results_root,
            rebuilt,
            tuple(f"{key}/input/case_manifest.json" for key in CASE_ORDER),
        )
        inputs_equal = _relative_bytes_equal(
            results_root,
            rebuilt,
            tuple(
                path
                for key in CASE_ORDER
                for path in (
                    f"{key}/input/annotation.json",
                    f"{key}/input/construction_config.json",
                )
            ),
        )
        constructors_equal = _relative_bytes_equal(
            results_root,
            rebuilt,
            tuple(f"{key}/construction_report.json" for key in CASE_ORDER),
        )
        grammar_primitive_paths = tuple(
            path.relative_to(results_root).as_posix()
            for path in results_root.rglob("*.json")
            if path.relative_to(results_root).parts[0] in CASE_ORDER
            and path.name
            in {
                "grammar.json",
                "grammar_before.json",
                "grammar_after.json",
                "primitives.json",
                "primitives_after.json",
            }
        )
        grammar_equal = _relative_bytes_equal(
            results_root, rebuilt, grammar_primitive_paths
        )
        reports_equal = _relative_bytes_equal(
            results_root,
            rebuilt,
            tuple(f"{key}/real_case_report.json" for key in CASE_ORDER),
        )
        same_environment = rebuilt_summary.get("determinism", {})
        same_environment_png_bytes = all(
            isinstance(same_environment.get(key), dict)
            and same_environment[key].get("png_bytes_equal") is True
            for key in CASE_ORDER
        )
        review_verification = temporary / "review_verification"
        shutil.copytree(rebuilt, review_verification)
        refresh_review_figures(cases_root, review_verification)
        review_paths = tuple(
            f"review/{name}.png" for name in (*CASE_ORDER, "three_case_overview")
        )
        panels_equal = _relative_bytes_equal(
            rebuilt,
            review_verification,
            review_paths,
        ) and all(
            isinstance(same_environment.get(key), dict)
            and same_environment[key].get("review_panels_equal") is True
            for key in CASE_ORDER
        )
        values = (
            source_equal,
            manifests_equal,
            inputs_equal,
            constructors_equal and not json_mismatch,
            grammar_equal,
            not png_pixel_mismatch,
            same_environment_png_bytes,
            not glb_byte_mismatch,
            not glb_structure_mismatch,
            reports_equal,
            panels_equal,
        )
        details = (
            "source bytes match rebuilt cases",
            "case manifest bytes match",
            "annotation/configuration bytes match",
            f"constructor/canonical JSON mismatches={json_mismatch}",
            "grammar and primitive bytes match",
            f"platform-neutral pixel mismatches={png_pixel_mismatch}",
            "independent same-environment PNG builds match byte-for-byte",
            f"GLB byte mismatches={glb_byte_mismatch}",
            f"GLB structure mismatches={glb_structure_mismatch}",
            "case report bytes match",
            "independent same-environment review panel builds match byte-for-byte",
        )
    except Exception as exc:
        values = (False,) * len(codes)
        details = (f"Determinism rebuild failed: {exc}",) * len(codes)
    finally:
        if temporary.parent == output.parent.resolve() and temporary.name.startswith(
            ".phase2-real-cases-verify-"
        ):
            shutil.rmtree(temporary)
    return [
        _check(code, description, value, detail)
        for (code, description), value, detail in zip(codes, values, details)
    ]


def _is_active_case_artifact(relative: str) -> bool:
    normalized = relative.removesuffix(" missing")
    parts = Path(normalized).parts
    first = parts[0] if parts else ""
    return first in CASE_ORDER or first == "review"


def _is_platform_neutral_png(relative: str) -> bool:
    """Return whether a PNG avoids platform-resolved text rendering."""
    normalized = relative.removesuffix(" missing")
    path = Path(normalized)
    if not _is_active_case_artifact(relative) or not path.parts:
        return False
    return path.parts[0] != "review" and path.name != "presentation_overlay.png"


def _relative_bytes_equal(
    first: Path,
    second: Path,
    paths: tuple[str, ...],
) -> bool:
    return all(
        (first / path).is_file()
        and (second / path).is_file()
        and (first / path).read_bytes() == (second / path).read_bytes()
        for path in paths
    )


def _evidence_model_check(
    rows: tuple[Phase2EvidenceRow, ...],
) -> Phase2AcceptanceCheck:
    valid = (
        tuple(row.case_key for row in rows) == CASE_ORDER
        and len(rows) == 3
        and all(
            row.open_images_id == EXPECTED_IDENTITIES[row.case_key]["image_id"]
            for row in rows
        )
    )
    return _check(
        "EVIDENCE_MODEL",
        "The evidence model contains exactly three descriptive rows in frozen order.",
        valid,
        f"rows={[row.case_key for row in rows]}; missing_value=''",
        paths=(
            "phase2_evidence_summary.json",
            "phase2_evidence_summary.csv",
            "phase2_evidence_summary.md",
        ),
    )


def _attribution_model_check(
    records: tuple[dict[str, Any], ...],
) -> Phase2AcceptanceCheck:
    valid = tuple(item["case_key"] for item in records) == CASE_ORDER and all(
        item["license_url"] in ALLOWED_IMAGE_LICENSES
        and item["annotation_license_url"] == OPEN_IMAGES_ANNOTATION_LICENSE
        and len(item["asset_paths"]) == 3
        for item in records
    )
    return _check(
        "ATTRIBUTION_MODEL",
        "Attribution records cover every used image and referencing asset.",
        valid,
        f"records={len(records)}; annotation_license={OPEN_IMAGES_ANNOTATION_LICENSE}",
        paths=("attribution.json", "ATTRIBUTION.md"),
    )


def _write_supporting_artifacts(
    output: Path,
    evidence_rows: tuple[Phase2EvidenceRow, ...],
    attribution_records: tuple[dict[str, Any], ...],
    regression_path: Path,
) -> None:
    atomic_write_text(
        canonical_json([evidence_row_to_data(row) for row in evidence_rows]),
        output / "phase2_evidence_summary.json",
        overwrite=True,
        create_parents=True,
    )
    atomic_write_text(
        evidence_to_csv(evidence_rows),
        output / "phase2_evidence_summary.csv",
        overwrite=True,
        create_parents=True,
    )
    atomic_write_text(
        evidence_to_markdown(evidence_rows),
        output / "phase2_evidence_summary.md",
        overwrite=True,
        create_parents=True,
    )
    atomic_write_text(
        canonical_json(list(attribution_records)),
        output / "attribution.json",
        overwrite=True,
        create_parents=True,
    )
    atomic_write_text(
        attribution_to_markdown(attribution_records),
        output / "ATTRIBUTION.md",
        overwrite=True,
        create_parents=True,
    )
    if regression_path.is_file():
        atomic_write_bytes(
            regression_path.read_bytes(),
            output / "phase2_regression_manifest.json",
            overwrite=True,
            create_parents=True,
        )


def _portable_paths_check(output: Path) -> Phase2AcceptanceCheck:
    problems = []
    for relative in (
        "phase2_evidence_summary.json",
        "attribution.json",
        "phase2_regression_manifest.json",
    ):
        path = output / relative
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            problems.append(path.name + ": invalid JSON")
            continue
        if _contains_absolute_path(data):
            problems.append(path.name + ": absolute path")
    return _check(
        "RELATIVE_PATHS",
        "Canonical output JSON contains relative paths only.",
        not problems,
        "All JSON paths are portable." if not problems else "; ".join(problems),
    )


def _contains_absolute_path(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_absolute_path(item) for item in value)
    if isinstance(value, str):
        return bool(
            re.match(r"^[A-Za-z]:[\\/]", value)
            or value.startswith("/")
            or value.startswith("\\\\")
            or value.startswith("file:")
        )
    return False


def _make_report(
    checks: list[Phase2AcceptanceCheck],
    cases: tuple[Phase2CaseAcceptance, ...],
) -> Phase2AcceptanceReport:
    required_failed = sum(
        item.required and item.status is not AcceptanceStatus.PASS for item in checks
    )
    overall = (
        AcceptanceStatus.PASS
        if required_failed == 0
        and len(cases) == 3
        and all(item.status is AcceptanceStatus.PASS for item in cases)
        else AcceptanceStatus.FAIL
    )
    policy_versions = _policy_versions(cases)
    return Phase2AcceptanceReport(
        overall_status=overall,
        policy_versions=policy_versions,
        cases=cases,
        checks=tuple(checks),
        total_checks=len(checks),
        passed_checks=sum(item.status is AcceptanceStatus.PASS for item in checks),
        failed_checks=sum(item.status is AcceptanceStatus.FAIL for item in checks),
        skipped_checks=sum(item.status is AcceptanceStatus.SKIP for item in checks),
        required_failed_checks=required_failed,
        reproduction_command=REPRODUCTION_COMMAND,
        known_limitations=(
            "The workflow is annotation-assisted and does not infer segmentation or metric depth.",
            "Proxy geometry is axis-aligned and does not preserve the curved limitation facade.",
            "Three qualitative cases provide descriptive evidence, not aggregate real-world accuracy.",
            "The overview is a qualitative visualization, not an accuracy metric.",
        ),
        next_step=NEXT_STEP,
        artifact_paths=OUTPUT_PATHS,
    )


def _policy_versions(
    cases: tuple[Phase2CaseAcceptance, ...],
) -> tuple[tuple[str, str], ...]:
    del cases
    return (
        ("phase2_acceptance", PHASE2_ACCEPTANCE_POLICY_VERSION),
        ("real_case", "0.1"),
        ("constructor", "0.1"),
        ("annotation_schema", "0.1"),
        ("construction_config_schema", "0.1"),
        ("annotation_review", "0.1"),
        ("lifting", "0.1"),
        ("split_induction", "0.1"),
        ("repeat_induction", "0.1"),
        ("grammar_schema", "0.1"),
        ("execution", "0.1"),
        ("renderer", "0.1"),
        ("editing", "0.1"),
    )


def _readme(report: Phase2AcceptanceReport) -> str:
    return (
        "# Integrated Phase 2 acceptance package\n\n"
        f"Overall status: **{report.overall_status.value}**\n\n"
        "This package audits the three frozen annotation-assisted Open Images "
        "cases without downloading data or changing their constructor outputs. "
        "It contains structured acceptance, descriptive evidence, attribution, "
        "regression locks, byte-identical review images, and a deterministic "
        "overview candidate.\n\n"
        "Reproduce with:\n\n"
        "```console\n"
        f"{report.reproduction_command}\n"
        "```\n"
    )


def _positive_forbidden_claim(
    manifest: dict[str, Any],
    annotation: dict[str, Any],
) -> bool:
    values = []
    for source in (
        manifest.get("factual_notes", []),
        manifest.get("selection_rationale", ""),
        annotation.get("description", ""),
        annotation.get("annotation_notes", []),
    ):
        if isinstance(source, list):
            values.extend(str(item) for item in source)
        else:
            values.append(str(source))
    banned = (
        "fully automatic",
        "automatic reconstruction",
        "automatically reconstructed",
        "metric depth recovery",
        "true 3d recovery",
    )
    for text in values:
        folded = text.casefold()
        if any(term in folded for term in banned):
            if not any(
                negation in folded
                for negation in (
                    "not automatic",
                    "no automatic",
                    "does not",
                    "not claimed",
                    "not inferred",
                )
            ):
                return True
    return False


def _grammar_summary(
    report: dict[str, Any],
    grammar_type: str,
) -> dict[str, Any]:
    return next(
        item
        for item in report["grammar_summaries"]
        if item["grammar_type"] == grammar_type
    )


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check(
    code: str,
    description: str,
    passed: bool,
    details: str,
    *,
    required: bool = True,
    case_key: str | None = None,
    paths: tuple[str, ...] = (),
) -> Phase2AcceptanceCheck:
    return Phase2AcceptanceCheck(
        code=code,
        description=description,
        status=AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
        required=required,
        details=details,
        case_key=case_key,
        artifact_paths=paths,
    )
