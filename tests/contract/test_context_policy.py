from __future__ import annotations

import inspect
import json
from importlib import resources

from blender_vse.api import BlenderVSE
from blender_vse.context import (
    CONTEXT_POLICY,
    CONTEXT_PROTOCOL_VERSION,
    DEFAULT_READ_VIEW,
    INCLUDE_GROUPS,
    READ_VIEWS,
)


def test_packaged_policy_is_the_runtime_source_of_truth() -> None:
    packaged = json.loads(
        resources.files("blender_vse")
        .joinpath("context-policy.json")
        .read_text(encoding="utf-8")
    )
    assert packaged == CONTEXT_POLICY
    assert packaged["version"] == CONTEXT_PROTOCOL_VERSION


def test_read_api_defaults_to_summary() -> None:
    signature = inspect.signature(BlenderVSE.read)
    assert signature.parameters["view"].default == DEFAULT_READ_VIEW == "summary"


def test_bounded_views_have_explicit_budgets() -> None:
    assert CONTEXT_POLICY["envelope_headroom_bytes"] == 512
    assert READ_VIEWS == {"summary", "range", "detail", "full"}
    for view in ("summary", "range", "detail"):
        policy = CONTEXT_POLICY["views"][view]
        assert policy["bounded"] is True
        assert 0 < policy["max_bytes"] <= 16_384
    assert CONTEXT_POLICY["views"]["full"]["explicit_only"] is True
    assert CONTEXT_POLICY["views"]["full"]["bounded"] is False


def test_optional_field_groups_are_declared_once() -> None:
    assert INCLUDE_GROUPS == set(CONTEXT_POLICY["strip_fields"]["includes"])
    assert INCLUDE_GROUPS == {
        "text",
        "source",
        "transform",
        "audio",
        "proxy",
        "metadata",
    }


def test_query_limits_match_bounded_protocol() -> None:
    assert CONTEXT_POLICY["query_limits"] == {
        "max_strip_ids": 200,
        "max_channels": 128,
        "max_strip_types": 32,
    }


def test_every_model_facing_tool_result_has_a_budget() -> None:
    results = CONTEXT_POLICY["tool_results"]
    assert set(results) == {"patch", "acknowledge", "verify", "error"}
    assert all(0 < settings["max_bytes"] <= 8192 for settings in results.values())
    assert results["patch"]["max_commands"] == 100


def test_compaction_policy_never_carries_observation_tokens() -> None:
    compaction = CONTEXT_POLICY["compaction"]
    assert not (set(compaction["preserve"]) & set(compaction["discard"]))
    assert "observation_id" in compaction["discard"]
    assert "project" in compaction["preserve"]
    assert any("new observation_id" in step for step in compaction["resume"])
    capsule = compaction["capsule"]
    assert capsule["max_bytes"] == 4096
    assert capsule["recent_limits"]["patch_ids"] <= 16
    assert set(capsule["recent_limits"]) == {
        "completed_actions",
        "patch_ids",
        "relevant_strip_ids",
        "user_constraints",
        "unresolved_blockers",
        "output_paths",
    }
    assert "cursor" in compaction["discard"]
