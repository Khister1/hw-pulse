"""Status fixer agent — part of the pulse loop (every 15 min).
Detects STALE agent statuses (working/done stuck for >25 min with no fresh
report) and resets them to resting, so no agent looks awake forever.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

MIRROR_DIR = Path(os.path.dirname(os.path.abspath(__file__)))


def _post_with_retry(base: str, tok: str, payload: dict, tries: int = 3) -> bool:
    """P0-3: retry a status POST with backoff before giving up."""
    data = json.dumps(payload).encode()
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(
                f"{base}/api/status", data=data,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            if attempt < tries:
                time.sleep(attempt * attempt)
    return False


def _mirror_store(base: str, tok: str) -> None:
    """P0-5: keep a last-good snapshot of each store on disk (checkpoint)."""
    try:
        req = urllib.request.Request(
            f"{base}/api/agents",
            headers={"Authorization": f"Bearer {tok}"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode())
        name = "vercel" if "vercel" in base else "local"
        (MIRROR_DIR / f"store-mirror-{name}.json").write_text(
            json.dumps(d, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

def load_env():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-status.env")
    try:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass

def main() -> int:
    load_env()
    primary = os.environ.get("AGENT_STATUS_URL", "http://127.0.0.1:8787").rstrip("/")
    alt = os.environ.get("AGENT_STATUS_URL_ALT", "").rstrip("/")
    tok = os.environ.get("AGENT_STATUS_TOKEN", "")
    now = time.time()
    stores = list(filter(None, (primary, alt)))
    if not stores:
        return 0
    fixed = 0
    for base in stores:  # fix each store independently (they can drift apart)
        try:
            with urllib.request.urlopen(f"{base}/api/agents", timeout=6) as r:
                d = json.loads(r.read().decode())
            agents = d.get("agents", d) if isinstance(d, dict) else d
        except Exception:
            continue  # store unreachable — skip
        _mirror_store(base, tok)  # P0-5: checkpoint before touching anything
        present = set()
        for a in agents or []:
            aid = a.get("id")
            present.add(aid)
            if aid not in ("research", "digest", "megatemp"):
                continue  # others self-report on their own cadence
            st = a.get("status")
            ts = a.get("updated_at", 0)
            stale = ts and (now - ts) > 25 * 60
            if aid == "megatemp":
                dirty = st in ("working", "done", "error") and stale  # de-listed target: clear ghost errors
            else:
                dirty = st in ("working", "done") and stale
            if not dirty and aid in ("research", "digest") and st in ("resting", "stale") and ts and (now - ts) > 20 * 60:
                dirty = "heartbeat"  # refresh resting so they never age into offline
            if dirty:
                payload = {
                    "agent": aid, "status": "resting",
                    "message": "reset after stale '" + st + "' (" + str(int(now - ts) // 60) + "m)" if dirty != "heartbeat" else "standby",
                    "ts": int(now),
                }
                if _post_with_retry(base, tok, payload):  # P0-3: retry w/ backoff
                    print(f"status-fix: {aid} {st} -> resting @ {base}")
                    fixed += 1
        # ensure known agents exist in the store (a backend restart can drop entries)
        for aid in ("research", "digest", "sentinel"):
            if aid in present:
                continue
            payload = {
                "agent": aid, "status": "resting",
                "message": "standby (re-seeded)",
                "ts": int(now),
            }
            if _post_with_retry(base, tok, payload):  # P0-3: retry w/ backoff
                print(f"status-fix: re-seeded missing agent {aid} @ {base}")
                fixed += 1
    if fixed:
        print(f"status-fix: {fixed} agent(s) reset")
    return 0

if __name__ == "__main__":
    sys.exit(main())
