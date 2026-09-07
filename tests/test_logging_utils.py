"""Tests for idempotent logging configuration."""

import logging
from pathlib import Path

from scene_grammar_kit.logging_utils import configure_logging


def test_repeated_logging_configuration_has_no_duplicate_handlers(
    tmp_path: Path,
) -> None:
    """Repeated initialization reuses one console and one file handler."""
    logger_name = "scene_grammar_kit.tests.idempotent"
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    log_file = tmp_path / "logs" / "test.log"

    first = configure_logging(logging.DEBUG, log_file, logger_name=logger_name)
    second = configure_logging(logging.INFO, log_file, logger_name=logger_name)

    assert first is second
    assert len(second.handlers) == 2
    second.info("one message")
    for handler in second.handlers:
        handler.flush()
    assert log_file.read_text(encoding="utf-8").count("one message") == 1

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
