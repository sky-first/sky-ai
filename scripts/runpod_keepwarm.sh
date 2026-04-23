#!/usr/bin/env bash
# Keep-warm ping for the Runpod Ollama instance.
#
# User paid-hours contract: 08h-22h Europe/Lisbon, Mon-Fri. Outside
# that window the script exits silently so the runpod_auto_stop cron
# can still idle-stop the pod.
#
# Action: a tiny (1 token) /api/generate on the orchestrator model so
# Ollama keeps qwen2.5-coder:32b loaded in GPU. Without this the first
# query after an idle gap pays the ~15-20s cold-start we tracked in
# diagnosis (see session checkpoint 2026-04-22 "AI latency diagnosis").
#
# Install as a cron inside the pod (OR externally hitting the pod's
# Ollama port):
#     */2 8-21 * * 1-5 /opt/sky-poc-ai/scripts/runpod_keepwarm.sh
# The hour range 8-21 is inclusive, so 21:58 still fires. 22:00+ stops.

set -euo pipefail

# ── Config ─────────────────────────────────────────────────────────────
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
MODEL="${KEEPWARM_MODEL:-qwen2.5-coder:32b}"
TIMEZONE="${KEEPWARM_TIMEZONE:-Europe/Lisbon}"
HOUR_START="${KEEPWARM_HOUR_START:-8}"    # inclusive
HOUR_END="${KEEPWARM_HOUR_END:-22}"       # exclusive
# Use ${VAR-default} (no `:`) so an explicit empty string means "no
# days allowed" — lets the test suite force the dow gate to skip.
ALLOWED_DOWS="${KEEPWARM_DOWS-1 2 3 4 5}"  # Mon..Fri in %u notation
LOG_FILE="${KEEPWARM_LOG:-/var/log/runpod_keepwarm.log}"

log() {
    # Always append; cron captures nothing by default.
    printf '[%s] %s\n' "$(TZ="$TIMEZONE" date '+%Y-%m-%d %H:%M:%S %Z')" "$*" >> "$LOG_FILE" 2>/dev/null || true
}

# ── Window check ───────────────────────────────────────────────────────
current_dow="$(TZ="$TIMEZONE" date +%u)"   # 1=Mon..7=Sun
current_hour="$(TZ="$TIMEZONE" date +%-H)"

# Weekday gate.
in_dow=0
for d in $ALLOWED_DOWS; do
    if [[ "$current_dow" == "$d" ]]; then in_dow=1; break; fi
done
if [[ "$in_dow" -eq 0 ]]; then
    log "skip: dow=$current_dow not in allowed [$ALLOWED_DOWS]"
    exit 0
fi

# Hour gate [start, end).
if [[ "$current_hour" -lt "$HOUR_START" ]] || [[ "$current_hour" -ge "$HOUR_END" ]]; then
    log "skip: hour=$current_hour outside [$HOUR_START, $HOUR_END)"
    exit 0
fi

# ── Ping ──────────────────────────────────────────────────────────────
# num_predict=1 keeps the GPU cost at ~50ms. keep_alive="15m" tells
# Ollama to keep the model resident in VRAM for 15 min after this
# call, so /api/ps reports it loaded and the next real query hits it
# warm. "stream": false gives us a single JSON reply (easier to log).

payload="$(cat <<EOF
{
  "model": "$MODEL",
  "prompt": ".",
  "stream": false,
  "keep_alive": "15m",
  "options": { "num_predict": 1, "temperature": 0 }
}
EOF
)"

response_code="$(
    curl -sS -o /tmp/runpod_keepwarm.out -w '%{http_code}' \
         -X POST "$OLLAMA_URL/api/generate" \
         -H 'Content-Type: application/json' \
         --max-time 30 \
         -d "$payload" 2>/dev/null || true
)"

if [[ "$response_code" == "200" ]]; then
    log "ok: model=$MODEL warm hit (${response_code})"
else
    body="$(head -c 400 /tmp/runpod_keepwarm.out 2>/dev/null || true)"
    log "fail: model=$MODEL http=${response_code:-<none>} body=${body:-<empty>}"
fi
