"""Command-line entrypoint for the Athena prototype."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from athena.config import load_config
from athena.logging_setup import configure_logging
from athena.model_backend import make_backend
from athena.orchestrator import run_orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Athena agent committee pipeline")
    parser.add_argument("--instructions", required=True, type=Path, metavar="FILE")
    parser.add_argument("--config", required=True, type=Path, metavar="FILE")
    parser.add_argument("--verbose", action="store_true", help="Stream agent reasoning to stdout")
    args = parser.parse_args()

    configure_logging(verbose=args.verbose)

    config = load_config(args.config)
    instructions = args.instructions.read_text()

    result = run_orchestrator(
        instructions=instructions,
        config=config,
        _backend_factory=make_backend,
    )

    sys.exit(0 if result is not None else 1)


if __name__ == "__main__":
    main()
