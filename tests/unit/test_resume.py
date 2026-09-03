from __future__ import annotations

import json

import pytest

from blender_vse.resume import CAPSULE_POLICY, ResumeCapsuleError, build_resume_capsule


def _size(value: dict) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested for item in value.values() for nested in _keys(item)
        }
    if isinstance(value, list):
        return {nested for item in value for nested in _keys(item)}
    return set()


def test_resume_capsule_is_deterministic_and_never_accepts_ephemeral_state() -> None:
    inputs = {
        "project": "/projects/demo.blend",
        "objective": "Tighten the opening interview",
        "last_verified_revision": 12,
        "last_verified_timeline_hash": "abc123",
        "completed_actions": ["removed false start", "balanced dialogue"],
        "patch_ids": ["patch-11", "patch-12"],
        "relevant_strip_ids": ["clip-a", "audio-a"],
        "next_action": "read frames 300-420 with audio and source",
    }
    first = build_resume_capsule(**inputs)
    second = build_resume_capsule(**inputs)

    assert first == second
    assert first["confirmed"] == {"revision": 12, "timeline_hash": "abc123"}
    assert first["history"]["patch_ids"]["recent"] == ["patch-11", "patch-12"]
    assert _size(first) == first["context"]["response_bytes"]
    assert _size(first) <= first["context"]["max_bytes"]
    assert "observation_id" not in _keys(first)
    assert "cursor" not in _keys(first)


def test_long_histories_keep_recent_evidence_plus_full_digest() -> None:
    patch_ids = [f"patch-{index:05d}" for index in range(10_000)]
    first = build_resume_capsule(
        project="/projects/long-session.blend",
        objective="Continue the approved long edit",
        last_verified_revision=10_000,
        last_verified_timeline_hash="f" * 64,
        completed_actions=[f"completed action {index}" for index in range(2_000)],
        patch_ids=patch_ids,
        relevant_strip_ids=[f"strip-{index}" for index in range(1_000)],
        user_constraints=[f"constraint {index}" for index in range(200)],
        unresolved_blockers=[f"blocker {index}" for index in range(200)],
        output_paths=[f"/outputs/version-{index}.mp4" for index in range(200)],
    )
    changed_old_history = build_resume_capsule(
        project="/projects/long-session.blend",
        objective="Continue the approved long edit",
        patch_ids=["different-old-entry", *patch_ids[1:]],
    )

    history = first["history"]["patch_ids"]
    assert history["total"] == 10_000
    assert history["shown"] <= CAPSULE_POLICY["recent_limits"]["patch_ids"]
    assert history["recent"][-1] == "patch-09999"
    assert history["omitted"] == history["total"] - history["shown"]
    assert all(index < history["shown"] for index in history["truncated_recent"])
    assert history["sha256"] != changed_old_history["history"]["patch_ids"]["sha256"]
    assert _size(first) <= int(CAPSULE_POLICY["max_bytes"])


def test_capsule_truncates_utf8_by_bytes_and_reports_fields() -> None:
    capsule = build_resume_capsule(
        project="/projects/" + "片" * 2_000 + ".blend",
        objective="目标" * 4_000,
        next_action="下一步" * 2_000,
        completed_actions=["动作" * 1_000],
    )
    limits = CAPSULE_POLICY["field_bytes"]
    assert len(capsule["project"].encode("utf-8")) <= limits["project"]
    assert len(capsule["objective"].encode("utf-8")) <= limits["objective"]
    assert "project" in capsule["truncated_fields"]
    assert "objective" in capsule["truncated_fields"]
    assert capsule["history"]["completed_actions"]["truncated_recent"] in ([0], [])
    assert _size(capsule) <= int(CAPSULE_POLICY["max_bytes"])


def test_capsule_shrinks_histories_then_large_fields(monkeypatch) -> None:
    monkeypatch.setitem(CAPSULE_POLICY, "max_bytes", 2500)
    capsule = build_resume_capsule(
        project="p" * 2_000,
        objective="o" * 2_000,
        next_action="n" * 2_000,
        completed_actions=[
            {"index": index, "action": "x" * 300} for index in range(20)
        ],
        patch_ids=["p" * 300 for _ in range(20)],
        relevant_strip_ids=list(range(20)),
    )

    assert _size(capsule) <= 2500
    assert (
        capsule["history"]["patch_ids"]["shown"]
        < CAPSULE_POLICY["recent_limits"]["patch_ids"]
    )
    assert (
        len(capsule["objective"].encode("utf-8"))
        < CAPSULE_POLICY["field_bytes"]["objective"]
    )
    assert "objective" in capsule["truncated_fields"]


def test_capsule_fails_closed_when_policy_budget_is_impossible(monkeypatch) -> None:
    monkeypatch.setitem(CAPSULE_POLICY, "max_bytes", 100)
    with pytest.raises(ResumeCapsuleError, match="context budget"):
        build_resume_capsule(project="demo.blend", objective="edit")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"project": "", "objective": "edit"}, "project"),
        ({"project": "demo.blend", "objective": ""}, "objective"),
        (
            {
                "project": "demo.blend",
                "objective": "edit",
                "last_verified_revision": -1,
            },
            "last_verified_revision",
        ),
    ],
)
def test_capsule_rejects_invalid_core_state(kwargs: dict, message: str) -> None:
    with pytest.raises(ResumeCapsuleError, match=message):
        build_resume_capsule(**kwargs)
