from __future__ import annotations

import ast
import json
from importlib import resources
from pathlib import Path

from blender_vse.blender.vse_ops import PROXY_MANIFEST_FIELDS
from blender_vse.catalog import (
    CONTROL_PLANE_COMMANDS,
    ERROR_CODES,
    PUBLIC_OPERATIONS,
    REMOVED_OPERATIONS,
)
from blender_vse.context import CONTEXT_POLICY, INCLUDE_GROUPS, READ_VIEWS


def _schema(name: str) -> dict:
    return json.loads(
        resources.files("blender_vse.schemas")
        .joinpath(name)
        .read_text(encoding="utf-8-sig")
    )


def test_all_distributed_schemas_are_valid_json() -> None:
    root = resources.files("blender_vse.schemas")
    for item in root.iterdir():
        if item.name.endswith(".json"):
            json.loads(item.read_text(encoding="utf-8-sig"))


def test_edit_command_schema_matches_public_router() -> None:
    operations = set(_schema("edit-command.schema.json")["properties"]["op"]["enum"])
    assert operations == PUBLIC_OPERATIONS | CONTROL_PLANE_COMMANDS


def test_schema_ids_are_unique_and_stable() -> None:
    root = resources.files("blender_vse.schemas")
    schemas = [
        json.loads(item.read_text(encoding="utf-8-sig"))
        for item in root.iterdir()
        if item.name.endswith(".json")
    ]
    identifiers = [schema["$id"] for schema in schemas]
    assert len(identifiers) == len(set(identifiers))
    assert all(
        identifier.startswith("urn:blender-vse:schema:") for identifier in identifiers
    )


def test_proxy_schema_matches_runtime_validator() -> None:
    schema = _schema("proxy-manifest.schema.json")
    assert set(schema["required"]) == PROXY_MANIFEST_FIELDS
    assert schema["additionalProperties"] is False


def test_result_schema_covers_catalog_routing_errors() -> None:
    schema = _schema("operation-result.schema.json")
    codes = set(schema["properties"]["error"]["properties"]["code"]["enum"])
    assert codes == ERROR_CODES
    assert {details["code"] for details in REMOVED_OPERATIONS.values()} <= codes


def test_read_query_schema_matches_context_policy() -> None:
    schema = _schema("read-query.schema.json")
    properties = schema["properties"]
    assert set(properties["view"]["enum"]) == READ_VIEWS
    assert properties["view"]["default"] == CONTEXT_POLICY["default_view"]
    assert set(properties["include"]["items"]["enum"]) == INCLUDE_GROUPS
    assert (
        properties["limit"]["maximum"] == CONTEXT_POLICY["views"]["detail"]["max_limit"]
    )
    query_limits = CONTEXT_POLICY["query_limits"]
    assert properties["strip_ids"]["maxItems"] == query_limits["max_strip_ids"]
    assert properties["channels"]["maxItems"] == query_limits["max_channels"]
    assert properties["strip_types"]["maxItems"] == query_limits["max_strip_types"]


def test_read_result_schema_matches_context_protocol() -> None:
    schema = _schema("read-result.schema.json")
    context = schema["properties"]["context"]
    assert (
        context["properties"]["protocol_version"]["const"] == CONTEXT_POLICY["version"]
    )
    assert set(context["properties"]["view"]["enum"]) == READ_VIEWS


def test_literal_source_error_codes_are_declared() -> None:
    package = Path(__file__).resolve().parents[2] / "src" / "blender_vse"
    emitted = set()
    call_positions = {
        "BlenderRunnerError": 0,
        "ContextQueryError": 0,
        "LiveSessionError": 0,
        "RoutingError": 0,
        "_failure": 1,
    }
    for source in package.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                position = call_positions.get(name)
                if (
                    position is not None
                    and len(node.args) > position
                    and isinstance(node.args[position], ast.Constant)
                    and isinstance(node.args[position].value, str)
                ):
                    emitted.add(node.args[position].value)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "code"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        emitted.add(value.value)
    assert emitted <= ERROR_CODES
