#!/usr/bin/env bash
set -euo pipefail

# Launch Athena's local Docker stack.
# Usage: ./run.sh

wait_for_healthy() {
    local service="$1"
    local container_id
    local status

    echo "Waiting for ${service} to be healthy..."
    until container_id="$(docker compose ps -q "${service}")" \
        && [ -n "${container_id}" ] \
        && status="$(docker inspect -f '{{.State.Health.Status}}' "${container_id}")" \
        && [ "${status}" = "healthy" ]; do
        sleep 2
    done
}

wait_for_url() {
    local url="$1"
    local attempts=60

    echo "Waiting for ${url}..."
    until curl -fsS "${url}" >/dev/null 2>&1; do
        attempts=$((attempts - 1))
        if [ "${attempts}" -le 0 ]; then
            echo "Timed out waiting for ${url}" >&2
            docker compose logs --tail=80 web >&2 || true
            exit 1
        fi
        sleep 2
    done
}

echo "Building images..."
docker compose build

echo "Starting Athena services..."
docker compose up -d target db web

wait_for_healthy target
wait_for_healthy db
wait_for_url "http://localhost:8000"

echo ""
echo "Athena web UI is ready: http://localhost:8000"
echo "Logs: docker compose logs -f web"
