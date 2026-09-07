# Integrated Phase 2 acceptance package

Overall status: **PASS**

This package audits the three frozen annotation-assisted Open Images cases without downloading data or changing their constructor outputs. It contains structured acceptance, descriptive evidence, attribution, regression locks, byte-identical review images, and a deterministic overview candidate.

Reproduce with:

```console
python -m scene_grammar_kit phase2-acceptance --cases inputs/real_cases --results results/real_cases --output results/phase2_acceptance --verify-determinism
```
