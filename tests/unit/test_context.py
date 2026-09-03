from __future__ import annotations

import json

import pytest

from blender_vse.context import (
    CONTEXT_POLICY,
    ContextQueryError,
    ReadQuery,
    project_acknowledge_result,
    project_patch_result,
    project_read_result,
    project_session_failure,
    project_verify_result,
)

BASE = {
    "project": "demo.blend",
    "revision": 7,
    "timeline_hash": "timeline-hash-7",
    "observation_id": "obs-7",
    "session": {"ready": True, "gui_visible": True},
}


def _strip(index: int, *, strip_type: str = "MOVIE", channel: int = 1) -> dict:
    return {
        "video_ai_id": f"strip-{index}",
        "id": f"Strip {index}",
        "name": f"Strip {index}",
        "type": strip_type,
        "channel": channel,
        "frame_start": index * 10,
        "frame_end": index * 10 + 9,
        "source_in": 0,
        "source_out": 0,
        "mute": False,
        "lock": False,
        "asset_id": f"asset-{index}",
        "asset_revision": 1,
        "source_path": f"/media/{index}.mp4",
        "text": f"Text {index}",
        "font_size": 48,
        "position": [0.5, 0.1],
        "transform": {"offset_x": 0, "offset_y": 0},
        "proxy": {"status": "ready"},
        "meta": {"shot": index},
        "volume": 1.0,
    }


def _timeline(strips: list[dict]) -> dict:
    return {
        "project": None,
        "scene": "VideoEditing",
        "fps": 30,
        "resolution": [1920, 1080],
        "frame_start": 1,
        "frame_end": 250,
        "playhead": 1,
        "strips": strips,
    }


def _size(value) -> int:
    return len(
        json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")
    )


def test_default_query_is_bounded_summary() -> None:
    query = ReadQuery.create()
    assert query.view == "summary"
    assert query.limit is None
    assert query.with_text is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"view": "unknown"},
        {"view": "range"},
        {"view": "detail"},
        {"view": "summary", "include": ["text"]},
        {"view": "summary", "cursor": "cursor"},
        {"view": "summary", "channels": []},
        {"view": "summary", "channels": [1, 1]},
        {"view": "range", "frame_range": [1, 10], "include": []},
        {"view": "full", "channels": [1]},
        {"view": "full", "channels": []},
        {"view": "detail", "strip_ids": [""]},
        {"view": "detail", "strip_ids": ["one", "one"]},
        {"view": "detail", "strip_types": ["text", "TEXT"]},
        {"view": "detail", "strip_ids": ["one"], "include": ["text", "text"]},
        {"view": "detail", "channels": [0]},
        {"view": "detail", "channels": [129]},
        {"view": "range", "frame_range": [20, 10]},
        {"view": "detail", "strip_ids": ["one"], "limit": 0},
        {"view": "detail", "strip_ids": ["one"], "limit": True},
        {"view": "detail", "strip_ids": ["one"], "limit": "bad"},
        {"view": "detail", "strip_ids": ["one"], "include": ["unknown"]},
        {"view": "detail", "strip_ids": [str(value) for value in range(201)]},
        {"view": "detail", "strip_types": [str(value) for value in range(33)]},
    ],
)
def test_invalid_queries_fail_before_blender(kwargs) -> None:
    with pytest.raises(ContextQueryError) as caught:
        ReadQuery.create(**kwargs)
    assert caught.value.code == "invalid_read_query"


def test_summary_counts_without_returning_strips() -> None:
    strips = [
        _strip(1),
        _strip(2),
        _strip(3, strip_type="TEXT", channel=3),
    ]
    result = project_read_result(
        base=BASE, timeline=_timeline(strips), query=ReadQuery.create()
    )
    assert result["project"] == "demo.blend"
    assert result["strips"] == []
    assert result["summary"] == {
        "total_strips": 3,
        "matched_strips": 3,
        "counts_by_type": {"MOVIE": 2, "TEXT": 1},
        "counts_by_channel": {"1": 2, "3": 1},
        "content_bounds": [10, 39],
    }
    assert result["context"]["bounded"] is True
    assert result["context"]["response_bytes"] == _size(result)
    assert _size(result) <= CONTEXT_POLICY["views"]["summary"]["max_bytes"]


def test_summary_filters_counts_without_detail() -> None:
    strips = [_strip(1), _strip(2, strip_type="TEXT", channel=3), _strip(3)]
    query = ReadQuery.create(view="summary", channels=[3])
    result = project_read_result(base=BASE, timeline=_timeline(strips), query=query)
    assert result["summary"]["total_strips"] == 3
    assert result["summary"]["matched_strips"] == 1
    assert result["summary"]["counts_by_type"] == {"TEXT": 1}


def test_range_view_is_paginated_with_revision_bound_cursor() -> None:
    strips = [_strip(index) for index in range(1, 7)]
    first_query = ReadQuery.create(view="range", frame_range=[1, 100], limit=2)
    first = project_read_result(
        base=BASE, timeline=_timeline(strips), query=first_query
    )
    assert [strip["video_ai_id"] for strip in first["strips"]] == ["strip-1", "strip-2"]
    assert first["context"]["has_more"] is True
    cursor = first["context"]["next_cursor"]
    assert cursor and "timeline-hash" not in cursor

    second_query = ReadQuery.create(
        view="range",
        frame_range=[1, 100],
        limit=2,
        cursor=cursor,
    )
    second = project_read_result(
        base=BASE, timeline=_timeline(strips), query=second_query
    )
    assert [strip["video_ai_id"] for strip in second["strips"]] == [
        "strip-3",
        "strip-4",
    ]


def test_cursor_rejects_changed_timeline() -> None:
    strips = [_strip(index) for index in range(1, 4)]
    query = ReadQuery.create(view="range", frame_range=[1, 100], limit=1)
    first = project_read_result(base=BASE, timeline=_timeline(strips), query=query)
    next_query = ReadQuery.create(
        view="range",
        frame_range=[1, 100],
        limit=1,
        cursor=first["context"]["next_cursor"],
    )
    with pytest.raises(ContextQueryError) as caught:
        project_read_result(
            base={**BASE, "revision": 8, "timeline_hash": "timeline-hash-8"},
            timeline=_timeline(strips),
            query=next_query,
        )
    assert caught.value.code == "stale_cursor"


def test_cursor_rejects_query_change_and_invalid_data() -> None:
    strips = [_strip(index) for index in range(1, 4)]
    first_query = ReadQuery.create(view="detail", channels=[1], limit=1)
    first = project_read_result(
        base=BASE, timeline=_timeline(strips), query=first_query
    )
    changed = ReadQuery.create(
        view="detail",
        channels=[1],
        include=["text"],
        limit=1,
        cursor=first["context"]["next_cursor"],
    )
    with pytest.raises(ContextQueryError) as caught:
        project_read_result(base=BASE, timeline=_timeline(strips), query=changed)
    assert caught.value.code == "invalid_cursor"

    invalid = ReadQuery.create(view="detail", channels=[1], cursor="not-base64")
    with pytest.raises(ContextQueryError) as caught:
        project_read_result(base=BASE, timeline=_timeline(strips), query=invalid)
    assert caught.value.code == "invalid_cursor"


def test_detail_returns_only_selected_optional_groups() -> None:
    query = ReadQuery.create(
        view="detail",
        strip_ids=["strip-2"],
        include=["text", "source"],
    )
    result = project_read_result(
        base=BASE,
        timeline=_timeline([_strip(1), _strip(2, strip_type="TEXT", channel=3)]),
        query=query,
    )
    assert len(result["strips"]) == 1
    strip = result["strips"][0]
    assert strip["video_ai_id"] == "strip-2"
    assert strip["text"] == "Text 2"
    assert strip["source_path"] == "/media/2.mp4"
    assert "proxy" not in strip
    assert "meta" not in strip


def test_large_optional_values_are_marked_and_bounded() -> None:
    strip = _strip(1, strip_type="TEXT", channel=3)
    strip["text"] = "字" * 20_000
    strip["meta"] = {"large": "值" * 20_000}
    query = ReadQuery.create(
        view="detail",
        strip_ids=["strip-1"],
        include=["text", "metadata"],
    )
    result = project_read_result(base=BASE, timeline=_timeline([strip]), query=query)
    projected = result["strips"][0]
    assert set(projected["_truncated_fields"]) == {"meta", "text"}
    assert projected["meta"]["truncated"] is True
    assert result["context"]["response_bytes"] <= result["context"]["max_bytes"]


def test_page_shrinks_to_honor_byte_budget() -> None:
    strips = [_strip(index) for index in range(1, 80)]
    for strip in strips:
        strip["name"] = "N" * 512
        strip["id"] = strip["name"]
    query = ReadQuery.create(view="detail", channels=[1], limit=50)
    result = project_read_result(base=BASE, timeline=_timeline(strips), query=query)
    assert 0 < result["context"]["returned"] < 50
    assert result["context"]["has_more"] is True
    assert result["context"]["response_bytes"] <= result["context"]["max_bytes"]


def test_thousand_strip_timeline_pages_without_zero_progress() -> None:
    strips = [_strip(index) for index in range(1, 1001)]
    timeline = _timeline(strips)
    cursor = None
    seen = []
    for _ in range(100):
        query = ReadQuery.create(
            view="detail",
            channels=[1],
            limit=200,
            cursor=cursor,
        )
        result = project_read_result(base=BASE, timeline=timeline, query=query)
        context = result["context"]
        assert context["response_bytes"] <= context["max_bytes"]
        assert context["returned"] == len(result["strips"])
        seen.extend(strip["video_ai_id"] for strip in result["strips"])
        if not context["has_more"]:
            break
        assert context["returned"] > 0
        assert context["next_cursor"]
        cursor = context["next_cursor"]
    assert len(seen) == 1000
    assert len(set(seen)) == 1000


def test_full_view_is_explicit_and_unbounded() -> None:
    strips = [_strip(1)]
    query = ReadQuery.create(view="full")
    result = project_read_result(base=BASE, timeline=_timeline(strips), query=query)
    assert result["strips"] == strips
    assert result["context"]["bounded"] is False
    assert "max_bytes" not in result["context"]


def test_verbose_session_failure_is_compact() -> None:
    session = {
        "ready": False,
        "code": "gui_not_visible",
        "message": "hidden " + "x" * 20_000,
        "launched": True,
        "session_log": "/logs/" + "y" * 20_000,
        "window_candidates": [{"huge": "z" * 20_000}],
        "last_observation": {
            "pid": 42,
            "filepath": "demo.blend",
            "workspace": "Layout",
            "vse_area_count": 0,
            "is_dirty": False,
        },
        "discovery": {
            "attempts": 100,
            "waited_seconds": 45,
            "observed_states": ["bridge_unreachable", "gui_not_visible"] * 20,
        },
    }
    result = project_session_failure(session)
    assert result["code"] == "gui_not_visible"
    assert result["pid"] == 42
    assert result["diagnostics_omitted"] is True
    assert "window_candidates" not in result
    assert set(result["truncated_fields"]) == {"message", "session_log"}
    assert result["context"]["response_bytes"] <= result["context"]["max_bytes"]


def test_patch_receipt_drops_raw_payload_history_and_stays_bounded() -> None:
    raw = {
        "applied": True,
        "base_revision": 1,
        "applied_revision": 2,
        "timeline_hash": "new-hash",
        "results": [
            {"index": index, "op": "set_text", "ok": True} for index in range(100)
        ],
        "payloads": [
            {"video_ai_id": f"text-{index}", "text": "x" * 10_000}
            for index in range(100)
        ],
    }
    result = project_patch_result(raw, session={"ready": True})
    assert result["applied_revision"] == 2
    assert result["commands"]["total"] == 100
    assert "payloads" not in result
    assert result["changes_omitted"] > 0
    assert result["next_action"].startswith("read ")
    assert result["context"]["response_bytes"] <= result["context"]["max_bytes"]


def test_acknowledge_receipt_is_bounded_and_requires_a_new_read() -> None:
    result = project_acknowledge_result(
        {"revision": 3, "timeline_hash": "hash", "acknowledged": True},
        session={"ready": True},
    )
    assert result["acknowledged"] is True
    assert "read again" in result["next_action"]
    assert result["context"]["response_bytes"] <= result["context"]["max_bytes"]


def test_verify_receipt_summarizes_large_proxy_state() -> None:
    raw = {
        "persistence_verified": True,
        "vse_strip_count": 1000,
        "movie_strips": 1000,
        "proxy_status": [{"name": f"clip-{index}"} for index in range(1000)],
        "proxy_warnings": [
            {"name": f"clip-{index}", "path": "x" * 5000} for index in range(100)
        ],
    }
    result = project_verify_result(raw, session={"ready": True})
    assert result["persistence_verified"] is True
    assert result["proxy_status_count"] == 1000
    assert len(result["proxy_warnings"]) <= 20
    assert result["proxy_warnings_omitted"] >= 80
    assert result["context"]["response_bytes"] <= result["context"]["max_bytes"]
