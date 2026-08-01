#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Stopping redteam_easy services..."
docker compose down --volumes --remove-orphans

echo "Done."
