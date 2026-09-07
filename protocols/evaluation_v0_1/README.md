# Evaluation protocol v0.1

This directory defines the frozen scope, system contract, and metrics used by
the repository's deterministic evaluation. Keeping the protocol versioned next
to the code makes assumptions reviewable and prevents silent changes to the
reported evidence.

- `scope.md` states supported claims and explicit non-claims.
- `system.md` defines inputs, outputs, limits, and determinism requirements.
- `metrics.md` defines the controlled evaluation and aggregation rules.

Changes that alter any result require a new protocol version or a clearly
documented compatibility note.
