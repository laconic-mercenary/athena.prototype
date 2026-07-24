#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Stopping fs-scan services..."
docker compose down --volumes --remove-orphans

echo "Done."
