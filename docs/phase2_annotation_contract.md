# Phase 2 annotation and construction contract

Batch 2.1 defines the input contract for SceneGrammarKit's annotation-assisted
workflow. It is not an automatic image-understanding or reconstruction system.
A human supplies visible semantic regions, object instances, depth-zone labels,
repeat membership, and structural axis hints. Later batches may deterministically
construct a grammar from these inputs, but this batch performs no construction.

## Normalized image coordinates

All annotation geometry uses `normalized_image_uv`. The origin `(0, 0)` is the
top-left image corner; `u` increases rightward and `v` increases downward;
`(1, 1)` is the bottom-right corner. Coordinates are resolution-independent and
describe visible image-space evidence only. They do not claim metric depth,
camera calibration, or true 3D recovery.

Shapes are strict positive-area rectangles or ordered polygons. Polygon order is
preserved. The contract exposes deterministic bounds, width, height, centroid,
signed-area, and absolute-area helpers without opening an image.

## Source image reference

`SourceImageReference` records a stable image ID, safe relative POSIX path,
positive declared pixel dimensions, and optional lowercase SHA-256 and
description. It does not open, hash, decode, or compare the referenced image.
Absolute, drive-qualified, parent-traversing, backslash, and malformed paths are
rejected.

## Supplied annotations

Regions describe visible structural, terminal, or open-space evidence using a
semantic class, normalized shape, and foreground, midground, or background
label. Optional parent IDs, split-axis hints, order hints, terminal geometry,
scalar attributes, and notes remain explicitly human supplied.

Instances describe visible object occurrences. Each has an explicit semantic
class, shape, depth zone, and terminal geometry. Optional parent and repeat-group
references are cross-validated.

Repeat groups contain an ordered list of at least two instance IDs and a
human-supplied `x`, `y`, or `z` axis hint. They do not store a derived repeat
count or spacing. A future constructor must derive count from membership and
estimate spacing, or preserve individual terminals when permitted.

The annotation document deliberately contains no grammar, derived split
boundary, repeat spacing, execution result, timestamp, username, annotator
identity, machine information, or absolute path.

## Construction configuration

Construction-config schema `0.1` supports only the
`normalized_orthographic_proxy` projection. Root bounds reuse SceneGrammarKit's
strict `Bounds3D` model. Three ordered, non-overlapping world-z intervals map
foreground, midground, and background annotations into the root bounds.

Complete coverage is required by default: the first interval starts at root
minimum z, the last ends at root maximum z, and adjacent intervals share
boundaries. Gaps are allowed only when
`require_complete_depth_coverage` is explicitly false.

Defaults are deterministic construction controls, not measurements:

- minimum normalized region extent: `0.01`
- boundary merge tolerance: `0.02`
- repeat alignment tolerance: `0.03`
- repeat size tolerance: `0.20`
- repeat spacing tolerance: `0.25`
- maximum grammar depth: `16`
- repeat fallback: enabled
- complete depth coverage: required

The `hints_then_geometry` axis policy permits a future constructor to use
supplied hints before deterministic geometry rules. `hints_required` requires a
human split-axis hint for every structural region. Batch 2.1 does not apply
either construction policy.

## Validation

Field-level model validation rejects malformed coordinates, shapes, paths,
attributes, enum values, tolerances, bounds, and intervals. Structured document
validation reports stable codes, severity, domain, annotation ID, deterministic
structural path, and factual message.

Annotation validation checks global IDs, parent references, hierarchy cycles and
depth, instance parents, repeat membership, semantic/depth/geometry consistency,
roles, and shapes. Configuration validation is reported separately.
Compatibility validation checks configured zones, minimum extents,
parent/child depth agreement, and required structural axis hints. Missing
information is reported rather than inferred.

## Canonical serialization and persistence

Both documents use UTF-8-compatible direct Unicode, sorted object keys, compact
separators, finite JSON numbers, and no final newline. Ordered regions,
instances, repeat groups, repeat members, polygon points, and depth intervals
retain their supplied order. The format contains no timestamps, generated IDs,
or environment values.

Saves are same-directory atomic writes. Parent creation and overwriting require
explicit permission, and temporary files are cleaned after failures.

Validate the canonical fixture from the repository root:

```text
python -m scene_grammar_kit validate-assisted-input \
  tests/fixtures/assisted/valid/urban_minimal.annotation.json \
  --config tests/fixtures/assisted/valid/urban_minimal.construction.json
```

## Explicit Batch 2.1 exclusions

This batch performs no image processing, image-dimension verification,
annotation overlay rendering, depth inference, segmentation, object detection,
camera estimation, 3D lifting, split or repeat induction, grammar construction,
scene execution, evaluation, presentation composition, or interactive annotation.
Those capabilities belong to Batch 2.2 or later.
