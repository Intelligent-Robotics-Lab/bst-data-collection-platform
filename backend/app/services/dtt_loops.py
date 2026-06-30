"""DTT loop generation (Phase 6, P0.6 piece 1).

At session start we materialize the six ``dtt_loops`` rows for the session from
its ``pb_order_group``, using the Latin-square mapping confirmed against
bst-study ``logic/latin_square.py``.

Structure (the 3-config cyclic Latin square):
  * Baseline is pinned to the ODD loop positions (loops 1, 3, 5).
  * The three problem-behavior challenge functions (PR/NR/AR) rotate through the
    EVEN positions (loops 2, 4, 6), one cyclic permutation per pb_order_group.
  * The discriminative stimulus is bound to the position itself (sd_{loop_index});
    the SD cell is fixed by position, only the function_class rotates by group.

Raw-data immutability: loops are generated exactly once. Generation is guarded so
an already-populated session is never overwritten or duplicated.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.dtt import DttLoop
from app.models.session import StudySession
from app.services.timeline import record_timeline_event

logger = logging.getLogger("bst.dtt_loops")

# Challenge-function assignment to the EVEN loop positions (2, 4, 6) by
# pb_order_group. This is the exact table provided for the study and is the
# cyclic Latin square confirmed against bst-study logic/latin_square.py
# (NR <-> Receptive Instruction, PR <-> Tacting, AR <-> Receptive Expression).
PB_ORDER_GROUP_EVEN_FUNCTION: dict[int, dict[int, str]] = {
    1: {2: "NR", 4: "PR", 6: "AR"},
    2: {2: "AR", 4: "NR", 6: "PR"},
    3: {2: "PR", 4: "AR", 6: "NR"},
}

BASELINE_LOOPS = (1, 3, 5)
ALL_LOOPS = (1, 2, 3, 4, 5, 6)


def loop_plan(pb_order_group: int) -> list[dict]:
    """Return the six (loop_index, function_class, sd_id, is_problem) rows for a
    given pb_order_group, without touching the DB. Pure function; the single
    source of the mapping for both generation and verification/tests."""
    even_function = PB_ORDER_GROUP_EVEN_FUNCTION[pb_order_group]
    plan = []
    for loop_index in ALL_LOOPS:
        if loop_index in BASELINE_LOOPS:
            function_class = "baseline"
            is_problem = "0"
        else:
            function_class = even_function[loop_index]
            is_problem = "1"
        plan.append(
            {
                "loop_index": loop_index,
                "sequence_position": loop_index,
                "function_class": function_class,
                "sd_id": f"sd_{loop_index}",
                "is_problem": is_problem,
            }
        )
    return plan


def generate_dtt_loops(db: Session, session: StudySession) -> list[DttLoop]:
    """Generate the six dtt_loops rows for ``session`` from its pb_order_group.

    Idempotent / non-destructive: if loops already exist for the session, returns
    the existing rows untouched (raw-data immutability). If the session has no
    pb_order_group assigned, generation is skipped (logged); a later loop-indexed
    trial will then fail validation, surfacing the missing assignment cleanly.

    Adds rows + a single timeline event and flushes; the caller owns the commit.
    """
    existing = db.scalars(
        select(DttLoop).where(DttLoop.session_id == session.session_id)
    ).all()
    if existing:
        logger.info(
            "dtt_loops already present for %s (%d rows); not regenerating",
            session.session_id,
            len(existing),
        )
        return list(existing)

    if session.pb_order_group is None:
        logger.warning(
            "session %s has no pb_order_group; skipping dtt_loops generation",
            session.session_id,
        )
        return []

    loops = []
    for row in loop_plan(session.pb_order_group):
        loop = DttLoop(
            session_id=session.session_id,
            participant_id=session.participant_id,
            loop_index=row["loop_index"],
            sequence_position=row["sequence_position"],
            function_class=row["function_class"],
            sd_id=row["sd_id"],
            is_problem=row["is_problem"],
            support_condition=session.support_condition,
            pb_order_group=session.pb_order_group,
        )
        db.add(loop)
        loops.append(loop)
    db.flush()

    record_timeline_event(
        db,
        session=session,
        source="dtt",
        type="dtt_loops_generated",
        payload={
            "pb_order_group": session.pb_order_group,
            "loops": [
                {
                    "loop_index": loop.loop_index,
                    "function_class": loop.function_class,
                    "sd_id": loop.sd_id,
                    "is_problem": loop.is_problem,
                }
                for loop in loops
            ],
        },
        ref_table="dtt_loops",
        ref_id=session.session_id,
    )
    logger.info(
        "generated %d dtt_loops for %s (pb_order_group=%s)",
        len(loops),
        session.session_id,
        session.pb_order_group,
    )
    return loops
