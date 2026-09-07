# Phase 2 Open Images real cases

Batch 2.7 adds three reproducible, annotation-assisted demonstrations
using legally reusable photographs from the official Open Images distribution.
It does not add perception, segmentation, or a new induction algorithm.
Batch 3.2 reselects the two positive photographs for closer alignment with
the existing axis-aligned split-and-repeat representation; it does not change
the constructor.

## Reproduction

```console
python -m scene_grammar_kit build-open-images-cases \
  --output results/real_cases \
  --all \
  --verify-determinism
```

The builder validates source hashes and attribution, invokes the unchanged
Batch 2.6 `construct_assisted_scene` workflow at 1200 x 800, verifies grammar,
render, edit, and source provenance, and produces case summaries and review
panels. Every panel says `Annotation-assisted`.

## Frozen cases

- `canonical_success`: Statens Hus, Leikanger; a regular planar facade with a
  supplied five-window group accepted and edited from 5 to 6.
- `moderate_case`: Komotini Demokratias Avenue and Parking; a structured
  street/parking layout with a supplied five-car group accepted and edited
  from 5 to 6. The compatibility role name remains `moderate_case`; the release
  presents it as the structured-street success.
- `limitation_case`: curved Turku facade; construction succeeds, while the
  axis-aligned proxy visibly loses curvature and projective foreshortening.

The image and annotation licenses are recorded separately in every manifest.
Candidate pixels and metadata caches remain ignored. The former Halifax and
Barcelona bundles are retained under `results/real_cases/archive/` as valid
pipeline outputs replaced for representational-scope alignment, not hidden
technical failures.
