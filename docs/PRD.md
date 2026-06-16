# PRD: BST Data Collection Platform

**Version:** 1.0 (derived from Product Plan v1.2)
**Owner:** Pourya Shahverdi
**Status:** Approved for build
**Date:** June 11, 2026
**Related documents:** `docs/product_plan.md` (v1.2, governs scope and the 7-day schedule), `docs/requirements.md` (original base prompt), `docs/perception_integration.md`

---

## Problem Statement

Researchers running robot-mediated BST/DTT study sessions must capture many concurrent data streams per participant: questionnaires, trial-level DTT performance, robot events, in-session emotional self-reports, raw audio/video, and behavioral signals from the existing HRI perception platform. No existing tool captures all of these in one synchronized, exportable record; ad hoc methods (spreadsheets, paper, manual notes) cannot guarantee timestamp alignment, raw-data preservation, or analysis-ready output. Each session is unrepeatable, so any data loss, desynchronization, or silent overwrite is a permanent loss to an NSF-funded study. The platform must be operable by a single experimenter and ready for real participants in 7 days.

## Goals

1. **Zero data loss:** 100% of session events persisted and recoverable through browser refreshes and backend restarts, demonstrated in rehearsal before first participant.
2. **Single-experimenter operability:** one person runs an entire 45-60 minute session with zero terminal use; DTT trial logging median <= 10 seconds per trial.
3. **Synchronized timeline:** every record carries UTC and session-relative timestamps from a single server clock; a complete session reconstructs from the timeline JSONL alone.
4. **Analysis-ready exports:** all export files load in pandas/R with zero manual fixes, immediately after each session.
5. **Research integrity by construction:** raw records are immutable; corrections and exclusions exist only as annotations; signal-quality gaps (missing predictions, low confidence, outages) are themselves logged data.

## Non-Goals

1. **Docker packaging.** One known host, one deployment, one week; containerization adds daily cost with deferred benefit. Architectural insurance retained via `.env` discipline (P2).
2. **Authentication and user accounts.** Closed lab LAN, single trusted experimenter; the participant route exposes only the assigned form. Auth adds friction with no threat model this study faces.
3. **Automated questionnaire scoring.** Raw responses are the research record; ERQ/BFI-2-S/RoSAS scoring is post hoc in analysis scripts. Prevents scoring-logic bugs from contaminating raw capture.
4. **Video playback/annotation UI.** Recordings are files plus a manifest; annotation happens later in dedicated tools, enabled by the timeline. Building review tooling now would consume the week without serving data capture.
5. **Real-time perception visualization.** The HRI perception platform already provides a live dashboard; duplicating it adds nothing. This platform ingests and logs only.
6. **Multi-study, multi-site, multi-language support.** One study, one server, English instruments.

## User Stories

**Experimenter (primary persona)**
1. As the experimenter, I want to register a participant with consent status and demographics so that a session cannot begin on an invalid basis.
2. As the experimenter, I want a pre-session checklist covering camera, perception link, tablet, storage, and consent so that I never start an unrepeatable session on a broken pipeline.
3. As the experimenter, I want to log each DTT trial with tap/click inputs in under 10 seconds so that logging never disrupts the live interaction.
4. As the experimenter, I want one-click pause/resume/stop recorded in the timeline so that interruptions are part of the honest research record.
5. As the experimenter, I want to push a specific questionnaire or self-report form to the participant tablet so that the participant always sees exactly the right screen.
6. As the experimenter, I want a timestamped note button available at all times so that unexpected events are captured in context.
7. As the experimenter, I want to exclude a trial or session via annotation so that mistakes are documented without destroying raw data.
8. As the experimenter, I want one-click export of all data files so that every session is backed up within minutes of ending.

**Participant**
9. As a participant, I want the tablet to show only my current form so that I am never confused or exposed to experimenter-facing data.
10. As a participant, I want self-report sliders completable in under 30 seconds so that reporting does not break the interaction flow.
11. As a participant, I want my partially completed questionnaire to survive an accidental refresh so that I never re-enter answers.

**Analyst (post-hoc persona)**
12. As the analyst, I want perception events logged even when predictions are missing or confidence is low so that signal quality is analyzable as data.
13. As the analyst, I want a data dictionary covering every exported column so that analysis scripts require no source-code reading.
14. As the analyst, I want recording start timestamps and session-relative event times in one clock so that video can be aligned to events for emotion labeling.

## Requirements

### Must-Have (P0)

**P0.1 Core backend and data models.** FastAPI + SQLite, models: participants, sessions, dtt_trials, robot_events, participant_self_reports, perception_events, media_recordings, session_timeline_events, experimenter_notes, questionnaire_responses, exports. Runs as user `pourya` on dedicated ports; never touches the perception stack.
- [ ] Server starts; all tables created; CRUD verified via /docs
- [ ] No model stores participant names; participant_id is the only identifier

**P0.2 Session lifecycle with scenario type.** States: created → running ⇄ paused → stopped → completed; `scenario_type` field (e.g., bst_dtt, customer_service).
- Given a running session, when the experimenter's browser is refreshed, then session state and all prior events are intact.
- Given any state transition, when it occurs, then a timeline event records it with UTC and session_time_ms.

**P0.3 Timeline event store.** Fields: event_id, participant_id, session_id, timestamp_utc, session_time_ms, source, type, payload JSON.
- [ ] Every P0 feature writes to it; ordering is monotonic per session
- [ ] A completed session's timeline JSONL alone is sufficient to reconstruct the session narrative

**P0.4 Config-driven questionnaire engine with real content.** Pre: demographics, ERQ (10 items, 7-point), BFI-2-S (30 items, 5-point). Post: RoSAS ×2 (18 items, 7-point; Trainer and Child robot). Placeholders: D-QEL, manipulation checks.
- Given a new questionnaire YAML in configs/, when the backend restarts, then it renders on the tablet with no code change.
- [ ] Item IDs are stable identifiers independent of display text

**P0.5 DTT trial logging panel.** Protocol-config-driven; captures trial number (auto), phase, target skill, response, correctness, latency if available, prompt level, reinforcement, error correction, missed/extra steps, deviation flag, notes.
- Given an active bst_dtt session, when the experimenter logs a typical trial, then it completes in <= 10 seconds and lands in dtt_trials plus the timeline.

**P0.6 Participant tablet route with push control.** Tablet displays exactly the form the experimenter has assigned; autosaves partial responses.
- Given the experimenter pushes a form, when the tablet polls, then the new form appears without participant action.
- Given a partially answered form, when the tablet refreshes, then all entered answers are restored.
- [ ] No experimenter data or navigation is reachable from the participant route

**P0.7 In-session self-report form.** Scales: valence, arousal, confidence, frustration, engagement, perceived challenge, perceived support, cognitive load; linked to session/phase/trial; before/after-robot-action flag.
- [ ] Submission writes participant_self_reports and a timeline event
- [ ] Completable in under 30 seconds on the tablet

**P0.8 Perception ingestion adapter.** Polls orchestrator /state/asr, /state/emotion, /state/gesture at configurable intervals; stores raw payload, source timestamp, received timestamp, confidence.
- Given the orchestrator is up, when polling runs, then events accumulate at >= 95% of expected intervals.
- Given a null prediction or low confidence, when received, then it is logged anyway (signal quality is data).
- Given the orchestrator goes down, when polling fails, then the platform continues unaffected and the outage interval is in the record.

**P0.9 Robot event logging (manual).** Role (Trainer/Child), utterance/action, condition, script version, payload JSON, source field.
- [ ] Event lands in robot_events and the timeline with one form submission

**P0.10 Server-side recording service.** Backend-managed ffmpeg subprocess; v4l2 capture of the dedicated Brio (MJPEG from camera); 1080p30; h264_nvenc (libx264 fallback); fixed ~4-5 Mbps; AAC audio; progressive write to `RECORDINGS_DIR` on the mounted SSD; graceful stop; manifest row and timeline events; live preview frame.
- Given a session, when recording starts and stops from the UI, then the file is playable and its duration matches the manifest within 1 second.
- Given the backend is killed (kill -9) mid-recording, when the file is inspected, then it is recoverable.
- Given ffmpeg fails to start or dies, when detected, then the failure is logged and surfaced, and the session continues.

**P0.11 Exports.** Participant CSV, questionnaire responses CSV, DTT trial CSV, self-report CSV, media manifest CSV, perception events JSONL, session timeline JSONL, session summary JSON, data dictionary MD.
- [ ] Every file loads in pandas with zero manual fixes
- [ ] Data dictionary covers every exported column

**P0.12 Pre-session checklist gating start.** Checks: recording camera preview OK, perception reachable, tablet route reachable, recordings path is a real mount point with >= 3 sessions of free space, consent confirmed.
- Given a failed required check, when the experimenter attempts to start, then start is blocked unless explicitly overridden, and any override is written to the timeline.

### Nice-to-Have (P1)

- **P1.1** Session review page (read-only completed-session summary)
- **P1.2** dtt_performance_events as fine-grained records (v1 folds into trials + timeline)
- **P1.3** participant_identity physically separated (v1 mitigates by storing IDs only)
- **P1.4** System health surfaced in UI (disk trend, backend errors, recording bitrate)
- **P1.5** Tablet validation polish and progress indicator
- **P1.6** systemd units (v1 runs in tmux)

### Future Considerations (P2)

- **P2.1** WebSocket perception ingestion → adapter is an interface; polling is one implementation
- **P2.2** Automated robot event ingestion → robot_events carries payload JSON + source field now
- **P2.3** Automated scoring → scoring slot in questionnaire schema; scores table exists, empty
- **P2.4** Docker Compose → all paths/ports in .env, nothing assumes localhost
- **P2.5** Trial-level video bookmarking → session_time_ms + recording start timestamp make offsets computable
- **P2.6** Multi-camera recording → media_recordings keyed by device; recording service parameterized

## Success Metrics

**Leading (measured in rehearsals and first 3 sessions)**
- Timeline integrity: 100% of events survive a forced browser refresh and a forced backend restart (method: scripted comparison of event counts before/after)
- Operability: full session by one experimenter, zero terminal interventions (method: observed rehearsal)
- Trial logging speed: median <= 10 s, stretch <= 7 s (method: timestamps between trial-panel open and submit)
- Perception capture rate: >= 95% of expected polling intervals while orchestrator is up (method: interval analysis on perception_events)
- Recording fidelity: 60-minute test file playable, duration within 1 s of manifest (method: ffprobe vs manifest)
- Export validity: 9/9 files load in pandas with zero fixes (method: validation script, runs in CI of day 6)

**Lagging (across the study)**
- Zero sessions lost or excluded due to platform failure (target: 0; threshold for postmortem: any)
- Zero raw-data overwrites (method: audit that corrections exist only as annotations)
- Session end to verified backup <= 5 minutes (method: run-book step timing)

## Open Questions

**Blocking (answer before Day 3)**
- [Pourya] DTT phases and target skills for the protocol config — shapes the trial panel UI.
- [Pourya] Robot events: manual-only for this study, or is there a machine-readable source to ingest now?

**Non-blocking (resolve during the week)**
- [Pourya] Audio source: recording Brio's mics vs dedicated microphone; pin the ALSA device either way.
- [Pourya] Self-report timing: experimenter-triggered only (v1 assumption) or also scheduled (every Nth trial)?
- [Pourya] Polling intervals — proposal: 500 ms ASR/gesture, 1 s emotion.
- [Pourya] Participant count target — sizes SSD and backup budget.
- [Pourya/IRB] Recording filename constraints — is participant ID in the filename acceptable?
- [Engineering/day 1 test] NVENC availability and v4l2 pixel-format behavior of the Brio on the server's distro.

## Timeline Considerations

- **Hard deadline:** ready for real participants in 7 days (target: Thu Jun 18, 2026); "ready" is defined by the Definition of Done below, not by feature completion.
- **External dependency:** dedicated external SSD must be mounted by Day 5 (P0.10 depends on it); ordered/located on Day 0.
- **Human dependency:** the two blocking questions are owned by Pourya and due Day 2 evening; Day 3 scope (trial panel, robot event form) consumes them.
- **Phasing:** governed by the 7-day plan in Product Plan v1.2, with one verification gate per day; any scope addition removes scope or consumes the Day 7 buffer, explicitly.
- **Cut ladder if behind (in order):** P1 items → tablet falls back to a second browser window on the experiment PC → post-questionnaires fall back to paper/Qualtrics with IDs. Timeline store, DTT logging, self-reports, perception logging, and recording are never cut.

## Definition of Done

A full rehearsal session (intake → demographics + ERQ + BFI-2-S on tablet → live session with 10+ trials, 2 self-reports, live perception logging, server-side recording to the SSD → RoSAS ×2 → export) completes with zero data loss, zero terminal interventions, a playable recording, and all exports validated in pandas — twice in a row.