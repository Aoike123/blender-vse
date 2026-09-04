# Changelog

[Chinese version](CHANGELOG_zh-CN.md)

## 0.1.0 - 2026-09-04

- Repositioned the project around local, revision-safe agent editing of
  persistent `.blend` timelines, with bounded context as a supporting guarantee.
- Expanded package and plugin discovery metadata for Blender VSE, AI video
  editing, MCP, NLE, agent Skills, revision safety, and local-first workflows.
- Fixed the public GUI smoke workflow to pass the observed strip name required
  by `set_text` while retaining the stable strip ID for follow-up reads.
- Added the missing distribution-content verification command to the release
  checklist.

- Standalone Blender VSE control package and CLI.
- Revision-safe read, patch, acknowledge, and verify workflow.
- Four-tool local MCP server with explicit project-root authorization.
- Low-context Agent Skill with bounded reads and resume capsules.
- Codex, Claude Code, and DSH installation paths.
- uv-managed Python 3.12 runtime bootstrap; no system Python required for plugin users.
- Bilingual English and Chinese documentation.
