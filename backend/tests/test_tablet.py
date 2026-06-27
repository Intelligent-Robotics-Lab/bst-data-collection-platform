"""Push-to-tablet tests (P0.6).

The tablet polls /tablet/assignment; a push bumps the revision and (when it
names a session) writes a form_pushed timeline event. Unknown questionnaires and
session-less pushes return a clean 422.
"""


def _session(client, pid="P220", sid="P220_S1"):
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"},
    )
    return sid


def test_push_questionnaire_updates_assignment_and_timeline(client, questionnaires):
    sid = _session(client)
    before = client.get("/tablet/assignment").json()["revision"]
    r = client.post(
        "/tablet/push",
        json={"form_type": "questionnaire", "session_id": sid, "questionnaire_key": "erq"},
    )
    assert r.status_code == 200, r.text
    a = client.get("/tablet/assignment").json()
    assert a["form_type"] == "questionnaire"
    assert a["questionnaire_key"] == "erq"
    assert a["questionnaire_version"]  # version resolved from the registry
    assert a["session_id"] == sid
    assert a["revision"] == before + 1

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(
        e["type"] == "form_pushed" and e["payload"]["questionnaire_key"] == "erq" for e in tl
    )


def test_push_self_report_carries_context(client):
    sid = _session(client)
    ctx = {"loop_index": 1, "phase": "dtt", "timepoint": "post", "function_class": "baseline"}
    r = client.post(
        "/tablet/push",
        json={"form_type": "self_report", "session_id": sid, "self_report_context": ctx},
    )
    assert r.status_code == 200, r.text
    a = client.get("/tablet/assignment").json()
    assert a["form_type"] == "self_report"
    assert a["self_report_context"]["function_class"] == "baseline"


def test_idle_clear(client):
    client.post("/tablet/clear")
    a = client.get("/tablet/assignment").json()
    assert a["form_type"] == "idle"


def test_push_unknown_questionnaire_is_422(client, questionnaires):
    sid = _session(client)
    r = client.post(
        "/tablet/push",
        json={"form_type": "questionnaire", "session_id": sid, "questionnaire_key": "nope"},
    )
    assert r.status_code == 422


def test_push_without_session_is_422(client, questionnaires):
    r = client.post("/tablet/push", json={"form_type": "questionnaire", "questionnaire_key": "erq"})
    assert r.status_code == 422


def test_push_unknown_session_is_404(client, questionnaires):
    r = client.post(
        "/tablet/push",
        json={"form_type": "questionnaire", "session_id": "NOPE", "questionnaire_key": "erq"},
    )
    assert r.status_code == 404
