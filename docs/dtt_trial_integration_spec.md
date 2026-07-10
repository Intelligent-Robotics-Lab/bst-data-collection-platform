# DTT Trial Interaction-Flow Integration — change spec for the BST owners

Status: SPEC ONLY. Nothing in the BST repo has been or should be edited by the
data-platform side. This document tells the BST owners exactly what to add so the
platform records the **within-trial interaction flow**.

The **data-platform side is implemented** (endpoint, append-only ingestion,
derivation, drift guard, export, data dictionary, tests). The BST-side work is
small, because **the robot already builds this data** — see §1.

Companion to `bst_sync_integration_spec.md` (the gates). Gates pause the robot;
this records **what happened inside a trial**.

---

## 0. What we capture, and why

The gates say *when* a loop reached a checkpoint. They say nothing about **how
the trial unfolded**.

Crucially, the **child's behavior is scripted** (`trial_data.json` fixes each
SD's `correctness` and `child_behavior`), so it carries no information. What
varies — and what we want — is **what the human trainer did**: which SDs and
prompts they delivered, whether each was recognized, and how many attempts it
took.

That is exactly what the robot records.

```
sd ─ recognized? ──► reinforcement                                   (correct first try)
   └─ child does not respond ──► prompting ─► hp_sd ─► retry sd ─► reinforcement
                                 (error correction; each may take >1 attempt)
```

The human fidelity panel scores this subjectively per loop (15 fields). This spec
adds the **objective machine record** of the same sequence, so the two can be
compared.

---

## 1. The robot already has this

`logic/feedback.py` accumulates `interaction_history` and
`build_evaluation_payload()` assembles the whole `event_log`.
`feedback_handler.py:59` **already calls it**, a few lines before the
`feedback_delivered` hook. `feedback.reset()` runs only at the start of the
*next* trial (`sd_processing_handler.py:54`), so the history is intact when we
post.

Real capture (`feedback_training_data/failed_hp_sd/…_Tacting and Labeling.json`):

```json
"interaction_history": [
  {"trial_state":"sd",           "text":"What am I holding?",     "recognized_as":"Tacting and Labeling", "successful":true,  "corrected_later":false},
  {"trial_state":"prompting",    "text":"No. What am I holding?", "recognized_as":"Tacting and Labeling", "successful":true,  "corrected_later":false},
  {"trial_state":"reinforcement","text":"Good job.",              "recognized_as":"Tacting and Labeling", "successful":true,  "corrected_later":false},
  {"trial_state":"hp_sd",        "text":"Can you dance?",         "recognized_as":null,                   "successful":false, "corrected_later":false},
  {"trial_state":"hp_sd",        "text":"Shake your head.",       "recognized_as":"SD_1",                 "successful":true,  "corrected_later":false},
  {"trial_state":"retry sd",     "text":"What I hope",            "recognized_as":null,                   "successful":false, "corrected_later":false}
]
```

Two properties to note, because they shape the contract:

- **Trainer-side only.** Across every capture the only `trial_state` values are
  `sd`, `prompting`, `reinforcement`, `hp_sd`, `retry sd`. There are no child
  steps and no `feedback` step.
- **A state may repeat.** Two `hp_sd` attempts above: the first not recognized,
  the second recognized. The flow is a list of **attempts**, not a fixed
  sequence. `step_index` orders them.

---

## 2. Map BST concepts → platform fields

| BST (robot)                                          | Platform field                    |
| ---------------------------------------------------- | --------------------------------- |
| `get_sd_display_number(ctx.trial_sd, cfg)`            | `loop_index` (1..6)               |
| `ctx.trial_sd` == `event_log.trial_id`                | `trial_name` (checked, see §5)    |
| `interaction_history[i].trial_state`                  | `steps[].step_label` (snake_cased)|
| the human trainer                                     | `steps[].actor` = `"user"`        |
| `interaction_history[i].successful`                   | `steps[].outcome`                 |
| `text` / `recognized_as` / `corrected_later`          | `steps[].detail`                  |
| `trial_data[ctx.trial_sd]["correctness"]`             | `response_correctness`            |

> **Use `ctx.trial_sd`, never `ctx.current_sd`.** `current_sd` is the *currently
> presented* SD: it swaps to a high-probability SD during error correction, and
> `reinforcement_handler.py:104` sets it to `None` before FEEDBACK. The robot
> already follows this rule at `reinforcement_handler.py:97`.

`step_label` is the `trial_state`, snake_cased — the only transform is
`"retry sd"` → `"retry_sd"`:

| `trial_state`   | send            |
| --------------- | --------------- |
| `sd`            | `sd`            |
| `prompting`     | `prompting`     |
| `reinforcement` | `reinforcement` |
| `hp_sd`         | `hp_sd`         |
| `retry sd`      | `retry_sd`      |

`outcome`: `"recognized"` when `successful` is true, else `"not_recognized"`.

`response_correctness` is the child's *scripted* response:
`"Correct"` → `correct`, `"No Response"` → `no_response`.

---

## 3. The contract (already live on the platform)

```
POST /sessions/{session_id}/trials                     -> 201, the created trial
GET  /sessions/{session_id}/trials                     -> all trials
GET  /sessions/{session_id}/trials/{trial_id}/steps    -> the flow, in order
```

Body — only `loop_index`, the outcome, and `steps` matter:

```json
{
  "loop_index": 4,
  "trial_name": "Tacting and Labeling",
  "response_correctness": "no_response",
  "reinforcement_delivered": true,
  "error_correction_delivered": true,
  "steps": [
    {"step_index":1,"step_label":"sd","actor":"user","outcome":"recognized",
     "detail":{"text":"What am I holding?","recognized_as":"Tacting and Labeling","corrected_later":false}},
    {"step_index":2,"step_label":"prompting","actor":"user","outcome":"recognized",
     "detail":{"text":"No. What am I holding?","recognized_as":"Tacting and Labeling","corrected_later":false}},
    {"step_index":3,"step_label":"reinforcement","actor":"user","outcome":"recognized",
     "detail":{"text":"Good job.","recognized_as":"Tacting and Labeling","corrected_later":false}},
    {"step_index":4,"step_label":"hp_sd","actor":"user","outcome":"not_recognized",
     "detail":{"text":"Can you dance?","recognized_as":null,"corrected_later":false}},
    {"step_index":5,"step_label":"hp_sd","actor":"user","outcome":"recognized",
     "detail":{"text":"Shake your head.","recognized_as":"SD_1","corrected_later":false}},
    {"step_index":6,"step_label":"retry_sd","actor":"user","outcome":"not_recognized",
     "detail":{"text":"What I hope","recognized_as":null,"corrected_later":false}}
  ]
}
```

`detail` is stored verbatim. `steps` is optional (a trial without a flow is still
a valid trial). **Write semantics:** the trial row and its step rows are inserted
in one transaction and never updated; a rejected trial leaves no orphan steps.

---

## 4. BST-side changes (proposed; not applied)

### 4.1 One new `SyncClient` method

`self.base` ends in `/sync`, but trials live at `/sessions/{sid}/trials`. Store
the session root in `__init__`:

```python
self.session_root = f"{base_url}/sessions/{session_id}"
self.base = f"{self.session_root}/sync"
```

```python
# logic/sync_client.py  (PROPOSED addition)

    async def log_trial(self, **body) -> dict | None:
        """Record one DTT trial and its interaction flow.
        Data logging must NEVER break a run: on any failure, log and continue."""
        try:
            r = await self._http.post(f"{self.session_root}/trials", json=body)
            r.raise_for_status()
            return r.json()
        except Exception as exc:            # noqa: BLE001
            print(f"[sync] log_trial failed (continuing): {exc}")
            return None
```

**Never let `raise_for_status()` escape this call.** Every other `SyncClient`
method raises; if `log_trial` does, a platform hiccup kills a live, unrepeatable
participant session. Recording a trial is bookkeeping, not control flow. Only
`wait_for_go_ahead` may block a run.

### 4.2 Transform `interaction_history` → `steps`

No per-handler edits are needed; the history already exists.

```python
def _to_steps(interaction_history: list[dict]) -> list[dict]:
    steps = []
    for i, e in enumerate(interaction_history, start=1):
        steps.append({
            "step_index": i,
            "step_label": str(e["trial_state"]).replace(" ", "_"),   # "retry sd" -> "retry_sd"
            "actor": "user",                                         # the human trainer
            "outcome": "recognized" if e.get("successful") else "not_recognized",
            "detail": {
                "text": e.get("text"),
                "recognized_as": e.get("recognized_as"),
                "corrected_later": e.get("corrected_later", False),
            },
        })
    return steps
```

### 4.3 Post it at the end of the loop

`feedback_handler.handle()` already computes `loop_index` (line 36) and calls
`feedback_delivered` (line 120). Post immediately after, and **before**
`wait_for_go_ahead`, so the trial is recorded even if the operator is slow:

```python
# logic/dtt_module/handlers/feedback_handler.py  (PROPOSED, after feedback_delivered)

        await self.sync.feedback_delivered(loop_index, trial_name=ctx.trial_sd)

        steps = _to_steps(feedback.interaction_history)
        labels = {s["step_label"] for s in steps}
        await self.sync.log_trial(
            loop_index=loop_index,
            trial_name=ctx.trial_sd,
            response_correctness=(
                "no_response" if trial_data[ctx.trial_sd]["correctness"] == "No Response"
                else "correct"
            ),
            reinforcement_delivered="reinforcement" in labels,
            error_correction_delivered="prompting" in labels,
            steps=steps,
        )

        await self.sync.wait_for_go_ahead(scope="loop", loop_index=loop_index,
                                          checkpoint="post_feedback")
```

### 4.4 Recommended: give each step a real timestamp (one line)

`interaction_history` entries carry **no time**, so every step would be stamped
with the post time and intra-trial timing would be lost. `trainer_events` already
records `time.time()`. Add the same when appending history (`logic/feedback.py`,
~line 104):

```python
        self.interaction_history.append({
            "trial_state": str(trial_state),
            "text": text,
            "recognized_as": recognized_as,
            "successful": successful,
            "corrected_later": False,
            "time": time.time(),                     # <-- add
        })
```

then in `_to_steps`, emit
`"timestamp_utc": datetime.fromtimestamp(e["time"], timezone.utc).isoformat()`.
The platform records it and still stamps its own `session_time_ms`.

---

## 5. What the platform does for you

**Derivation — do not hardcode platform vocabulary.** You send only
`loop_index`. From the participant's Latin-square order group the platform
resolves:

- `phase_key` → `rehearsal` (the protocol's only phase)
- `sd_id` → `sd_{loop_index}` (positional cell, matching `dtt_loops`)
- `target_skill` → the named SD's skill (`manding`, `reception`, …)
- `instruction` → the real SD wording, e.g. group 1 loop 2 → `"Nod your head."`

**Drift guard.** `trial_name` is checked against the Latin square. A mismatch is
a loud `422`, not a silently mislabeled trial:

```
422  trial_name 'Manding' does not match the named SD for loop 2 of
     pb_order_group 1 (expected 'Receptive Instruction')
```

Send it — it is cheap, and it is the tripwire that keeps the two repos honest.

**Error-correction depth is derived, not sent.** This protocol has no
`prompt_level`. How far a trial went is read off the steps: labels stopping at
`reinforcement` mean correct first try; reaching `prompting` / `hp_sd` /
`retry_sd` shows how deep error correction went, and repeated labels show how
many attempts each stage took.

---

## 6. What NOT to send

**Never send `study_config`.** It contains `participant_name` (a real name).
Platform rule: participant **IDs** only, no names in research data. Send nothing
from that block.

**Do not send `precomputed_analysis` (yet).** `build_evaluation_payload()`
includes automated scores (`sd_score`, `prompt_score`, `reinforcement_score`,
`sequencing_score`, `error_correction_score`, `overall_preliminary_score`) and
`recovery_metrics`. These are an **automated fidelity score**, and the v3 spec
requires the operator to score **blind** to any machine score so the human rating
remains valid ground truth (`OPERATOR_CONSOLE_PLAN.md` §8: the LLM-scoring
research track is kept separate and *after* v3).

If we later capture them, they must live in their own table, be written
independently of `fidelity_scores`, and **never be surfaced in the console**.
That is a separate, deliberate decision — not part of this spec.

---

## 7. Failure policy

| Situation                     | Behaviour                                                    |
| ----------------------------- | ------------------------------------------------------------ |
| Platform unreachable / 5xx    | log and continue; the trial is lost, not the session          |
| `422` (drift, bad step label) | log loudly — the repos disagree and must be reconciled        |
| Trial posted twice            | two rows; `trial_number` auto-increments. Post once, at feedback |
| Robot crashes mid-trial       | that trial's flow is lost; gates + timeline still record progress |

Only `wait_for_go_ahead` may block the run. Everything here is fire-and-log.

---

## 8. Verification (after the BST-side change)

Run one session, then:

```bash
SID=<session_id>
sqlite3 data/bst.db "
  SELECT trial_number, loop_index, target_skill, instruction, error_correction_delivered
  FROM dtt_trials WHERE session_id='$SID' ORDER BY trial_number;"
sqlite3 data/bst.db "
  SELECT t.loop_index, p.step_index, p.step_label, p.outcome
  FROM dtt_performance_events p JOIN dtt_trials t USING (trial_id)
  WHERE p.session_id='$SID' ORDER BY t.loop_index, p.step_index;"
```

Expect:

- **6 trials** (one per loop), `instruction` showing the real SD wording.
- Loops 1/3/5 (baseline): a short flow, typically `sd → reinforcement`.
- Loops 2/4/6 (PR/NR/AR): a longer flow reaching `prompting` / `hp_sd` /
  `retry_sd`, with repeated labels where the trainer needed several attempts.
- `error_correction_delivered = 1` exactly on the problem loops.
- `dtt_performance_events.csv` present in the session export.
