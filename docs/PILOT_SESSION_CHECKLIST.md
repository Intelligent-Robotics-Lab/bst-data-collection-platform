---
title: "BST Pilot Session Checklist"
subtitle: "Operator run sheet — robot-mediated BST/DTT study"
---

# BST Pilot Session Checklist

**Participant ID:** ______________  **Session ID:** ______________
**Date:** ____________  **Operator:** ____________  **Start / End:** _______ / _______

> **Sessions are unrepeatable.** Every box in Part A exists because a real pilot
> lost data. Do not tick a box you have not actually verified.

---

## A. Before the participant arrives (T-30 min)

### A1. Bring the backend up correctly

- [ ] Reconnect SSH **fresh** (group membership only applies at login).
- [ ] Confirm the `audio` group is active — without it, **recordings have no sound**:

  ```bash
  groups | tr ' ' '\n' | grep -x audio      # must print: audio
  arecord -l | grep -i brio                 # must list: card 1: BRIO
  ```

- [ ] Confirm the two enable flags in `.env`. **If either is missing, that data is
      silently never captured** (no error, no rows):

  ```bash
  cd ~/projects/bst-data-collection-platform
  grep -E "^(RECORDING_ENABLED|PERCEPTION_ENABLED)=" .env
  # must show BOTH:  RECORDING_ENABLED=true   PERCEPTION_ENABLED=true
  ```

- [ ] Start the backend **as `pourya`** (not root), from the fresh login:

  ```bash
  cd ~/projects/bst-data-collection-platform/backend && source .venv/bin/activate
  uvicorn app.main:app --host 0.0.0.0 --port 8080
  ```

- [ ] Backend healthy: `curl -s localhost:8080/health` → `{"status":"ok"}`
- [ ] Running as the right user: `ps -o user= -p $(ss -ltnp | grep :8080 | grep -o 'pid=[0-9]*' | cut -d= -f2)` → `pourya`

### A2. Verify the capture chain (do not assume)

- [ ] Camera present: `ls /dev/video0`
- [ ] Perception orchestrator healthy: `curl -s -o /dev/null -w "%{http_code}" localhost:8000/health` → `200`
- [ ] Free disk for recordings (~2.5 GB per hour at 5 Mbps): `df -h ~/projects/bst-data-collection-platform/data`
- [ ] Console loads: `http://<server>:8080/ui/console.html`
- [ ] Tablet loads: `http://<server>:8080/ui/tablet.html`

### A3. Robot (BST) client

- [ ] `logic/bst.py` → `PLATFORM_BASE` points at **this** server and port (`http://141.210.88.210:8080`).
- [ ] Furhat reachable / robot program loaded.

### A4. Study area & consent

- [ ] Consent completed and media-recording consent captured.
- [ ] Study area set up; tablet charged and within reach of the participant.

---

## B. Create the session (Console — Stage 1: Setup)

- [ ] Enter Participant ID and Session ID. **This Session ID is canonical.**
- [ ] Set **PB order group** (1/2/3) and **Support condition** (supportive / neutral).
- [ ] Click **Create & start session**.

> **Alignment is mandatory.** When you launch the robot client it will prompt you.
> Type the **same three values**, or the two systems will disagree about the design:

| Console (platform)        | Robot client prompt                       |
| ------------------------- | ----------------------------------------- |
| Session ID                | `Session_id (match the platform exactly)` |
| PB order group (1/2/3)    | `Configuration (1, 2, or 3)`              |
| Support condition         | `Feedback style (supportive or neutral)`  |

- [ ] Recording started: **Recordings** tab shows a `recording` status pill.

---

## C. Onboarding (Console — Stage 2)

Push each **pre**-questionnaire to the tablet; participant completes it; the console
pill flips to **submitted**.

- [ ] `demographics` submitted
- [ ] `erq` submitted
- [ ] `bfi2s` submitted

---

## D. Live session (Console — Stage 3)

- [ ] Start the robot client: `cd ~/projects/bst-study && python main.py`
- [ ] `register` succeeded (console header shows the matching condition).

The robot pauses at **15 gated checkpoints**. At each one the tablet **auto-shows**
the self-report; when the participant submits, the robot proceeds.

- [ ] 3 stage baselines: `tutorial`, `instruction`, `modeling`
- [ ] 6 loops × 2 checkpoints (`post_kid_response`, `post_feedback`) = 12
- [ ] **Total: 15 / 15 self-reports collected**

**Human fidelity scoring** — score each loop *as it happens*:

- [ ] SD1 scored + marked complete
- [ ] SD2 scored + marked complete
- [ ] SD3 scored + marked complete
- [ ] SD4 scored + marked complete
- [ ] SD5 scored + marked complete
- [ ] SD6 scored + marked complete

**Override** (the gate safety valve) — use only if the tablet genuinely fails:

- [ ] If used: reason entered. Overridden checkpoints are recorded as
      **skipped-by-override**, not missing-by-error. Note them here:
      ______________________________________________

---

## E. Post-session (Console — Stage 4)

- [ ] `rosas_trainer` submitted
- [ ] `rosas_child` submitted
- [ ] `dqel` submitted
- [ ] `manipulation_checks` submitted
- [ ] Qualitative note captured (if any)
- [ ] Participant debriefed; questions answered; compensation handled

---

## F. Closeout (Console — Stage 5)

- [ ] Open **Session completeness** — read it *while the participant is still here*.
- [ ] Fix anything missing (a post-questionnaire can still be pushed from Stage 4).
- [ ] Click **Review & finish session** → stops recording + perception, re-checks.
- [ ] Review the summary, then **Confirm & finalize**.
- [ ] "✓ Session finished" shown, with the export location.

---

## G. Verify before the participant leaves (don't trust — check)

Set `SID` and run:

```bash
cd ~/projects/bst-data-collection-platform
SID=<your_session_id>
sqlite3 data/bst.db "
 SELECT 'self_reports      ', count(*) FROM participant_self_reports WHERE session_id='$SID'
 UNION ALL SELECT 'gates (15)        ', count(*) FROM sync_gates            WHERE session_id='$SID'
 UNION ALL SELECT 'overridden        ', count(*) FROM sync_gates            WHERE session_id='$SID' AND closed_by='override'
 UNION ALL SELECT 'questionnaires (7)', count(DISTINCT questionnaire_key) FROM questionnaire_responses WHERE session_id='$SID' AND is_partial=0
 UNION ALL SELECT 'fidelity (6)      ', count(*) FROM fidelity_scores       WHERE session_id='$SID'
 UNION ALL SELECT 'perception (>0!)  ', count(*) FROM perception_events     WHERE session_id='$SID'
 UNION ALL SELECT 'recording         ', count(*) FROM media_recordings      WHERE session_id='$SID';"
```

| Item                    | Expected                        | ✓ |
| ----------------------- | ------------------------------- | - |
| Self-reports            | **15**                          |   |
| Sync gates              | **15** (note any overrides)     |   |
| Questionnaires          | **7** finalized (3 pre, 4 post) |   |
| Fidelity scores         | **6**, all `complete`           |   |
| **Perception events**   | **> 0** (≈9 rows/sec)           |   |
| Recording status        | `completed`                     |   |
| DTT trials              | `0` — **expected** (no panel)   |   |

- [ ] Recording is real video **with audio**, and duration ≈ session length:

  ```bash
  F=$(sqlite3 data/bst.db "SELECT file_path FROM media_recordings WHERE session_id='$SID';")
  ffprobe -v error -show_entries format=duration -show_entries stream=codec_type,codec_name -of csv "$F"
  # expect: a video (h264) stream AND an audio (aac) stream, plus a duration
  ```

- [ ] Export folder written: `ls -d data/exports/$SID/*/`
- [ ] Completion backup written: `ls -t data/backups/*completion* | head -1`
- [ ] Rewatch the video in the console's **Recordings** tab; **Save As** a copy to
      the archive drive (the original is never moved).

---

## H. Hard rules

- **Never `kill -9` the backend while recording.** Use Ctrl+C / SIGTERM so the mp4
  is finalized. (If it does crash: just restart — startup reconciliation SIGINTs the
  orphaned recorder and rescues the file.)
- **Never move or delete anything in `data/recordings/`.** Use **Save / Save As**,
  which only ever copies.
- **Never run a second backend against the real `data/bst.db`.** Use a temp
  `DB_PATH` for any testing.
- **A recording that reads `failed` means there is no usable video** — check the
  ffmpeg log in `data/logs/` before continuing.

---

## I. If something goes wrong

| Symptom                              | Do this                                                                 |
| ------------------------------------ | ----------------------------------------------------------------------- |
| Tablet doesn't show the self-report  | Check the gate is open in Stage 3; re-push; override only as last resort |
| Recording pill shows `failed`        | Check `data/logs/ffmpeg_*.log`; session continues — video is lost        |
| Perception shows 0 rows              | `PERCEPTION_ENABLED=true` in `.env`? orchestrator `:8000/health` = 200?  |
| Robot won't proceed past a gate      | Confirm the self-report submitted; else override (recorded + logged)     |
| Backend died mid-session             | Restart it — the recording is reconciled and the file rescued            |
| Console shows a stale session        | Finish it via Closeout; never edit the database by hand                  |

---

## J. Sign-off

- [ ] All Part G checks pass (or exceptions written down below).
- [ ] Recording copy archived off the server.
- [ ] Tablet reset to idle; area reset for next participant.

**Exceptions / incidents:**

______________________________________________________________________

______________________________________________________________________

**Operator signature:** ____________________  **Date:** ____________
