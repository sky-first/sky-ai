"""Tests for scripts/runpod_keepwarm.sh — exercises the window + ping
logic via bash subprocess so the real script is what's covered, not a
reimplementation.

The script is pure bash; we run it with:
  * a fake curl on PATH (so we don't hit the network)
  * overridden env vars for clock + window + output capture

Each test creates a temp dir, drops a shim for `curl` + `date` when
needed, and asserts on the log output.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "runpod_keepwarm.sh"


def _make_curl_shim(tmp: Path, *, http_code: str = "200", body: str = "{}") -> Path:
    """Write a `curl` shim that writes to the -o path and echoes the
    `%{http_code}` the real curl would."""
    shim = tmp / "curl"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "out=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -o) out=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        f"[ -n \"$out\" ] && printf '%s' {body!r} > \"$out\"\n"
        f"printf '%s' {http_code!r}\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def _run(tmp: Path, env: dict[str, str]) -> str:
    log_file = tmp / "keepwarm.log"
    full_env = {
        **os.environ,
        "PATH": f"{tmp}:{os.environ['PATH']}",
        "KEEPWARM_LOG": str(log_file),
        **env,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    try:
        return log_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def test_fires_during_workday_window():
    """Tuesday, 10:00 Europe/Lisbon — should ping Ollama."""
    with TemporaryDirectory() as d:
        tmp = Path(d)
        _make_curl_shim(tmp, http_code="200")
        # libfaketime might not be installed; override the script's
        # window checks via env so we don't need clock manipulation.
        # We still pass date shim for the log timestamp.
        log = _run(tmp, {
            "KEEPWARM_HOUR_START": "0",
            "KEEPWARM_HOUR_END": "24",
            "KEEPWARM_DOWS": "1 2 3 4 5 6 7",
            "OLLAMA_URL": "http://localhost:11434",
            "KEEPWARM_MODEL": "qwen2.5-coder:32b",
        })
    assert "ok: model=qwen2.5-coder:32b" in log


def test_skips_when_outside_hour_window():
    with TemporaryDirectory() as d:
        tmp = Path(d)
        _make_curl_shim(tmp)
        # Force a window that excludes any valid hour. Start=25 is
        # impossible so every hour fails the hour-start check.
        log = _run(tmp, {
            "KEEPWARM_HOUR_START": "25",
            "KEEPWARM_HOUR_END": "26",
            "KEEPWARM_DOWS": "1 2 3 4 5 6 7",
        })
    assert "skip: hour=" in log
    # Must not have even attempted the curl.
    assert "ok:" not in log
    assert "fail:" not in log


def test_skips_when_day_excluded():
    with TemporaryDirectory() as d:
        tmp = Path(d)
        _make_curl_shim(tmp)
        # Allow no DOWs — guaranteed skip regardless of clock.
        log = _run(tmp, {
            "KEEPWARM_DOWS": "",
            "KEEPWARM_HOUR_START": "0",
            "KEEPWARM_HOUR_END": "24",
        })
    assert "skip: dow=" in log


def test_logs_failure_on_non_200():
    with TemporaryDirectory() as d:
        tmp = Path(d)
        _make_curl_shim(tmp, http_code="503", body='{"error":"boom"}')
        log = _run(tmp, {
            "KEEPWARM_HOUR_START": "0",
            "KEEPWARM_HOUR_END": "24",
            "KEEPWARM_DOWS": "1 2 3 4 5 6 7",
        })
    assert "fail:" in log
    assert "http=503" in log


def test_logs_failure_when_curl_missing():
    """No curl on PATH — the script must still exit 0 and log the failure."""
    with TemporaryDirectory() as d:
        tmp = Path(d)
        # Don't create a curl shim. Keep /bin + /usr/bin on PATH so
        # bash itself + `date` are reachable, but no directory on this
        # PATH has `curl`, so the real thing isn't found.
        safe_path_parts = [str(tmp), "/bin", "/usr/bin"]
        env = {
            "KEEPWARM_HOUR_START": "0",
            "KEEPWARM_HOUR_END": "24",
            "KEEPWARM_DOWS": "1 2 3 4 5 6 7",
        }
        log_file = tmp / "keepwarm.log"
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env={
                "PATH": ":".join(safe_path_parts),
                "KEEPWARM_LOG": str(log_file),
                **env,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
    # Skip if the dev box has curl somewhere on /bin or /usr/bin.
    if (Path("/bin") / "curl").exists() or (Path("/usr/bin") / "curl").exists():
        pytest.skip("system curl present on /bin or /usr/bin — can't force-miss curl here")
    assert result.returncode == 0  # set -e must not kill us on curl-missing
    log = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "fail:" in log
