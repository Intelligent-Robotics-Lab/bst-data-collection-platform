# BST Launch Integration — spec for the BST owners (Operator Console v2)

Status: SPEC ONLY. Nothing in the BST repo has been changed by the data-platform
side. This describes the small BST-side change that lets the operator start the
robot interaction from the Operator Console, using the platform's canonical
session config instead of terminal `input()`.

The **data-platform side is implemented** (launch model, endpoints, console card,
tests). This document is the matching BST-side work.

---

## 0. What this replaces and why

Today `logic/bst.py` `BST()` gathers the session via `input()`:

```python
study_config = {
    "participant_name": input("Participant name: "),
    "configuration": input("Configuration (1, 2, or 3): "),
    "trainer_feedback_style": input("Feedback style (supportive or neutral): "),
    "session_id": input("Session_id (match the platform exactly): "),
    "platform_base": PLATFORM_BASE,
}
```

That manual re-typing is the fragile part: the robot session must match the
platform session exactly (session_id, configuration=`pb_order_group`, feedback
style=`support_condition`). v2 removes it: **the platform session is the single
source of truth, and BST fetches the config instead of asking the operator.**

---

## 1. The launch endpoints (already live on the platform)

Base: `{platform_base}/sessions/{session_id}/launch/...`

| Call | Method / path | Body | Returns |
| --- | --- | --- | --- |
| fetch config | `GET  …/launch/config` | – | `{session_id, participant_id, scenario_type, pb_order_group, support_condition, support_label, platform_base}` |
| poll status | `GET  …/launch/status` | – | `{status, prepared_at, config_fetched_at, start_requested_at, started_at, error_at, error_text, …}` |
| ack | `POST …/launch/ack` | `{phase:"config_received"\|"started"}` | status |
| report error | `POST …/launch/error` | `{message}` | status |

The operator drives `prepare` and `start` from the console; **BST only calls
`config`, `status`, `ack`, and `error`.**

`status` values: `none` (nothing prepared) → `prepared` (operator readied it) →
`waiting` (BST fetched config + acked) → `start_requested` (operator pressed
Start) → `started` (BST acked) / `error`.

---

## 2. BST-side flow (proposed; not applied)

Two small pieces: BST needs `session_id` before it can call these. Provide it
one of two ways — (a) the operator still types just the `session_id` once (much
less error-prone than typing all four fields), or (b) a launcher passes it as an
arg/env var. Everything else comes from the platform.

```python
# logic/launch_client.py  (PROPOSED - new, mirrors the existing sync_client.py)
import asyncio, httpx

class LaunchClient:
    def __init__(self, session_id, base_url):
        self.base = f"{base_url}/sessions/{session_id}/launch"
        self._http = httpx.AsyncClient(timeout=5.0)

    async def get_config(self):
        r = await self._http.get(f"{self.base}/config"); r.raise_for_status(); return r.json()
    async def get_status(self):
        r = await self._http.get(f"{self.base}/status"); r.raise_for_status(); return r.json()
    async def ack(self, phase):
        await self._http.post(f"{self.base}/ack", json={"phase": phase})
    async def error(self, message):
        await self._http.post(f"{self.base}/error", json={"message": message})

    async def wait_for_start(self, poll=0.5):
        """Block until the operator presses Start in the console."""
        while True:
            s = await self.get_status()
            if s.get("status") == "start_requested":
                return s
            await asyncio.sleep(poll)
```

`BST()` then replaces the `input()` block:

```python
# logic/bst.py  BST()  (PROPOSED)
session_id = input("Session_id (from the console): ")   # or from an arg/env
launch = LaunchClient(session_id, PLATFORM_BASE)

cfg = await launch.get_config()          # canonical config - no manual re-typing
await launch.ack("config_received")      # console shows "waiting"

study_config = {
    "session_id":            cfg["session_id"],
    "configuration":         cfg["pb_order_group"],       # was typed by hand
    "trainer_feedback_style": cfg["support_label"],       # was typed by hand
    "platform_base":         cfg["platform_base"],
    "participant_name":      cfg["participant_id"],        # research ID, not a name
}

await launch.wait_for_start()            # blocks until operator presses Start

try:
    # ... existing SyncClient(...).register(...) and the Tutorial/…/DTT run ...
    await launch.ack("started")          # console shows "started"
except Exception as e:
    await launch.error(str(e))           # console shows the error
    raise
```

Notes:
- `configuration` (the Latin-square config in `logic/latin_square.py`) is exactly
  `pb_order_group`; `trainer_feedback_style` is `support_label`
  (`support_condition` 1→supportive / 0→neutral). No conversion beyond that.
- This composes with the existing `SyncClient.register(...)`, which already
  cross-checks `pb_order_group`/`support_condition` — now both sides read the same
  platform values, so the check can only pass.
- `wait_for_start` should tolerate transient network errors (log + keep polling),
  same robustness note as the sync gate poll.

---

## 3. Fallback (no BST change yet)

Until the above lands, the console's launch card shows a **fallback config block**
with the exact `session_id`, `pb_order_group` (=configuration), `support_label`
(=feedback style), and `platform_base` pulled from the platform session. The BST
operator copies those into the current `input()` prompts. It is still the
platform's values — just carried by hand instead of over HTTP — so the session
stays matched.

---

## 4. Net BST change
- New `logic/launch_client.py` (4 calls + a poll).
- `BST()`: replace the multi-field `input()` block with one `session_id` input
  (or arg/env), `get_config()`, `ack("config_received")`, `wait_for_start()`,
  `ack("started")` / `error()`.
- Zero changes to the interaction logic, the state machine, the recognizer, or the
  sync gate flow.
