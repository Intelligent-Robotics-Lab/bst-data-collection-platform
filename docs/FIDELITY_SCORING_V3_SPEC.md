# Fidelity Scoring v3 Spec

Status: SPEC ONLY.

This document defines the human ABA/BST fidelity scoring panel for Operator Console v3. This is human scoring only. Do not add automated or LLM scoring in v3.

## Purpose

The operator scores each DTT loop/SD using the ABA fidelity table. Scores are linked to `session_id` and `loop_index`, saved during the live session, and included in exports.

## Scope

Build only human fidelity scoring.

Do not:
- add LLM scoring
- add perception/video tab
- block robot progress on fidelity scoring
- change sync gate logic
- change questionnaire or self-report logic
- change BST behavior

## Scoring unit

One score row per `session_id + loop_index`.

The UI should support six loop rows:

- SD1 / loop_index 1
- SD2 / loop_index 2
- SD3 / loop_index 3
- SD4 / loop_index 4
- SD5 / loop_index 5
- SD6 / loop_index 6

## Required scoring fields

Each field should support:

- correct
- incorrect
- not_applicable
- unscored

Use compact UI controls such as ✓ / ✗ / N/A.

Fields:

1. delivered_target
   Label: Delivered this target?

2. sd_delivered_as_written
   Label: SD delivered as written

3. sd_timing
   Label: SD timing

4. primary_rplus_delivery
   Label: Primary R+ delivery

5. primary_rplus_timing
   Label: Primary R+ timing

6. ec_prompting_delivery
   Label: EC prompting delivery

7. ec_prompting_timing
   Label: EC prompting timing

8. ec_hp_delivery
   Label: EC HP delivery

9. ec_hp_timing
   Label: EC HP timing

10. ec_rplus_delivery
    Label: EC R+ delivery

11. ec_rplus_timing
    Label: EC R+ timing

12. initial_sd_delivery
    Label: Initial SD delivery

13. initial_sd_timing
    Label: Initial SD timing

14. final_rplus_delivery
    Label: Final R+ delivery

15. final_rplus_timing
    Label: Final R+ timing

## Terminology

- SD = discriminative stimulus / instruction
- R+ = reinforcement
- EC = error correction
- HP = high-prompt or high-probability step, use the label already used in the BST protocol if available

## Error source

Add a multi-select error source field.

Options:
- interaction_flow
- ordering
- timing
- latency
- wrong_item
- sd_delivery
- prompting
- reinforcement
- error_correction
- other

Also include an optional free-text notes field.

## UI behavior

Add a Human Fidelity Scoring card to Stage 3 Live.

The UI should support:
- loop selector or six-row table for SD1 to SD6
- current loop highlighted
- draft autosave
- mark loop score complete
- status per loop: unscored, draft, complete
- edit previous loop scores if needed
- no blocking of robot progression

Recommended live layout:
- show one loop/SD at a time for fast scoring
- include an optional “review all loops” table view

## Backend behavior

Add storage for human fidelity scores.

Suggested table: `fidelity_scores`

Required columns:
- fidelity_score_id
- session_id
- participant_id
- loop_index
- function_class, if available from dtt_loops
- sd_id, if available from dtt_loops
- delivered_target
- sd_delivered_as_written
- sd_timing
- primary_rplus_delivery
- primary_rplus_timing
- ec_prompting_delivery
- ec_prompting_timing
- ec_hp_delivery
- ec_hp_timing
- ec_rplus_delivery
- ec_rplus_timing
- initial_sd_delivery
- initial_sd_timing
- final_rplus_delivery
- final_rplus_timing
- error_sources_json
- notes
- status: draft or complete
- scored_by
- created_at
- updated_at

Each session_id + loop_index should have at most one current human fidelity score row.

## API

Suggested endpoints:

GET /sessions/{session_id}/fidelity-scores
Return all loop scores for the session.

GET /sessions/{session_id}/fidelity-scores/{loop_index}
Return one loop score.

PUT /sessions/{session_id}/fidelity-scores/{loop_index}
Create or update a draft/complete score.

POST /sessions/{session_id}/fidelity-scores/{loop_index}/complete
Mark the loop score complete.

## Export

Add `fidelity_scores.csv` to session exports.

Export should include all scoring fields, metadata, status, notes, error sources, and timestamps.

## Acceptance criteria

- Operator can score SD1 to SD6 from the console.
- Scores autosave or save reliably.
- Operator can mark each loop score complete.
- Scores are stored by session_id + loop_index.
- Scores export as `fidelity_scores.csv`.
- Human scoring remains blind to automated scores.
- No LLM/automated score is shown in v3.
- Existing v1/v2 behavior remains unchanged.