"""Questionnaire engine tests (P0.4 / P0.6).

Configs are registered from disk via the ``questionnaires`` fixture (mirrors
startup). Responses validate against the parsed config; bad references and
out-of-range values must return a clean 422, never a DB 500. Autosave is
refresh-safe; a finalized questionnaire cannot be re-submitted (raw immutability).
"""


def _session(client, pid="P200", sid="P200_S1"):
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"},
    )
    return sid


def test_registry_lists_real_instruments(client, questionnaires):
    rows = {r["questionnaire_key"]: r for r in client.get("/questionnaires").json()}
    # Real instruments with correct item counts and scales.
    assert rows["erq"]["item_count"] == 10
    assert rows["erq"]["scale_type"] == "likert_7"
    assert rows["erq"]["timepoint"] == "pre"
    assert rows["bfi2s"]["item_count"] == 30
    assert rows["bfi2s"]["scale_type"] == "likert_5"
    assert rows["rosas_trainer"]["item_count"] == 18
    assert rows["rosas_child"]["item_count"] == 18
    assert rows["rosas_trainer"]["timepoint"] == "post"
    # Placeholders are present.
    assert "dqel" in rows and "manipulation_checks" in rows


def test_pre_post_filter(client, questionnaires):
    pre = {r["questionnaire_key"] for r in client.get("/questionnaires?timepoint=pre").json()}
    post = {r["questionnaire_key"] for r in client.get("/questionnaires?timepoint=post").json()}
    assert {"demographics", "erq", "bfi2s"} <= pre
    assert {"rosas_trainer", "rosas_child"} <= post
    assert "erq" not in post


def test_config_render_spec(client, questionnaires):
    cfg = client.get("/questionnaires/erq/config").json()
    assert len(cfg["items"]) == 10
    item = cfg["items"][0]
    assert item["item_id"] == "erq_01"
    assert item["type"] == "likert"
    assert item["scale"]["min"] == 1 and item["scale"]["max"] == 7
    # No copyrighted text: placeholder wording only.
    assert "placeholder" in item["text"].lower()


def test_unknown_questionnaire_config_is_404(client, questionnaires):
    assert client.get("/questionnaires/nope/config").status_code == 404


def test_autosave_then_restore_is_refresh_safe(client, questionnaires):
    sid = _session(client)
    r = client.post(
        f"/sessions/{sid}/questionnaires/erq/autosave",
        json={"answers": {"erq_01": 5, "erq_02": 3}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_partial"] is True

    saved = client.get(f"/sessions/{sid}/questionnaires/erq/responses").json()
    assert saved["finalized"] is False
    assert saved["answers"]["erq_01"]["value"] == 5
    assert saved["answers"]["erq_01"]["is_partial"] is True

    # A second autosave updates the same draft (no duplicate rows).
    client.post(
        f"/sessions/{sid}/questionnaires/erq/autosave",
        json={"answers": {"erq_01": 6}},
    )
    saved = client.get(f"/sessions/{sid}/questionnaires/erq/responses").json()
    assert saved["answers"]["erq_01"]["value"] == 6


def _full_erq():
    return {f"erq_{i:02d}": ((i % 7) + 1) for i in range(1, 11)}


def test_submit_writes_rows_and_timeline_and_locks(client, questionnaires):
    sid = _session(client)
    r = client.post(
        f"/sessions/{sid}/questionnaires/erq/submit", json={"answers": _full_erq()}
    )
    assert r.status_code == 201, r.text
    assert r.json()["item_count"] == 10

    saved = client.get(f"/sessions/{sid}/questionnaires/erq/responses").json()
    assert saved["finalized"] is True
    assert all(not rec["is_partial"] for rec in saved["answers"].values())

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(
        e["type"] == "questionnaire_submitted" and e["payload"]["questionnaire_key"] == "erq"
        for e in tl
    )

    # Re-submit and autosave are both rejected once finalized.
    assert client.post(
        f"/sessions/{sid}/questionnaires/erq/submit", json={"answers": _full_erq()}
    ).status_code == 409
    assert client.post(
        f"/sessions/{sid}/questionnaires/erq/autosave", json={"answers": {"erq_01": 1}}
    ).status_code == 409


def test_submit_missing_required_is_422(client, questionnaires):
    sid = _session(client)
    r = client.post(
        f"/sessions/{sid}/questionnaires/erq/submit", json={"answers": {"erq_01": 5}}
    )
    assert r.status_code == 422, r.text
    assert "missing required" in r.json()["detail"]


def test_submit_unknown_item_is_422(client, questionnaires):
    sid = _session(client)
    answers = _full_erq()
    answers["erq_99"] = 4
    r = client.post(f"/sessions/{sid}/questionnaires/erq/submit", json={"answers": answers})
    assert r.status_code == 422
    assert "erq_99" in r.json()["detail"]


def test_likert_out_of_range_is_422(client, questionnaires):
    sid = _session(client)
    r = client.post(
        f"/sessions/{sid}/questionnaires/erq/autosave", json={"answers": {"erq_01": 8}}
    )
    assert r.status_code == 422
    assert "outside scale" in r.json()["detail"]


def test_demographics_mixed_types_validate(client, questionnaires):
    sid = _session(client)
    # bad single_choice option
    r = client.post(
        f"/sessions/{sid}/questionnaires/demographics/autosave",
        json={"answers": {"dem_gender": "robot"}},
    )
    assert r.status_code == 422 and "valid" in r.json()["detail"]
    # integer out of range
    r = client.post(
        f"/sessions/{sid}/questionnaires/demographics/autosave",
        json={"answers": {"dem_age": 5}},
    )
    assert r.status_code == 422
    # good mixed answers
    r = client.post(
        f"/sessions/{sid}/questionnaires/demographics/autosave",
        json={"answers": {"dem_age": 34, "dem_gender": "woman", "dem_baseline_confidence": 6}},
    )
    assert r.status_code == 200, r.text


def test_submit_on_unknown_session_is_404(client, questionnaires):
    assert client.post(
        "/sessions/NOPE/questionnaires/erq/submit", json={"answers": _full_erq()}
    ).status_code == 404


def test_submit_unknown_questionnaire_is_422(client, questionnaires):
    sid = _session(client)
    assert client.post(
        f"/sessions/{sid}/questionnaires/nope/submit", json={"answers": {}}
    ).status_code == 422
