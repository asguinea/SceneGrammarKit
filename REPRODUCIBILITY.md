# Reproducibility guide

This guide rebuilds and verifies every reference result without network access
after dependencies are installed.

## Reference environment

- Python: 3.11 or newer
- Runtime dependencies: Pillow and trimesh
- Hardware: CPU only; no GPU or display server is required
- Dependency resolution: `uv.lock`
- Canonical encodings: UTF-8 JSON/text, deterministic PNG, deterministic GLB

Use the lock file for the closest reproduction of the tested environment:

```bash
uv sync --extra dev --frozen
```

## Fast verification

```bash
uv run scene-grammar doctor
uv run pytest
```

The test suite covers schema validation, bounded execution, persistence,
rendering, editing, annotation lifting, grammar induction, deterministic
rebuilds, and the evaluation pipeline.

## Full artifact rebuild

Run one of the convenience scripts from the repository root:

```bash
bash scripts/reproduce.sh
```

```powershell
.\scripts\reproduce.ps1
```

The scripts perform three ordered stages:

1. Rebuild the three attributed real-image cases.
2. Audit provenance, expected outcomes, hashes, and same-environment determinism.
3. Regenerate the twelve-case controlled evaluation and figures.

All generated paths remain under `results/`. After a successful run,
`git diff -- results` should be empty except for the explicitly documented
machine-specific runtime diagnostics. Those diagnostics are excluded from
canonical artifact indexes.

## Determinism boundary

Canonical reports exclude absolute paths, timestamps, and wall-clock runtimes.
Same-environment checks compare canonical JSON, decoded PNG pixels and bytes,
GLB bytes and reopened geometry, source-image bytes, and summary tables.

Cross-platform byte identity is not claimed for third-party compression or
floating-point implementations. Semantic and structural checks remain the
portable acceptance boundary.

## Data provenance

Each image case records the Open Images identifier, upstream URL, original
landing page, author, license, byte hash, and the separate annotation license.
The manifests also distinguish dataset-supplied facts, researcher-supplied
annotations, derived proxy geometry, and information that is not inferred.
