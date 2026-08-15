# hw-pulse — Hermes World 24/7 heartbeat crew

A free, card-less cloud pulse for [Hermes World](https://hermes-world.vercel.app).
GitHub Actions runs the exact same scripts your local `pulse.sh` runs —
every 15 minutes, forever, even when your laptop is off.

## What it does each tick
1. Posts `resting` heartbeats for **hermes, memory, vault, lulu** to the live
   Vercel status API (same payloads as the local crew)
2. Runs the **status_fix patrol** — re-seeds missing agents, resets stale
   statuses, clears ghost entries
3. Reports back with a `cloud pulse ok` confirmation

## How it's wired
- `.github/workflows/pulse.yml` — schedule `*/15 * * * *` (UTC cron, Manila
  display time) + manual `workflow_dispatch`
- `scripts/agent_status.py` / `scripts/status_fix.py` — stdlib-only, identical
  to the local copies (single source of truth)
- Secrets: `HW_STATUS_URL` (Vercel API base) + `HW_STATUS_TOKEN` (status
  bearer token) — the env file is generated at runtime, never committed

## Ops
- **Manual tick:** Actions → hw-pulse → Run workflow
- **Pause:** Actions → hw-pulse → ⋯ → Disable workflow
- **Verify it's alive:** open `https://hermes-world.vercel.app` → ACTIVITY LOG
  should show fresh `cloud pulse ok` entries from `hermes` every 15 minutes

## Notes
- Scheduled workflows auto-disable after **60 days without repo activity** —
  push a commit (or leave the cron touching the API) to keep it alive; a
  workflow_dispatch run also counts as activity.
- This is the interim step before the Oracle ARM VPS takes over the same job;
  when the VPS lives, disable this workflow.
