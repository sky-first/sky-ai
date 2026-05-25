# Runpod keep-warm

Script: `scripts/runpod_keepwarm.sh`

## What it does

Every 2 minutes, during **Mon–Fri 08h–22h Europe/Lisbon**, pings the
Runpod Ollama instance with a 1-token `/api/generate` call + `keep_alive: 15m`
so `qwen2.5-coder:32b` stays resident in GPU memory. Outside the window
the script exits silently (so `runpod_auto_stop.sh` can still idle-stop
the pod — the two scripts are intentionally composable).

## Why

Diagnosed latency: first chat call after an idle gap pays ~15–20s of
cold start on the 32B model (see session checkpoint notes). Paid pod
hours are already locked (08h–22h workdays), so keeping the model
loaded during that window is free compute, not a new cost. Expected
user-perceived impact: 30s first-question → ~8–10s.

## Install — pod-internal cron (preferred)

```bash
sudo install -m 0755 scripts/runpod_keepwarm.sh /opt/sky-poc-ai/scripts/runpod_keepwarm.sh
sudo touch /var/log/runpod_keepwarm.log && sudo chmod 666 /var/log/runpod_keepwarm.log
(crontab -l 2>/dev/null; echo "*/2 8-21 * * 1-5 /opt/sky-poc-ai/scripts/runpod_keepwarm.sh") | crontab -
```

The hour range `8-21` is inclusive → last fire is at 21:58; 22:00+ is
silent. Uses weekdays only (`1-5`).

## Install — external cron (monitoring host)

If you'd rather keep the ping outside the pod, expose Ollama on a
public port and run the script from any host that can reach it:

```bash
OLLAMA_URL=https://ollama.mydomain.com:11434 \
  KEEPWARM_TIMEZONE=Europe/Lisbon \
  ./runpod_keepwarm.sh
```

## Config (env vars)

| Var | Default | Notes |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `KEEPWARM_MODEL` | `qwen2.5-coder:32b` | Must match the LLM the chat path uses |
| `KEEPWARM_TIMEZONE` | `Europe/Lisbon` | IANA zone string |
| `KEEPWARM_HOUR_START` | `8` | Inclusive |
| `KEEPWARM_HOUR_END` | `22` | Exclusive |
| `KEEPWARM_DOWS` | `1 2 3 4 5` | Day-of-week in %u (Mon=1…Sun=7) |
| `KEEPWARM_LOG` | `/var/log/runpod_keepwarm.log` | Append-only log |

## Verify

After installing:

```bash
# Force a fire + check the log tail
./scripts/runpod_keepwarm.sh && tail -5 /var/log/runpod_keepwarm.log

# Confirm Ollama reports the model loaded
curl -s $OLLAMA_URL/api/ps | jq '.models[] | .name'
```

If `/api/ps` is empty after a successful fire, `keep_alive` isn't
sticking — double-check that no other caller is passing `keep_alive: 0`
or that the pod didn't get stopped by `runpod_auto_stop.sh` (which
shouldn't happen during work-hours if the keep-warm is running).
