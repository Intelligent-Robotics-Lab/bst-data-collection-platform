"""Participant self-report tests (P0.7).

A self-report writes a participant_self_reports row (source='sr') plus a
timeline event. Slider range and the trial_id FK are guarded (clean 422).
"""


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


def test_self_report_writes_row_and_timeline(client):
    sid = _running(client)
    r = client.post(
        f"/sessions/{sid}/self-reports",
        json=_ctx(pleasure=3.5, arousal=-2.0, dominance=1.0),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "sr"
    assert body["pleasure"] == 3.5
    assert body["arousal"] == -2.0
    assert body["dominance"] == 1.0
    # PAD only: the removed dimensions are not collected (NULL, not a fake 0)
    assert body["confidence"] is None
    assert body["cognitive_load"] is None
    assert body["loop_index"] == 2 and body["phase"] == "rehearsal"

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(
        e["type"] == "self_report_submitted" and e["payload"]["pleasure"] == 3.5 for e in tl
    )


def test_two_self_reports_listed_in_order(client):
    sid = _running(client)
    client.post(f"/sessions/{sid}/self-reports", json=_ctx(before_after_robot_action="before"))
    client.post(f"/sessions/{sid}/self-reports", json=_ctx(before_after_robot_action="after"))
    reports = client.get(f"/sessions/{sid}/self-reports").json()
    assert len(reports) == 2
    assert [r["before_after_robot_action"] for r in reports] == ["before", "after"]


def test_slider_out_of_range_is_422(client):
    sid = _running(client)
    assert client.post(f"/sessions/{sid}/self-reports", json=_ctx(pleasure=6)).status_code == 422
    assert client.post(f"/sessions/{sid}/self-reports", json=_ctx(arousal=-9)).status_code == 422


def test_bad_enum_is_422(client):
    sid = _running(client)
    assert client.post(f"/sessions/{sid}/self-reports", json=_ctx(phase="nope")).status_code == 422
    assert client.post(f"/sessions/{sid}/self-reports", json=_ctx(loop_index=7)).status_code == 422


def test_dangling_trial_id_is_422(client):
    sid = _running(client)
    r = client.post(f"/sessions/{sid}/self-reports", json=_ctx(trial_id=999))
    assert r.status_code == 422
    assert "trial_id" in r.json()["detail"]


def test_self_report_on_unknown_session_is_404(client):
    assert client.post("/sessions/NOPE/self-reports", json=_ctx()).status_code == 404


# --- autosave drafts (P0.7 autosave) ---------------------------------------


def _draft_params(ctx):
    """Context dict -> query params the GET /draft endpoint expects."""
    keys = (
        "loop_index", "phase", "timepoint", "function_class",
        "is_problem", "sequence_position", "before_after_robot_action", "trial_id",
    )
    return {k: ctx[k] for k in keys if k in ctx and ctx[k] is not None}


def test_autosave_then_restore_returns_sliders(client):
    sid = _running(client)
    ctx = _ctx()
    r = client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 2.5, "arousal": -1.0})
    assert r.status_code == 200, r.text
    assert r.json()["is_partial"] is True

    got = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()
    assert got["found"] is True
    assert got["sliders"]["pleasure"] == 2.5
    assert got["sliders"]["arousal"] == -1.0
    # an untouched PAD slider keeps its true-zero center
    assert got["sliders"]["dominance"] == 0.0
    # PAD only: removed dimensions are not part of the draft
    assert set(got["sliders"]) == {"pleasure", "arousal", "dominance"}


def test_autosave_does_not_write_raw_row_or_timeline(client):
    sid = _running(client)
    ctx = _ctx()
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 3.0})
    # No raw participant_self_reports row...
    assert client.get(f"/sessions/{sid}/self-reports").json() == []
    # ...and no timeline event (drafts are working state, not significant events).
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert not any(e["type"] == "self_report_submitted" for e in tl)


def test_autosave_upserts_same_context(client):
    sid = _running(client)
    ctx = _ctx()
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 1.0})
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**ctx, "pleasure": 4.0})
    got = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()
    assert got["sliders"]["pleasure"] == 4.0


def test_drafts_are_isolated_per_context(client):
    sid = _running(client)
    before = _ctx(before_after_robot_action="before")
    after = _ctx(before_after_robot_action="after")
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**before, "pleasure": 2.0})
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**after, "pleasure": -2.0})

    g_before = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(before)).json()
    g_after = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(after)).json()
    assert g_before["sliders"]["pleasure"] == 2.0
    assert g_after["sliders"]["pleasure"] == -2.0
    # different contexts must not share a draft key
    assert g_before["context_key"] != g_after["context_key"]


def test_submit_deletes_matching_draft_only(client):
    sid = _running(client)
    before = _ctx(before_after_robot_action="before")
    after = _ctx(before_after_robot_action="after")
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**before, "pleasure": 2.0})
    client.post(f"/sessions/{sid}/self-reports/autosave", json={**after, "pleasure": -2.0})

    # Submit the 'before' context; its draft goes away, 'after' is untouched.
    r = client.post(f"/sessions/{sid}/self-reports", json={**before, "pleasure": 2.0})
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
