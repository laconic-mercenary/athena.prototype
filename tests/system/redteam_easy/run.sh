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
docker compose up -d athena_web target redis redis_seeder

wait_for_healthy athena_web

# Resolve key hostnames from within the harness container
TARGET_IP="$(docker compose exec athena_web \
    sh -c 'getent hosts target | awk "{print \$1}"' 2>/dev/null || true)"

echo ""
echo "redteam_easy (Meridian Systems) ready"
echo ""
echo "  UI:        http://localhost:8001"
echo "  Ensemble:  tests/ensembles/redteamv1"
echo "  Target:    ${TARGET_IP:-<resolve with ./print-docker-ips.sh>}"
echo ""
echo "  Engagement parameters:"
echo "    target  = target          (Flask app — hostname on engagement-net)"
echo "    lhost   = athena_web      (reverse shell callback — hostname on engagement-net)"
echo "    lport   = 4444"
echo ""
echo "  Redis is on db-net only — not reachable from harness directly."
echo "  Credential in /root/.redis_password on target (root-only)."
echo ""
echo "Logs:  docker compose logs -f"
echo "Stop:  ./stop.sh"
