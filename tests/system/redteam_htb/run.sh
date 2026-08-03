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

# --- VPN preflight: host tun0 must be up (Option B — OpenVPN runs on the host) ----------
TUN_IP="$(ip -4 addr show tun0 2>/dev/null | grep -oP 'inet \K[\d.]+' || true)"
if [ -z "${TUN_IP}" ]; then
    echo "ERROR: no tun0 interface found on the host." >&2
    echo "Connect the Hack The Box OpenVPN profile first, e.g.:" >&2
    echo "    sudo openvpn --config ~/htb.ovpn" >&2
    echo "Then re-run ./run.sh" >&2
    exit 1
fi

echo "Building image..."
docker compose build

echo "Starting athena_web (host networking)..."
docker compose up -d athena_web

wait_for_healthy athena_web

echo ""
echo "redteam_htb ready"
echo ""
echo "  UI:        http://localhost:8002"
echo "  Ensemble:  tests/ensembles/redteamv1"
echo "  Your VPN:  tun0 = ${TUN_IP}"
echo ""
echo "  Start a new engagement in the UI. When prompted, enter:"
echo "     target : <HTB machine IP>   (from the HTB machine page)"
echo "     lhost  : ${TUN_IP}          (your tun0 — the reverse shell calls back here)"
echo "     lport  : 4444               (or any free port)"
echo ""
echo "Logs:  docker compose logs -f"
echo "Stop:  ./stop.sh"
