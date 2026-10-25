from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from mcp.types import TextContent

import blender_vse.mcp as mcp_package
from blender_vse.mcp import server as server_module
from blender_vse.mcp.boundary import MCPAdapter, ProjectBoundary
from blender_vse.mcp.server import SERVER_INSTRUCTIONS, SERVER_NAME

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOLS = {
    "blender_read",
    "blender_patch",
    "blender_acknowledge",
    "blender_verify",
}
pytestmark = pytest.mark.mcp


class StubController:
    def __init__(self) -> None:
        self.calls = []

    def _result(self, op, project, kwargs):
        self.calls.append((op, project, kwargs))
        return {
            "ok": True,
            "op": op,
            "data": {"project": str(project), "received": kwargs},
        }

    def read(self, project, **kwargs):
        return self._result("read", project, kwargs)

    def patch(self, project, **kwargs):
        return self._result("patch", project, kwargs)

    def acknowledge(self, project, **kwargs):
        return self._result("acknowledge", project, kwargs)

    def verify(self, project, **kwargs):
        return self._result("verify", project, kwargs)


def _server(tmp_path: Path):
    controller = StubController()
    adapter = MCPAdapter(
        controller=controller,  # type: ignore[arg-type]
        boundary=ProjectBoundary([tmp_path]),
    )
    return mcp_package.create_server(adapter), controller


def test_console_entry_helpers_delegate_without_starting_on_import(
    monkeypatch, tmp_path: Path
) -> None:
    server, _controller = _server(tmp_path)
    called = []
    monkeypatch.setattr(server_module, "mcp", server)
    monkeypatch.setattr(server, "run", lambda **kwargs: called.append(kwargs))

    mcp_package.main()

    assert called == [{"transport": "stdio"}]


def test_server_exposes_exactly_four_public_tools(tmp_path: Path) -> None:
    server, _controller = _server(tmp_path)

    async def inspect():
        async with Client(server) as client:
            return client.server_info.name, await client.list_tools()

    server_name, listing = asyncio.run(inspect())
    assert server_name == SERVER_NAME
    assert {tool.name for tool in listing.tools} == EXPECTED_TOOLS
    assert "execute" not in " ".join(tool.name for tool in listing.tools)
    assert "summary" in SERVER_INSTRUCTIONS
    assert "compaction" in SERVER_INSTRUCTIONS


def test_stdio_transport_discovers_the_same_four_tools(tmp_path: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "blender_vse.mcp.server"],
        env={
            "BLENDER_VSE_WORKSPACE": str(tmp_path),
            "PYTHONPATH": str(ROOT / "src"),
        },
    )

    async def inspect():
        async with Client(parameters) as client:
            return await client.list_tools()

    listing = asyncio.run(asyncio.wait_for(inspect(), timeout=5))
    assert {tool.name for tool in listing.tools} == EXPECTED_TOOLS


def test_mcp_in_memory_transport_calls_bounded_adapter(tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    server, controller = _server(tmp_path)

    async def call_read():
        async with Client(server) as client:
            return await client.call_tool(
                "blender_read",
                {"project": str(project), "view": "summary"},
            )

    result = asyncio.run(call_read())
    assert not result.is_error
    assert result.structured_content["ok"] is True
    assert result.structured_content["op"] == "read"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == json.dumps(
        result.structured_content,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert controller.calls[0][0] == "read"
    assert controller.calls[0][2]["view"] == "summary"


def test_mcp_maps_patch_acknowledge_and_verify_arguments(tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    server, controller = _server(tmp_path)

    async def call_tools():
        async with Client(server) as client:
            patch = await client.call_tool(
                "blender_patch",
                {
                    "project": str(project),
                    "base_revision": 1,
                    "base_timeline_hash": "hash",
                    "observation_id": "obs",
                    "patch_id": "patch-1",
                    "commands": [{"op": "set_text", "text": "Hello"}],
                },
            )
            acknowledge = await client.call_tool(
                "blender_acknowledge",
                {
                    "project": str(project),
                    "observed_revision": 2,
                    "observed_hash": "new-hash",
                    "observation_id": "obs-2",
                },
            )
            verify = await client.call_tool(
                "blender_verify",
                {"project": str(project), "expected": {"text": 1}},
            )
            return patch, acknowledge, verify

    results = asyncio.run(call_tools())
    assert all(not result.is_error for result in results)
    assert [call[0] for call in controller.calls] == [
        "patch",
        "acknowledge",
        "verify",
    ]
    assert controller.calls[0][2]["read_token"] == "obs"
    assert controller.calls[1][2]["read_token"] == "obs-2"
    assert controller.calls[2][2]["expected"] == {"text": 1}


def test_generated_schemas_encode_context_and_write_guards(tmp_path: Path) -> None:
    server, _controller = _server(tmp_path)

    async def list_tools():
        async with Client(server) as client:
            return await client.list_tools()

    listing = asyncio.run(list_tools())
    tools = {tool.name: tool for tool in listing.tools}
    read_schema = tools["blender_read"].input_schema
    patch_schema = tools["blender_patch"].input_schema

    assert read_schema["properties"]["view"]["default"] == "summary"
    assert set(read_schema["properties"]["view"]["enum"]) == {
        "summary",
        "range",
        "detail",
        "full",
    }
    limit_types = read_schema["properties"]["limit"]["anyOf"]
    assert (
        next(item for item in limit_types if item.get("type") == "integer")["maximum"]
        == 200
    )
    channel_types = read_schema["properties"]["channels"]["anyOf"]
    channel_items = next(item for item in channel_types if item.get("type") == "array")[
        "items"
    ]
    assert (channel_items["minimum"], channel_items["maximum"]) == (1, 128)
    assert set(patch_schema["required"]) >= {
        "project",
        "base_revision",
        "base_timeline_hash",
        "observation_id",
        "patch_id",
        "commands",
    }
    assert patch_schema["properties"]["commands"]["maxItems"] == 100


def test_mcp_validation_rejects_an_empty_patch_before_adapter(tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    server, controller = _server(tmp_path)

    async def call_patch():
        async with Client(server) as client:
            return await client.call_tool(
                "blender_patch",
                {
                    "project": str(project),
                    "base_revision": 1,
                    "base_timeline_hash": "hash",
                    "observation_id": "obs",
                    "patch_id": "patch",
                    "commands": [],
                },
            )

    result = asyncio.run(call_patch())
    assert result.is_error
    assert controller.calls == []


def test_mcp_path_denial_is_a_bounded_tool_error(tmp_path: Path) -> None:
    server, controller = _server(tmp_path)

    async def call_read():
        async with Client(server) as client:
            return await client.call_tool(
                "blender_read", {"project": str(tmp_path.parent / "outside.blend")}
            )

    result = asyncio.run(call_read())
    assert result.is_error
    assert result.structured_content["error"]["code"] == "project_not_allowed"
    assert controller.calls == []
    assert isinstance(result.content[0], TextContent)
    assert (
        len(result.content[0].text.encode("utf-8"))
        <= result.structured_content["context"]["max_bytes"]
    )
