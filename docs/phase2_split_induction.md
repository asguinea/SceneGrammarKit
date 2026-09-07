# Phase 2 constrained split-induction policy

Batch 2.4 introduces split-induction policy `0.1`. It is independent of the
annotation, construction-config, annotation-review, lifting, grammar,
execution, renderer, demo, and package versions.

The constructor turns validated lifted proxy observations into an executable
split-only SceneGrammarKit grammar. It is annotation-assisted and deterministic. It
does not analyze image pixels, recover metric geometry, infer a new semantic
hierarchy, or generate repeat rules.

## Frozen root construction

The grammar root is always:

```text
induced_scene_depth_zones: Split axis=z
  foreground
  midground
  background
```

Its three ordered weights are the configured interval lengths:

```text
weight(zone) = configured_z_max - configured_z_min
```

Weights are persisted as physical proxy lengths and are not normalized by the
constructor. The existing executor interprets them as relative weights. Batch
2.4 therefore requires the configured intervals to form contiguous complete
root-z coverage so execution reproduces the supplied zone boundaries exactly.

## Supplied hierarchy and ordering

`parent_region_id` is the sole semantic-parent authority. Parentless
observations are placed directly in their supplied depth zone. Direct siblings
retain annotation order unless every sibling has a distinct supplied
`order_hint`, in which case the hints order them with annotation order as the
stable tie-breaker. A spatial ordering that contradicts the supplied sibling
order fails instead of silently moving observations.

Structural regions form subtrees. Terminal regions and object instances use
their supplied semantic class, geometry, and attributes. Open-space regions
become explicit `empty` terminals. A structural region without usable children
fails with `structural_region_without_children`.

When a terminal region contains child instances, the children partition the
region and uncovered fragments retain the parent region's semantics. This
split-only carving policy lets supplied child instances remain under their
declared parent without introducing an overlay operator.

## Axis selection

For a parent with multiple direct children, priority is:

1. the structural parent's supplied split-axis hint;
2. the supplied repeat-group axis when all children are instances from one
   group;
3. deterministic geometry when `axis_policy=hints_then_geometry`;
4. failure when `axis_policy=hints_required` supplies no applicable hint.

Every axis candidate records:

- validity;
- overlap violations;
- normalized centroid spread;
- normalized interval coverage;
- required explicit gap count.

Valid geometry candidates are compared lexicographically by:

```text
fewer overlap violations
greater normalized centroid spread
greater normalized coverage
fewer explicit gaps
fixed tie break x, y, z
```

An axis is valid only when every child interval is positive, lies inside the
parent within tolerance, and has no interior overlap greater than tolerance.

## Boundary and gap policy

For parent extent `L`:

```text
world_tolerance = boundary_merge_tolerance * L
```

Adjacent boundaries whose overlap or gap magnitude is within tolerance are
replaced by their midpoint. A small positive gap also records
`small_gap_absorbed`. A boundary within tolerance of the parent edge is
absorbed to that exact edge.

Overlaps larger than tolerance fail. Larger internal gaps and parent margins
become explicit empty terminals. Observed semantic segments smaller than
`minimum_normalized_region_extent * L` on the selected axis fail and are never
discarded.

Final split weights are:

```text
weight_i = final_interval_max_i - final_interval_min_i
```

They remain positive, finite, ordered, and unnormalized.

## Wrapper splits

A partition assigns each child a slab spanning its parent on the other axes.
To isolate a child's lifted bounds, ordinary wrapper splits are added in fixed
axis order `x`, `y`, then `z`.

Each material difference produces:

```text
optional leading filler
content matching the lifted observation
optional trailing filler
```

Fillers are explicit empty terminals, except inside a terminal parent where
they retain that parent region's semantics. Differences within boundary
tolerance are absorbed. No zero-width wrapper segment is generated.

## Stable identifiers and provenance

Stable human-readable IDs use deterministic sanitized source tokens:

```text
induced_region_<source>
induced_instance_<source>
induced_split_<parent>_<axis>_<index>
induced_wrapper_<source>_<axis>_<index>
induced_gap_<parent>_<axis>_<index>
```

Sanitization collisions fail rather than collapsing two source IDs. Reports
map every source observation to all generated wrapper, split, fragment, and
terminal IDs and identify a primary node.

## Repeat-candidate baseline

Supplied repeat membership and member order are preserved. The supplied group
axis may select a split, but every member remains an independent terminal.
Reports record:

```text
compression_status = deferred_to_batch_2_5
```

No `RepeatNode`, repeat spacing, regularity score, or repeat optimization is
created.

## Validation and execution

Induction verifies annotation/config compatibility and the lifted document's
scene ID, root bounds, configured intervals, annotation hash, config hash,
observation IDs, and ordering.

The result must:

- validate through the existing grammar validator;
- contain zero `RepeatNode` values;
- execute by default through the existing executor;
- preserve configured root bounds;
- map every source observation exactly once;
- reproduce each non-structural source proxy's bounding bounds within the
  configured tolerance;
- keep every primitive inside root bounds.

Empty sources are verified through grammar mapping because they intentionally
produce no primitive.

## Diagnostics

Stable codes include:

```text
supplied_split_axis_used
supplied_repeat_axis_used
geometry_axis_selected
no_partition_axis
child_outside_parent
child_interval_overlap
boundary_snapped
small_gap_absorbed
explicit_gap_created
leading_margin_created
trailing_margin_created
observation_below_minimum_extent
structural_region_without_children
source_observation_omitted
duplicate_source_representation
wrapper_split_created
repeat_candidate_deferred
execution_verification_failed
```

Diagnostics follow deterministic construction traversal.

## Outputs and CLI

```text
annotation.json
construction_config.json
lifted_observations.json
induced_grammar.json
grammar_tree.txt
split_induction_report.txt
execution_report.json          # when execution is verified
split_induction_report.json    # written last
```

Canonical JSON uses sorted keys, compact separators, direct Unicode, finite
numbers, stable list ordering, no timestamps, no absolute paths, and no final
newline. Text outputs have exactly one final newline. Persistence protects
nonempty directories unless overwrite is explicit, preserves unrelated files,
uses same-directory atomic writes, cleans temporary files, and removes stale
success reports after failures.

Run:

```text
python -m scene_grammar_kit induce-split-grammar annotation.json \
  --config construction.json --out output_directory
```

Optional controls load precomputed observations, skip source-image
verification during lifting, disable execution verification, override maximum
grammar depth, and limit primitive expansion.

## Explicit nonclaims

The constructor does not infer image segmentation, metric depth, calibrated
cameras, new semantic labels, a parent hierarchy beyond the supplied
annotation, repeat spacing, `RepeatNode` structure, stochastic rules, learned
structure, photorealistic geometry, or a reconstructed scene.
