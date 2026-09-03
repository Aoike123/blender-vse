"""Replay stateful scenarios and measure bounded long-session context growth."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

context_module = importlib.import_module("blender_vse.context")
resume_module = importlib.import_module("blender_vse.resume")
CONTEXT_POLICY = context_module.CONTEXT_POLICY
ReadQuery = context_module.ReadQuery
project_patch_result = context_module.project_patch_result
project_read_result = context_module.project_read_result
build_resume_capsule = resume_module.build_resume_capsule

SCENARIOS = ROOT / "evals" / "stateful-scenarios.json"
BASELINE = ROOT / "evals" / "baseline.json"
CAPSULE_SCHEMA = ROOT / "src" / "blender_vse" / "schemas" / "resume-capsule.schema.json"


def _size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


class WorkflowOracle:
    def __init__(self) -> None:
        self.revision = 1
        self.timeline_hash = "timeline-1"
        self.observation: tuple[int, str] | None = None
        self.targeted = False
        self.cursor: tuple[int, str] | None = None
        self.applied: set[str] = set()
        self.patch_ids: list[str] = []
        self.completed: list[str] = []

    def observe(self, *, targeted: bool, has_more: bool = False) -> str:
        self.observation = (self.revision, self.timeline_hash)
        self.targeted = targeted
        self.cursor = (self.revision, self.timeline_hash) if has_more else None
        return "ok"

    def act(self, step: dict[str, Any]) -> str:
        action = step["action"]
        if action == "read_summary":
            return self.observe(targeted=False)
        if action in {"read_detail", "read_range"}:
            if step.get("oversized"):
                return "context_budget_exceeded"
            return self.observe(
                targeted=True,
                has_more=bool(step.get("has_more")),
            )
        if action == "manual_edit":
            self.timeline_hash = f"manual-{self.revision}-{len(self.completed)}"
            return "manual_change"
        if action == "page":
            if self.cursor is None:
                return "invalid_cursor"
            if self.cursor != (self.revision, self.timeline_hash):
                self.cursor = None
                return "stale_cursor"
            return self.observe(targeted=True)
        if action == "compact":
            capsule = build_resume_capsule(
                project="/projects/eval.blend",
                objective="Complete the scenario",
                last_verified_revision=self.revision,
                last_verified_timeline_hash=self.timeline_hash,
                completed_actions=self.completed,
                patch_ids=self.patch_ids,
                next_action="read summary, then targeted detail",
            )
            if _size(capsule) > capsule["context"]["max_bytes"]:
                raise AssertionError("oracle compaction exceeded capsule budget")
            self.observation = None
            self.targeted = False
            self.cursor = None
            return "compacted"
        if action == "acknowledge":
            if self.observation is None:
                return "read_required"
            if self.observation != (self.revision, self.timeline_hash):
                return "stale_observation"
            self.revision += 1
            self.observation = None
            self.targeted = False
            return "acknowledged"
        if action == "patch":
            patch_id = str(step.get("patch_id") or "")
            if patch_id in self.applied:
                return "already_applied"
            commands = list(step.get("commands") or [])
            if "restore_checkpoint" in commands and len(commands) != 1:
                return "invalid_args"
            if self.observation is None:
                return "read_required"
            if self.observation != (self.revision, self.timeline_hash):
                return "stale_base"
            if not self.targeted:
                return "targeted_read_required"
            self.applied.add(patch_id)
            self.patch_ids.append(patch_id)
            self.completed.append("+".join(commands))
            self.revision += 1
            self.timeline_hash = f"timeline-{self.revision}"
            self.observation = None
            self.targeted = False
            self.cursor = None
            return "applied"
        if action == "verify":
            return "verified"
        if action == "project_denied":
            return "project_not_allowed"
        if action == "missing_tools":
            return "setup_required"
        raise AssertionError(f"unknown eval action: {action}")


def replay_scenarios(minimums: dict[str, int]) -> dict[str, int]:
    payload = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    scenarios = payload["scenarios"]
    identifiers = [scenario["id"] for scenario in scenarios]
    if len(identifiers) != len(set(identifiers)):
        raise AssertionError("scenario IDs must be unique")
    positives = sum(bool(scenario["should_trigger"]) for scenario in scenarios)
    negatives = len(scenarios) - positives
    if (
        len(scenarios) < minimums["total"]
        or positives < minimums["positive"]
        or negatives < minimums["negative"]
    ):
        raise AssertionError("eval corpus needs positive and negative routing cases")

    steps_run = 0
    for scenario in scenarios:
        oracle = WorkflowOracle()
        actions = [step["action"] for step in scenario["steps"]]
        forbidden = set(scenario["forbidden_actions"])
        overlap = forbidden.intersection(actions)
        if overlap:
            raise AssertionError(f"{scenario['id']} uses forbidden actions: {overlap}")
        if not scenario["should_trigger"] and actions:
            raise AssertionError(f"negative scenario {scenario['id']} has tool actions")
        for step in scenario["steps"]:
            actual = oracle.act(step)
            if actual != step["expect"]:
                raise AssertionError(
                    f"{scenario['id']} {step['action']}: "
                    f"expected {step['expect']}, got {actual}"
                )
            steps_run += 1
    return {
        "scenarios": len(scenarios),
        "positive": positives,
        "negative": negatives,
        "steps": steps_run,
    }


def _timeline(strip_count: int = 1_000) -> dict[str, Any]:
    return {
        "scene": "VideoEditing",
        "fps": 30,
        "resolution": [1920, 1080],
        "frame_start": 1,
        "frame_end": strip_count * 30,
        "strips": [
            {
                "video_ai_id": f"strip-{index}",
                "id": f"Strip {index}",
                "name": f"Strip {index}",
                "type": "TEXT" if index % 10 == 0 else "MOVIE",
                "channel": index % 8 + 1,
                "frame_start": index * 30 + 1,
                "frame_end": index * 30 + 30,
                "text": "caption " + ("x" * 256),
            }
            for index in range(strip_count)
        ],
    }


def measure_long_session(cycles: int = 250, compact_every: int = 25) -> dict[str, Any]:
    timeline = _timeline()
    session = {"ready": True, "gui_visible": True, "project": "eval.blend"}
    patch_ids: list[str] = []
    completed: list[str] = []
    naive_bytes = 0
    active_bytes = 0
    peak_active_bytes = 0
    max_tool_result_bytes = 0
    capsules = 0
    final_capsule: dict[str, Any] | None = None

    for index in range(1, cycles + 1):
        base = {
            "project": "/projects/long-session.blend",
            "revision": index,
            "timeline_hash": f"hash-{index:05d}",
            "observation_id": f"observation-{index:05d}",
            "session": session,
        }
        target = f"strip-{(index * 17) % len(timeline['strips'])}"
        summary = project_read_result(
            base=base,
            timeline=timeline,
            query=ReadQuery.create(view="summary"),
        )
        detail = project_read_result(
            base=base,
            timeline=timeline,
            query=ReadQuery.create(
                view="detail",
                strip_ids=[target],
                include=["text"],
                limit=1,
            ),
        )
        patch_id = f"patch-{index:05d}"
        patch = project_patch_result(
            {
                "patch_id": patch_id,
                "applied": True,
                "base_revision": index,
                "applied_revision": index + 1,
                "committed": True,
                "timeline_hash": f"hash-{index + 1:05d}",
                "results": [{"index": 0, "op": "set_text", "ok": True}],
                "payloads": [{"video_ai_id": target, "text": "updated"}],
            },
            session=session,
        )
        results = (summary, detail, patch)
        for result in results:
            size = _size(result)
            if size > result["context"]["max_bytes"]:
                raise AssertionError("tool result exceeded its declared budget")
            max_tool_result_bytes = max(max_tool_result_bytes, size)
            naive_bytes += size
            active_bytes += size
        peak_active_bytes = max(peak_active_bytes, active_bytes)
        patch_ids.append(patch_id)
        completed.append(f"updated {target}")

        if index % compact_every == 0:
            final_capsule = build_resume_capsule(
                project=base["project"],
                objective=f"Complete a {cycles}-step editorial pass without losing user intent",
                last_verified_revision=index + 1,
                last_verified_timeline_hash=f"hash-{index + 1:05d}",
                completed_actions=completed,
                patch_ids=patch_ids,
                relevant_strip_ids=[target],
                user_constraints=["preserve manual edits", "never use full view"],
                output_paths=["/outputs/long-session.mp4"],
                next_action="read summary, then the next target detail",
            )
            active_bytes = _size(final_capsule)
            capsules += 1

    if final_capsule is None:
        raise AssertionError("long session never compacted")
    schema = json.loads(CAPSULE_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(final_capsule, schema)
    if final_capsule["history"]["patch_ids"]["total"] != cycles:
        raise AssertionError("resume capsule lost the full patch count")
    if final_capsule["history"]["patch_ids"]["recent"][-1] != patch_ids[-1]:
        raise AssertionError("resume capsule lost the latest patch ID")
    return {
        "cycles": cycles,
        "timeline_strips": len(timeline["strips"]),
        "compactions": capsules,
        "naive_context_bytes": naive_bytes,
        "peak_active_context_bytes": peak_active_bytes,
        "final_capsule_bytes": _size(final_capsule),
        "max_tool_result_bytes": max_tool_result_bytes,
        "naive_to_peak_ratio": round(naive_bytes / peak_active_bytes, 2),
    }


def main() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    if baseline["context_protocol"] != CONTEXT_POLICY["version"]:
        raise AssertionError("eval baseline targets a different context protocol")
    settings = baseline["long_session"]
    scenarios = replay_scenarios(baseline["scenario_minimums"])
    long_session = measure_long_session(
        cycles=int(settings["cycles"]),
        compact_every=int(settings["compact_every"]),
    )
    if long_session["timeline_strips"] != settings["timeline_strips"]:
        raise AssertionError("long-session timeline size differs from the baseline")
    for actual_key, limit_key in (
        ("peak_active_context_bytes", "max_peak_active_context_bytes"),
        ("final_capsule_bytes", "max_final_capsule_bytes"),
        ("max_tool_result_bytes", "max_tool_result_bytes"),
    ):
        if long_session[actual_key] > settings[limit_key]:
            raise AssertionError(f"{actual_key} exceeded the eval baseline")
    if long_session["naive_to_peak_ratio"] < settings["min_naive_to_peak_ratio"]:
        raise AssertionError("compaction ratio fell below the eval baseline")
    report = {
        "scenario_eval": scenarios,
        "long_session": long_session,
        "context_protocol": CONTEXT_POLICY["version"],
        "baseline_version": baseline["version"],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
