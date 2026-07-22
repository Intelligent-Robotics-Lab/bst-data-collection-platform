"""Participant self-report tests (P0.7).

PAD is a 9-point Self-Assessment Manikin per dimension: integer [-4, +4]. Submit
requires all three (no auto-neutral default); autosave accepts any subset. A
finalized row writes a participant_self_reports row (source='sr') tagged in
raw_json with instrument='SAM-9', plus a timeline event. Range, integer-ness, the
enums, and the trial_id FK are all guarded (clean 422).
"""

import json

from app.models.signals import ParticipantSelfReport


def _running(client, pid="P210", sid="P210_S1"):
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"},
    )
    client.post(f"/sessions/{sid}/start")
    return sid


def _ctx(**over):
    payload = {
        "loop_index": 2,
        "phase": "rehearsal",
        "timepoint": "pre",
        "function_class": "PR",
        "before_after_robot_action": "before",
    }
    payload.update(over)
    return payload


def _pad(**over):
    """A valid full answer set: three SAM ints + the categorical emotion; all
    required at submit."""
    pad = {"pleasure": 2, "arousal": -1, "dominance": 0, "emotion_category": "happy"}
    pad.update(over)
    return pad


def test_self_report_writes_row_and_timeline(client):
    sid = _running(client)
    r = client.post(
        f"/sessions/{sid}/self-reports",
        json={**_ctx(), **_pad(pleasure=3, arousal=-2, dominance=1)},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "sr"
    assert body["pleasure"] == 3
    assert body["arousal"] == -2
    assert body["dominance"] == 1
    # PAD only: the removed dimensions are not collected (NULL, not a fake 0)
    assert body["confidence"] is None
    assert body["cognitive_load"] is None
    assert body["loop_index"] == 2 and body["phase"] == "rehearsal"

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(
        e["type"] == "self_report_submitted" and e["payload"]["pleasure"] == 3 for e in tl
    )


def test_finalized_row_is_tagged_sam9(client, _session_factory):
    """Provenance: the raw_json distinguishes SAM-9 rows from the pre-SAM [-5,+5]
    slider pilots (whose raw_json has no instrument key)."""
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), **_pad(pleasure=4)})
    assert r.status_code == 201, r.text

    db = _session_factory()
    try:
        row = db.query(ParticipantSelfReport).one()
        meta = json.loads(row.raw_json)
    finally:
        db.close()
    assert meta["instrument"] == "SAM-9"
    assert meta["scale_min"] == -4 and meta["scale_max"] == 4
    assert meta["pleasure"] == 4  # sliders stay flat in raw_json alongside the tag
    assert meta["emotion_category"] == "happy"


def test_two_self_reports_listed_in_order(client):
    sid = _running(client)
    client.post(f"/sessions/{sid}/self-reports", json={**_ctx(before_after_robot_action="before"), **_pad()})
    client.post(f"/sessions/{sid}/self-reports", json={**_ctx(before_after_robot_action="after"), **_pad()})
    reports = client.get(f"/sessions/{sid}/self-reports").json()
    assert len(reports) == 2
    assert [r["before_after_robot_action"] for r in reports] == ["before", "after"]


def test_submit_requires_all_three(client):
    """No auto-neutral default: a missing SAM dimension is 'not answered' -> 422."""
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), "pleasure": 2})
    assert r.status_code == 422  # arousal + dominance missing


def test_non_integer_pick_is_422(client):
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), **_pad(pleasure=2.5)})
    assert r.status_code == 422


def test_range_boundaries(client):
    sid = _running(client)
    # inclusive [-4, +4] is valid; +/-5 is out of range
    assert client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), **_pad(pleasure=4)}).status_code == 201
    assert client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), **_pad(pleasure=-4)}).status_code == 201
    assert client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), **_pad(pleasure=5)}).status_code == 422
    assert client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), **_pad(arousal=-5)}).status_code == 422


def test_emotion_category_required_at_submit(client):
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports",
                    json={**_ctx(), "pleasure": 2, "arousal": 0, "dominance": 0})
    assert r.status_code == 422  # emotion_category missing


def test_bad_emotion_category_is_422(client):
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), **_pad(emotion_category="ecstatic")})
    assert r.status_code == 422


def test_emotion_category_stored_returned_and_on_timeline(client):
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports", json={**_ctx(), **_pad(emotion_category="anger")})
    assert r.status_code == 201, r.text
    assert r.json()["emotion_category"] == "anger"
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(
        e["type"] == "self_report_submitted" and e["payload"]["emotion_category"] == "anger" for e in tl
    )


def test_bad_enum_is_422(client):
    sid = _running(client)
    assert client.post(f"/sessions/{sid}/self-reports", json={**_ctx(phase="nope"), **_pad()}).status_code == 422
    assert client.post(f"/sessions/{sid}/self-reports", json={**_ctx(loop_index=7), **_pad()}).status_code == 422


def test_dangling_trial_id_is_422(client):
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports", json={**_ctx(trial_id=999), **_pad()})
    assert r.status_code == 422
    assert "trial_id" in r.json()["detail"]


def test_self_report_on_unknown_session_is_404(client):
    assert client.post("/sessions/NOPE/self-reports", json={**_ctx(), **_pad()}).status_code == 404


# --- autosave drafts (P0.7 autosave) ---------------------------------------


def _draft_params(ctx):
    """Context dict -> query params the GET /draft endpoint expects."""
    keys = (
        "loop_index", "phase", "timepoint", "function_class",
        "is_problem", "sequence_position", "before_after_robot_action", "trial_id",
    )
    return {k: ctx[k] for k in keys if k in ctx and ctx[k] is not None}


def test_autosave_then_restore_returns_picks(client):
    sid = _running(client)
    ctx = _ctx()
    r = client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 2, "arousal": -1})
    assert r.status_code == 200, r.text
    assert r.json()["is_partial"] is True

    got = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()
    assert got["found"] is True
    assert got["sliders"]["pleasure"] == 2
    assert got["sliders"]["arousal"] == -1
    # an un-picked SAM dimension is not answered yet -> None, never a fake 0
    assert got["sliders"]["dominance"] is None
    # PAD only: the three dimensions are the whole draft
    assert set(got["sliders"]) == {"pleasure", "arousal", "dominance"}


def test_autosave_accepts_a_single_partial_pick(client):
    """The lenient autosave schema takes any subset (submit still needs all 3)."""
    sid = _running(client)
    ctx = _ctx()
    r = client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 3})
    assert r.status_code == 200, r.text
    got = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()
    assert got["sliders"] == {"pleasure": 3, "arousal": None, "dominance": None}


def test_autosave_restores_emotion_category(client):
    sid = _running(client)
    ctx = _ctx()
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "emotion_category": "sad"})
    got = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()
    assert got["emotion_category"] == "sad"
    assert got["sliders"] == {"pleasure": None, "arousal": None, "dominance": None}


def test_autosave_does_not_write_raw_row_or_timeline(client):
    sid = _running(client)
    ctx = _ctx()
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 3})
    # No raw participant_self_reports row...
    assert client.get(f"/sessions/{sid}/self-reports").json() == []
    # ...and no timeline event (drafts are working state, not significant events).
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert not any(e["type"] == "self_report_submitted" for e in tl)


def test_autosave_upserts_same_context(client):
    sid = _running(client)
    ctx = _ctx()
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 1})
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 4})
    got = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()
    assert got["sliders"]["pleasure"] == 4


def test_drafts_are_isolated_per_context(client):
    sid = _running(client)
    before = _ctx(before_after_robot_action="before")
    after = _ctx(before_after_robot_action="after")
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**before, "pleasure": 2})
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**after, "pleasure": -2})

    g_before = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(before)).json()
    g_after = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(after)).json()
    assert g_before["sliders"]["pleasure"] == 2
    assert g_after["sliders"]["pleasure"] == -2
    # different contexts must not share a draft key
    assert g_before["context_key"] != g_after["context_key"]


def test_submit_deletes_matching_draft_only(client):
    sid = _running(client)
    before = _ctx(before_after_robot_action="before")
    after = _ctx(before_after_robot_action="after")
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**before, "pleasure": 2})
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**after, "pleasure": -2})

    # Submit the 'before' context (all three required); its draft goes away,
    # 'after' is untouched.
    r = client.post(f"/sessions/{sid}/self-reports", json={**before, **_pad(pleasure=2)})
    assert r.status_code == 201, r.text

    assert client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(before)).json()["found"] is False
    assert client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(after)).json()["found"] is True


def test_restore_when_no_draft_is_not_found(client):
    sid = _running(client)
    got = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(_ctx())).json()
    assert got["found"] is False
    assert got["sliders"] == {}


def test_autosave_dangling_trial_id_is_422(client):
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports/autosave", json=_ctx(trial_id=999))
    assert r.status_code == 422
    assert "trial_id" in r.json()["detail"]
