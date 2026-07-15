#!/usr/bin/env bash
set -euo pipefail

echo "Stopping Athena services..."
docker compose down --volumes --remove-orphans

echo "Athena services stopped."
