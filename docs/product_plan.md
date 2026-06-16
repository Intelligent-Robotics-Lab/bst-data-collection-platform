# Product Plan: BST Data Collection Platform (FINAL)

**Version:** 1.3 (build week, reset to start Jun 16)
**Owner:** Pourya
**Date:** June 16, 2026
**Target:** Ready for real participants in 7 days (Day 1 = Tue Jun 16, target Mon Jun 22)
**Companion documents:** `docs/requirements.md` (base prompt), `docs/perception_integration.md` (perception API shapes), `docs/run_book.md` (written day 7)

**Changes from v1.1:** Infrastructure findings confirmed and folded in. Server capacity verified (CPU/RAM abundant, NVENC available). Storage confirmed as the single hardware constraint: one shared 1.9 TB NVMe at 89%, no spare disks; resolved by a dedicated external SSD with mount-guard checks, needed by day 5. Final plan, ready to execute.

---

## 1. Problem Statement

Running a robot-mediated BST/DTT study requires capturing many synchronized data streams per session: questionnaires, trial-level DTT performance, robot events, participant self-reports, raw video/audio, and behavioral signals from the existing HRI perception platform. No single tool does this; ad hoc methods cannot guarantee timestamp alignment, raw-data preservation, or analysis-ready exports. Every participant session is unrepeatable, so any data loss or desynchronization is a permanent loss to the study.

## 2. Product Vision

A local-first web platform running on the lab server that lets one experimenter run a complete study session end to end, with a participant-facing tablet for self-reports and a server-attached camera for raw recording, producing a fully synchronized, exportable research record with zero data loss.

## 3. System Topology (final)

| Machine | Role | Components |
|---|---|---|
| Lab server (Linux, in experiment room, sn4622121115) | Hosts everything | FastAPI backend, SQLite, served React frontend, ffmpeg recording service, recording Brio (USB), external SSD recordings volume, perception platform (already running, untouched) |
| Windows experiment PC | Pure edge client | GStreamer sender (sender Brio), experimenter browser pointed at server URL |
| Tablet | Participant client | Browser pointed at server participant route over WiFi |

**Confirmed infrastructure facts:**
- CPU: many-core machine at ~17% utilization; platform adds ~2% (ffmpeg) or near 0% with NVENC. Verified via top.
- Memory: 481 GB free of 515 GB. Non-issue.
- GPU: NVIDIA present; NVENC hardware encoder available for near-zero-CPU recording. Try `h264_nvenc` first, `libx264 -preset veryfast` as fallback.
- Storage: single 1.9 TB NVMe at 89% (205 GB free), shared with the team, no unmounted disks. **Constraint.** Resolution below.
- Clock: all timestamps (timeline, recording, perception receive-time) originate on one machine. No cross-machine clock sync needed.

**Storage resolution (required by day 5):**
1. Dedicated external USB 3 SSD (1-2 TB), ext4, labeled (e.g., BSTDATA), mounted at `/data/bst` via fstab with `nofail`.
2. `.env` sets `RECORDINGS_DIR=/data/bst/recordings`. No recording ever targets the root filesystem.
3. Mount-guard against silent fallback: unmounted mount point is `chmod 000`; backend checklist verifies the path is a real mount point (`os.path.ismount`) and has >= 3 sessions of free space.
4. Fixed bitrate (~4-5 Mbps at 1080p30) makes per-session cost predictable (~2 GB/hour).
5. Run-book post-session step: copy recordings to backup location, verify, confirm free space for next participant.
6. Interim (days 1-4): development needs no large files; the day 1 test capture (a few hundred MB) goes to home directory and is deleted.

**Shared-server etiquette (binding):** platform runs as user pourya (not root), own ports, own process (tmux for week one, systemd P1), own data directories, never modifies the perception compose stack, normal scheduling priority. One-line heads-up to the team before adding the USB device and service ports.

## 4. Goals

1. **Zero data loss:** every event persisted and recoverable through browser refreshes and backend restarts. Verified by rehearsal.
2. **Single-experimenter operability:** full session with zero terminal use.
3. **Synchronized timeline:** UTC plus session-relative time on everything; full session reconstructs from timeline JSONL alone.
4. **Analysis-ready exports:** load in Python/R with zero manual fixes.
5. **Raw data immutability:** corrections and exclusions are annotations, never overwrites.

## 5. Non-Goals (v1)

1. No Docker packaging (paths/ports in `.env` keep it easy later).
2. No authentication (closed lab LAN; participant route exposes only the assigned form).
3. No automated questionnaire scoring (raw responses export; scoring post hoc; scores table exists, stays empty).
4. No video playback/annotation UI (files plus manifest; timeline enables later annotation).
5. No real-time perception visualization (perception platform's own dashboard does that).
6. No browser-based recording (server-side ffmpeg only).
7. No multi-study/multi-site support.

## 6. User Stories (priority order)

**Experimenter**
1. Register a participant with consent status and demographics so the session is valid before it starts.
2. Pre-session checklist (camera preview, perception reachable, tablet reachable, recordings volume mounted with space, consent confirmed) so no unrecoverable session starts broken.
3. Log each DTT trial in under 10 seconds with tap/click inputs.
4. Pause/resume/stop with one click, honestly recorded in the timeline.
5. Push the next questionnaire or self-report form to the tablet.
6. Add a timestamped note at any moment.
7. Exclude a trial or session via annotation, never deletion.
8. One-click export immediately after each session.

**Participant**
9. Tablet shows only the current form.
10. Self-report sliders take under 30 seconds.

**Researcher (post hoc)**
11. Every perception event logged even when prediction is missing or confidence is low.
12. Data dictionary covers every exported column.

## 7. Requirements and Priorities

### P0: cannot run a session without these

| # | Requirement | Acceptance criteria |
|---|---|---|
| P0.1 | FastAPI + SQLite backend, core models: participants, sessions, dtt_trials, robot_events, participant_self_reports, perception_events, media_recordings, session_timeline_events, experimenter_notes, questionnaire_responses, exports | Server starts on own port as pourya; tables migrate; CRUD via /docs |
| P0.2 | Session lifecycle (start/pause/resume/stop/complete) with `scenario_type` (bst_dtt, customer_service, ...) | Timeline reconstructs full session; mid-session refresh loses nothing |
| P0.3 | Timeline event store: event_id, participant_id, session_id, timestamp_utc, session_time_ms, source, type, payload JSON | Every P0 feature writes here; ordering monotonic |
| P0.4 | Config-driven questionnaire engine with real content: demographics, ERQ (10 items, 7-pt), BFI-2-S (30 items, 5-pt) pre; RoSAS x2 (18 items, 7-pt; Trainer, Child) post; D-QEL + manipulation checks as placeholders | New/edited questionnaire is a config change only; tablet renders all instruments |
| P0.5 | DTT trial logging panel driven by protocol config: auto trial number, phase, target skill, response, correctness, prompt level, reinforcement, error correction, missed/extra steps, deviation flag, notes | Trial logs in <=10 s; lands in dtt_trials + timeline |
| P0.6 | Participant tablet route: shows exactly the experimenter-pushed form; autosaves partial responses | Real tablet over WiFi loads form; push works; refresh-safe |
| P0.7 | Self-report form: valence, arousal, confidence, frustration, engagement, perceived challenge, perceived support, cognitive load; linked to session/phase/trial; before/after robot action flag | Writes participant_self_reports + timeline |
| P0.8 | Perception adapter: polls /state/asr, /state/emotion, /state/gesture on configurable intervals; logs raw payload, source timestamp, received timestamp, confidence; logs nulls, gaps, connection failures | Events accumulate at expected rate while orchestrator up; outages are in the record; platform unaffected when orchestrator down |
| P0.9 | Robot event logging (manual form): role, utterance/action, condition, script version, payload | Lands in robot_events + timeline |
| P0.10 | Server-side recording service: backend-managed ffmpeg subprocess, v4l2 capture of recording Brio (MJPEG from camera), 1080p30, h264_nvenc (libx264 fallback) + AAC, fixed ~4-5 Mbps, progressive write to RECORDINGS_DIR, graceful stop, manifest row + timeline events, live preview frame in checklist | Start/stop from UI yields playable file, duration within 1 s of manifest; kill -9 mid-recording leaves recoverable file; failure logged, session continues |
| P0.11 | Exports: participant CSV, questionnaire responses CSV, DTT trial CSV, self-report CSV, media manifest CSV, perception events JSONL, timeline JSONL, session summary JSON, data dictionary MD | Every file loads in pandas with zero fixes |
| P0.12 | Pre-session checklist gating session start: camera preview, perception reachable, tablet reachable, recordings path is a mount with >= 3 sessions free, consent confirmed; overrides allowed but logged | Failed required check blocks start unless overridden; override in timeline |

### P1: if time permits, else fast follow

| # | Requirement |
|---|---|
| P1.1 | Session review page (read-only summary) |
| P1.2 | dtt_performance_events as fine-grained records (v1 folds into trials + timeline) |
| P1.3 | participant_identity physically separated (v1: never store names; ID only) |
| P1.4 | System health events in UI (disk trend, backend errors, recording bitrate) |
| P1.5 | Tablet validation polish, progress indicator |
| P1.6 | systemd unit files (v1 runs in tmux) |

### P2: design for, do not build

| # | Requirement | Design insurance now |
|---|---|---|
| P2.1 | WebSocket perception ingestion | Adapter is an interface; polling is one implementation |
| P2.2 | Automated robot event ingestion | robot_events takes arbitrary payload JSON + source field |
| P2.3 | Automated scoring | Scoring config slot in questionnaire schema; scores table exists |
| P2.4 | Docker Compose | All paths/ports in .env |
| P2.5 | Trial-level video bookmarking | session_time_ms + recording start timestamp make offsets computable |
| P2.6 | Multi-camera recording | media_recordings keyed by device; recording service parameterized |

## 8. Success Metrics

**Leading (rehearsals + first 3 sessions)**
- 100% of timeline events survive forced browser refresh and forced backend restart
- Full session by one experimenter, zero terminal use
- DTT trial logging median <= 10 s
- Perception events at >= 95% of expected polling intervals while orchestrator up
- 60-minute test recording playable, duration within 1 s of manifest
- All exports load in pandas/R with zero manual fixes

**Lagging (across the study)**
- Zero sessions lost to platform failure
- Zero raw-data overwrites (audited via annotations)
- Session end to backed-up export <= 5 minutes

## 9. Seven-Day Plan

Calendar (reset): Day 1 = Tue Jun 16, Day 2 = Wed Jun 17, Day 3 = Thu Jun 18, Day 4 = Fri Jun 19, Day 5 = Sat Jun 20, Day 6 = Sun Jun 21, Day 7 = Mon Jun 22. Blocking inputs (DTT phases, robot events) due end of Day 2 (Jun 17). SSD required by Day 5 (Jun 20).

| Day | Deliverable | Verification gate |
|---|---|---|
| 1 | **Hardware/network first, no code:** (a) recording Brio into server; 10-min manual ffmpeg v4l2 1080p capture (try NVENC) while perception processes the live PC stream; (b) tablet-to-server port test from the real tablet on WiFi; (c) `video` group permission; (d) record `nproc`/`df -h`; (e) order/locate the SSD; (f) heads-up message to team. Then: repo scaffold, CLAUDE.md, docs/, backend skeleton, all models | Both hardware tests pass or mitigations chosen; server runs; **data model reviewed and approved by Pourya** |
| 2 | Session lifecycle with scenario_type, timeline store, participant intake API + page | Start/pause/resume/stop via UI; timeline inspected; refresh test passes |
| 3 | DTT trial panel, notes, robot event form, live session dashboard skeleton | 10 fake trials logged in a mock session in <2 min total |
| 4 | Questionnaire engine + real configs (demographics, ERQ, BFI-2-S, RoSAS x2) + tablet route + self-report + push-to-tablet | Pre-questionnaires and 2 self-reports completed from the real tablet |
| 5 | Recording service wrapping day-1 ffmpeg command, writing to mounted SSD; perception adapter against live orchestrator | 15-min recording while raising one hand: playable file on SSD, gesture event in DB, manifest correct |
| 6 | Exports, data dictionary, seed data, pre-session checklist with mount-guard | Full dry-run rehearsal, intake to export |
| 7 | Buffer: fix findings, second rehearsal, run-book (startup order, ports, mount check, post-session backup, team coexistence) | Clean rehearsal, zero interventions |

**Scope rule:** any addition removes something or consumes day 7, explicitly.
**Cut ladder if behind (in order):** P1 items → tablet becomes second browser window on the PC turned toward participant → post-questionnaires fall back to paper/Qualtrics with IDs. Timeline, DTT logging, self-reports, perception logging, and recording are never cut.

## 10. Risks (final)

| Risk | Status | Mitigation |
|---|---|---|
| Shared root disk at 89% | **Confirmed constraint** | Dedicated SSD by day 5, mount-guard, fixed bitrate, per-session offload; dev needs no large files before day 5 |
| Tablet WiFi VLAN blocked from server subnet | Open until day 1 test | Test day 1; fallbacks: same-subnet AP, or second window on PC |
| ffmpeg/v4l2/NVENC quirks with Brio on this distro | Open until day 1 test | Day 1 manual test produces the exact command the backend wraps; command stored in config |
| Shared-server interference | Managed | Etiquette rules in section 3; heads-up to team |
| Week too short for full P0 | Managed | Cut ladder above |
| DTT protocol content not finalized | **Blocking by day 3** | Protocol is config; placeholder ships; Pourya supplies structure |
| Robot event source undecided | **Blocking by day 3** | v1 assumes manual; payload JSON + source field keep automated ingestion open |
| D-QEL / manipulation checks not finalized | Open, non-blocking | Placeholder configs; later config edit |

## 11. Open Questions

**Blocking (before day 3)**
- [Pourya] Rough DTT phases and target skills for the protocol config.
- [Pourya] Robot events: manual-only for this study, or machine-readable source to ingest?

**Non-blocking**
- [Pourya] Audio source: recording Brio's mics vs dedicated microphone (pin ALSA device either way).
- [Pourya] Self-report timing: experimenter-triggered only (v1 assumption) or also scheduled.
- [Pourya] Polling intervals (proposal: 500 ms ASR/gesture, 1 s emotion).
- [Pourya] Participant count target (sizes the SSD and backup budget).
- [Pourya/IRB] Recording file naming constraints (participant ID in filename allowed?).

## 12. Definition of Done

Ready for real participants when a full rehearsal (intake, demographics + ERQ + BFI-2-S on tablet, live session with 10+ trials, 2 self-reports, live perception logging, server-side recording to the SSD, RoSAS x2 post, export) completes with zero data loss, zero terminal interventions, a playable recording, and all exports validated in pandas, twice in a row.