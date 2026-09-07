"""Utilities for deterministic, CPU-safe development."""

from __future__ import annotations

import os
import random
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SeedSummary:
    """Structured record of deterministic seed configuration."""

    seed: int
    python_random: bool
    numpy: bool
    python_hash_seed: str

    def to_dict(self) -> dict[str, Any]:
        """Return the summary as a plain serializable dictionary."""
        return asdict(self)


def seed_everything(seed: int) -> SeedSummary:
    """Seed Python and NumPy, when available, without requiring NumPy.

    ``PYTHONHASHSEED`` is recorded for child processes. Hash randomization for
    the already-running interpreter cannot be changed at runtime.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")

    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    numpy_seeded = _seed_numpy(seed)
    return SeedSummary(
        seed=seed,
        python_random=True,
        numpy=numpy_seeded,
        python_hash_seed=str(seed),
    )


def _seed_numpy(seed: int) -> bool:
    """Seed NumPy if it is installed and return whether it was seeded."""
    try:
        import numpy as np
    except ImportError:
        return False

    np.random.seed(seed)
    return True
