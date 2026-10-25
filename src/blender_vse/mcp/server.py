"""Local stdio MCP server exposing Blender VSE Control's public workflow."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from blender_vse import __version__
from blender_vse.mcp.boundary import MCPAdapter

SERVER_NAME = "blender-vse-control"
SERVER_INSTRUCTIONS = (
    "Projects live in the workspace blender-vse-projects folder; pass paths "
    "relative to it, such as demo.blend. Start with "
    "blender_read summary, then use a targeted range/detail read before editing. "
    "Pass its revision, timeline_hash, and observation_id to exactly one patch or "
    "acknowledgement. After stale state or context compaction, discard the token "
    "and read again. Use blender_verify for final persistence proof."
)

ProjectPath = Annotated[
    str,
    Field(
        min_length=1,
        max_length=2048,
        description=(
            ".blend path relative to the workspace blender-vse-projects folder, "
            "e.g. demo.blend."
        ),
    ),
]
Token = Annotated[str, Field(min_length=1, max_length=512)]
StripId = Annotated[str, Field(min_length=1, max_length=512)]
StripType = Annotated[str, Field(min_length=1, max_length=64)]
Channel = Annotated[int, Field(ge=1, le=128)]
ExpectedName = Annotated[str, Field(min_length=1, max_length=128)]
ExpectedCount = Annotated[int, Field(ge=0)]
ReadView = Literal["summary", "range", "detail", "full"]
IncludeGroup = Literal["text", "source", "transform", "audio", "proxy", "metadata"]
FrameRange = Annotated[list[int] | None, Field(min_length=2, max_length=2)]
StripIds = Annotated[list[StripId] | None, Field(max_length=200)]
Channels = Annotated[list[Channel] | None, Field(max_length=128)]
StripTypes = Annotated[list[StripType] | None, Field(max_length=32)]
Includes = Annotated[list[IncludeGroup] | None, Field(max_length=6)]
PageLimit = Annotated[int | None, Field(ge=1, le=200)]
Commands = Annotated[list[dict[str, Any]], Field(min_length=1, max_length=100)]
ExpectedCounts = Annotated[
    dict[ExpectedName, ExpectedCount] | None,
    Field(max_length=64),
]


def _tool_result(result: dict[str, Any]) -> CallToolResult:
    """Preserve the context byte budget in model-visible MCP content."""

    compact = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return CallToolResult(
        content=[TextContent(type="text", text=compact)],
        structured_content=result,
        is_error=not bool(result.get("ok")),
    )


def create_server(adapter: MCPAdapter | None = None) -> MCPServer:
    """Build an isolated server, allowing dependency injection in tests."""

    operations = adapter or MCPAdapter()
    server = MCPServer(
        SERVER_NAME,
        version=__version__,
        instructions=SERVER_INSTRUCTIONS,
    )

    @server.tool(
        name="blender_read",
        title="Read Blender VSE timeline",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def blender_read(
        project: ProjectPath,
        create_if_missing: bool = False,
        resolution_width: Annotated[int, Field(ge=4, le=16384)] = 1920,
        resolution_height: Annotated[int, Field(ge=4, le=16384)] = 1080,
        fps: Annotated[int, Field(ge=1, le=240)] = 30,
        view: ReadView = "summary",
        frame_range: FrameRange = None,
        strip_ids: StripIds = None,
        channels: Channels = None,
        strip_types: StripTypes = None,
        include: Includes = None,
        cursor: Annotated[str | None, Field(max_length=4096)] = None,
        limit: PageLimit = None,
    ) -> CallToolResult:
        """Observe one project; prefer summary, then targeted range/detail pages."""

        return _tool_result(
            operations.read(
                project,
                create_if_missing=create_if_missing,
                resolution=(resolution_width, resolution_height),
                fps=fps,
                view=view,
                frame_range=frame_range,
                strip_ids=strip_ids,
                channels=channels,
                strip_types=strip_types,
                include=include,
                cursor=cursor,
                limit=limit,
            )
        )

    @server.tool(
        name="blender_patch",
        title="Patch Blender VSE timeline",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def blender_patch(
        project: ProjectPath,
        base_revision: Annotated[int, Field(ge=0)],
        base_timeline_hash: Token,
        observation_id: Token,
        patch_id: Token,
        commands: Commands,
    ) -> CallToolResult:
        """Atomically apply allowlisted commands from one fresh read observation."""

        return _tool_result(
            operations.patch(
                project,
                base_revision=base_revision,
                base_timeline_hash=base_timeline_hash,
                read_token=observation_id,
                patch_id=patch_id,
                commands=commands,
            )
        )

    @server.tool(
        name="blender_acknowledge",
        title="Acknowledge manual Blender edit",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def blender_acknowledge(
        project: ProjectPath,
        observed_revision: Annotated[int, Field(ge=0)],
        observed_hash: Token,
        observation_id: Token,
    ) -> CallToolResult:
        """Adopt a manual timeline change only after a fresh targeted read."""

        return _tool_result(
            operations.acknowledge(
                project,
                observed_revision=observed_revision,
                observed_hash=observed_hash,
                read_token=observation_id,
            )
        )

    @server.tool(
        name="blender_verify",
        title="Verify Blender project persistence",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def blender_verify(
        project: ProjectPath,
        expected: ExpectedCounts = None,
    ) -> CallToolResult:
        """Reopen one project in a fresh Blender process and verify persistence."""

        return _tool_result(operations.verify(project, expected=expected))

    return server


mcp = create_server()


def main() -> None:
    """Run the server over stdio; stdout is reserved for MCP framing."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
