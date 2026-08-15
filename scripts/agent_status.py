#!/usr/bin/env python3
"""agent_status.py — status reporter for autonomous agents.

Posts an agent's status to the Hermes World status API (local office backend
by default; point AGENT_STATUS_URL at the Vercel site after deploy).

Usage:
    python agent_status.py <agent_id> <resting|working|done|error> [message]

Config: reads AGENT_STATUS_URL / AGENT_STATUS_TOKEN from this file's sibling
agent-status.env, then from the environment.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / "agent-status.env"
CB_FILE = Path(__file__).resolve().parent / "cb.json"
CB_MAX_FAILS = 5      # consecutive failures before the circuit opens
CB_OPEN_SECS = 600    # how long the circuit stays open
CB_RETRIES = 3        # attempts per post
CB_BACKOFF = (1, 4)   # sleeps between attempts (exp: 1s, 4s)


def load_env() -> None:
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def _load_cb() -> dict:
    try:
        return json.loads(CB_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cb(cb: dict) -> None:
    try:
        CB_FILE.write_text(json.dumps(cb), encoding="utf-8")
    except Exception:
        pass


def post(url: str, token: str, payload: dict) -> str:
    """POST with exponential-backoff retry + a per-endpoint circuit breaker.

    Retry: 3 attempts, sleeping 1s then 4s between them (P0-3).
    Circuit breaker: 5 consecutive failures opens the endpoint for 10 min —
    it is then skipped (not hammered) until the breaker closes (P0-4).
    """
    key = url.rstrip("/")
    cb = _load_cb()
    st = cb.get(key, {})
    now = time.time()
    open_until = st.get("open_until", 0)
    if open_until > now:
        return f"circuit OPEN (skipped, closes in {int(open_until - now)}s)"
    last_err = "unknown error"
    body = json.dumps(payload).encode()
    for attempt in range(1, CB_RETRIES + 1):
        try:
            req = urllib.request.Request(
                key + "/api/status",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                out = r.read().decode()[:200]
            cb[key] = {"fails": 0, "open_until": 0}
            _save_cb(cb)
            return out
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:120]
            if attempt < CB_RETRIES:
                time.sleep(CB_BACKOFF[attempt - 1])
    fails = st.get("fails", 0) + 1
    cb[key] = {"fails": fails, "open_until": now + CB_OPEN_SECS if fails >= CB_MAX_FAILS else 0}
    _save_cb(cb)
    return f"FAIL x{fails} {last_err}"


def main() -> int:
    load_env()
    if len(sys.argv) < 3:
        print("usage: agent_status.py <agent> <status> [message]")
        return 2
    agent = sys.argv[1]
    status = sys.argv[2]
    message = " ".join(sys.argv[3:])[:200]
    if status not in ("resting", "working", "done", "error"):
        print(f"bad status: {status}")
        return 2

    url = os.environ.get("AGENT_STATUS_URL", "http://127.0.0.1:8787")
    alt = os.environ.get("AGENT_STATUS_URL_ALT", "")
    token = os.environ.get("AGENT_STATUS_TOKEN", "")
    payload = {"agent": agent, "status": status, "message": message}
    results = []
    for target in ([url] + ([alt] if alt else [])):
        try:
            results.append(f"{target}: {post(target, token, payload)}")
        except Exception as e:
            results.append(f"{target}: FAIL {e}")
    print(f"{agent}={status} · " + " | ".join(results))
    return 0 if all("FAIL" not in r for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
