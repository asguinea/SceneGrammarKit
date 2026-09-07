# Phase 2 annotation-to-grammar constructor

Batch 2.6 integrates the existing assisted stages into one deterministic
workflow. Its constructor-policy version is `0.1`; all annotation,
configuration, review, lifting, induction, grammar, execution, renderer, and
editing policy versions remain `0.1`.

## Scope

The constructor is orchestration, disclosure, and artifact packaging. It
introduces no new induction, perception, grammar, rendering, or editing
algorithm. It reuses:

1. assisted input validation;
2. source-image verification and annotation review;
3. coarse proxy lifting;
4. Batch 2.4 split-only induction;
5. Batch 2.5 supplied repeat-group induction;
6. grammar validation and execution;
7. deterministic GLB export;
8. semantic preview rendering;
9. immutable typed editing.

The workflow is annotation-assisted. Pixels are decoded only for evidence
verification and overlay composition; they are not analyzed for segmentation,
objects, structure, depth, or repeat membership.

## Integrated API

```python
construct_assisted_scene(
    annotation_path,
    config_path,
    output_directory,
    overwrite=False,
    verify_image=True,
    verify_execution=True,
    render_width=1200,
    render_height=800,
    camera="isometric",
    apply_default_edit=True,
    maximum_depth=128,
    maximum_primitives=1_000_000,
)
```

Input models are immutable. A successful result retains the review, lifting,
split, repeat, primary, edit, render, and report objects.

## Stage policy

The canonical report records these stages in fixed order:

```text
annotation_validation
config_validation
compatibility_validation
image_verification
annotation_review
lifting
split_induction
repeat_induction
grammar_validation
execution
export
rendering
default_edit
persistence
```

Each stage is `PASS`, `FAIL`, or `SKIP`, with factual detail, portable artifact
paths, and warnings. Explicitly disabled image or execution work is `SKIP`.
Required failures raise a constructor-domain error and cannot leave a successful
construction report.

## Primary grammar

The repeat grammar is primary when one or more supplied groups are accepted.
Otherwise, the split-only grammar is primary. Both grammars remain in the
bundle. Primary grammar JSON, tree, execution, GLB, semantic index, and render
bytes are exact copies of the selected grammar family.

## Source evidence

By default, the source image is verified through the Batch 2.2 policy. Its
original PNG or JPEG bytes are atomically copied to a safe
`input/source_image.<ext>` name without recompression. The copied digest must
equal the verified digest. Original absolute paths never enter canonical
reports.

Explicit `--skip-image-verification` records image verification and annotation
review as `SKIP`. Lifting then uses the existing explicit unverified-input
policy and warning; no image hash or overlay is invented.

## Rendering

Split-only, repeat, primary, and edited-primary scenes use one shared
`RenderConfig`: identical camera preset, dimensions, semantic palette, ground,
edges, and root bounds. Defaults are `isometric`, 1200 by 800 pixels.
This batch does not compose labels, panels, or a final presentation.

## Default procedural edit

Selection is deterministic:

1. increase the first accepted supplied repeat group count by one;
2. otherwise increase the central child weight of the first eligible supplied
   structural split by factor 1.25;
3. otherwise use a terminal substitution only when the annotation explicitly
   supplies `default_edit_semantic_class`;
4. otherwise skip.

The canonical urban edit changes `induced_repeat_parked_cars` from count 3 to
4 while preserving spacing. It is explicitly reported as a user-requested
procedural variation. The fourth instance is not claimed as observed, inferred,
hidden, or reconstruction evidence.

## Disclosure

The report separates:

- supplied annotation evidence: regions, instances, hierarchy, depth zones,
  semantic classes, terminal geometry, split hints, repeat membership, and
  repeat-axis hints;
- configured controls: root bounds, depth intervals, tolerances, axis policy,
  fallback policy, and depth limits;
- derived proxy values: lifted bounds, split axes/boundaries, gaps, wrappers,
  repeat decisions/spacing, primary selection, execution geometry, and semantic
  previews.

Explicit nonclaims include pixel segmentation, metric monocular depth, camera
calibration, hidden objects, additional repeat members, physical dimensions,
photorealistic reconstruction, and appearance models.

## Canonical and runtime reports

`construction_report.json` is canonical: sorted compact UTF-8 JSON with stable
ordering, finite values, relative POSIX paths, no timestamps, no machine facts,
and no runtime measurements. It round-trips structurally and byte-for-byte.

`runtime_report.json` is explicitly noncanonical. It contains machine-specific
wall-clock durations, operating-system family, machine architecture, and Python
version, but no usernames or absolute paths. It is excluded from the artifact
index so its instability cannot change canonical index bytes.

The deterministic text report has exactly one final newline. The bundle README
describes assisted scope, contents, reproduction, inspection, the default
procedural edit, and limitations.

## Artifact index and persistence

The index hashes final persisted bytes for every stable artifact except itself,
the final construction report, and the noncanonical runtime report. Records are
sorted by relative POSIX path and contain category, stage, byte size, SHA-256,
required status, grammar type, and edit key where applicable.

Persistence:

- rejects nonempty output unless overwrite is explicit;
- preserves unrelated files;
- clears only the stale success report before an overwrite attempt;
- removes stale known artifacts omitted by a new successful configuration;
- uses same-directory temporary files and atomic replacement;
- cleans temporary files;
- writes `construction_report.json` last;
- removes the success report after any persistence failure.

## CLI

```text
python -m scene_grammar_kit construct-assisted-scene ANNOTATION \
  --config CONFIG --out DIRECTORY
```

Options:

```text
--overwrite
--skip-image-verification
--no-verify-execution
--camera {isometric,front,top}
--width INTEGER
--height INTEGER
--no-default-edit
--maximum-depth INTEGER
--maximum-primitives INTEGER
```

Expected domain, validation, rendering, editing, geometry, and I/O failures
produce a short nonzero CLI result without an ordinary traceback.

## Limitations

The bundle contains normalized semantic proxy geometry. It does not provide
automatic annotation, image segmentation, object detection, metric depth,
calibrated cameras, hidden geometry, physical dimensions, textures, or
photorealistic reconstruction. Real-image assisted demonstrations remain Batch
2.7 work.
