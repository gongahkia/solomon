# SPDX-License-Identifier: MIT

import json
from pathlib import Path


ARTIFACT = Path("benchmarks/results/learned-policy-stage1-local.json")
TIER_RANK = {"cold": 0, "warm": 1, "hot": 2}
ALLOWED_ACTIONS = {
    "noop",
    "promote",
    "demote",
    "merge_with_provenance",
    "flag_for_review",
}
DESTRUCTIVE_ACTIONS = {"delete", "overwrite", "destructive_mutation"}


def load_artifact() -> dict:
    return json.loads(ARTIFACT.read_text())


def test_learned_policy_stage1_concludes_rl_not_justified() -> None:
    artifact = load_artifact()
    metrics = artifact["metrics"]

    assert metrics["candidate_score"] <= metrics["baseline_score"]
    assert metrics["score_margin"] <= 0
    assert metrics["recommendation"] == "StopBaselineNotBeaten"
    assert metrics["rl_justified"] is False
    assert artifact["conclusion"] == "deterministic significance is sufficient; RL not justified"


def test_learned_policy_trace_preserves_never_delete_property() -> None:
    artifact = load_artifact()

    for decision in artifact["action_trace"]:
        action_name = decision["candidate_action"]["name"]
        before = decision["state_before"]
        after = decision["state_after_candidate"]

        assert action_name in ALLOWED_ACTIONS
        assert action_name not in DESTRUCTIVE_ACTIONS
        assert not decision["invariant_violations"]
        assert after["memory_id"] == decision["memory_id"]
        assert after["deleted"] is False
        assert after["overwritten"] is False
        assert set(before["source_memory_ids"]) <= set(after["source_memory_ids"])


def test_learned_policy_trace_preserves_floor_and_pin_properties() -> None:
    artifact = load_artifact()

    for decision in artifact["action_trace"]:
        action = decision["candidate_action"]
        before = decision["state_before"]
        after = decision["state_after_candidate"]
        floor_rank = TIER_RANK[before["credence_floor"]]

        assert TIER_RANK[after["tier"]] >= floor_rank
        assert TIER_RANK[after["credence_floor"]] >= floor_rank

        if before["pinned"]:
            assert action["name"] != "demote"
            assert after["pinned"] is True

        if action["name"] == "demote":
            assert TIER_RANK[action["to"]] >= floor_rank
