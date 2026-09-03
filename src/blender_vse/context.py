"""Bounded timeline projections for long-running agent contexts."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

CONTEXT_PROTOCOL_VERSION = "1.1"
CONTEXT_POLICY: dict[str, Any] = json.loads(
    resources.files(__package__)
    .joinpath("context-policy.json")
    .read_text(encoding="utf-8")
)
READ_VIEWS = frozenset(CONTEXT_POLICY["views"])
DEFAULT_READ_VIEW = str(CONTEXT_POLICY["default_view"])
INCLUDE_GROUPS = frozenset(CONTEXT_POLICY["strip_fields"]["includes"])


class ContextQueryError(ValueError):
    """A stable validation failure for bounded timeline reads."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _tuple(values: Iterable[Any] | None) -> tuple[Any, ...]:
    return tuple(values or ())


@dataclass(frozen=True)
class ReadQuery:
    """Validated query controlling what timeline data enters model context."""

    view: str = DEFAULT_READ_VIEW
    frame_range: tuple[int, int] | None = None
    strip_ids: tuple[str, ...] = ()
    channels: tuple[int, ...] = ()
    strip_types: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    cursor: str | None = None
    limit: int | None = None

    @classmethod
    def create(
        cls,
        *,
        view: str = DEFAULT_READ_VIEW,
        frame_range: Iterable[int] | None = None,
        strip_ids: Iterable[str] | None = None,
        channels: Iterable[int] | None = None,
        strip_types: Iterable[str] | None = None,
        include: Iterable[str] | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> ReadQuery:
        normalized_view = str(view).strip().lower()
        if normalized_view not in READ_VIEWS:
            raise ContextQueryError(
                "invalid_read_query",
                f"unknown read view: {view}; use {sorted(READ_VIEWS)}",
            )

        normalized_range = None
        if frame_range is not None:
            items = tuple(frame_range)
            if len(items) != 2 or any(type(item) is not int for item in items):
                raise ContextQueryError(
                    "invalid_read_query", "frame_range must contain two integers"
                )
            if items[0] > items[1]:
                raise ContextQueryError(
                    "invalid_read_query", "frame_range start must be <= end"
                )
            normalized_range = (items[0], items[1])

        id_values = _tuple(strip_ids)
        if strip_ids is not None and (
            not id_values
            or any(
                not isinstance(value, str) or not value.strip() for value in id_values
            )
        ):
            raise ContextQueryError(
                "invalid_read_query", "strip_ids must contain non-empty strings"
            )
        normalized_ids = tuple(value.strip() for value in id_values)
        query_limits = CONTEXT_POLICY["query_limits"]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ContextQueryError("invalid_read_query", "strip_ids must be unique")
        if len(id_values) > int(query_limits["max_strip_ids"]):
            raise ContextQueryError(
                "invalid_read_query",
                f"strip_ids accepts at most {query_limits['max_strip_ids']} values",
            )
        channel_values = _tuple(channels)
        if any(
            type(value) is not int or value < 1 or value > 128
            for value in channel_values
        ):
            raise ContextQueryError(
                "invalid_read_query", "channels must be integers between 1 and 128"
            )
        if channels is not None and not channel_values:
            raise ContextQueryError(
                "invalid_read_query", "channels must contain at least one value"
            )
        if len(channel_values) != len(set(channel_values)):
            raise ContextQueryError("invalid_read_query", "channels must be unique")
        normalized_channels = channel_values
        if len(channel_values) > int(query_limits["max_channels"]):
            raise ContextQueryError(
                "invalid_read_query",
                f"channels accepts at most {query_limits['max_channels']} values",
            )
        type_values = _tuple(strip_types)
        if strip_types is not None and (
            not type_values
            or any(
                not isinstance(value, str) or not value.strip() for value in type_values
            )
        ):
            raise ContextQueryError(
                "invalid_read_query", "strip_types must contain non-empty strings"
            )
        normalized_types = tuple(value.strip().upper() for value in type_values)
        if len(normalized_types) != len(set(normalized_types)):
            raise ContextQueryError("invalid_read_query", "strip_types must be unique")
        if len(type_values) > int(query_limits["max_strip_types"]):
            raise ContextQueryError(
                "invalid_read_query",
                f"strip_types accepts at most {query_limits['max_strip_types']} values",
            )
        include_values = _tuple(include)
        if include is not None and (
            not include_values
            or any(
                not isinstance(value, str) or not value.strip()
                for value in include_values
            )
        ):
            raise ContextQueryError(
                "invalid_read_query", "include must contain non-empty strings"
            )
        normalized_include = tuple(value.strip().lower() for value in include_values)
        if len(normalized_include) != len(set(normalized_include)):
            raise ContextQueryError(
                "invalid_read_query", "include groups must be unique"
            )
        unknown_includes = sorted(set(normalized_include) - INCLUDE_GROUPS)
        if unknown_includes:
            raise ContextQueryError(
                "invalid_read_query",
                f"unknown include groups: {unknown_includes}; use {sorted(INCLUDE_GROUPS)}",
            )

        view_policy = CONTEXT_POLICY["views"][normalized_view]
        paged = bool(view_policy["paged"])
        if not paged and (cursor is not None or limit is not None):
            raise ContextQueryError(
                "invalid_read_query",
                f"{normalized_view} view does not accept cursor or limit",
            )
        if normalized_view == "range" and normalized_range is None:
            raise ContextQueryError(
                "invalid_read_query", "range view requires frame_range"
            )
        if normalized_view == "detail" and not (
            normalized_ids
            or normalized_channels
            or normalized_types
            or normalized_range
        ):
            raise ContextQueryError(
                "invalid_read_query",
                "detail view requires strip_ids, channels, strip_types, or frame_range",
            )
        if normalized_view == "summary" and normalized_include:
            raise ContextQueryError(
                "invalid_read_query",
                "summary view does not return optional strip fields",
            )
        if normalized_view == "full" and (
            frame_range is not None
            or strip_ids is not None
            or channels is not None
            or strip_types is not None
            or include is not None
        ):
            raise ContextQueryError(
                "invalid_read_query", "full compatibility view does not accept filters"
            )

        normalized_limit = None
        if paged:
            if type(limit) is bool:
                raise ContextQueryError(
                    "invalid_read_query", "limit must be an integer"
                )
            try:
                normalized_limit = int(
                    limit if limit is not None else view_policy["default_limit"]
                )
            except (TypeError, ValueError) as exc:
                raise ContextQueryError(
                    "invalid_read_query", "limit must be an integer"
                ) from exc
            if normalized_limit < 1 or normalized_limit > int(view_policy["max_limit"]):
                raise ContextQueryError(
                    "invalid_read_query",
                    f"limit must be between 1 and {view_policy['max_limit']}",
                )

        return cls(
            view=normalized_view,
            frame_range=normalized_range,
            strip_ids=normalized_ids,
            channels=normalized_channels,
            strip_types=normalized_types,
            include=normalized_include,
            cursor=cursor,
            limit=normalized_limit,
        )

    @property
    def with_text(self) -> bool:
        return self.view == "full" or "text" in self.include

    def fingerprint(self) -> str:
        payload = {
            "view": self.view,
            "frame_range": self.frame_range,
            "strip_ids": self.strip_ids,
            "channels": self.channels,
            "strip_types": self.strip_types,
            "include": self.include,
            "limit": self.limit,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _encode_cursor(
    *,
    offset: int,
    revision: int,
    timeline_hash: str,
    query_fingerprint: str,
) -> str:
    payload = {
        "v": 1,
        "o": offset,
        "r": revision,
        "h": timeline_hash,
        "q": query_fingerprint,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str,
    *,
    revision: int,
    timeline_hash: str,
    query_fingerprint: str,
) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
    except Exception as exc:
        raise ContextQueryError("invalid_cursor", "cursor is not valid") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ContextQueryError("invalid_cursor", "cursor version is not supported")
    if payload.get("r") != revision or payload.get("h") != timeline_hash:
        raise ContextQueryError(
            "stale_cursor", "timeline changed; restart the bounded read from page one"
        )
    if payload.get("q") != query_fingerprint:
        raise ContextQueryError(
            "invalid_cursor", "cursor does not match the current read query"
        )
    offset = payload.get("o")
    if type(offset) is not int or offset < 0:
        raise ContextQueryError("invalid_cursor", "cursor offset is invalid")
    return offset


def _json_size(value: Any) -> int:
    return len(
        json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")
    )


def _payload_budget(context: Mapping[str, Any]) -> int:
    return int(context["max_bytes"]) - int(CONTEXT_POLICY["envelope_headroom_bytes"])


def _truncate_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


def _bounded_string(value: Any, limit: int) -> tuple[Any, bool]:
    if not isinstance(value, str) or len(value.encode("utf-8")) <= limit:
        return value, False
    return _truncate_utf8(value, limit), True


def _bounded_object(value: Any, limit: int) -> tuple[Any, bool]:
    if _json_size(value) <= limit:
        return value, False
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    preview = _truncate_utf8(serialized, max(0, limit - 128))
    bounded = {"truncated": True, "preview": preview}
    while preview and _json_size(bounded) > limit:
        preview = _truncate_utf8(preview, max(0, len(preview.encode("utf-8")) - 64))
        bounded["preview"] = preview
    return bounded, True


def _project_strip(
    strip: Mapping[str, Any], include: tuple[str, ...]
) -> dict[str, Any]:
    fields = CONTEXT_POLICY["strip_fields"]
    selected = list(fields["core"])
    for group in include:
        selected.extend(fields["includes"][group])
    limits = CONTEXT_POLICY["value_limits"]
    result: dict[str, Any] = {}
    truncated: list[str] = []
    for name in dict.fromkeys(selected):
        if name not in strip:
            continue
        value = strip[name]
        if name in {"video_ai_id", "id", "name"}:
            value, shortened = _bounded_string(value, limits["identifier_bytes"])
        elif name == "text":
            value, shortened = _bounded_string(value, limits["text_bytes"])
        elif name == "source_path":
            value, shortened = _bounded_string(value, limits["path_bytes"])
        elif isinstance(value, (dict, list, tuple)):
            value, shortened = _bounded_object(value, limits["object_bytes"])
        else:
            shortened = False
        result[name] = value
        if shortened:
            truncated.append(name)
    if truncated:
        result["_truncated_fields"] = sorted(truncated)
    return result


def _matches(strip: Mapping[str, Any], query: ReadQuery) -> bool:
    if query.strip_ids:
        references = {
            str(strip.get("video_ai_id") or ""),
            str(strip.get("id") or ""),
            str(strip.get("name") or ""),
        }
        if not references.intersection(query.strip_ids):
            return False
    if query.channels and strip.get("channel") not in query.channels:
        return False
    if (
        query.strip_types
        and str(strip.get("type") or "").upper() not in query.strip_types
    ):
        return False
    if query.frame_range:
        start, end = query.frame_range
        strip_start = int(strip.get("frame_start") or 0)
        strip_end = int(strip.get("frame_end") or 0)
        if strip_end < start or strip_start > end:
            return False
    return True


def _summary(
    all_strips: list[Mapping[str, Any]], matched: list[Mapping[str, Any]]
) -> dict:
    counts_by_type: dict[str, int] = {}
    counts_by_channel: dict[str, int] = {}
    for strip in matched:
        strip_type = str(strip.get("type") or "UNKNOWN")
        channel = str(strip.get("channel") or 0)
        counts_by_type[strip_type] = counts_by_type.get(strip_type, 0) + 1
        counts_by_channel[channel] = counts_by_channel.get(channel, 0) + 1
    starts = [int(strip.get("frame_start") or 0) for strip in matched]
    ends = [int(strip.get("frame_end") or 0) for strip in matched]
    return {
        "total_strips": len(all_strips),
        "matched_strips": len(matched),
        "counts_by_type": dict(sorted(counts_by_type.items())),
        "counts_by_channel": dict(
            sorted(counts_by_channel.items(), key=lambda item: int(item[0]))
        ),
        "content_bounds": [min(starts), max(ends)] if starts else None,
    }


def project_read_result(
    *,
    base: Mapping[str, Any],
    timeline: Mapping[str, Any],
    query: ReadQuery,
) -> dict[str, Any]:
    """Project a canonical full timeline into one context-bounded response."""

    revision = int(base.get("revision") or 0)
    timeline_hash = str(base.get("timeline_hash") or "")
    all_strips = [
        strip for strip in timeline.get("strips", []) if isinstance(strip, Mapping)
    ]

    common = {
        **dict(base),
        **{key: value for key, value in timeline.items() if key != "strips"},
    }
    common["project"] = base.get("project") or timeline.get("project")
    common["summary"] = _summary(all_strips, all_strips)

    if query.view == "full":
        result = {**common, "strips": list(all_strips)}
        result["context"] = {
            "protocol_version": CONTEXT_PROTOCOL_VERSION,
            "view": "full",
            "bounded": False,
            "response_bytes": 0,
        }
        result["context"]["response_bytes"] = _json_size(result)
        return result

    matched = [strip for strip in all_strips if _matches(strip, query)]
    common["summary"] = _summary(all_strips, matched)
    context = {
        "protocol_version": CONTEXT_PROTOCOL_VERSION,
        "view": query.view,
        "bounded": True,
        "max_bytes": int(CONTEXT_POLICY["views"][query.view]["max_bytes"]),
        "matched": len(matched),
        "returned": 0,
        "has_more": False,
        "next_cursor": None,
        "response_bytes": 0,
    }
    if query.view == "summary":
        result = {**common, "strips": [], "context": context}
        for _ in range(3):
            context["response_bytes"] = _json_size(result)
        if context["response_bytes"] > _payload_budget(context):
            raise ContextQueryError(
                "context_budget_exceeded", "summary response exceeds its context budget"
            )
        return result

    fingerprint = query.fingerprint()
    offset = 0
    if query.cursor:
        offset = _decode_cursor(
            query.cursor,
            revision=revision,
            timeline_hash=timeline_hash,
            query_fingerprint=fingerprint,
        )
    if offset > len(matched):
        raise ContextQueryError(
            "invalid_cursor", "cursor offset exceeds matched strips"
        )

    limit = int(query.limit or 0)
    projected = [
        _project_strip(strip, query.include)
        for strip in matched[offset : offset + limit]
    ]
    result = {**common, "strips": projected, "context": context}
    while True:
        returned = len(result["strips"])
        next_offset = offset + returned
        has_more = next_offset < len(matched)
        context.update(
            {
                "returned": returned,
                "has_more": has_more,
                "next_cursor": (
                    _encode_cursor(
                        offset=next_offset,
                        revision=revision,
                        timeline_hash=timeline_hash,
                        query_fingerprint=fingerprint,
                    )
                    if has_more
                    else None
                ),
            }
        )
        for _ in range(3):
            context["response_bytes"] = _json_size(result)
        if context["response_bytes"] <= _payload_budget(context):
            return result
        if len(result["strips"]) <= 1:
            raise ContextQueryError(
                "context_budget_exceeded",
                f"one {query.view} strip cannot fit within the context budget",
            )
        result["strips"].pop()


def _settle_size(result: dict[str, Any]) -> int:
    context = result["context"]
    for _ in range(3):
        context["response_bytes"] = _json_size(result)
    return int(context["response_bytes"])


def project_session_failure(session: Mapping[str, Any]) -> dict[str, Any]:
    """Project verbose session discovery into a bounded model-facing error."""

    policy = CONTEXT_POLICY["tool_results"]["error"]
    last = session.get("last_observation") or {}

    def value(name: str, default: Any = None) -> Any:
        return session.get(name, last.get(name, default))

    message, message_truncated = _bounded_string(
        value("message", "Blender session is not ready"), 1024
    )
    session_log, log_truncated = _bounded_string(value("session_log"), 1024)
    discovery = session.get("discovery") or {}
    states = [
        _bounded_string(str(state), 128)[0]
        for state in list(discovery.get("observed_states") or [])[:16]
    ]
    result = {
        "ready": False,
        "code": value("code", "session_not_ready"),
        "message": message,
        "connected": bool(value("connected", False)),
        "launched": bool(value("launched", False)),
        "pid": value("pid"),
        "project": value("filepath") or value("requested_project") or "",
        "is_dirty": bool(value("is_dirty", False)),
        "workspace": value("workspace"),
        "vse_area_count": int(value("vse_area_count", 0) or 0),
        "gui_visible": bool(value("gui_visible", False)),
        "session_log": session_log,
        "discovery": {
            "attempts": int(discovery.get("attempts") or 0),
            "waited_seconds": float(discovery.get("waited_seconds") or 0.0),
            "observed_states": states,
        },
        "diagnostics_omitted": True,
        "truncated_fields": sorted(
            name
            for name, truncated in {
                "message": message_truncated,
                "session_log": log_truncated,
            }.items()
            if truncated
        ),
        "context": {
            "protocol_version": CONTEXT_PROTOCOL_VERSION,
            "view": "error",
            "bounded": True,
            "max_bytes": int(policy["max_bytes"]),
            "response_bytes": 0,
        },
    }
    if _settle_size(result) > _payload_budget(result["context"]):
        raise ContextQueryError(
            "context_budget_exceeded", "session error projection exceeds its budget"
        )
    return result


def project_patch_result(
    data: Mapping[str, Any],
    *,
    session: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a bounded patch receipt; callers must read for fresh state."""

    policy = CONTEXT_POLICY["tool_results"]["patch"]
    core_keys = (
        "status",
        "patch_id",
        "applied",
        "base_revision",
        "applied_revision",
        "committed",
        "timeline_hash",
        "rolled_back",
        "error",
        "checkpoint_path",
        "pre_restore_backup",
        "gui_reloaded",
    )
    result = {key: data[key] for key in core_keys if key in data}
    if "error" in result:
        result["error"] = _bounded_string(result["error"], 512)[0]

    raw_results = [
        item for item in data.get("results", []) if isinstance(item, Mapping)
    ]
    operations = [str(item.get("op") or "") for item in raw_results]
    failures = [
        {
            "index": item.get("index"),
            "op": item.get("op"),
            "error": _bounded_string(item.get("error"), 256)[0],
        }
        for item in raw_results
        if not item.get("ok")
    ]
    max_failures = int(policy["max_failures"])
    result["commands"] = {
        "total": len(raw_results),
        "succeeded": sum(bool(item.get("ok")) for item in raw_results),
        "failed": sum(not bool(item.get("ok")) for item in raw_results),
        "operations": operations,
        "operations_omitted": 0,
        "failures": failures[:max_failures],
        "failures_omitted": max(0, len(failures) - max_failures),
    }

    raw_payloads = list(data.get("payloads", []))
    changes = []
    for index, payload in enumerate(raw_payloads):
        if not isinstance(payload, Mapping):
            continue
        bounded, truncated = _bounded_object(
            dict(payload), int(policy["payload_bytes"])
        )
        changes.append(
            {"index": index, "payload": bounded, "truncated": bool(truncated)}
        )
    result["changes"] = changes
    result["changes_omitted"] = len(raw_payloads) - len(changes)
    result["session"] = dict(session)
    result["next_action"] = "read summary or targeted detail before another patch"
    result["context"] = {
        "protocol_version": CONTEXT_PROTOCOL_VERSION,
        "view": "patch",
        "bounded": True,
        "max_bytes": int(policy["max_bytes"]),
        "response_bytes": 0,
    }
    while _settle_size(result) > _payload_budget(result["context"]):
        if result["changes"]:
            result["changes"].pop()
            result["changes_omitted"] += 1
            continue
        if result["commands"]["operations"]:
            result["commands"]["operations"].pop()
            result["commands"]["operations_omitted"] += 1
            continue
        raise ContextQueryError(
            "context_budget_exceeded", "patch receipt exceeds its context budget"
        )
    return result


def project_acknowledge_result(
    data: Mapping[str, Any],
    *,
    session: Mapping[str, Any],
) -> dict[str, Any]:
    policy = CONTEXT_POLICY["tool_results"]["acknowledge"]
    result = {
        key: data[key]
        for key in ("revision", "timeline_hash", "acknowledged")
        if key in data
    }
    result["session"] = dict(session)
    result["next_action"] = "read again before constructing a patch"
    result["context"] = {
        "protocol_version": CONTEXT_PROTOCOL_VERSION,
        "view": "acknowledge",
        "bounded": True,
        "max_bytes": int(policy["max_bytes"]),
        "response_bytes": 0,
    }
    if _settle_size(result) > _payload_budget(result["context"]):
        raise ContextQueryError(
            "context_budget_exceeded", "acknowledge receipt exceeds its context budget"
        )
    return result


def project_verify_result(
    data: Mapping[str, Any],
    *,
    session: Mapping[str, Any],
) -> dict[str, Any]:
    policy = CONTEXT_POLICY["tool_results"]["verify"]
    scalar_keys = (
        "verified",
        "persistence_verified",
        "scene",
        "strip_owner_scene",
        "window_scene",
        "sequencer_scene",
        "sequencer_scene_supported",
        "scene_binding_persisted",
        "internal_strip_count",
        "visible_strip_count",
        "visible_strip_match",
        "layout_profile_version",
        "vse_strip_count",
        "movie_strips",
        "sound_strips",
        "text_strips",
        "image_strips",
        "scene_strips",
        "effect_strips",
        "missing_proxy_count",
        "active_workspace",
        "video_editing_workspace",
        "reason",
    )
    result = {key: data[key] for key in scalar_keys if key in data}
    expected, expected_truncated = _bounded_object(
        data.get("expected") or {}, int(policy["warning_bytes"])
    )
    result["expected"] = expected
    result["expected_truncated"] = bool(expected_truncated)
    raw_status = list(data.get("proxy_status") or [])
    warnings = []
    for warning in list(data.get("proxy_warnings") or [])[
        : int(policy["max_proxy_warnings"])
    ]:
        bounded, truncated = _bounded_object(warning, int(policy["warning_bytes"]))
        warnings.append({"data": bounded, "truncated": bool(truncated)})
    result["proxy_status_count"] = len(raw_status)
    result["proxy_warnings"] = warnings
    result["proxy_warnings_omitted"] = max(
        0, len(data.get("proxy_warnings") or []) - len(warnings)
    )
    result["session"] = dict(session)
    result["context"] = {
        "protocol_version": CONTEXT_PROTOCOL_VERSION,
        "view": "verify",
        "bounded": True,
        "max_bytes": int(policy["max_bytes"]),
        "response_bytes": 0,
    }
    while _settle_size(result) > _payload_budget(result["context"]):
        if result["proxy_warnings"]:
            result["proxy_warnings"].pop()
            result["proxy_warnings_omitted"] += 1
            continue
        raise ContextQueryError(
            "context_budget_exceeded", "verify receipt exceeds its context budget"
        )
    return result
