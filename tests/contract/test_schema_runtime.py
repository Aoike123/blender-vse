from __future__ import annotations

import json
from importlib import resources

import jsonschema
import pytest

from blender_vse.context import ReadQuery, project_read_result
from blender_vse.resume import build_resume_capsule


def _schema(name: str) -> dict:
    return json.loads(
        resources.files("blender_vse.schemas")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def test_read_schemas_are_valid_draft_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(_schema("read-query.schema.json"))
    jsonschema.Draft202012Validator.check_schema(_schema("read-result.schema.json"))
    jsonschema.Draft7Validator.check_schema(_schema("resume-capsule.schema.json"))


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"view": "summary", "channels": [1]},
        {"view": "range", "frame_range": [1, 100], "limit": 20},
        {"view": "detail", "strip_ids": ["clip-1"], "include": ["text"]},
        {"view": "full"},
    ],
)
def test_valid_read_queries_conform_to_schema(query: dict) -> None:
    jsonschema.validate(query, _schema("read-query.schema.json"))


@pytest.mark.parametrize(
    "query",
    [
        {"include": ["text"]},
        {"view": "summary", "cursor": "cursor"},
        {"view": "range"},
        {"view": "detail"},
        {"view": "detail", "strip_ids": []},
        {"view": "detail", "strip_ids": ["one"], "limit": 201},
        {"view": "full", "channels": [1]},
    ],
)
def test_invalid_read_queries_are_rejected_by_schema(query: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(query, _schema("read-query.schema.json"))


def test_runtime_summary_result_conforms_to_schema() -> None:
    base = {
        "project": "demo.blend",
        "revision": 1,
        "timeline_hash": "hash",
        "observation_id": "obs",
        "session": {"ready": True},
    }
    timeline = {
        "scene": "VideoEditing",
        "fps": 30,
        "resolution": [1920, 1080],
        "frame_start": 1,
        "frame_end": 100,
        "playhead": 1,
        "strips": [
            {
                "video_ai_id": "clip-1",
                "id": "Clip",
                "name": "Clip",
                "type": "MOVIE",
                "channel": 1,
                "frame_start": 1,
                "frame_end": 100,
            }
        ],
    }
    result = project_read_result(base=base, timeline=timeline, query=ReadQuery.create())
    jsonschema.validate(result, _schema("read-result.schema.json"))


def test_runtime_resume_capsule_conforms_to_schema() -> None:
    capsule = build_resume_capsule(
        project="demo.blend",
        objective="Continue the edit",
        last_verified_revision=3,
        last_verified_timeline_hash="hash",
        patch_ids=["patch-1", "patch-2"],
    )
    jsonschema.validate(capsule, _schema("resume-capsule.schema.json"))
