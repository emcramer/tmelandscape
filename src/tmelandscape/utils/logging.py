"""Structured logging via structlog."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structlog to emit human-readable logs to stderr.

    Called once at CLI / MCP server startup. Library code should *not* call this;
    it should just acquire a logger via :func:`get_logger`.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for the given name (typically ``__name__``)."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
