"""Bounded resume capsules for context compaction and task handoff."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .context import CONTEXT_POLICY, CONTEXT_PROTOCOL_VERSION

CAPSULE_POLICY: Mapping[str, Any] = CONTEXT_POLICY["compaction"]["capsule"]
HISTORY_FIELDS = tuple(CAPSULE_POLICY["recent_limits"])


class ResumeCapsuleError(ValueError):
    """Stable validation or budget failure while building a resume capsule."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _json_size(value: Any) -> int:
    return len(_json_bytes(value))


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple)):
        return _json_bytes(value).decode("utf-8")
    return str(value)


def _truncate(value: Any, byte_limit: int) -> tuple[str, bool]:
    encoded = _text(value).encode("utf-8")
    if len(encoded) <= byte_limit:
        return encoded.decode("utf-8"), False
    return encoded[:byte_limit].decode("utf-8", errors="ignore"), True


def _history_digest(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _history(values: Iterable[Any], *, limit: int, item_bytes: int) -> dict[str, Any]:
    normalized = [_text(value) for value in values]
    selected = normalized[-limit:] if limit else []
    recent: list[str] = []
    truncated_recent: list[int] = []
    for value in selected:
        bounded, truncated = _truncate(value, item_bytes)
        recent.append(bounded)
        if truncated:
            truncated_recent.append(len(recent) - 1)
    return {
        "total": len(normalized),
        "shown": len(recent),
        "omitted": len(normalized) - len(recent),
        "truncated_recent": truncated_recent,
        "sha256": _history_digest(normalized),
        "recent": recent,
    }


def _settle_size(capsule: dict[str, Any]) -> int:
    context = capsule["context"]
    for _ in range(3):
        context["response_bytes"] = _json_size(capsule)
    return int(context["response_bytes"])


def _shrink_histories(capsule: dict[str, Any], max_bytes: int) -> None:
    histories = capsule["history"]
    while _settle_size(capsule) > max_bytes:
        candidates = [
            (name, _json_size(summary["recent"]))
            for name, summary in histories.items()
            if summary["recent"]
        ]
        if not candidates:
            return
        name = max(candidates, key=lambda item: (item[1], item[0]))[0]
        summary = histories[name]
        summary["recent"].pop(0)
        summary["truncated_recent"] = [
            index - 1 for index in summary["truncated_recent"] if index > 0
        ]
        summary["shown"] = len(summary["recent"])
        summary["omitted"] = summary["total"] - summary["shown"]


def _shrink_fields(capsule: dict[str, Any], max_bytes: int) -> None:
    candidates = (
        ("objective", 128),
        ("next_action", 128),
        ("project", 256),
    )
    truncated = set(capsule["truncated_fields"])
    while _settle_size(capsule) > max_bytes:
        changed = False
        for field, minimum in candidates:
            value = capsule[field]
            current = len(value.encode("utf-8"))
            if current <= minimum:
                continue
            capsule[field], _ = _truncate(value, max(minimum, current // 2))
            truncated.add(field)
            changed = True
            if _settle_size(capsule) <= max_bytes:
                break
        if not changed:
            break
    capsule["truncated_fields"] = sorted(truncated)


def build_resume_capsule(
    *,
    project: str | Path,
    objective: str,
    last_verified_revision: int | None = None,
    last_verified_timeline_hash: str | None = None,
    completed_actions: Iterable[Any] = (),
    patch_ids: Iterable[Any] = (),
    relevant_strip_ids: Iterable[Any] = (),
    user_constraints: Iterable[Any] = (),
    unresolved_blockers: Iterable[Any] = (),
    output_paths: Iterable[Any] = (),
    next_action: str = "read summary, then targeted detail",
) -> dict[str, Any]:
    """Build a deterministic, byte-bounded context resume capsule.

    Observation IDs and pagination cursors are deliberately not accepted. Long
    histories keep recent entries plus a total count and digest of the full
    sequence, so repeated compaction cannot grow the active context without a
    bound.
    """

    if last_verified_revision is not None and (
        type(last_verified_revision) is not int or last_verified_revision < 0
    ):
        raise ResumeCapsuleError(
            "last_verified_revision must be a non-negative integer or null"
        )
    if not str(project).strip():
        raise ResumeCapsuleError("project must be a non-empty path")
    if not str(objective).strip():
        raise ResumeCapsuleError("objective must be non-empty")

    field_limits = CAPSULE_POLICY["field_bytes"]
    top_values = {
        "project": _truncate(project, int(field_limits["project"])),
        "objective": _truncate(objective, int(field_limits["objective"])),
        "next_action": _truncate(next_action, int(field_limits["next_action"])),
    }
    timeline_hash, hash_truncated = _truncate(
        last_verified_timeline_hash or "", int(field_limits["timeline_hash"])
    )
    histories = {
        "completed_actions": completed_actions,
        "patch_ids": patch_ids,
        "relevant_strip_ids": relevant_strip_ids,
        "user_constraints": user_constraints,
        "unresolved_blockers": unresolved_blockers,
        "output_paths": output_paths,
    }
    item_bytes = int(field_limits["history_item"])
    capsule: dict[str, Any] = {
        "capsule_version": str(CAPSULE_POLICY["version"]),
        "project": top_values["project"][0],
        "objective": top_values["objective"][0],
        "confirmed": {
            "revision": last_verified_revision,
            "timeline_hash": timeline_hash,
        },
        "history": {
            name: _history(
                values,
                limit=int(CAPSULE_POLICY["recent_limits"][name]),
                item_bytes=item_bytes,
            )
            for name, values in histories.items()
        },
        "next_action": top_values["next_action"][0],
        "resume": list(CONTEXT_POLICY["compaction"]["resume"]),
        "truncated_fields": sorted(
            [
                name
                for name, (_value, was_truncated) in top_values.items()
                if was_truncated
            ]
            + (["confirmed.timeline_hash"] if hash_truncated else [])
        ),
        "context": {
            "protocol_version": CONTEXT_PROTOCOL_VERSION,
            "view": "resume_capsule",
            "bounded": True,
            "max_bytes": int(CAPSULE_POLICY["max_bytes"]),
            "response_bytes": 0,
        },
    }
    max_bytes = int(CAPSULE_POLICY["max_bytes"])
    _shrink_histories(capsule, max_bytes)
    _shrink_fields(capsule, max_bytes)
    if _settle_size(capsule) > max_bytes:
        raise ResumeCapsuleError("resume capsule exceeds its context budget")
    return capsule


__all__ = [
    "CAPSULE_POLICY",
    "HISTORY_FIELDS",
    "ResumeCapsuleError",
    "build_resume_capsule",
]
