# CLAUDE.md

## Project
BST Data Collection Platform: a local-first web app for an in-person robot-mediated
BST/DTT human-robot interaction study. One experimenter runs a full session; a
participant tablet collects self-reports; a server-attached camera records raw A/V;
behavioral signals are ingested from an existing HRI perception platform. Every
session is unrepeatable, so zero data loss and raw-data immutability are paramount.

## Stack
- Backend: Python FastAPI + SQLite
- Frontend: React + Vite
- Local file storage for recordings, exports, logs, session timelines
- YAML/JSON configs for questionnaires, DTT protocols, study conditions
- No Docker for v1 (runs as plain processes; .env keeps containerizing easy later)

## Source of truth (read these in docs/)
- requirements.md   original spec (note the "Deltas" section; some original points superseded)
- product_plan.md   v1.3, governs SCOPE and the Jun 16-22 SCHEDULE
- PRD.md            governs ACCEPTANCE CRITERIA
- perception_integration.md   contract for the perception adapter (P0.8)
- sprint_plan.md    daily gates
Where documents conflict: product_plan governs scope/schedule, PRD governs acceptance.

## Hard rules (research integrity)
- NEVER overwrite raw records. Corrections, exclusions, scoring = annotations/derived rows only.
- Participant IDs only in research tables. No participant names in research data.
- No copyrighted questionnaire item text beyond what I provide; configs use stable item IDs.
- Every significant event also writes a session_timeline_events row (UTC + session_time_ms).
- Perception data is logged even when missing/low-confidence; outages are logged rows, not gaps.
- Validate required fields; autosave where reasonable; never let a session "complete" with
  required steps missing.

## Runtime environment (verified Day 1)
- Target: native Linux server (Ubuntu 22.04), runs as user pourya, not root
- Recording: ffmpeg 4.4 + h264_nvenc, pix_fmt yuv420p, ~5 Mbps, 1080p30
  - ffmpeg 4.4 syntax: use -vsync passthrough, NOT -fps_mode (5.x only)
  - Recording camera: /dev/video0 (MJPEG input)
  - Audio: hw:CARD=BRIO,DEV=0 (pin by name, not hw:4,0), add -thread_queue_size 1024
  - Stop ffmpeg by sending 'q' to stdin, never kill -9, so the mp4 trailer writes
- Do not introduce WSL, Docker, or Linux/POSIX-only path assumptions in app code; use pathlib
- Never touch the perception platform's compose stack or ports

## Working style
- Full files when implementing, not patch fragments.
- Work in phases; one daily gate at a time. Do not run ahead to later phases.
- Flag ambiguities as questions instead of guessing.
- All paths and ports come from .env; nothing hardcodes localhost or absolute paths.
- Commit after each gate passes.

## Conventions
- Preferred name: Pourya. No em dashes in writing.