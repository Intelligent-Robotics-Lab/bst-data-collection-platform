# Requirements (Original Base Prompt)

> This is the original specification for the platform, preserved verbatim as the source-of-truth requirements. Where this document and `product_plan.md` (v1.3) or `PRD.md` differ, the product plan governs scope and schedule and the PRD governs acceptance criteria. This file is retained so the original intent is never lost.

You are Claude Code acting as a senior full-stack software architect and research software engineer.

I am building a repository named `bst-data-collection-platform`.

This project is a local-first web application for an in-person social human-robot interaction study. The study involves robot-mediated Behavior Skills Training, BST, for Discrete Trial Training, DTT. The platform should help researchers manage participants, run experimental sessions, collect questionnaires, log DTT performance, record webcam video/audio, ingest behavioral signals from an external perception framework, collect self-reported emotional states during the interaction, and export clean research data.

This should be built as a local web app, not a public online website and not a traditional desktop app. It should run on the experiment PC and open in a browser through localhost.

Use this default architecture unless the existing repo already has a different structure:

* Backend: Python FastAPI
* Database: SQLite for MVP
* Frontend: React with Vite
* Local file storage for recordings, logs, exports, and session timelines
* JSON or YAML configuration files for questionnaires, DTT protocols, and study conditions
* Optional Docker Compose setup for easier deployment later

The external MVP perception framework already exists and should be treated as a separate signal source. Do not rebuild or replace the perception framework. This platform should connect to it through a configurable adapter. For the MVP, implement a mock perception ingestion service first, then make it easy to replace with real API polling, WebSocket subscription, or file-based ingestion later.

## Important research requirements

### 1. Before robot interaction

The platform should support participant intake and pre-study measures.

Participant profile fields should include: Participant ID, Session ID, Consent status, Media recording consent status, Demographics, Prior robot experience, Prior teaching experience, Prior ABA/BST/DTT/autism intervention/caregiving/clinical training experience, Baseline confidence, Baseline emotional state, ERQ questionnaire, BFI-2-S questionnaire.

Participant identity, if implemented, should be stored separately from research data. The main research tables should use participant IDs, not names.

Do not include copyrighted questionnaire item text unless I provide it. Use placeholder item IDs and configurable questionnaire schemas so I can add the approved item text later.

### 2. During robot interaction

The platform should support a live experimental session. It should collect: raw webcam video and audio from the experiment PC; DTT trial-level performance logs; experimenter notes; robot events; participant self-reported emotional states; time-stamped behavioral signals from the external perception framework.

For webcam recording, use browser MediaRecorder if feasible for the MVP. Store recording metadata even if the actual recording implementation is initially limited. [SUPERSEDED by product plan: recording is a server-side ffmpeg service capturing a dedicated Brio on the lab server, not browser MediaRecorder.]

Each media recording should track: Session ID, Participant ID, Recording type, Device name if available, Start timestamp, Stop timestamp, File path, Recording status, Notes or errors.

For DTT trial logging, each trial should track: Trial number, DTT phase, Target skill, Instruction or discriminative stimulus, Participant response, Response correctness, Response latency if available, Prompt level, Whether reinforcement was delivered, Whether error correction was delivered, Missed protocol steps, Extra or incorrect protocol steps, Protocol deviation flag, Experimenter notes.

For robot event logging, each event should track: Robot role (Trainer or Child), Robot utterance or action, Script version, Robot behavior condition, Timestamp, Payload JSON.

For participant self-reported emotional states, support simple Likert or slider-based input for: Valence, Arousal, Confidence, Frustration, Engagement, Perceived challenge, Perceived support, Cognitive load. [EXTENDED by product plan and data frame: add Dominance to support the PAD self-report triple.] Self-reports should be linked to the current session, phase, and trial, and indicate whether they occurred before or after a robot action.

For perception events, support: Transcript events, Emotion prediction events, Gesture events, Face detection status, Confidence scores, Source timestamp, Local received timestamp, Raw payload JSON. Perception data should be logged even when the prediction is missing or confidence is low. Signal quality is part of the research record.

### 3. After robot interaction

Post-study measures should include placeholders for: D-QEL, RoSAS for Trainer robot, RoSAS for Child robot, Manipulation checks, Perceived robot support, Perceived robot challenge, Task engagement or flow, Open-ended feedback. Do not include official questionnaire item text unless I provide it.

### 4. Core system behavior

The platform must create a synchronized session timeline. Every important event should be written to a timeline/event store with: Event ID, Participant ID, Session ID, Timestamp UTC, Monotonic session time in milliseconds if possible, Event source, Event type, Payload JSON.

The platform should preserve raw records. Corrections, scoring updates, exclusions, and notes should be stored as annotations or derived records, not by overwriting raw data.

The platform should support: Session start, pause, resume, stop, completion; Trial exclusion; Session exclusion; Manual experimenter notes; System health logs; Export generation.

### 5. Required data models

Design the database with models for at least: participants, participant_identity (optional, separate), sessions, study_conditions, questionnaires, questionnaire_responses, questionnaire_scores, dtt_protocols, dtt_phases, dtt_trials, dtt_performance_events, robot_events, participant_self_reports, perception_events, media_recordings, session_timeline_events, experimenter_notes, system_health_events, exports.

### 6. Required user interface screens

Home/study dashboard, Participant intake, Pre-interaction questionnaires, Session setup checklist, Camera and microphone check, Perception framework connection check, Live session dashboard, DTT trial logging panel, Participant self-report screen, Post-interaction questionnaires, Session review, Export data page.

The live session dashboard should show: Current participant ID, Current session ID, Current phase, Current trial, Recording status, Perception connection status, Latest transcript, Latest emotion prediction, Face detected status, Manual note button, Pause/Resume/Stop buttons.

### 7. Export requirements

Implement export functions for: participant-level CSV, questionnaire response CSV, questionnaire score CSV, DTT trial-level CSV, DTT performance event CSV, participant self-report CSV, media manifest CSV, perception events JSONL, full session timeline JSONL, session summary JSON, data dictionary Markdown file. Exports should be analysis-ready for Python, R, SPSS, JASP, Excel, or similar tools.

### 8. Reliability and research integrity

Validate required fields; autosave form responses where reasonable; log backend errors, recording failures, perception connection failures; prevent accidental completion of a session when required steps are missing; keep raw data separate from derived data; include protocol version, questionnaire version, robot script version, and platform version where possible; make data folders predictable and easy to back up.

### 9. Suggested repository structure

```text
bst-data-collection-platform/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
├── data/
│   ├── recordings/
│   ├── exports/
│   ├── logs/
│   └── sessions/
├── configs/
│   ├── questionnaires/
│   ├── dtt_protocols/
│   └── study_conditions/
├── docs/
├── .env.example
├── docker-compose.yml
├── README.md
└── LICENSE
```

### 10. MVP implementation target

FastAPI backend; SQLite database; basic React frontend; participant creation; session creation; placeholder ERQ and BFI-2-S forms; manual DTT trial logging; participant self-report form; mock perception event ingestion; basic media recording metadata; post-questionnaire placeholders for D-QEL and RoSAS Trainer/Child; session timeline JSONL writing; basic CSV and JSONL exports; README setup instructions; `.env.example`; sample seed data.

### 11. Development process

Start by inspecting the current repository structure. Then provide: a concise architecture summary, the planned folder structure, the database model design, and the MVP implementation plan. After that, begin implementing the MVP files. Work incrementally. Keep the code clean and readable. Do not over-engineer. Prefer a working local MVP over a complex architecture.

When implementation is done, provide: how to run the backend, how to run the frontend, how to create sample data, how to test the main study flow, how to export data, what is implemented, and what is intentionally stubbed for future development.

---

## Deltas from the original (decided during planning)

These supersede the original where noted; see `product_plan.md` v1.3 for full rationale:

1. **Runtime is the lab server, not the experiment PC.** Backend, frontend, recording, and the existing perception platform all run on one Linux server in the experiment room. The Windows PC is a pure GStreamer edge client. The tablet is a participant client over WiFi.
2. **Recording is server-side ffmpeg, not browser MediaRecorder.** Verified Day 1: ffmpeg 4.4 + h264_nvenc, 1080p30, yuv420p, AAC audio from the Brio (`hw:CARD=BRIO,DEV=0`). Stop via `q` to stdin, never kill.
3. **No Docker for v1.** Runs as user `pourya` in plain processes; `.env` keeps containerization easy later.
4. **No browser MediaRecorder, no auth, no automated scoring, no perception visualization** (the perception platform has its own dashboard).
5. **Self-report gains Dominance** (PAD triple) and **sessions gain scenario_type, support_condition, pb_order_group**, with per-loop `function_class` on self-reports, to support the affect-regulation data frame and analysis.
6. **Perception ingestion is real polling against the co-located orchestrator** (see `perception_integration.md`), behind a `PerceptionSource` interface so a future WebSocket/LSL push can replace it.