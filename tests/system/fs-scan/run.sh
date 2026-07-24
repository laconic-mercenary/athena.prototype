#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

wait_for_healthy() {
    local service="$1"
    local container_id status
    echo "Waiting for ${service} to be healthy..."
    until container_id="$(docker compose ps -q "${service}")" \
        && [ -n "${container_id}" ] \
        && status="$(docker inspect -f '{{.State.Health.Status}}' "${container_id}")" \
        && [ "${status}" = "healthy" ]; do
        sleep 2
    done
}

echo "Building images..."
docker compose build

echo "Starting athena_web..."
docker compose up -d athena_web

wait_for_healthy athena_web

echo ""
echo "fs-scan UI ready: http://localhost:8001"
echo "Ensemble:  tests/system/fs-scan/ensemble/"
echo "Testdata:  /data/testfiles  (mounted read-only)"
echo ""
echo "Logs:  docker compose logs -f athena_web"
echo "Stop:  ./stop.sh"
