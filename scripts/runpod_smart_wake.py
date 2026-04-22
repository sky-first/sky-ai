#!/usr/bin/env python3
"""Runpod smart wake — single entry point that replaces the manual ritual
of stop → retry start → try migrate → find new URL → update .env.

Codifies every step we hit the hard way on 2026-04-22:

    1. List pods by name; pick the one that matches the configured
       sky-ollama pod. (Matches `--pod-name` prefix so a running
       "-migration" twin is picked up too.)
    2. If RUNNING: test /api/tags; if green, done.
    3. If EXITED: POST /pods/{id}/start. If it fails with
       "not enough free GPUs", retry every `--retry-seconds` for up
       to `--max-tries`. Between retries we fall back to migrate on
       the last `--migrate-after` attempts.
    4. If a migrate produced a new pod (pod_id changed), update the
       `OLLAMA_BASE_URL` line in the `.env` file in place.
    5. Poll /api/tags on the final endpoint until Ollama reports at
       least one model loaded OR we time out — models return `[]` for
       a while after migrate while the volume re-indexes.

The script exits 0 on success (endpoint reachable, models listed) and
non-zero on each distinct failure path so CI / the backend can branch:

    2  — pod not found
    3  — all start attempts exhausted without a running pod
    4  — migrate attempted but API refused (runpod console required)
    5  — pod is running but /api/tags never returned models in time

Design goal: this is the ONLY runpod CLI anyone should run from now
on. Stop/start/migrate/url-update are all here so the behaviour is
reproducible and logged. GitHub Actions can run this with --non-
interactive; the backend can shell out on first-request 502.

Usage:
    ./venv/bin/python scripts/runpod_smart_wake.py \\
        --pod-name sky-ollama-dev-v2 \\
        --env-file .env \\
        --retry-seconds 120 \\
        --max-tries 15 \\
        --migrate-after 3 \\
        --models-timeout 900

Env:
    RUNPOD_API_KEY   required. Loaded from ~/.runpod-env if present.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RUNPOD_REST = "https://rest.runpod.io/v1"


def _load_api_key() -> str:
    key = os.environ.get("RUNPOD_API_KEY")
    if key:
        return key
    # Try the conventional home dotfile.
    env_path = Path.home() / ".runpod-env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            m = re.match(r"(?:export\s+)?RUNPOD_API_KEY\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip('"\'')
    print("error: RUNPOD_API_KEY not set and ~/.runpod-env not readable", file=sys.stderr)
    sys.exit(1)


def _api(method: str, path: str, api_key: str, body: dict | None = None) -> tuple[int, dict | list | str]:
    url = f"{RUNPOD_REST}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode()
            try:
                return resp.status, json.loads(payload)
            except json.JSONDecodeError:
                return resp.status, payload
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, str(e)
    except urllib.error.URLError as e:
        return -1, str(e)


def _find_pod(name_prefix: str, api_key: str) -> dict[str, Any] | None:
    status, pods = _api("GET", "/pods", api_key)
    if status != 200 or not isinstance(pods, list):
        print(f"error: list pods failed (status={status}): {pods}", file=sys.stderr)
        return None
    # Prefer a RUNNING match, then the newest EXITED — migrate can
    # leave a `<name>-migration` twin running alongside the original.
    candidates = [p for p in pods if p.get("name", "").startswith(name_prefix)]
    if not candidates:
        return None
    running = [p for p in candidates if p.get("desiredStatus") == "RUNNING"]
    if running:
        return running[0]
    candidates.sort(key=lambda p: p.get("lastStartedAt") or "", reverse=True)
    return candidates[0]


def _probe_ollama(pod_id: str, timeout: int = 8) -> tuple[bool, int]:
    """Return (reachable, model_count).

    Runpod's proxy rejects the default Python urllib User-Agent with
    403 even when the pod itself is happy — so we ship a normal UA.
    """
    url = f"https://{pod_id}-11434.proxy.runpod.net/api/tags"
    req = urllib.request.Request(url, headers={"User-Agent": "runpod-smart-wake/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
            return True, len(payload.get("models", []))
    except Exception:
        return False, 0


def _update_env_file(env_file: Path, new_pod_id: str) -> bool:
    """Rewrite OLLAMA_BASE_URL=... to point at new_pod_id. Returns True if changed."""
    if not env_file.exists():
        print(f"warn: env file {env_file} not found — skipping .env update", file=sys.stderr)
        return False
    new_url = f"https://{new_pod_id}-11434.proxy.runpod.net"
    lines = env_file.read_text().splitlines(keepends=True)
    out = []
    changed = False
    for line in lines:
        if line.strip().startswith("OLLAMA_BASE_URL="):
            current = line.strip().split("=", 1)[1]
            if current != new_url:
                out.append(f"OLLAMA_BASE_URL={new_url}\n")
                changed = True
                continue
        out.append(line)
    if changed:
        env_file.write_text("".join(out))
        print(f"✓ updated {env_file} → OLLAMA_BASE_URL={new_url}")
    return changed


def _try_start(pod_id: str, api_key: str) -> tuple[bool, str]:
    """POST /pods/{id}/start. Returns (success, message)."""
    status, body = _api("POST", f"/pods/{pod_id}/start", api_key, {})
    if status == 200:
        return True, "started"
    if isinstance(body, dict):
        msg = body.get("error") or body.get("message") or str(body)
    else:
        msg = str(body)
    return False, msg


def _wait_models(pod_id: str, timeout_seconds: int, log_every: int = 30) -> bool:
    deadline = time.time() + timeout_seconds
    last_log = 0.0
    while time.time() < deadline:
        ok, n = _probe_ollama(pod_id)
        if ok and n > 0:
            print(f"✓ Ollama ready ({n} model{'s' if n != 1 else ''} loaded)")
            return True
        now = time.time()
        if now - last_log >= log_every:
            elapsed = int(timeout_seconds - (deadline - now))
            print(f"  waiting for models ({elapsed}s elapsed, reachable={ok}, models={n})...")
            last_log = now
        time.sleep(10)
    return False


def wake(
    pod_name: str,
    env_file: Path,
    retry_seconds: int,
    max_tries: int,
    migrate_after: int,
    models_timeout: int,
) -> int:
    api_key = _load_api_key()
    pod = _find_pod(pod_name, api_key)
    if not pod:
        print(f"error: no pod matching name prefix '{pod_name}'", file=sys.stderr)
        return 2
    pod_id = pod["id"]
    print(f"pod: {pod['name']} (id={pod_id}, status={pod['desiredStatus']})")

    if pod["desiredStatus"] == "RUNNING":
        ok, n = _probe_ollama(pod_id)
        if ok and n > 0:
            print(f"✓ already running with {n} model(s)")
            _update_env_file(env_file, pod_id)
            return 0
        print("pod is RUNNING but Ollama not ready — will poll")
    else:
        # Drive the start / migrate loop.
        for attempt in range(1, max_tries + 1):
            print(f"\n→ attempt {attempt}/{max_tries}: start pod {pod_id}")
            ok, msg = _try_start(pod_id, api_key)
            if ok:
                print("✓ started")
                break

            is_no_gpu = "not enough free GPU" in msg or "host machine" in msg
            print(f"  start failed: {msg}")

            if attempt >= max_tries:
                print("error: exhausted start attempts", file=sys.stderr)
                return 3

            if is_no_gpu and attempt >= migrate_after:
                # Runpod's migrate isn't in the public REST — only the
                # UI offers "Automatically migrate your Pod data". We
                # surface the signal for the caller to escalate (CI job
                # should page a human, or we call the private GraphQL
                # mutation if we later reverse-engineer it).
                print("! GPU stayed unavailable past migrate threshold — MANUAL MIGRATE REQUIRED", file=sys.stderr)
                print(f"  Open https://runpod.io/console/pods and click 'Automatically migrate'", file=sys.stderr)
                print(f"  After migrate completes, re-run this script — it will pick up the new pod by name prefix.", file=sys.stderr)
                return 4

            print(f"  sleeping {retry_seconds}s before retry...")
            time.sleep(retry_seconds)

        # After start succeeded, pod_id may have changed if a migrate-
        # created twin was picked up by _find_pod. Re-resolve.
        pod = _find_pod(pod_name, api_key) or pod
        if pod["id"] != pod_id:
            print(f"  pod id changed: {pod_id} → {pod['id']} (migrate twin?)")
            pod_id = pod["id"]

    print(f"\n→ waiting for models (timeout {models_timeout}s)")
    if not _wait_models(pod_id, models_timeout):
        print("error: Ollama is reachable but no models loaded within timeout", file=sys.stderr)
        return 5

    _update_env_file(env_file, pod_id)
    print("\n✓ done — everything green")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pod-name", default="sky-ollama-dev-v2", help="Pod name prefix to match")
    p.add_argument("--env-file", default=".env", type=Path, help="Path to .env to update OLLAMA_BASE_URL")
    p.add_argument("--retry-seconds", type=int, default=120, help="Seconds between start retries")
    p.add_argument("--max-tries", type=int, default=15, help="Maximum start attempts")
    p.add_argument("--migrate-after", type=int, default=3, help="Escalate to manual migrate after this many no-GPU failures")
    p.add_argument("--models-timeout", type=int, default=900, help="Seconds to wait for Ollama to load models")
    args = p.parse_args()

    return wake(
        pod_name=args.pod_name,
        env_file=args.env_file,
        retry_seconds=args.retry_seconds,
        max_tries=args.max_tries,
        migrate_after=args.migrate_after,
        models_timeout=args.models_timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
