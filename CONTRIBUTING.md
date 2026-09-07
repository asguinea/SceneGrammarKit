# Contributing

Thanks for considering an improvement to SceneGrammarKit.

## Development setup

```bash
uv sync --extra dev --frozen
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Keep changes focused and include tests for observable behavior. New persisted
formats must be versioned, deterministic, and backward-compatible or clearly
documented as breaking. Canonical artifacts must not contain absolute paths,
timestamps, machine-specific values, or unlicensed data.

## Pull requests

- Explain the problem and the chosen tradeoff.
- Add or update tests and documentation.
- Run the full local checks.
- Avoid unrelated generated-file churn.
- Call out schema, metric, or reproducibility changes explicitly.

By contributing, you affirm that you have the right to provide the change and
its included data or media under the repository's applicable license terms.
