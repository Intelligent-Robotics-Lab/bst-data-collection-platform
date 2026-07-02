# Operator Console — Product Plan

_The researcher-facing web app for running a BST study session end to end: configure,
launch, monitor, intervene, and close out. Built in verified phases (v1 → v4), plus a
separate research track for automated scoring._

---

## 1. Purpose and scope

The platform, robots, tablet, recording, perception, and the auto-push self-report loop
are all built and proven in a full rehearsal. Today the operator drives sessions through
the developer/Swagger tool. This console replaces that with a professional, reliable,
user-friendly screen that walks the operator through the session.

**Key scoping fact:** because self-report forms already auto-push to the tablet on
gate-open, the console does **not** run the measurements. Its job is
**setup → launch → monitor → intervene → close out**. It is a control-and-observation
console over an already-automatic measurement pipeline, not a robot puppeteer.

**Not in the console:** live participant video. The existing perception web page already
shows the live feed and signals; the operator keeps it open in a separate window. (Video
is integrated into the console only later, in v4's perception tab.)

---

## 2. Design principles

- **Reliability over flash.** This runs live, unrepeatable sessions. Correct and clear
  beats clever. No action should be able to crash or corrupt a running session.
- **One authoritative session ID.** The console creates the session and displays its ID
  prominently — this is the single source of truth that ends the manual ID-matching
  fragility between platform and robots.
- **Stage-walker mirrors the 8-step protocol.** The UI moves through the real session
  flow, doubling as the operator's checklist so nothing is skipped.
- **Reuse the existing stack.** Static HTML + JS served from the platform (like the
  tablet page), hitting existing API endpoints. Professional, clean styling. No new
  framework unless a later phase (v4 charts/video) clearly needs it.
- **Read-only by default; actions are deliberate.** The only write actions are explicit
  operator choices (create session, push forms, override, note, export, and later launch).
- **Build and verify one phase at a time.** Each version ships and is tested before the
  next begins.

---

## 3. Phasing overview

| Version | What it delivers | Depends on |
| --- | --- | --- |
| **v1 — Operational core** | Run a whole session from one screen: setup, onboarding, live monitor (progress + gate + override + status + notes), closeout + export | Existing API; maybe one small "current open gate" read endpoint |
| **v2 — Launch integration** | Start the robots from the console (config handoff + launch signal) | bst-side change to accept config + start signal |
| **v3 — Fidelity scoring panel** | Human scores each loop via the ABA fidelity table (structured form) | v1 live screen; scoring storage on platform |
| **v4 — Perception tab** | Integrated, professional live view of perception signals + participant video | Existing perception/orchestrator feed |
| **Research track (separate)** | LLM-based auto-scoring of fidelity + validation against human scores | v3 (human ground truth); bst LLM-feedback change |

Ship v1 first. After v1, the operator can run a real session from the console. Everything
else is additive.

---

## 4. v1 — Operational core (BUILD FIRST)

### Persistent header (always visible)
- Participant ID + **canonical session ID**
- Stage indicator: Setup → Onboarding → Live → Post → Closeout
- Session state (created / running / paused / complete)
- Always-available "Add note" button

### Stage 1 — Setup & Configure
- Inputs: participant ID, session ID, pb_order_group (1/2/3), support_condition
  (supportive/neutral)
- "Create & start session" → creates + starts the session, generates dtt_loops
- Pre-session checklist (tick-boxes): study area set, program loaded, perception running,
  connections established
- Cannot advance until the session is confirmed running

### Stage 2 — Onboarding
- Checklist: consent completed, media consent, briefing read
- "Push pre-questionnaire to tablet" for each: demographics, ERQ, BFI-2-S — with
  completion status shown as each returns
- "All pre-steps complete → begin interaction" confirmation

### Stage 3 — Live Session (the operational heart; deliberately minimal in v1)
- **Progress:** current phase (tutorial / instruction / modeling / rehearsal) and current
  loop (1–6)
- **Current gate:** which gate is open, its checkpoint, and how long it has been waiting
  (e.g. "loop 2 · post-kid-response · waiting 0:14")
- **Override button** for the currently open gate (the safety valve)
- **Status:** recording running/healthy, perception connection healthy
- **Notes** panel
- No fidelity scoring (v3), no rich perception viz/video (v4)

### Stage 4 — Post-session
- "Push post-questionnaire to tablet" for each: RoSAS (trainer), RoSAS (child), D-QEL,
  manipulation checks — with status
- Qualitative-response notes field
- Debrief checklist

### Stage 5 — Closeout
- Data-completeness summary (counts: self-reports, trials, gates fired/overridden,
  recording status)
- "Generate export" button
- Reset-for-next-participant checklist

### v1 acceptance criteria (how we know it's done)
- [ ] Operator can create + start a session from Stage 1; the canonical session ID is
      shown and used everywhere.
- [ ] Pre- and post-questionnaires push to the tablet from the console, with status.
- [ ] Stage 3 correctly shows current phase, current loop, and the open gate in real time
      during a live run.
- [ ] Override from the console releases the open gate and the robot proceeds.
- [ ] Recording and perception status reflect reality.
- [ ] Notes save and appear in the session record.
- [ ] Closeout export produces the files; completeness summary counts are correct.
- [ ] Nothing in the console can crash or corrupt a running session (all failures are
      handled gracefully).
- [ ] A full session can be run end to end from the console alone (no Swagger needed),
      verified in a rehearsal-style run.

### Possible small backend addition for v1
- A read endpoint for "current open gate(s) for this session" if one does not already
  exist (the live screen needs it). Everything else should use existing endpoints.

---

## 5. v2 — Launch integration
- Console hands session config (session ID, pb_order_group, support_condition) to the
  robots and triggers start, replacing terminal input on the bst side.
- **bst-side change (owned by the team):** accept config + a start signal from the
  platform instead of `input()`; start the interaction on the signal.
- Acceptance: operator starts the robots from the console; config is guaranteed to match
  the platform session (no manual re-typing).

## 6. v3 — Fidelity scoring panel (human)
- The ABA fidelity table as a fast structured form the operator fills per loop
  (per-SD component + timing scores; error-source options).
- Stored per loop, linked to session + loop_index, exported.
- **Independence requirement:** operator scores **blind** to any automated score, so the
  human rating stays a valid ground truth for later validation.
- Acceptance: operator can score each loop; scores save and export; scoring is
  independent of any machine score.

## 7. v4 — Perception tab
- Integrated, professional live view of perception signals (emotion/valence-arousal,
  gesture, ASR) and the participant video feed, folded into the console.
- Likely justifies a charting library and continuous updates (revisit tech here).
- Acceptance: live signals + video display reliably while the orchestrator is streaming;
  does not affect session control reliability.

## 8. Research track (separate from console phases)
- Structure the trainer robot's existing LLM feedback to also emit a per-component
  fidelity score matching the ABA table, and send it to the platform (likely alongside
  `feedback_delivered`).
- Store the automated score independently of the human score.
- Validate the automated score against human ground truth (agreement analysis).
- **Kept separate and after v3** because: (a) it is a research-grade effort with its own
  uncertainty (LLM reliably filling the table, timing components), and (b) independence
  from the human score is required for valid validation. It must not block a runnable
  console with human scoring.

---

## 9. Pre-real-participant prerequisites (unchanged, tracked elsewhere)
Migration strategy (Alembic), SSD mount, real questionnaire text (gitignore-local),
and rehearsals remain hard prerequisites for the study — independent of console phases.
