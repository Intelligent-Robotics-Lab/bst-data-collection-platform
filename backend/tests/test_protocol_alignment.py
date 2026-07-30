"""The DTT protocol config must agree with the code that materializes loops.

The named SDs and their function_class live in TWO places: the protocol config
(configs/dtt_protocols/bst_dtt_v1.yaml, mirroring the robot repo's
data/trial_data.json) and NAMED_SD_BY_GROUP / loop_plan in app.services.dtt_loops
(which generates dtt_loops at session start). If they drift, a session's loop
structure silently stops matching the protocol the robot is actually running.
These tests pin them together.
"""

import yaml

from app.core.config import settings
from app.services.dtt_loops import NAMED_SD_BY_GROUP, loop_plan, resolve_named_sd

PROBLEM_SDS = {"Receptive Instruction": "NR", "Tacting and Labeling": "PR", "Receptive Expression": "AR"}
BASELINE_SDS = {"Manding", "Imitation", "Emotion Labeling"}


def _config() -> dict:
    path = settings.configs_dir / "dtt_protocols" / "bst_dtt_v1.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _named() -> dict[str, dict]:
    return {e["name"]: e for e in _config()["named_sds"]}


def test_config_defines_the_six_named_sds():
    named = _named()
    assert set(named) == BASELINE_SDS | set(PROBLEM_SDS)


def test_named_sd_function_class_matches_loop_plan_for_every_group_and_loop():
    """The heart of it: for each order group, the function_class the platform
    assigns to a loop must equal the function_class of the named SD the Latin
    square puts in that loop."""
    named = _named()
    for group in (1, 2, 3):
        for row in loop_plan(group):
            loop_index = row["loop_index"]
            sd_name = resolve_named_sd(group, loop_index)
            assert sd_name in named, f"group {group} loop {loop_index}: {sd_name!r} not in config"
            assert named[sd_name]["function_class"] == row["function_class"], (
                f"group {group} loop {loop_index} ({sd_name}): config says "
                f"{named[sd_name]['function_class']}, loop_plan says {row['function_class']}"
            )


def test_baseline_sds_sit_in_odd_cells_problem_sds_rotate_even_cells():
    for group in (1, 2, 3):
        for loop_index, sd_name in NAMED_SD_BY_GROUP[group].items():
            if loop_index % 2 == 1:
                assert sd_name in BASELINE_SDS, f"group {group} loop {loop_index}: {sd_name}"
            else:
                assert sd_name in PROBLEM_SDS, f"group {group} loop {loop_index}: {sd_name}"


def test_only_problem_sds_have_an_error_correction_path():
    for name, entry in _named().items():
        expected = name in PROBLEM_SDS
        assert entry["error_correction"] is expected, name
        # a problem SD is scripted to not respond; a baseline SD responds correctly
        assert entry["scripted_correctness"] == ("No Response" if expected else "Correct"), name


def test_named_sd_target_skills_exist_in_the_rehearsal_phase():
    cfg = _config()
    phase = next(p for p in cfg["phases"] if p["phase_key"] == "rehearsal")
    skills = {s["skill_id"] for s in phase["target_skills"]}
    for name, entry in _named().items():
        assert entry["target_skill"] in skills, f"{name}: {entry['target_skill']} not a rehearsal skill"


def test_protocol_has_no_prompt_hierarchy_but_a_fixed_ec_sequence():
    cfg = _config()
    assert cfg["prompt_levels"] == []
    assert cfg["ec_sequence"] == ["prompting", "hp_sd", "retry_sd"]
    assert [h["hp_id"] for h in cfg["hp_sds"]] == ["SD_1", "SD_2", "SD_3"]


def test_positional_sd_cells_match_dtt_loops_sd_ids():
    cfg = _config()
    assert [s["sd_id"] for s in cfg["sds"]] == [f"sd_{i}" for i in range(1, 7)]
    for group in (1, 2, 3):
        for row in loop_plan(group):
            assert row["sd_id"] == f"sd_{row['loop_index']}"
