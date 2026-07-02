"""Data dictionary generator (Phase 6, P0.11 Part C).

Renders DATA_DICTIONARY.md describing every exported file/field and the
load-bearing study decisions that must not live only in conversation. The
Latin-square resolution table is generated from the same source mappings used to
materialize dtt_loops, so the dictionary can never drift from the data.
"""

from __future__ import annotations

from pathlib import Path

from app.services.dtt_loops import (
    BASELINE_LOOPS,
    NAMED_SD_BY_GROUP,
    PB_ORDER_GROUP_EVEN_FUNCTION,
)

FUNCTION_FULL = {
    "PR": "Positive Reinforcement",
    "NR": "Negative Reinforcement",
    "AR": "Automatic Reinforcement",
    "baseline": "baseline (no problem behavior)",
}


def _function_for(group: int, loop_index: int) -> str:
    if loop_index in BASELINE_LOOPS:
        return "baseline"
    return PB_ORDER_GROUP_EVEN_FUNCTION[group][loop_index]


def _sd_resolution_table() -> str:
    """position x order group -> named SD (function). Generated, never hand-typed."""
    lines = [
        "| sd_id (position) | group 1 | group 2 | group 3 |",
        "| --- | --- | --- | --- |",
    ]
    for loop_index in (1, 2, 3, 4, 5, 6):
        cells = []
        for group in (1, 2, 3):
            named = NAMED_SD_BY_GROUP[group][loop_index]
            fn = _function_for(group, loop_index)
            cells.append(f"{named} ({fn})")
        lines.append(f"| sd_{loop_index} | {cells[0]} | {cells[1]} | {cells[2]} |")
    return "\n".join(lines)


def render_data_dictionary() -> str:
    sd_table = _sd_resolution_table()
    return f"""# BST Data Collection Platform - Export Data Dictionary

This export has two layers:

- **Part A - raw per-table dumps (fidelity layer):** one file per table/concept,
  faithful to the database rows. Column names and order match the source tables;
  values are emitted verbatim with no transformation. **This is the source of
  truth.**
- **Part B - joined analysis-ready frames (convenience layer):** derived entirely
  from the raw rows by joining, so a row can be analyzed under the 2x3 design
  without manual joins. In Part B, columns native to the base row keep their
  name (**raw**); columns pulled in via a join are prefixed with their source
  table (`loop__`, `session__`) (**derived-via-join**); computed columns are
  prefixed `derived__` (**derived**).

Exports are READ-only against the database: producing an export never modifies
any source row (research-integrity rule). Re-exporting a session writes a new
timestamped directory; it never overwrites a prior export.

---

## Load-bearing decisions (read this first)

These encode study design that an analyst cannot recover from the column values
alone:

- **`support_condition` polarity:** `1 = supportive`, `0 = neutral`. This is a
  **between-subjects** factor on the session. `derived__support_label` spells it
  out (`supportive` / `neutral`).
- **`function_class` = PR / NR / AR:** **P**ositive / **N**egative / **A**utomatic
  **R**einforcement - the function of the problem behavior the robot-child
  exhibits. `baseline` = no problem behavior. These are the 3 levels of the
  within-session function factor (the even loops 2/4/6); baseline occupies the
  odd loops 1/3/5.
- **`sd_id` is a POSITIONAL cell, not a fixed stimulus.** `sd_1..sd_6` denote the
  loop position (`sd_{{loop_index}}`). The *named* DTT skill and its function at a
  given position depend on the session's `pb_order_group` (the Latin square).
  Resolve with the table below: e.g. `sd_2` in group 1 = Receptive Instruction
  (NR), but `sd_2` in group 3 = Tacting and Labeling (PR).
- **Prompt model:** a **single** prompt. The trial-level distinction is
  **independent vs. prompted**, NOT a graded prompt-fading hierarchy.
- **Feedback is a per-trial event, not a phase.** Do not treat feedback as a DTT
  protocol phase; it is logged against individual trials / the timeline.
- **Recording fps is REQUESTED, not measured.** `media_recordings.fps` stores the
  requested rate (30). Actual sustained capture can differ (the Brio sustains
  ~22 fps at 1080p). For true frame rate/duration, trust `ffprobe` / the file,
  not this field.

### Latin-square resolution: sd position -> named SD (function), by pb_order_group

Baseline is pinned to the odd positions (loops 1, 3, 5) and is identical across
groups; the three challenge functions rotate through the even positions (loops
2, 4, 6). Generated from the same mapping that materializes `dtt_loops`.

{sd_table}

Function abbreviations: PR = {FUNCTION_FULL['PR']}; NR = {FUNCTION_FULL['NR']};
AR = {FUNCTION_FULL['AR']}.

---

## Part A - raw dumps

### participants.csv
The session's participant (research table; no names by design).
- `participant_id` - stable research ID (e.g. P001).
- `consent_status` - consented / not_consented / withdrawn.
- `media_recording_consent` - granted / denied / withdrawn / not_asked.
- `created_at`, `notes`.

### sessions.csv
The single session row (the export/analysis unit for between-subject factors).
- `session_id`, `participant_id`, `scenario_type` (bst_dtt / customer_service).
- `support_condition` - **1 = supportive, 0 = neutral** (between-subjects).
- `pb_order_group` - 1/2/3; selects the Latin-square configuration (see above).
- `protocol_id` - FK to the DTT protocol config registered for the session.
- `state` - created/running/paused/stopped/completed.
- `start_timestamp_utc` - t0 anchor for all `session_time_ms`.
- `stop_timestamp_utc`, `completed_at`, `platform_version`, `created_at`, `notes`.

### dtt_loops.csv
The six canonical per-session loop rows, generated at session start. Source of
truth for loop attributes.
- `loop_index` - 1..6 (loop position == `sequence_position` in v1).
- `function_class` - baseline / PR / NR / AR (baseline on 1/3/5).
- `sd_id` - positional cell `sd_{{loop_index}}` (resolve named SD via the table above).
- `is_problem` - '1' for challenge loops (PR/NR/AR), '0' for baseline.
- `support_condition`, `pb_order_group` - denormalized from the session.
- `loop_id`, `session_id`, `participant_id`, `sequence_position`, `created_at`.

### dtt_trials.csv
One row per logged DTT trial. `loop_index` references `dtt_loops`.
- `trial_number` - auto, per session, 1..N.
- `loop_index` - the loop this trial belongs to (validated against dtt_loops).
- `phase_key` - DTT protocol phase from the protocol config (NOT feedback).
- `sd_id` - SD chosen from the protocol config for this trial.
- `target_skill`, `instruction` (human-readable SD label), `participant_response`.
- `response_correctness` - correct / incorrect / no_response / partial.
- `prompt_level` - prompt value from the config (single-prompt model:
  independent vs prompted; not a fading hierarchy).
- `reinforcement_delivered`, `error_correction_delivered`, `deviation_flag` - 0/1.
- `missed_steps_json`, `extra_steps_json` - JSON arrays of step IDs (as stored).
- `response_latency_ms`, `dtt_phase_id`, `protocol_id`, `notes`.
- `timestamp_utc`, `session_time_ms` (relative to session start), `created_at`.

### questionnaire_responses.csv
One row per item response (ERQ, BFI-2-S, RoSAS, etc.). No copyrighted item text:
- `questionnaire_key`, `questionnaire_version`, `item_id` (stable), `item_index`.
- `response_raw`, `response_numeric`, `timepoint` (pre/post/na).
- `is_partial` - 0/1 (1 = autosaved partial, not a final submission).
- `recorded_at`, `created_at`, plus `session_id`, `participant_id`.

### questionnaire_scores.csv
Defined but UNUSED in v1 (scoring is post-hoc). Header is present; rows likely 0.

### self_reports.csv
Participant self-reports (PAD + ratings), continuous bipolar sliders in [-5, +5]
(true-zero center). Each row carries its own analysis context:
- `loop_index` - 1..6 for loop-bound reports; **NULL for the three instructional
  baseline reports** (phase tutorial/instruction/modeling) which precede any loop.
- `sequence_position`; `timepoint` (pre/post).
- `phase` - one of `tutorial | instruction | modeling | rehearsal | feedback`.
  **`tutorial`, `instruction`, `modeling` are the three baseline self-reports**
  (collected at the end of each instructional stage, before rehearsal, no problem
  behavior in play). `rehearsal` = the post-kid-response report within a loop
  (the participant's reaction to the CHILD'S behavior - the PR/NR/AR manipulation
  - collected after the kid-behavior arc and before feedback); `feedback` = the
  post-feedback report within a loop. Two reports per DTT loop (rehearsal +
  feedback) plus three baseline = the 15 gated measurements.
- `function_class` - carried for convenience; canonical value is in `dtt_loops`.
  Baseline self-reports carry `function_class='baseline'`.
- `before_after_robot_action` - before / after / na.
- `source` - 'sr' (self-report). ML affect lives in perception_events, not here.
- Sliders: `pleasure` (==valence), `arousal`, `dominance`, `confidence`,
  `frustration`, `engagement`, `perceived_challenge`, `perceived_support`,
  `cognitive_load`.
- `trial_id`, `raw_json`, `timestamp_utc`, `session_time_ms`, `created_at`.

### media_recordings.csv
A/V recording manifest (one row per recording attempt).
- `file_path`, `file_name`, `status` (pending/recording/completed/failed/interrupted).
- `start_timestamp_utc`, `stop_timestamp_utc`, `session_time_ms_at_start`,
  `duration_ms`.
- `codec`, `container`, `resolution`, **`fps` (REQUESTED rate, e.g. 30 - actual
  may be lower; trust ffprobe)**, `bitrate_kbps`, `pix_fmt`, `audio_device`.
- `ffmpeg_command`, `device_name`, `error_text`, `notes`.

### sync_gates.csv
The BST<->platform synchronization barriers (15 per fully gated session: 3
instructional baseline + 6 loops x 2 checkpoints). One row per gate.
- `gate_key` - canonical id, e.g. `stage:tutorial:baseline`, `loop:2:post_kid_response`.
- `scope` - `stage` | `loop`; `stage_key` (tutorial/instruction/modeling) or
  `loop_index` (1..6); `checkpoint` - `baseline` | `post_kid_response` |
  `post_feedback`. `post_kid_response` opens after the child-behavior arc
  completes (the child has exhibited its behavior / problem behavior, the
  PR/NR/AR manipulation) and before the trainer's feedback; `post_feedback`
  opens after feedback is delivered.
- `status` - `open` | `closed`.
- **`closed_by`** - `self_report` (a matching report was submitted) or
  **`override`** (operator released the gate). **`closed_by='override'` is the
  skipped-by-override marker: that checkpoint's measurement was intentionally
  skipped, NOT missing-by-error.** The same event also appears in the timeline as
  `self_report_gate_overridden`.
- `override_operator`, `override_reason` - who/why for an override.
- `opened_at`, `closed_at`.

### perception_events.jsonl
One JSON object per line; one row per perception poll. Outages are data, not gaps
(a failed poll writes a row with `connection_status='down'` and null payload).
- `task` - asr / emotion / gesture; `backend_name`; `source` = 'ml'.
- `detected_label`, `confidence`, `valence` (==pleasure), `arousal`, `transcript`,
  `face_detected` (0/1), `latency_ms`.
- `connection_status` - ok / degraded / down.
- `source_timestamp_utc`, `received_timestamp_utc`, `session_time_ms`.
- `raw_payload` - the orchestrator payload, parsed back to nested JSON (lossless).

### session_timeline.jsonl
The unified event spine; a completed session reconstructs from this alone. One
JSON object per line, ordered by `event_id`.
- `event_id`, `session_id`, `participant_id`, `timestamp_utc`, `session_time_ms`.
- `source`, `type` (e.g. session_started, dtt_loops_generated, trial_logged,
  self_report_gate_opened, self_report_gate_closed, **self_report_gate_overridden**).
- `payload` - event detail, parsed to nested JSON.
- `ref_table`, `ref_id` - soft link to the row this event describes.

### session_summary.json
Provenance + counts for the export: session metadata, `support_label`,
`pb_order_group`, per-table `row_counts`, the file list, and `exported_at_utc`.

---

## Part B - joined analysis frames

Every Part B value is derived from Part A. Join keys: trials/self-reports ->
`dtt_loops` on `(session_id, loop_index)`; -> `sessions` on `session_id`.

### analysis_trials.csv
One row per DTT trial, ready for the 2x3 analysis.
- **Raw** (from `dtt_trials`): `trial_id`, `session_id`, `participant_id`,
  `trial_number`, `loop_index`, `protocol_id`, `phase_key`, `sd_id`,
  `target_skill`, `instruction`, `response_correctness`, `prompt_level`,
  `reinforcement_delivered`, `error_correction_delivered`, `deviation_flag`,
  `response_latency_ms`, `timestamp_utc`, `session_time_ms`.
- **Derived-via-join** (from `dtt_loops`): `loop__function_class`, `loop__sd_id`,
  `loop__is_problem`, `loop__sequence_position`. (from `sessions`):
  `session__support_condition`, `session__pb_order_group`, `session__scenario_type`.
- **Derived (computed):** `derived__support_label` (supportive/neutral),
  `derived__named_sd` (named DTT skill resolved from pb_order_group + loop_index).

Note: `sd_id` (raw, from the trial) and `loop__sd_id` (the loop's positional cell)
should agree for a well-formed trial; both are included so disagreements are
visible rather than hidden.

### analysis_self_reports.csv
One row per self-report, ready for the 2x3 analysis.
- **Raw** (from `participant_self_reports`): `self_report_id`, `session_id`,
  `participant_id`, `trial_id`, `loop_index`, `sequence_position`, `phase`,
  `timepoint`, `function_class`, `is_problem`, `before_after_robot_action`,
  `source`, the nine sliders, `timestamp_utc`, `session_time_ms`.
- **Derived-via-join** (from `dtt_loops`): `loop__function_class` (canonical),
  `loop__sd_id`. (from `sessions`): `session__support_condition`,
  `session__pb_order_group`.
- **Derived (computed):** `derived__support_label`, `derived__named_sd`.

The raw `function_class` is the value captured with the self-report; the
canonical loop value is `loop__function_class`. They should match; both are kept
so any mismatch is auditable.
"""


def write_data_dictionary(path: Path) -> None:
    path.write_text(render_data_dictionary(), encoding="utf-8")
