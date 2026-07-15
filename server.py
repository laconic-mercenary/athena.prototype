"""Web server entry point for the Athena Workspaces UI.

Starts a FastAPI + uvicorn server that wraps the pipeline in a web service.
The React UI connects to this server for engagement management, SSE events,
operator chat, and artifact serving.

Usage:
    python server.py --config athena.yml [--host 0.0.0.0] [--port 8000]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from athena.config import load_config
from athena.logging_setup import configure_logging
from athena.server.app import create_app


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Athena Workspaces server")
    parser.add_argument("--config", required=True, type=Path, metavar="FILE",
                        help="Path to athena.yml")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port to listen on (default: 8000)")
    parser.add_argument("--verbose", action="store_true",
                        help="Stream agent reasoning to stdout")
    args = parser.parse_args()

    configure_logging(verbose=args.verbose)

    config = load_config(args.config)
    app = create_app(config)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
