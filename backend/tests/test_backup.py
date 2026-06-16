"""Tests for the DB backup safeguard. Uses temp paths only; never touches the
real data/bst.db."""

from app.core.config import settings
from app.services.backup import _prune_backups, backup_database


def _point_settings_at_tmp(monkeypatch, tmp_path, keep=20):
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "live.db")
    monkeypatch.setattr(settings, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(settings, "DB_BACKUP_KEEP", keep)


def test_backup_creates_timestamped_copy(monkeypatch, tmp_path):
    _point_settings_at_tmp(monkeypatch, tmp_path)
    settings.db_path.write_bytes(b"PARTICIPANT-DATA")

    dest = backup_database(reason="completion")

    assert dest is not None
    assert dest.exists()
    assert dest.parent == settings.backups_dir
    assert "completion" in dest.name
    assert dest.read_bytes() == b"PARTICIPANT-DATA"
    # live DB untouched (non-destructive)
    assert settings.db_path.read_bytes() == b"PARTICIPANT-DATA"


def test_backup_skips_when_no_db(monkeypatch, tmp_path):
    _point_settings_at_tmp(monkeypatch, tmp_path)
    # no live.db created
    assert backup_database(reason="startup") is None


def test_prune_keeps_last_n(monkeypatch, tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    # timestamp-prefixed names sort chronologically
    names = [
        "bst-20260616T100000_000000Z-startup.db",
        "bst-20260616T110000_000000Z-completion.db",
        "bst-20260616T120000_000000Z-completion.db",
        "bst-20260616T130000_000000Z-startup.db",
        "bst-20260616T140000_000000Z-completion.db",
    ]
    for n in names:
        (backups / n).write_bytes(b"x")

    _prune_backups(backups, keep=3)

    remaining = sorted(p.name for p in backups.glob("bst-*.db"))
    assert remaining == names[-3:]  # newest 3 kept, oldest 2 pruned
