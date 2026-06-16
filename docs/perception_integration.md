# Perception Integration Spec

**Purpose:** Defines how the BST Data Collection Platform ingests behavioral signals from the existing HRI Perception Platform (the "orchestrator"). This is the contract the Day 5 perception adapter (P0.8) implements, and it informs the `perception_events` data model in Phase 0.

**Golden rule:** This platform is a read-only consumer of the perception orchestrator. It never modifies, restarts, or reconfigures the perception stack. It polls, logs, and gets out of the way. If the orchestrator is down, this platform keeps running and logs the gap.

---

## 1. Topology

- The perception orchestrator runs on the **same server** as this platform (localhost), already serving its own debug dashboard and state/metrics endpoints.
- The orchestrator ingests a live video/audio stream sent from the Windows PC client via GStreamer.
- This platform reaches the orchestrator over localhost HTTP. Base URL is configurable in `.env` (e.g., `PERCEPTION_BASE_URL=http://localhost:8000`).

## 2. Endpoints consumed

State endpoints return the latest result snapshot per task. Metrics endpoints return latency/processing snapshots. The adapter polls the state endpoints; metrics are optional and logged when present.

| Task | State endpoint | Metrics endpoint | Default poll interval |
|---|---|---|---|
| ASR (speech) | `/state/asr` | `/metrics/live/asr` | 500 ms |
| Emotion | `/state/emotion` | `/metrics/live/emotion` | 1000 ms |
| Gesture | `/state/gesture` | `/metrics/live/gesture` | 500 ms |
| Health (liveness) | `/health` | — | 5000 ms |

Debug image endpoints exist (`/debug/image/input`, `/debug/image/annotated`, `/debug/image/gesture`) but are NOT polled into the research record in v1. They may be sampled later for QA. The pre-session checklist may fetch one frame to confirm the perception camera is live.

All intervals are configurable per task in `perception_config` (see section 6). Defaults reflect the proposal in the product plan: dense for ASR/gesture, lighter for emotion.

## 3. Expected payload shapes

These shapes come from the perception platform's documented output conventions. The adapter must NOT assume every field is present; it stores the full raw payload and extracts a known subset. Missing or null fields are logged as-is (signal quality is data).

### 3.1 Gesture (`/state/gesture`)
```json
{
  "timestamp_utc": "...",
  "session_id": "...",
  "frame_id": 123,
  "source_id": "live_client",
  "task": "gesture_recognition",
  "backend_name": "gesture_holistic_events",
  "backend_mode": "real",
  "instant_gesture": "one_hand_up",
  "detected_gesture": "one_hand_up",
  "confidence": 1.0,
  "motion": { "dx": 0.001, "dy": -0.002, "nod_state": null, "shake_state": null,
              "one_hand_up_counter": 0, "cooldown_active": true, "display_hold_active": true },
  "last_action": "one_hand_up",
  "face_detected": true,
  "latency_ms": 23.4,
  "warnings": [],
  "error": null,
  "meta": { "input_kind": "frame", "frame_shape": [480,640,3],
            "one_hand_up": true, "left_hand_up": false, "right_hand_up": true }
}
```
Fields the adapter extracts to columns: `task`, `backend_name`, `detected_gesture`, `instant_gesture`, `confidence`, `face_detected`, `latency_ms`, `timestamp_utc` (source time), and the `meta.one_hand_up/left_hand_up/right_hand_up` booleans. Everything (including `motion`) is preserved in the raw payload JSON.

### 3.2 Emotion / affect (`/state/emotion`)
The active emotion backend may be `affect_hse_va`, which returns both categorical and continuous affect:
```json
{
  "task": "affect_dimensions",
  "dominant_label": "...",
  "confidence": 0.0,
  "scores": { "...": 0.0 },
  "valence": 0.0,
  "arousal": 0.0,
  "quadrant": "...",
  "latency_ms": 0.0
}
```
Fields extracted: `task`, `dominant_label`, `confidence`, `valence`, `arousal`, `quadrant`, `latency_ms`. The full `scores` vector is preserved in raw payload (and is the basis for the future derived-dominance computation noted in the analysis plan). Note: this stream provides VALENCE and AROUSAL only; dominance is not produced by the model and is captured via self-report, with an optional post-hoc derivation from `scores`.

### 3.3 ASR (`/state/asr`)
Returns the latest transcript snapshot. Exact shape is backend-dependent (`asr_riva` or `asr_whisper`), but the adapter expects at least a transcript string and treats empty/null transcripts as valid logged events (silence and short chunks are part of the record). The full payload is preserved; the adapter extracts the transcript text, any confidence if present, and `latency_ms` if present.

### 3.4 Health (`/health`)
Used only for liveness. Any non-200 or unreachable result flips the perception connection status to "down" and starts logging an outage interval until it recovers.

## 4. What gets stored: `perception_events`

Every successful poll that returns a payload writes one row. Polls that fail (orchestrator down, timeout) write a gap/outage marker, not silence.

Proposed columns (Phase 0 to finalize types):
- `event_id` (PK)
- `session_id` (FK), `participant_id` (FK)
- `task` (asr | emotion | gesture)
- `backend_name` (nullable)
- `source_timestamp_utc` (from payload, nullable)
- `received_timestamp_utc` (this platform's clock, always set)
- `session_time_ms` (monotonic session time at receipt)
- `detected_label` (gesture name, dominant emotion, or null)
- `confidence` (nullable)
- `valence`, `arousal` (nullable; emotion only)
- `transcript` (nullable; asr only)
- `face_detected` (nullable)
- `latency_ms` (nullable)
- `connection_status` (ok | degraded | down)
- `raw_payload` (JSON, full response)

Every row also emits a `session_timeline_events` entry (source=perception) so the unified timeline carries perception alongside trials, self-reports, and robot events.

## 5. Adapter behavior (Day 5, P0.8)

1. One async poller per task, each on its configured interval, started when a session starts and stopped when it stops.
2. Each poll: GET the state endpoint with a short timeout (e.g., 2 s). On success, parse + store. On failure, increment a failure counter and store a gap marker; do not crash the poller.
3. The platform's session runs independently of perception availability. Perception down != session down.
4. Connection status surfaced on the live dashboard and gated in the pre-session checklist (perception reachable = green).
5. Timestamps: store BOTH the payload's source timestamp and this platform's receive timestamp. Since both machines' relevant clock for the research record is the server clock (perception and this platform are co-located), receive time is the canonical timeline anchor; source time is secondary.
6. Rate: log actual achieved poll rate; success metric is >= 95% of expected intervals while the orchestrator is up.

## 6. Configuration (`.env` + perception_config)

```
PERCEPTION_BASE_URL=http://localhost:8000
PERCEPTION_POLL_MS_ASR=500
PERCEPTION_POLL_MS_EMOTION=1000
PERCEPTION_POLL_MS_GESTURE=500
PERCEPTION_HEALTH_MS=5000
PERCEPTION_HTTP_TIMEOUT_MS=2000
```
Per-task enable/disable flags so a researcher can log only the tasks a given study needs.

## 7. Future path (P2.1): WebSocket / push ingestion

Polling is v1 because it is simple and the orchestrator already exposes state endpoints. The adapter is written behind an interface (`PerceptionSource`) with one method to yield events; polling is one implementation. A future WebSocket or LSL-based push implementation can replace it without touching the storage layer or the data model. This also aligns with the LSL-ready design note from the competitive analysis: keep the event/marker layer abstract.

## 8. Open items to confirm against the live orchestrator (Day 5)

- Exact ASR payload shape and field names for the active backend (`asr_riva` vs `asr_whisper`).
- Whether `/state/*` returns a stable snapshot or only changes on new results (affects how to detect duplicate vs fresh events; may need a frame_id / timestamp dedupe).
- Confirm the orchestrator's actual port (assumed 8000) and whether any path prefix is in use.
- Whether emotion endpoint currently serves `affect_hse_va` (VA-capable) or a categorical-only backend, since that determines if valence/arousal columns populate.