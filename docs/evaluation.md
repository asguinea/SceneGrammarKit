# Minimal evaluation

## Scope

Evaluation policy version 0.1 produces **preliminary evidence for an
annotation-assisted prototype**. It reuses the existing Phase 1 grammar,
executor, renderer, and editor and the Phase 2 assisted constructor. It adds
no dataset, induction algorithm, grammar operator, renderer, or interface.

Run from the repository root without network access:

```console
python -m scene_grammar_kit evaluate \
  --output results/evaluation \
  --verify-determinism
```

The source definitions are the 12 JSON files under
`evaluation/benchmark_v0_1/cases/`: four urban streets, four repeated facades,
and four indoor corridors. Each freezes its parameters, expected observation
counts, repeat membership and count, key split boundaries, constructor
outcome, repeat decision, and edit outcome. These compact definitions expand
deterministically into the existing annotation schema and common construction
configuration.

## Controlled metrics

All coordinates below are camera-independent normalized proxy coordinates.
No value is an image-inference accuracy measurement.

### Construction and execution

- **Constructor success:** the existing assisted constructor completed.
- **Grammar-validation success:** both split-only and repeat-result grammars
  passed the existing schema and semantic validator.
- **Execution success:** the repeat-result grammar executed into legal proxy
  terminals.

### Observation transfer

- **Source-observation coverage:** represented supplied regions and instances
  divided by all supplied regions and instances.
- **Omitted-observation count:** supplied observations lacking a constructor
  mapping.
- **Duplicate-observation count:** extra source mappings after counting unique
  source annotation identifiers.

Complete coverage requires coverage 1.0 and zero omitted and duplicate
observations.

### Split-boundary transfer

For each frozen key boundary:

```text
absolute error = |constructed boundary - supplied boundary| / parent extent
```

The produced boundary is the nearest boundary in the constructor's audited
decision for the supplied structural parent and axis. Results retain the axis
and every per-boundary value. The aggregate reports the median and range over
24 normalized boundary observations and always reports that denominator.
No incomparable physical or angular boundary types are combined.

### Repeat decision and fidelity

- **Supplied repeat count:** number of ordered supplied member identifiers.
- **Produced repeat count:** accepted `RepeatNode` member count; zero when the
  existing constructor takes its permitted split-only fallback.
- **Exact repeat count:** equality of supplied and produced counts.
- **Repeat decision:** the existing induction decision, either accepted or
  rejected with fallback for this frozen set.
- **Maximum accepted-member proxy-boundary error:** maximum absolute bound
  residual reported by the existing repeat-fidelity audit. It is meaningful
  for accepted groups; fallback cases preserve the supplied terminals
  explicitly.

The corridor definitions intentionally freeze the observed split-only fallback
behavior. They are not relabeled as compressed repeats.

### Symbolic representation

For both the split-only and repeat-result grammar, the evaluation records:

- symbolic node count;
- UTF-8 byte count of the existing compact canonical JSON.

The **byte ratio** is repeat-result grammar bytes divided by split-only grammar
bytes. This measures the existing repeat-compression transformation. It is
separate from the flat baseline.

### Flat explicit terminals

The factual baseline is an ordered canonical JSON list containing, for every
executed repeat-result terminal:

- order;
- semantic class;
- geometry type;
- normalized bounds;
- scalar semantic attributes.

The evaluation verifies that regenerating this list from the same execution
produces exactly the same canonical content. It records flat terminal count
and UTF-8 bytes alongside split-only and repeat-result bytes. This is not a
comparison with dense or appearance-based representations.

### Predefined edit and pixels

The existing constructor chooses its documented predefined edit: accepted
repeats receive a count variation; fallback cases receive the documented
structural split-weight variation. An edit is valid when the edited grammar
and execution exist. Pixel-difference status is `changed` only when matched
before/after semantic PNGs contain at least one different RGB pixel.

### Runtime diagnostics

Constructor stage runtimes are machine-specific and noncanonical. They are
stored only in `runtime_diagnostics.json`, excluded from artifact hashing, and
not aggregated into a performance claim.

## Controlled aggregation

Only the 12 controlled cases are aggregated. The report includes explicit
numerators and denominators for:

- valid grammar rate;
- execution-success rate;
- complete observation-coverage rate;
- exact repeat-count rate;
- valid visible-edit rate.

It also reports accepted and fallback repeat-group counts out of 12, boundary
median and range over 24 boundaries, and medians over 12 cases for split-only
bytes, repeat-result bytes, and repeat/split byte ratio. No hypothesis test is
performed.

## Frozen real cases

The three Phase 2 Open Images roles appear in their fixed order:

1. `canonical_success`;
2. `moderate_case`;
3. `limitation_case`.

Their rows are descriptive. They include outcome, supplied observations,
repeat acceptance/fallback, primary grammar, node and byte counts, primitive
count, edit status, warnings, limitation, image ID, license, and frozen
hashes. No three-example real-case accuracy is calculated, and the curved
facade limitation remains explicit in both the table and evaluation panel.
Batch 3.2 replaces the two positive identities with a regular facade success
and a structured-street success. Both use accepted repeats; this descriptive
change does not alter the 12 controlled definitions, controlled results,
aggregation, compactness metrics, or evaluation methodology.

## Provenance and determinism

Every controlled or real-case row records the frozen Phase 2 foundation
commit, policy and metric versions, input hashes, constructor-report hash,
grammar hashes, and repository-relative artifact paths. The metric
implementation has its own source hash. Canonical reports contain no
timestamps or absolute paths.

With `--verify-determinism`, all controlled cases are constructed twice and
canonical rows, aggregate values, and all three figure byte streams are
compared. The noncanonical runtime sidecar is excluded.

## Interpretation and boundary

This package answers only whether supplied structure transfers into valid
executable grammars, whether accepted repeats preserve supplied membership
within reported proxy residuals, whether repeat transformation changes
symbolic size, whether predefined edits remain valid and visible, and how the
three frozen real examples behave.

Packaging or presenting the results is outside this evaluation workflow.
