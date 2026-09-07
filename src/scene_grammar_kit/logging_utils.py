"""Logging helpers for SceneGrammarKit commands and runs."""

from __future__ import annotations

import logging
from pathlib import Path

_HANDLER_MARKER = "_scene_grammar_kit_handler"
_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(
    level: int | str = logging.INFO,
    log_file: Path | None = None,
    *,
    logger_name: str = "scene_grammar_kit",
) -> logging.Logger:
    """Configure idempotent console and optional file logging.

    Repeated calls update levels without adding duplicate SceneGrammarKit handlers.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    console = _find_handler(logger, "console")
    if console is None:
        console = logging.StreamHandler()
        setattr(console, _HANDLER_MARKER, "console")
        logger.addHandler(console)
    console.setLevel(level)
    console.setFormatter(formatter)

    if log_file is not None:
        resolved_log_file = Path(log_file).expanduser().resolve()
        resolved_log_file.parent.mkdir(parents=True, exist_ok=True)
        marker = f"file:{resolved_log_file}"
        file_handler = _find_handler(logger, marker)
        if file_handler is None:
            file_handler = logging.FileHandler(resolved_log_file, encoding="utf-8")
            setattr(file_handler, _HANDLER_MARKER, marker)
            logger.addHandler(file_handler)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)

    return logger


def _find_handler(logger: logging.Logger, marker: str) -> logging.Handler | None:
    """Find a handler installed by :func:`configure_logging`."""
    return next(
        (
            handler
            for handler in logger.handlers
            if getattr(handler, _HANDLER_MARKER, None) == marker
        ),
        None,
    )
