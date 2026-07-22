"""Session finish / completeness-check tests (Operator Console closeout).

Covers the read-only completeness report that guards finalizing an unrepeatable
session: gated self-report accounting (collected / overridden / open / not_fired),
robustness to the gate's lazy-close (a collected self-report counts even if the
gate row is still open), questionnaire submit-vs-missing, recording status,
trials, and the overall 'ready' flag.
"""

from app.models.questionnaire import QuestionnaireResponse
from app.models.signals import MediaRecording


def _session(client, protocol_id, sid="FN_S1", pid="FNP", group=1, support=1):
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={
            "session_id": sid,
            "participant_id": pid,
            "scenario_type": "bst_dtt",
            "protocol_id": protocol_id,
            "support_condition": support,
            "pb_order_group": group,
        },
    )
    client.post(f"/sessions/{sid}/start")  # generates dtt_loops 1..6
    return sid, pid


def _readiness(client, sid):
    r = client.get(f"/sessions/{sid}/finish-readiness")
    assert r.status_code == 200, r.text
    return r.json()


def _insert(_session_factory, obj):
    db = _session_factory()
    try:
        db.add(obj)
        db.commit()
    finally:
        db.close()


def _close_all_gates(client, sid):
    """Drive a full gated session: 3 stage baselines + 6 loops x 2 checkpoints."""
    for stage in ("tutorial", "instruction", "modeling"):
        client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": stage})
        client.post(
            f"/sessions/{sid}/self-reports",
            json={"phase": stage, "timepoint": "post", "function_class": "baseline", "pleasure": 0, "arousal": 0, "dominance": 0, "emotion_category": "neutral"},
        )
    for loop in range(1, 7):
        client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": loop})
        client.post(
            f"/sessions/{sid}/self-reports",
            json={"loop_index": loop, "phase": "rehearsal", "timepoint": "pre", "function_class": "not_applicable", "pleasure": 0, "arousal": 0, "dominance": 0, "emotion_category": "neutral"},
        )
        client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": loop})
        client.post(
            f"/sessions/{sid}/self-reports",
            json={"loop_index": loop, "phase": "feedback", "timepoint": "post", "function_class": "not_applicable", "pleasure": 0, "arousal": 0, "dominance": 0, "emotion_category": "neutral"},
        )


# --- gated self-reports ------------------------------------------------------

def test_fresh_session_all_gated_missing(client, protocol_id):
    sid, _ = _session(client, protocol_id)
    rep = _readiness(client, sid)
    sr = rep["self_reports"]
    assert sr["expected"] == 15
    assert sr["collected"] == 0
    assert sr["not_fired"] == 15
    assert len(sr["missing"]) == 15
    # recording is disabled by default (RECORDING_ENABLED=false) -> reported as
    # 'disabled' (an intentional config), not a failure, and it does not block.
    assert rep["recording"]["status"] == "disabled"
    assert rep["recording"]["ok"] is True
    # no recording *alarm* (the 'still running' note mentions recording/perception
    # but is not a recording-capture warning)
    assert not any("recording row" in w or "recording status" in w for w in rep["warnings"])
    assert rep["ready"] is False  # still not ready: 15 gated self-reports missing
    assert any("missing" in w for w in rep["warnings"])


def test_collected_overridden_open_accounting(client, protocol_id):
    sid, _ = _session(client, protocol_id, group=1)
    # collected: stage tutorial baseline satisfied by a self-report
    client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": "tutorial"})
    client.post(
        f"/sessions/{sid}/self-reports",
        json={"phase": "tutorial", "timepoint": "post", "function_class": "baseline", "pleasure": 0, "arousal": 0, "dominance": 0, "emotion_category": "neutral"},
    )
    # overridden: loop 6 post_feedback opened then overridden (intentional skip)
    client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": 6})
    client.post(
        f"/sessions/{sid}/sync/override",
        json={"scope": "loop", "loop_index": 6, "checkpoint": "post_feedback",
              "operator": "op1", "reason": "tablet froze"},
    )
    # open: loop 2 post_kid_response opened and left waiting
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 2})

    sr = _readiness(client, sid)["self_reports"]
    assert sr["collected"] == 1
    assert sr["overridden"] == 1
    assert sr["open"] == 1
    assert sr["not_fired"] == 12
    assert "loop:2:post_kid_response" in sr["gates_open"]
    assert "stage:tutorial:baseline" not in sr["missing"]   # collected
    assert "loop:2:post_kid_response" in sr["missing"]       # open == needs attention
    assert "loop:6:post_feedback" not in sr["missing"]       # overridden != missing


def test_collected_even_when_gate_still_open(client, protocol_id):
    """Robustness: a self-report was submitted but the robot never re-polled
    go-ahead, so the gate row is still 'open'. It must count as collected, not
    missing."""
    sid, _ = _session(client, protocol_id, group=1)
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 3})
    client.post(
        f"/sessions/{sid}/self-reports",
        json={"loop_index": 3, "phase": "rehearsal", "timepoint": "pre", "function_class": "not_applicable", "pleasure": 0, "arousal": 0, "dominance": 0, "emotion_category": "neutral"},
    )
    # deliberately do NOT poll go-ahead, so the gate stays open in the DB
    sr = _readiness(client, sid)["self_reports"]
    assert sr["collected"] == 1
    assert "loop:3:post_kid_response" not in sr["missing"]


# --- questionnaires ----------------------------------------------------------

def test_questionnaire_submitted_vs_missing(client, protocol_id, questionnaires, _session_factory):
    sid, pid = _session(client, protocol_id)
    pre = client.get("/questionnaires", params={"timepoint": "pre"}).json()
    assert pre, "expected pre questionnaires registered"
    key, ver = pre[0]["questionnaire_key"], pre[0]["version"]

    assert key in _readiness(client, sid)["questionnaires"]["missing"]

    _insert(_session_factory, QuestionnaireResponse(
        session_id=sid, participant_id=pid, questionnaire_key=key,
        questionnaire_version=ver, item_id="i1", timepoint="pre", is_partial=0))

    rep = _readiness(client, sid)
    assert key not in rep["questionnaires"]["missing"]
    assert any(q["key"] == key and q["submitted"] for q in rep["questionnaires"]["pre"])


def test_draft_response_not_counted_as_submitted(client, protocol_id, questionnaires, _session_factory):
    sid, pid = _session(client, protocol_id)
    pre = client.get("/questionnaires", params={"timepoint": "pre"}).json()
    key, ver = pre[0]["questionnaire_key"], pre[0]["version"]
    _insert(_session_factory, QuestionnaireResponse(
        session_id=sid, participant_id=pid, questionnaire_key=key,
        questionnaire_version=ver, item_id="i1", timepoint="pre", is_partial=1))  # draft
    assert key in _readiness(client, sid)["questionnaires"]["missing"]


# --- recording ---------------------------------------------------------------

def test_recording_completed_is_ok(client, protocol_id, _session_factory):
    sid, _ = _session(client, protocol_id)
    _insert(_session_factory, MediaRecording(session_id=sid, file_path="/tmp/x.mp4", status="completed"))
    rec = _readiness(client, sid)["recording"]
    assert rec["status"] == "completed" and rec["ok"] is True


def test_recording_failed_is_flagged(client, protocol_id, _session_factory):
    sid, _ = _session(client, protocol_id)
    _insert(_session_factory, MediaRecording(session_id=sid, file_path="/tmp/x.mp4", status="failed"))
    rep = _readiness(client, sid)
    assert rep["recording"]["ok"] is False
    assert any("recording status" in w for w in rep["warnings"])


def test_recording_enabled_but_no_row_is_flagged(client, protocol_id, monkeypatch):
    # When recording is ENABLED but no row exists, that is a real anomaly (the
    # service always writes a row when on) -> status 'none' + a warning. Create
    # the session WITHOUT starting it, so no real ffmpeg is spawned in the test.
    from app.core.config import settings

    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    client.post("/participants", json={"participant_id": "REN"})
    client.post("/sessions", json={
        "session_id": "REN_S1", "participant_id": "REN", "scenario_type": "bst_dtt",
        "protocol_id": protocol_id, "support_condition": 1, "pb_order_group": 1,
    })
    rep = _readiness(client, "REN_S1")  # never started -> no recording attempt/row
    assert rep["recording"]["status"] == "none"
    assert rep["recording"]["ok"] is False
    assert any("recording" in w for w in rep["warnings"])


def test_zero_trials_is_not_a_warning(client, protocol_id):
    # No trial-entry panel in the console workflow -> 0 trials is informational,
    # never a "needs attention" warning.
    sid, _ = _session(client, protocol_id)
    rep = _readiness(client, sid)
    assert rep["trials"]["count"] == 0
    assert not any("trial" in w.lower() for w in rep["warnings"])


# --- overall readiness -------------------------------------------------------

def test_ready_true_when_everything_captured(client, protocol_id, questionnaires, _session_factory):
    sid, pid = _session(client, protocol_id)
    _close_all_gates(client, sid)

    # a DTT trial logged (so the completeness view has no advisory notes either)
    client.post(f"/sessions/{sid}/trials", json={
        "loop_index": 1, "sd_id": "sd_1", "phase_key": "rehearsal",
        "target_skill": "manding", "response_correctness": "correct",
        "reinforcement_delivered": True, "error_correction_delivered": False,
    })

    # submit every registered pre/post questionnaire (one finalized item each)
    for tp in ("pre", "post"):
        for q in client.get("/questionnaires", params={"timepoint": tp}).json():
            _insert(_session_factory, QuestionnaireResponse(
                session_id=sid, participant_id=pid, questionnaire_key=q["questionnaire_key"],
                questionnaire_version=q["version"], item_id="i1", timepoint=tp, is_partial=0))

    _insert(_session_factory, MediaRecording(session_id=sid, file_path="/tmp/x.mp4", status="completed"))
    client.post(f"/sessions/{sid}/stop")  # running -> stopped

    rep = _readiness(client, sid)
    sr = rep["self_reports"]
    assert sr["collected"] == 15 and not sr["missing"]
    assert not rep["questionnaires"]["missing"]
    assert rep["recording"]["ok"] is True
    assert rep["state"] == "stopped"
    assert rep["ready"] is True
    assert rep["warnings"] == []


def test_unknown_session_is_404(client, protocol_id):
    assert client.get("/sessions/NOPE/finish-readiness").status_code == 404
