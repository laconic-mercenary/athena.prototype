"""Logging configuration for the Athena pipeline.

Call configure_logging() once from main(). All Athena modules then use
logging.getLogger(__name__) or a named child of "athena".

Third-party libraries (anthropic, urllib3, etc.) are silenced to WARNING
so they do not drown out pipeline events.
"""

from __future__ import annotations

import logging
import sys
import time

# Shared UTC formatter — reused by both the stream handler and RunLogger's file handler.
UTC_FORMATTER = logging.Formatter(
    fmt="%(asctime)s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
UTC_FORMATTER.converter = time.gmtime  # force UTC regardless of system timezone


def configure_logging(verbose: bool = False) -> None:
    """Configure the athena logger. Call once at process startup."""
    # Suppress noisy third-party loggers.
    logging.getLogger().setLevel(logging.WARNING)

    athena = logging.getLogger("athena")
    athena.setLevel(logging.DEBUG if verbose else logging.INFO)
    athena.propagate = False

    if not athena.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(UTC_FORMATTER)
        athena.addHandler(handler)
