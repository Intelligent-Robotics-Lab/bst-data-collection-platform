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
    # D-QEL is a real 13-item instrument; manipulation_checks stays a placeholder.
    assert rows["dqel"]["item_count"] == 13
    assert rows["dqel"]["scale_type"] == "likert_5"
    assert rows["dqel"]["version"] == "1.0.0"
    assert rows["manipulation_checks"]["version"] == "0.1.0-placeholder"


def test_pre_post_filter(client, questionnaires):
    pre = {r["questionnaire_key"] for r in client.get("/questionnaires?timepoint=pre").json()}
    post = {r["questionnaire_key"] for r in client.get("/questionnaires?timepoint=post").json()}
    assert {"demographics", "erq", "bfi2s"} <= pre
    assert {"rosas_trainer", "rosas_child", "dqel", "manipulation_checks"} <= post
    assert "erq" not in post


def test_pre_questionnaires_start_with_demographics(client, questionnaires):
    """Onboarding pushes pre-questionnaires in list order; demographics is first."""
    pre = [r["questionnaire_key"] for r in client.get("/questionnaires?timepoint=pre").json()]
    assert pre[0] == "demographics"
    assert pre == ["demographics", "erq", "bfi2s"]


def test_render_spec_exposes_intro_and_instruction(client, questionnaires):
    """Every questionnaire carries a plain-language intro; copyrighted ones also
    carry their official instruction (merged from the gitignored local file)."""
    for key in ("demographics", "erq", "bfi2s", "rosas_trainer", "dqel"):
        cfg = client.get(f"/questionnaires/{key}/config").json()
        assert cfg["intro"], f"{key} missing intro"
        assert isinstance(cfg["intro"], str) and len(cfg["intro"]) > 10
    # demographics defines its instruction inline (own instrument)
    assert client.get("/questionnaires/demographics/config").json()["instruction"]


def test_demographics_has_teaching_and_family_items_with_hints(client, questionnaires):
    items = {it["item_id"]: it for it in client.get("/questionnaires/demographics/config").json()["items"]}
    assert "dem_teaching_experience" in items
    assert "dem_family_disability_experience" in items
    # both carry a clarifying hint for the participant
    assert items["dem_teaching_experience"].get("hint")
    assert items["dem_family_disability_experience"].get("hint")
    # the sensitive question offers a decline option
    vals = {o["value"] for o in items["dem_family_disability_experience"]["options"]}
    assert "no_answer" in vals


def test_new_demographic_items_accept_answers(client, questionnaires):
    client.post("/participants", json={"participant_id": "DZ"})
    client.post("/sessions", json={"session_id": "DZ_S1", "participant_id": "DZ", "scenario_type": "bst_dtt"})
    r = client.post("/sessions/DZ_S1/questionnaires/demographics/autosave", json={"answers": {
        "dem_teaching_experience": "yes",
        "dem_teaching_experience_detail": "Two years tutoring high-school math.",
        "dem_family_disability_experience": "no_answer",
    }})
    assert r.status_code == 200, r.text


def test_dqel_renders_13_real_items(client, questionnaires):
    cfg = client.get("/questionnaires/dqel/config").json()
    assert len(cfg["items"]) == 13
    assert cfg["response_scale"]["min"] == 1 and cfg["response_scale"]["max"] == 5
    # item text is a string (verbatim text, if present, comes from the gitignored
    # local file -- never asserted here so the test needs no copyrighted text)
    assert all(isinstance(it["text"], str) for it in cfg["items"])


def test_list_returns_one_row_per_key_latest_version(client, _session_factory):
    """A version bump leaves the old row registered (lower id); the list must not
    show a key twice -- only the latest (highest-id) version."""
    from app.models.questionnaire import Questionnaire

    db = _session_factory()
    try:
        # old registration first (lower id), then the bumped version (higher id)
        db.add(Questionnaire(questionnaire_key="dqel", version="0.1.0-placeholder",
                             title="old", scale_type="likert_5", item_count=3,
                             timepoint="post", config_path="", config_hash="old"))
        db.commit()
        db.add(Questionnaire(questionnaire_key="dqel", version="1.0.0",
                             title="new", scale_type="likert_5", item_count=13,
                             timepoint="post", config_path="", config_hash="new"))
        db.commit()
    finally:
        db.close()

    post = [r for r in client.get("/questionnaires?timepoint=post").json()
            if r["questionnaire_key"] == "dqel"]
    assert len(post) == 1
    assert post[0]["version"] == "1.0.0"


def test_config_render_spec(client, questionnaires):
    cfg = client.get("/questionnaires/erq/config").json()
    assert len(cfg["items"]) == 10
    item = cfg["items"][0]
    assert item["item_id"] == "erq_01"
    assert item["type"] == "likert"
    assert item["scale"]["min"] == 1 and item["scale"]["max"] == 7
    # Order is load-bearing (items 1 & 3 define terms later items use): the
    # render spec is in index order 1..10.
    assert [it["index"] for it in cfg["items"]] == list(range(1, 11))
    # Item text is a string; the verbatim (copyrighted) wording, when present,
    # is merged from the gitignored local file, so it is never asserted here
    # (keeps the test independent of local files / copyrighted text).
    assert isinstance(item["text"], str)


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
        json={"answers": {"dem_fluent_english": "robot"}},
    )
    assert r.status_code == 422 and "valid" in r.json()["detail"]
    # integer out of range (dem_age max is 120)
    r = client.post(
        f"/sessions/{sid}/questionnaires/demographics/autosave",
        json={"answers": {"dem_age": 200}},
    )
    assert r.status_code == 422
    # multi_choice expects a list, not a scalar
    r = client.post(
        f"/sessions/{sid}/questionnaires/demographics/autosave",
        json={"answers": {"dem_gender_identity": "woman"}},
    )
    assert r.status_code == 422
    # good mixed answers (integer + multi_choice + single_choice)
    r = client.post(
        f"/sessions/{sid}/questionnaires/demographics/autosave",
        json={"answers": {"dem_age": 34, "dem_gender_identity": ["woman"], "dem_familiarity": "high"}},
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
