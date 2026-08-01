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

echo "Starting services..."
docker compose up -d athena_web target

wait_for_healthy athena_web

# Resolve the target's IP on the engagement network so it can go in the instructions
TARGET_IP="$(docker compose exec athena_web \
    sh -c 'getent hosts target | awk "{print \$1}"' 2>/dev/null || true)"

echo ""
echo "redteam_easy ready"
echo ""
echo "  UI:        http://localhost:8001"
echo "  Ensemble:  tests/ensembles/redteamv1"
echo "  Target IP: ${TARGET_IP:-<resolve via 'docker compose exec athena_web getent hosts target'>}"
echo ""
echo "  Open the UI and start a new engagement."
echo "  When prompted, use the target IP above and lhost=athena_web (service name on engagement-net)."
echo ""
echo "Logs:  docker compose logs -f"
echo "Stop:  ./stop.sh"
