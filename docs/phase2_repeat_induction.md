# Phase 2 repeat-group induction

Batch 2.5 converts only human-supplied repeat groups into deterministic
`RepeatNode` structures. Its independent policy version is `0.1`. It preserves
annotation schema `0.1`, construction-config schema `0.1`, lifting policy
`0.1`, split-induction policy `0.1`, grammar schema `0.1`, and execution policy
`0.1`.

## Scientific boundary

Repeat membership and repeat axis are supplied by the annotation author.
Regularity checks, proxy spacing, the representative proxy bounds, grammar
construction, and diagnostic comparisons are derived deterministically.

The implementation does not inspect pixels to discover repetition. It does not
add hidden or occluded members, infer semantic classes, recover physical object
sizes, learn regularity, estimate metric depth, construct photorealistic
geometry, or introduce stochastic repeat rules.

The required baseline is a complete Batch 2.4 `SplitInductionResult`. Each
supplied member must already have one independent split-only terminal. Groups
are evaluated in annotation order; arbitrary terminal collections are never
considered.

## Eligibility and frozen calculations

For supplied axis `a`, ordered member intervals are `[lower_i, upper_i]`.
Member order is not changed. Pairwise gap `i` is
`lower_(i+1) - upper_i`. A negative gap no larger than the Batch 2.4 world
boundary tolerance is treated as zero; a larger overlap rejects the group.

The group span is exactly `[lower_1, upper_n]`. Count is exactly the number of
supplied member IDs. Spacing is the deterministic median of nonnegative gaps.
For an even number of gaps, the median is the arithmetic mean of the two
central sorted values. No library median or randomness is used.

The existing repeat executor has equal-cell semantics. Therefore:

```text
element_extent =
  (group_extent - (count - 1) * spacing) / count
```

The fit is rejected unless this extent is positive. Predicted interval `i`,
indexed from zero, begins at:

```text
group_min + i * (element_extent + spacing)
```

The final predicted maximum is explicitly set to `group_max`.

Eligibility also requires:

- every supplied member to exist as a lifted instance observation;
- a common supplied parent and depth zone;
- equal supplied semantic class and terminal geometry;
- canonically equal supplied attributes;
- positive proxy extents on every axis;
- monotonic supplied order;
- acceptable overlap, alignment, size, spacing, and positional residual;
- consensus orthogonal bounds inside the supplied parent bounds;
- exactly one split-only baseline terminal for each supplied member.

## Alignment, size, and spacing metrics

For both axes orthogonal to the supplied repeat axis, median center and median
extent are calculated deterministically. Center deviations use the configured
construction root extent as the stable parent coordinate frame. This is the
relevant normalized frame shared by all Batch 2.4 parent partitions. The
aggregate alignment error is the maximum normalized center deviation.

Size consistency is evaluated on all axes. The repeat axis uses the implied
equal-cell element extent; orthogonal axes use their median extents. Each error
is the absolute difference divided by the representative extent. The aggregate
is the maximum member/axis error.

When median spacing is greater than `1e-12`, gap error is normalized by that
spacing. Otherwise, absolute gap is normalized by group extent. Positional
residual is the maximum observed-versus-predicted interval-boundary difference
divided by group extent. Both values must satisfy
`repeat_spacing_tolerance`.

The implementation never relaxes a configured tolerance.

## Representative element and grammar construction

The representative terminal uses the common supplied semantic class, geometry
type, and canonical attributes. Orthogonal bounds use median member center and
extent. The repeat-axis envelope is the exact supplied group span. Element size
is not stored: the existing executor derives it from count, spacing, and the
envelope.

Accepted groups use stable IDs:

```text
induced_repeat_<group-id>
induced_repeat_element_<group-id>
induced_repeat_wrapper_<group-id>_<axis>
```

The Batch 2.4 grammar is transformed structurally using its recorded independent
member terminals. The contiguous member range is replaced with one repeat
subtree. Leading and trailing parent partitions remain unchanged. Orthogonal
wrappers preserve the parent envelope and add deterministic semantic filler
where needed. Internal member terminals and their split-only gaps are removed.
No source member is privileged as a prototype: the semantic values are common
to every eligible member and the geometry is a group consensus.

Multiple disjoint supplied groups are processed sequentially in annotation
order. Nested groups are outside policy `0.1`.

## Decisions and member mappings

`RepeatRegularityMetrics` records all intervals, extents, gaps, the group span,
median spacing, implied extent, orthogonal medians, aggregate errors, and
configured tolerances.

`RepeatGroupDecision` records accepted, rejected fallback, or fatal rejection;
ordered source members; stable reason codes; source parent; supplied semantics;
and generated node IDs.

`RepeatMemberMapping` gives every member its supplied index, observed bounds,
predicted bounds and boundary residual when compressed, generated repeat and
element IDs, or its independent fallback terminal. Multiple members can map to
one symbolic element while retaining distinct conceptual repeat indices.

`RepeatCompressionSummary` records factual split-only and repeat grammar node
counts, canonical byte sizes, byte ratio/difference, and executed primitive
counts. These values are diagnostics, not a scientific superiority claim.

## Fallback and transaction policy

A rejected group falls back only when both
`ConstructionConfig.allow_repeat_fallback` and
`RepeatGroupAnnotation.allow_fallback_to_individuals` are true. Its Batch 2.4
terminals remain unchanged and a warning records the rejection reasons.

If either permission is false, the complete induction raises a
`RepeatInductionValidationError`. Persistence happens only after successful
construction, validation, and optional execution. A fatal rejection therefore
cannot create a successful report.

## Validation and fidelity

The repeat grammar is validated under the configured or explicit depth limit.
By default, both baseline and repeat grammars execute under the existing
execution policy and primitive limit.

Each accepted member is matched to exactly one executed representative
primitive by terminal ID and repeat index. Its predicted proxy bounds are
compared with the lifted observation. Non-repeat executed terminals are matched
by source terminal ID and their bounds must remain unchanged within the
deterministic epsilon. Root bounds must equal the split-only baseline.

The fidelity report records conceptual source count before and after, maximum
accepted-member boundary error, maximum non-repeat change, root equality, and
both execution outcomes. Generated fillers are not treated as source-backed
members.

## Stable diagnostics

Diagnostics appear in group evaluation order, followed by ordered eligibility
reasons:

- `repeat_group_evaluated`
- `repeat_group_accepted`
- `repeat_group_rejected_fallback`
- `repeat_group_rejected_fatal`
- `repeat_member_missing`
- `repeat_member_parent_mismatch`
- `repeat_member_depth_zone_mismatch`
- `repeat_member_semantic_mismatch`
- `repeat_member_geometry_mismatch`
- `repeat_member_attribute_mismatch`
- `repeat_member_order_nonmonotonic`
- `repeat_member_overlap`
- `repeat_group_interleaved_source_observation`
- `repeat_alignment_tolerance_exceeded`
- `repeat_size_tolerance_exceeded`
- `repeat_spacing_tolerance_exceeded`
- `repeat_invalid_fit`
- `repeat_consensus_bounds_outside_parent`
- `repeat_node_created`
- `repeat_geometry_verification_failed`
- `repeat_fallback_preserved`
- `no_repeat_groups_supplied`

Each structured diagnostic has stable code, severity, group/member/node context
where relevant, structural path, and a factual message.

## Persistence and CLI

`induce_repeat_grammar_from_files` either reuses existing lifting and split
induction implementations or verifies and reconstructs a supplied Batch 2.4
bundle. It rejects annotation, configuration, lifted-observation, report, or
grammar hash mismatches.

The canonical output set contains:

```text
annotation.json
construction_config.json
lifted_observations.json
split_only_grammar.json
split_only_grammar_tree.txt
repeat_grammar.json
repeat_grammar_tree.txt
split_induction_report.json
repeat_induction_report.json
repeat_induction_report.txt
split_only_execution_report.json
repeat_execution_report.json
```

Execution reports are omitted only when execution verification is explicitly
disabled. A nonempty output directory is protected unless overwrite is
explicit. Overwrite replaces only known artifacts and preserves unrelated
files. Writes use same-directory temporary files and atomic replacement; the
success report is written last and removed if persistence fails. An explicit
overwrite also clears only the known stale success marker before construction,
so a fatal rerun cannot leave an older run looking successful.

The command is:

```text
python -m scene_grammar_kit induce-repeat-grammar ANNOTATION \
  --config CONFIG --out DIRECTORY
```

It supports `--split-induction-directory`, `--overwrite`,
`--skip-image-verification`, `--no-verify-execution`, `--maximum-depth`, and
`--maximum-primitives`. Expected domain, validation, and I/O failures produce a
short nonzero result without an ordinary traceback.
