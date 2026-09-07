# Integrated Phase 2 acceptance

Batch 2.8 introduces independent `phase2-acceptance` policy version `0.1`.
It audits and packages the existing annotation-assisted workflow without
changing induction, grammar, rendering, or editing. Batch 3.2 intentionally
updates the two positive frozen identities and their regression hashes.

## Formal command

```console
python -m scene_grammar_kit phase2-acceptance \
  --cases inputs/real_cases \
  --results results/real_cases \
  --output results/phase2_acceptance \
  --verify-determinism
```

The command is offline. It uses the three already frozen Open Images V7
validation photographs and never starts candidate search or dataset download.
The required order is `canonical_success`, `moderate_case`, then
`limitation_case`; missing, duplicate, or unexpected roles fail acceptance.

## Dataset and attribution policy

Every manifest must retain the Open Images ID, source SHA-256, title, author,
original landing page, official CVDF mirror, and permitted image license.
Source photographs use CC BY 2.0 in this frozen set. Open Images annotations
are recorded separately as CC BY 4.0. These checks audit repository metadata
and are not a general legal certification.

## Assisted-evidence disclosure

Dataset-supplied facts, project-authored annotations, and SceneGrammarKit-derived
proxy values remain separate. The acceptance package explicitly rejects claims
of automatic reconstruction, automatic segmentation, true 3D recovery, or
metric-depth recovery. Source pixels are evidence and panel content; they are
not analyzed by this batch.

## Expected outcomes

- `canonical_success`: repeat grammar, one accepted supplied repeat group,
  no fallback, and a disclosed repeat-count edit.
- `moderate_case`: structured-street repeat grammar, one accepted supplied
  car group, no fallback, and a disclosed repeat-count edit.
- `limitation_case`: constructor-generated degraded success whose axis-aligned
  proxy visibly loses facade curvature and projective foreshortening.

A matched degraded-success limitation is evidence of the representation
boundary and is not an acceptance failure.

## Evidence table

The evidence summary is descriptive: one row per frozen case with supplied
counts, lifted counts, grammar sizes, repeat decisions, primary grammar,
primitive count, edit status, warnings, limitation code, and license. Missing
values use the empty string. No means, percentages, significance tests,
rankings, or three-case performance claims are generated.

## Deterministic verification

With `--verify-determinism`, the existing Batch 2.7 builder reconstructs every
case in a temporary directory from frozen local inputs. Acceptance compares
source, manifest, annotation, configuration, constructor report, grammar,
primitive, PNG pixel, PNG byte, GLB byte, reopened GLB structure, case report,
and review-panel evidence. Explicitly unstable runtime reports and their
dependent artifact-index hashes are excluded. Temporary verification
directories are removed.

## Regression manifest

`tests/fixtures/phase2/phase2_regression_manifest.json` locks policy versions,
case order, identities, source/annotation/configuration hashes, constructor
report hashes, primary grammar hashes, outcomes, repeat decisions, review
panels, and evidence-row identities.

After an intentional case change, rebuild all Batch 2.7 results with
deterministic verification, run the full suite, regenerate every locked value
from canonical artifacts, inspect the complete diff, and commit the approved
case change and manifest update together. Never update one hash to silence an
unexplained mismatch.

## Limitations and Phase boundary

This package contains proxy geometry and qualitative evidence from three
licensed images. It is not an accuracy benchmark, final presentation layout, final
representative image or distribution package. The generated overview is
only a deterministic design candidate.

The Batch 3.2 hero follows input, supplied structure, actual constructor
grammar, structured-scene proxy, and explicit edit, with the street success
and Turku limitation in its support strip.
