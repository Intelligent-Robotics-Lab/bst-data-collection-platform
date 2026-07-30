"""Recording rewatch + save tests.

Playback streams the file inline; 'Save'/'Save As' copy it to an archival
location. Everything here must leave the ORIGINAL file untouched (zero
video-data loss).
"""

from pathlib import Path

import pytest

from app.core.config import settings
from app.models.signals import MediaRecording


def _recording(client, _session_factory, tmp_path, *, sid="RS_S1", pid="RSP", status="completed", make_file=True):
    client.post("/participants", json={"participant_id": pid})
    client.post("/sessions", json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"})
    src = tmp_path / "rec_src.mp4"
    if make_file:
        src.write_bytes(b"\x00\x01\x02" * 5000)  # 15000 bytes of "video"
    db = _session_factory()
    rec = MediaRecording(
        session_id=sid, participant_id=pid, recording_type="av",
        file_path=str(src), file_name=src.name, status=status,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec, src


def test_stream_returns_the_file(client, _session_factory, tmp_path):
    rec, src = _recording(client, _session_factory, tmp_path)
    r = client.get(f"/sessions/RS_S1/recordings/{rec.recording_id}/file")
    assert r.status_code == 200, r.text
    assert r.content == src.read_bytes()
    assert "video/mp4" in r.headers["content-type"]


def test_stream_409_when_no_file(client, _session_factory, tmp_path):
    rec, _ = _recording(client, _session_factory, tmp_path, status="failed", make_file=False)
    r = client.get(f"/sessions/RS_S1/recordings/{rec.recording_id}/file")
    assert r.status_code == 409


def test_save_default_copies_and_keeps_original(client, _session_factory, tmp_path, monkeypatch):
    saved = tmp_path / "saved"
    monkeypatch.setattr(settings, "SAVED_RECORDINGS_DIR", saved)
    rec, src = _recording(client, _session_factory, tmp_path)

    r = client.post(f"/sessions/RS_S1/recordings/{rec.recording_id}/save", json={"mode": "default"})
    assert r.status_code == 200, r.text
    body = r.json()
    dest = Path(body["saved_to"])
    assert dest.exists() and dest.read_bytes() == src.read_bytes()  # faithful copy
    assert src.exists() and src.read_bytes()  # ORIGINAL kept
    assert body["bytes"] == src.stat().st_size
    assert body["overwritten"] is False


def test_save_as_to_full_path_and_to_directory(client, _session_factory, tmp_path):
    rec, src = _recording(client, _session_factory, tmp_path)

    # full file path (parent dirs auto-created)
    target = tmp_path / "fav" / "mysession.mp4"
    r = client.post(f"/sessions/RS_S1/recordings/{rec.recording_id}/save",
                    json={"mode": "as", "dest_path": str(target)})
    assert r.status_code == 200, r.text
    assert target.exists() and target.read_bytes() == src.read_bytes()

    # a directory target keeps the original file name
    folder = tmp_path / "fav2"
    folder.mkdir()
    r = client.post(f"/sessions/RS_S1/recordings/{rec.recording_id}/save",
                    json={"mode": "as", "dest_path": str(folder)})
    assert r.status_code == 200, r.text
    assert (folder / src.name).exists()
    assert src.exists()  # still there


def test_save_as_requires_dest_path(client, _session_factory, tmp_path):
    rec, _ = _recording(client, _session_factory, tmp_path)
    r = client.post(f"/sessions/RS_S1/recordings/{rec.recording_id}/save", json={"mode": "as"})
    assert r.status_code == 422


def test_save_refuses_to_overwrite_without_flag_then_allows(client, _session_factory, tmp_path):
    rec, src = _recording(client, _session_factory, tmp_path)
    target = tmp_path / "dupe.mp4"
    target.write_bytes(b"existing")

    r = client.post(f"/sessions/RS_S1/recordings/{rec.recording_id}/save",
                    json={"mode": "as", "dest_path": str(target)})
    assert r.status_code == 409  # would clobber an existing file

    r = client.post(f"/sessions/RS_S1/recordings/{rec.recording_id}/save",
                    json={"mode": "as", "dest_path": str(target), "overwrite": True})
    assert r.status_code == 200, r.text
    assert r.json()["overwritten"] is True
    assert target.read_bytes() == src.read_bytes()


def test_save_refuses_when_dest_is_the_original(client, _session_factory, tmp_path):
    rec, src = _recording(client, _session_factory, tmp_path)
    r = client.post(f"/sessions/RS_S1/recordings/{rec.recording_id}/save",
                    json={"mode": "as", "dest_path": str(src)})
    assert r.status_code == 422
    assert src.exists()  # original never at risk


def test_save_409_when_recording_has_no_file(client, _session_factory, tmp_path):
    rec, _ = _recording(client, _session_factory, tmp_path, status="failed", make_file=False)
    r = client.post(f"/sessions/RS_S1/recordings/{rec.recording_id}/save", json={"mode": "default"})
    assert r.status_code == 409


def test_save_unknown_recording_404(client, _session_factory, tmp_path):
    _recording(client, _session_factory, tmp_path)
    r = client.post("/sessions/RS_S1/recordings/999/save", json={"mode": "default"})
    assert r.status_code == 404
