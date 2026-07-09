"""Human fidelity scoring tests (Operator Console v3).

Exercises the per-loop scoring API: create/update (upsert), get/list, mark
complete, loop-meta backfill from dtt_loops, autosave never demoting a completed
loop, validation, timeline events, and export of fidelity_scores.csv.
"""

import csv

import pytest

from app.core.config import settings


@pytest.fixture
def exports_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    return tmp_path


def _session(client, protocol_id, sid="FD_S1", pid="FDP", group=1, support=1):
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
    return sid


def _blank_payload(**overrides):
    """A full upsert payload (all ratings default unscored) with overrides."""
    payload = {"error_sources": [], "notes": None}
    payload.update(overrides)
    return payload


# --- create / get ------------------------------------------------------------

def test_put_creates_score_and_get_returns_it(client, protocol_id):
    sid = _session(client, protocol_id)
    r = client.put(
        f"/sessions/{sid}/fidelity-scores/2",
        json=_blank_payload(delivered_target="correct", sd_timing="incorrect"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["loop_index"] == 2
    assert body["delivered_target"] == "correct"
    assert body["sd_timing"] == "incorrect"
    assert body["status"] == "draft"  # default on create

    g = client.get(f"/sessions/{sid}/fidelity-scores/2")
    assert g.status_code == 200
    assert g.json()["fidelity_score_id"] == body["fidelity_score_id"]


def test_backfills_function_class_and_sd_from_loops(client, protocol_id):
    # group 1, loop 2 -> function_class NR, sd_id sd_2 (matches export test).
    sid = _session(client, protocol_id, group=1)
    r = client.put(f"/sessions/{sid}/fidelity-scores/2", json=_blank_payload())
    body = r.json()
    assert body["function_class"] == "NR"
    assert body["sd_id"] == "sd_2"


def test_upsert_updates_same_row(client, protocol_id):
    sid = _session(client, protocol_id)
    first = client.put(
        f"/sessions/{sid}/fidelity-scores/1",
        json=_blank_payload(delivered_target="correct"),
    ).json()
    second = client.put(
        f"/sessions/{sid}/fidelity-scores/1",
        json=_blank_payload(delivered_target="incorrect"),
    ).json()
    assert second["fidelity_score_id"] == first["fidelity_score_id"]  # same row
    assert second["delivered_target"] == "incorrect"
    # exactly one row for the loop
    assert len(client.get(f"/sessions/{sid}/fidelity-scores").json()) == 1


def test_error_sources_and_notes_roundtrip(client, protocol_id):
    sid = _session(client, protocol_id)
    r = client.put(
        f"/sessions/{sid}/fidelity-scores/3",
        json=_blank_payload(
            error_sources=["timing", "prompting"], notes="EC prompt was late"
        ),
    )
    body = r.json()
    assert body["error_sources"] == ["timing", "prompting"]
    assert body["notes"] == "EC prompt was late"


# --- complete ----------------------------------------------------------------

def test_complete_flips_status(client, protocol_id):
    sid = _session(client, protocol_id)
    client.put(f"/sessions/{sid}/fidelity-scores/4", json=_blank_payload())
    r = client.post(f"/sessions/{sid}/fidelity-scores/4/complete")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "complete"


def test_complete_missing_row_is_404(client, protocol_id):
    sid = _session(client, protocol_id)
    r = client.post(f"/sessions/{sid}/fidelity-scores/5/complete")
    assert r.status_code == 404


def test_autosave_does_not_demote_completed(client, protocol_id):
    sid = _session(client, protocol_id)
    client.put(f"/sessions/{sid}/fidelity-scores/1", json=_blank_payload())
    client.post(f"/sessions/{sid}/fidelity-scores/1/complete")
    # A later autosave (status omitted) must keep it complete.
    r = client.put(
        f"/sessions/{sid}/fidelity-scores/1",
        json=_blank_payload(sd_timing="correct"),
    )
    assert r.json()["status"] == "complete"
    assert r.json()["sd_timing"] == "correct"


# --- list / validation -------------------------------------------------------

def test_list_ordered_by_loop(client, protocol_id):
    sid = _session(client, protocol_id)
    for loop in (3, 1, 2):
        client.put(f"/sessions/{sid}/fidelity-scores/{loop}", json=_blank_payload())
    loops = [r["loop_index"] for r in client.get(f"/sessions/{sid}/fidelity-scores").json()]
    assert loops == [1, 2, 3]


def test_invalid_score_value_is_422(client, protocol_id):
    sid = _session(client, protocol_id)
    r = client.put(
        f"/sessions/{sid}/fidelity-scores/1",
        json=_blank_payload(delivered_target="maybe"),
    )
    assert r.status_code == 422


def test_invalid_loop_index_is_422(client, protocol_id):
    sid = _session(client, protocol_id)
    assert client.put(f"/sessions/{sid}/fidelity-scores/7", json=_blank_payload()).status_code == 422
    assert client.get(f"/sessions/{sid}/fidelity-scores/0").status_code == 422


def test_unknown_session_is_404(client, protocol_id):
    r = client.put("/sessions/NOPE/fidelity-scores/1", json=_blank_payload())
    assert r.status_code == 404


# --- timeline ----------------------------------------------------------------

def _timeline(client, sid):
    return client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()


def test_timeline_records_started_and_completed(client, protocol_id):
    sid = _session(client, protocol_id)
    client.put(f"/sessions/{sid}/fidelity-scores/2", json=_blank_payload())
    client.post(f"/sessions/{sid}/fidelity-scores/2/complete")
    types = [e["type"] for e in _timeline(client, sid)]
    assert "fidelity_score_started" in types
    assert "fidelity_score_completed" in types
    # A second autosave must NOT add another "started" event.
    client.put(f"/sessions/{sid}/fidelity-scores/2", json=_blank_payload(sd_timing="correct"))
    types2 = [e["type"] for e in _timeline(client, sid)]
    assert types2.count("fidelity_score_started") == 1


# --- export ------------------------------------------------------------------

def test_export_includes_fidelity_scores_csv(client, protocol_id, exports_tmp):
    sid = _session(client, protocol_id)
    client.put(
        f"/sessions/{sid}/fidelity-scores/2",
        json=_blank_payload(delivered_target="correct", error_sources=["timing"]),
    )
    client.post(f"/sessions/{sid}/fidelity-scores/2/complete")

    r = client.post(f"/sessions/{sid}/export")
    assert r.status_code == 201, r.text
    body = r.json()
    assert "fidelity_scores.csv" in body["files"]
    assert body["row_counts"]["fidelity_scores"] == 1

    from pathlib import Path

    path = Path(body["export_dir"]) / "fidelity_scores.csv"
    with path.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["loop_index"] == "2"
    assert rows[0]["delivered_target"] == "correct"
    assert rows[0]["status"] == "complete"
    assert "timing" in rows[0]["error_sources_json"]
