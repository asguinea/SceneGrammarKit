# SceneGrammarKit evaluation

Policy version: **0.1**

This package is preliminary evidence for an annotation-assisted prototype. It evaluates 12 frozen controlled cases and reports three frozen Open Images cases descriptively. It does not measure general reconstruction accuracy, automatic image understanding, broad generalization, or metric 3D recovery.

Reproduce offline:

    python -m scene_grammar_kit evaluate --output results/evaluation --verify-determinism

`runtime_diagnostics.json` is machine-specific and noncanonical. All other outputs are deterministic and indexed by relative path.
