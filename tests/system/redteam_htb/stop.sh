#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Stopping redteam_htb services..."
docker compose down --remove-orphans

echo "Done."
