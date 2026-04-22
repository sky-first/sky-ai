# Runpod automation — end of the manual ritual

## What this replaces

Everything we hit manually on 2026-04-22 (docs of that incident in the
commit history of this file, plus `DOC_RUNPOD_RECOVERY.md`):

1. Pod is `EXITED`.
2. Click "Start" in the UI → "not enough free GPUs".
3. Wait, retry, fail, retry.
4. Eventually click "Automatically migrate" — twin pod with new id.
5. Scramble to find `OLLAMA_BASE_URL` in `.env` and update it.
6. Test `/api/tags`, re-install auto-stop cron in the new pod.

Every one of those steps is now a single command or skipped entirely.

## Three pieces

### 1. `runpod_auto_stop.sh` (inside the pod, cron every 5 min)

Already existed. Detects idle (no Ollama models loaded for >15 min) and
calls `POST /pods/{RUNPOD_POD_ID}/stop`. Installed once per pod — see
header of the script. Uses the `RUNPOD_POD_ID` env the runtime injects,
so it's portable: a migrated pod just needs the script re-installed.

### 2. `runpod_smart_wake.py` (run from laptop, CI, or backend)

The one-shot CLI that:

- Finds the pod by name prefix (catches `-migration` twins).
- If running + healthy: no-op.
- If exited: POSTs `/pods/{id}/start` with retry + backoff.
- If "not enough free GPUs" persists `--migrate-after` attempts: prints
  a clear escalation message with the console URL (Runpod doesn't
  expose migrate via public API — yet).
- After start, polls `/api/tags` until models appear.
- Rewrites `OLLAMA_BASE_URL` in `.env` in place if the pod id changed.

Exit codes let a parent process branch:

    0  everything green
    2  pod not found
    3  start attempts exhausted
    4  manual migrate needed (no-GPU beyond threshold)
    5  running but models never loaded

### 3. `.github/workflows/runpod-wake.yml`

Thin wrapper around the CLI. `workflow_dispatch` lets a human fire it
from the Actions tab with custom retry knobs. `workflow_call` lets
deploy-staging (or any other workflow) chain it before invoking
anything that hits the AI service.

## Usage

### From your laptop, after a stop

    ./scripts/runpod_smart_wake.py

Defaults: name `sky-ollama-dev-v2`, env `.env`, 15 retries × 120s with
migrate-escalation after 3 consecutive no-GPU failures, 15 min timeout
for models to load.

### From CI before a job that needs Ollama

Add at the top of any workflow that depends on the LLM being live:

    jobs:
      wake-ollama:
        uses: ./.github/workflows/runpod-wake.yml
      test-that-needs-ai:
        needs: wake-ollama
        runs-on: ubuntu-latest
        steps: ...

### From the backend on a connection-refused

Hook that `sky-poc-ai/core/llm/providers.py` can use — when an Ollama
call returns 502/connection refused, fire the script once in the
background and retry. (Not yet wired; next follow-up.)

    import subprocess, pathlib
    subprocess.Popen(
        [pathlib.Path(__file__).parent.parent.parent / "scripts/runpod_smart_wake.py"],
        start_new_session=True,
    )

## What still needs a human hand

- **`Automatically migrate` button.** Runpod's REST/GraphQL don't
  expose it publicly, so when we exhaust retries the script prints the
  console URL and exits 4. CI then pages the on-call.
- **Rename pod** (strip `-migration` suffix). Cosmetic, UI only.
- **Re-install `runpod_auto_stop.sh`** on a newly-migrated pod. One-
  shot `scp` + `ssh` that the README at the top of that file documents.
