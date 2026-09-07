# Phase 2 acceptance

**Overall status:** PASS

## Policy versions

- phase2_acceptance: `0.1`
- real_case: `0.1`
- constructor: `0.1`
- annotation_schema: `0.1`
- construction_config_schema: `0.1`
- annotation_review: `0.1`
- lifting: `0.1`
- split_induction: `0.1`
- repeat_induction: `0.1`
- grammar_schema: `0.1`
- execution: `0.1`
- renderer: `0.1`
- editing: `0.1`

## Case results

| Case | Image ID | Expected | Observed | Primary | Repeats A/F | Status |
|---|---|---|---|---|---:|---|
| canonical_success | `736a482693c18962` | success | success | repeat | 1/0 | PASS |
| moderate_case | `40992cf7a7bbf20e` | success | success | repeat | 1/0 | PASS |
| limitation_case | `692c5c6be088dbf8` | degraded_success | degraded_success | split_only | 0/0 | PASS |

## Acceptance totals

- Total: 65
- Passed: 65
- Failed: 0
- Skipped: 0
- Required failures: 0

## Failed checks

- None.

## Skipped checks

- None.

## Evidence summary

One frozen row is reported per case. Missing values use the empty string. No aggregate statistics or rankings are calculated.

| case_key | open_images_id | case_role | constructor_status | source_width | source_height | supplied_region_count | supplied_instance_count | supplied_repeat_group_count | lifted_observation_count | split_symbolic_node_count | split_terminal_count | split_grammar_bytes | repeat_symbolic_node_count | repeat_terminal_count | repeat_grammar_bytes | accepted_repeat_groups | fallback_repeat_groups | primary_grammar | primary_primitive_count | default_edit_type | default_edit_status | warning_count | limitation_code | source_license |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| canonical_success | 736a482693c18962 | canonical_success | success | 1024 | 683 | 6 | 5 | 1 | 11 | 63 | 43 | 11206 | 32 | 19 | 5419 | 1 | 0 | repeat | 8 | set_repeat_count | applied | 0 |  | https://creativecommons.org/licenses/by/2.0/ |
| moderate_case | 40992cf7a7bbf20e | moderate_case | success | 1024 | 768 | 6 | 5 | 1 | 11 | 62 | 44 | 11201 | 31 | 20 | 5469 | 1 | 0 | repeat | 15 | set_repeat_count | applied | 0 |  | https://creativecommons.org/licenses/by/2.0/ |
| limitation_case | 692c5c6be088dbf8 | limitation_case | success | 1024 | 305 | 6 | 0 | 0 | 6 | 21 | 13 | 3690 | 21 | 13 | 3690 | 0 | 0 | split_only | 5 | set_split_child_weight | applied | 1 | axis_aligned_proxy_curvature_loss | https://creativecommons.org/licenses/by/2.0/ |

## Attribution status

- Complete attribution records are in `attribution.json` and `ATTRIBUTION.md`.
- Source-image licenses and the Open Images annotation license are recorded separately.

## Deterministic verification

- `DETERMINISM_SOURCE`: PASS — source bytes match rebuilt cases
- `DETERMINISM_MANIFESTS`: PASS — case manifest bytes match
- `DETERMINISM_ANNOTATION_CONFIG`: PASS — annotation/configuration bytes match
- `DETERMINISM_CONSTRUCTOR_REPORTS`: PASS — constructor/canonical JSON mismatches=[]
- `DETERMINISM_GRAMMARS_PRIMITIVES`: PASS — grammar and primitive bytes match
- `DETERMINISM_PNG_PIXELS`: PASS — platform-neutral pixel mismatches=[]
- `DETERMINISM_PNG_BYTES`: PASS — independent same-environment PNG builds match byte-for-byte
- `DETERMINISM_GLB_BYTES`: PASS — GLB byte mismatches=[]
- `DETERMINISM_GLB_STRUCTURES`: PASS — GLB structure mismatches=[]
- `DETERMINISM_CASE_REPORTS`: PASS — case report bytes match
- `DETERMINISM_REVIEW_PANELS`: PASS — independent same-environment review panel builds match byte-for-byte

## Known limitations

- The workflow is annotation-assisted and does not infer segmentation or metric depth.
- Proxy geometry is axis-aligned and does not preserve the curved limitation facade.
- Three qualitative cases provide descriptive evidence, not aggregate real-world accuracy.
- The overview is a qualitative visualization, not an accuracy metric.

## Reproduction

```console
python -m scene_grammar_kit phase2-acceptance --cases inputs/real_cases --results results/real_cases --output results/phase2_acceptance --verify-determinism
```

## Explicit next step

public release validation and broader evaluation
