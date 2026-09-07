# Evaluation table

Preliminary evidence for an annotation-assisted prototype.

## Controlled cases

| Case | Family | Valid/executable | Coverage | Repeat | Split B | Repeat B | Flat B | Edit |
|---|---|---|---:|---:|---:|---:|---:|---|
| street_01 | urban_street | yes | 1.0 | 3/3 accepted | 7543 | 4789 | 2433 | valid/changed |
| street_02 | urban_street | yes | 1.0 | 4/4 accepted | 8996 | 4790 | 2858 | valid/changed |
| street_03 | urban_street | yes | 1.0 | 5/5 accepted | 10561 | 4790 | 3012 | valid/changed |
| street_04 | urban_street | yes | 1.0 | 6/6 accepted | 12121 | 4772 | 3281 | valid/changed |
| facade_01 | repeated_facade | yes | 1.0 | 3/3 accepted | 7764 | 4840 | 2514 | valid/changed |
| facade_02 | repeated_facade | yes | 1.0 | 4/4 accepted | 9226 | 4840 | 2890 | valid/changed |
| facade_03 | repeated_facade | yes | 1.0 | 5/5 accepted | 10851 | 4843 | 3077 | valid/changed |
| facade_04 | repeated_facade | yes | 1.0 | 6/6 accepted | 12498 | 4855 | 3321 | valid/changed |
| corridor_01 | indoor_corridor | yes | 1.0 | 0/3 rejected_fallback | 7838 | 7838 | 4610 | valid/changed |
| corridor_02 | indoor_corridor | yes | 1.0 | 0/4 rejected_fallback | 9330 | 9330 | 6005 | valid/changed |
| corridor_03 | indoor_corridor | yes | 1.0 | 0/5 rejected_fallback | 10846 | 10846 | 7154 | valid/changed |
| corridor_04 | indoor_corridor | yes | 1.0 | 0/6 rejected_fallback | 12542 | 12542 | 8491 | valid/changed |

## Frozen real assisted cases

| Case | Outcome | Primary | Repeat | Edit | Principal limitation |
|---|---|---|---|---|---|
| canonical_success | success | repeat | accepted=1; fallback=0 | applied | No principal limitation declared for this representation-aligned success case. |
| moderate_case | success | repeat | accepted=1; fallback=0 | applied | No principal limitation declared for this representation-aligned success case. |
| limitation_case | degraded_success | split_only | accepted=0; fallback=0 | applied | Curved and receding facade geometry is reduced to axis-aligned bounding-box proxies; the semantic result is deterministic but does not preserve curvature or perspective. |

The real cases are descriptive; no three-example accuracy is calculated.
