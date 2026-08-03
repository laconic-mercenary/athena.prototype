#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

TARGET_IP="$(docker compose exec athena_web \
    sh -c 'getent hosts target | awk "{print \$1}"' 2>/dev/null || true)"

LHOST_IP="$(docker compose exec target \
    sh -c 'getent hosts athena_web | awk "{print \$1}"' 2>/dev/null || true)"

REDIS_IP="$(docker compose exec target \
    sh -c 'getent hosts redis | awk "{print \$1}"' 2>/dev/null || true)"

echo "target (meridian)    : ${TARGET_IP:-<not resolved>}"
echo "lhost  (athena)      : ${LHOST_IP:-<not resolved>}"
echo "redis  (from target) : ${REDIS_IP:-<not resolved>}"
