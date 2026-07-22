"""ensure_added_columns(): add post-release columns to an existing DB that was
created before they existed (create_all never ALTERs an existing table)."""

from sqlalchemy import create_engine

from app.db.session import ensure_added_columns


def _cols(conn, table):
    return {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


def test_ensure_added_columns_adds_missing_then_is_idempotent():
    eng = create_engine("sqlite://", future=True)
    with eng.begin() as c:
        # old-schema tables WITHOUT emotion_category
        c.exec_driver_sql("CREATE TABLE participant_self_reports (self_report_id INTEGER PRIMARY KEY, pleasure REAL)")
        c.exec_driver_sql("CREATE TABLE self_report_drafts (draft_id INTEGER PRIMARY KEY, pleasure REAL)")

    added = ensure_added_columns(eng)
    assert set(added) == {
        "participant_self_reports.emotion_category",
        "participant_self_reports.referent",
        "participant_self_reports.child_behaviors",
        "self_report_drafts.emotion_category",
        "self_report_drafts.child_behaviors",
        "self_report_drafts.handling_pleasure",
        "self_report_drafts.handling_arousal",
        "self_report_drafts.handling_dominance",
        "self_report_drafts.handling_emotion_category",
    }
    with eng.begin() as c:
        sr = _cols(c, "participant_self_reports")
        assert {"emotion_category", "referent", "child_behaviors"} <= sr
        dr = _cols(c, "self_report_drafts")
        assert {"emotion_category", "child_behaviors", "handling_pleasure",
                "handling_arousal", "handling_dominance", "handling_emotion_category"} <= dr

    # second run is a no-op (idempotent)
    assert ensure_added_columns(eng) == []


def test_ensure_added_columns_skips_absent_tables():
    """A brand-new DB with no tables yet: nothing to alter (create_all will build
    them from the model, already including the column)."""
    eng = create_engine("sqlite://", future=True)
    assert ensure_added_columns(eng) == []
