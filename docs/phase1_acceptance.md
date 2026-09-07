# Phase 1 integrated demo and acceptance

Phase 1 covers deterministic validation and inspection of hand-authored scene
grammars, semantic proxy-geometry execution, reopenable GLB export, headless
semantic rendering, typed structural editing, provenance, and integrated bundle
verification. It does not claim automatic reconstruction or quantitative
recovery performance.

## Formal acceptance

Run from the repository root:

```text
python -m scene_grammar_kit demo --output runs/phase1_demo --all --seed 42 --verify-determinism
```

The command returns zero only when every required check passes. It writes
`demo_manifest.json`, `artifact_index.json`, structured and Markdown acceptance
reports, a bundle README, complete builder artifacts under `scenes/`, and seven
byte-identical review copies under `review/`.

The checks cover the Phase 0 definitions and canonical sources, package
declarations, grammar validity and inspection, execution and bounds, GLB
reopening, rendering and image differences, edit provenance and realization,
determinism, relative report paths, and a practical scope scan.

## Quick and full modes

Full mode renders at 1200 by 800 and is the formal acceptance mode. `--quick`
renders at 640 by 426 while preserving the same grammars, edit parameters,
semantic content, validation, execution, GLBs, and reports. Determinism
verification is optional for exploratory runs and required for the formal run.

With `--verify-determinism`, the selected scenes are built again in a temporary
sibling directory. Canonical JSON, decoded and encoded PNG data, GLB bytes, and
reopened GLB structures are compared. The temporary directory is removed and
the requested bundle remains.

## Diagnosing failures

Start with `phase1_acceptance.json`: each ordered check has a stable code,
status, factual detail, and relevant relative paths. Use
`phase1_acceptance.md` for a concise summary. A protected nonempty output needs
`--overwrite`; that permission replaces known artifacts but preserves unrelated
files. The final structured acceptance report is written last so a failed
verification cannot leave a stale PASS result.

The regression lock at
`tests/fixtures/phase1/phase1_regression_manifest.json` records stable source
hashes, policy versions, counts, and edit keys. Update it only with an
intentional canonical-source change, after reviewing the grammar and manifest
diffs and regenerating every recorded value with the project serializers.

## Limitations and Phase 2 boundary

The grammars are hand-authored and the geometry and rendering are schematic.
There is no photograph processing, image inference, automatic grammar
induction, quantitative recovery evaluation, photorealistic rendering, final
presentation PDF, or GUI. Annotation-assisted construction, perception, synthetic
recovery evaluation, metrics, and final presentation composition remain Phase 2 or
later work.
