"""Formal minimal evaluation package."""

from scene_grammar_kit.evaluation.models import (
    CASE_DEFINITION_VERSION,
    EVALUATION_POLICY_VERSION,
    METRIC_IMPLEMENTATION_VERSION,
    ControlledCaseResult,
    EvaluationResult,
    RealCaseResult,
)
from scene_grammar_kit.evaluation.persistence import (
    EvaluationPersistenceError,
)
from scene_grammar_kit.evaluation.runner import (
    EvaluationError,
    run_evaluation,
)

__all__ = [
    "CASE_DEFINITION_VERSION",
    "METRIC_IMPLEMENTATION_VERSION",
    "EVALUATION_POLICY_VERSION",
    "ControlledCaseResult",
    "EvaluationResult",
    "EvaluationError",
    "EvaluationPersistenceError",
    "RealCaseResult",
    "run_evaluation",
]
