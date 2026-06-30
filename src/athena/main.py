"""Command-line entrypoint for the Athena prototype."""

from __future__ import annotations

from athena.config import load_config


def main() -> None:
    """Print the loaded scaffold configuration."""

    config = load_config()
    print(f"Athena scaffold ready. Target: {config.target_host}")


if __name__ == "__main__":
    main()
