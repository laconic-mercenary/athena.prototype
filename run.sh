#!/usr/bin/env bash
set -euo pipefail

# Start the target, wait for it to be healthy, then run the Athena pipeline.
# Usage: ./run.sh [--verbose]
#   --verbose  streams agent reasoning to stdout

echo "Building images..."
docker compose build

echo "Starting target..."
docker compose up -d target

echo "Waiting for target to be healthy..."
until [ "$(docker compose ps -q target | xargs docker inspect -f '{{.State.Health.Status}}')" = "healthy" ]; do
    sleep 2
done

echo "Target ready. Starting Athena..."
echo ""

rm -rf artifacts/

docker compose run --rm runner "$@"
