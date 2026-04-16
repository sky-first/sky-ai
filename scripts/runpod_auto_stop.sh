#!/bin/bash
# runpod_auto_stop.sh — idle-based self-stop for the RunPod Ollama pod.
#
# Runs INSIDE the pod on a cron (every 5 min). Detects idle state and
# calls RunPod's REST API to stop this very pod, preserving volume +
# URL for the next cold-start.
#
# Install on pod:
#   scp runpod_auto_stop.sh root@<pod-ssh>:/opt/runpod_auto_stop.sh
#   ssh root@<pod-ssh>
#   chmod +x /opt/runpod_auto_stop.sh
#   # secrets (NEVER in git):
#   echo "RUNPOD_API_KEY=rpa_..." > /opt/runpod_auto_stop.env
#   chmod 600 /opt/runpod_auto_stop.env
#   # cron:
#   (crontab -l 2>/dev/null; echo "*/5 * * * * /opt/runpod_auto_stop.sh >> /var/log/runpod_auto_stop.log 2>&1") | crontab -
#   service cron start || cron
#
# Wake-up: call POST https://rest.runpod.io/v1/pods/${POD_ID}/start with the
# same API key. The backend can do this transparently on the first LLM
# request that hits a connection-refused (see sky-poc-ai core/llm/factory.py
# for the retry wrapper once added).
set -euo pipefail

IDLE_THRESHOLD_SECONDS="${IDLE_THRESHOLD_SECONDS:-900}"    # 15 min
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
STATE_FILE="/tmp/ollama_last_active"

# Load secrets (RUNPOD_API_KEY). Pod ID comes from RunPod-injected env.
if [ -f /opt/runpod_auto_stop.env ]; then
    # shellcheck disable=SC1091
    source /opt/runpod_auto_stop.env
fi

: "${RUNPOD_API_KEY:?RUNPOD_API_KEY must be set in /opt/runpod_auto_stop.env}"
: "${RUNPOD_POD_ID:?RUNPOD_POD_ID must be set by RunPod runtime}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# 1. Probe Ollama for loaded models.
#    When idle, Ollama unloads models after `keep_alive` (default 5 min),
#    so .models becomes an empty array. That's our primary signal.
ps_json=$(curl -sf --max-time 5 "$OLLAMA_URL/api/ps" || echo '{"models":[]}')
active_count=$(echo "$ps_json" | grep -c '"name"' || true)

if [ "$active_count" -gt 0 ]; then
    # Something is loaded — reset idle timer, exit fast.
    date +%s > "$STATE_FILE"
    log "active (${active_count} model(s) loaded) — resetting idle timer"
    exit 0
fi

# 2. Nothing loaded right now. Compare against the last-active mark.
if [ ! -f "$STATE_FILE" ]; then
    date +%s > "$STATE_FILE"
    log "no models loaded, seeding timer — will stop in ${IDLE_THRESHOLD_SECONDS}s of continued idle"
    exit 0
fi

last_active=$(cat "$STATE_FILE")
now=$(date +%s)
idle=$(( now - last_active ))

if [ "$idle" -lt "$IDLE_THRESHOLD_SECONDS" ]; then
    log "idle ${idle}s (threshold ${IDLE_THRESHOLD_SECONDS}s) — not stopping yet"
    exit 0
fi

# 3. Idle beyond threshold — stop ourselves.
log "idle ${idle}s >= ${IDLE_THRESHOLD_SECONDS}s — stopping pod ${RUNPOD_POD_ID}"
http_code=$(curl -s -o /tmp/stop_response.json -w "%{http_code}" \
    -X POST "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}/stop" \
    -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{}')

if [ "$http_code" = "200" ]; then
    log "stop issued successfully"
    rm -f "$STATE_FILE"
else
    log "stop request failed: http=${http_code} body=$(cat /tmp/stop_response.json)"
    exit 1
fi
