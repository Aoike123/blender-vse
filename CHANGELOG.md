# Changelog

[Chinese version](CHANGELOG_zh-CN.md)

## 0.1.1 - 2026-09-04

- Rewrote all 25 English/Chinese documentation pairs for clear, natural prose
  while preserving commands, contracts, and safety boundaries.
- Standardized terminology for revisions, observation IDs, targeted reads,
  operation catalogs, allowlists, Agent hosts, and proxy media.
- Fixed Markdown emphasis boundaries and added contract checks for emphasis,
  heading spacing, and fenced code blocks.
- Replaced the English and Chinese social-preview taglines with concise,
  reader-friendly copy and regenerated the verified image assets.
- Corrected documentation examples and claims for `set_text`, new project
  paths, the GUI smoke workflow, and persistence verification.

## 0.1.0 - 2026-09-04

- Reframed the project as a local, revision-safe agent editor for persistent
  `.blend` timelines, with bounded context as a supporting guarantee rather
  than the product category itself.
- Expanded the package and plugin discovery metadata to cover Blender VSE, AI
  video editing, MCP, NLE, Agent Skills, revision safety, and local-first
  workflows.
- Corrected the public GUI smoke workflow so `set_text` receives the observed
  strip name while follow-up reads continue to use the stable strip ID.
- Added the missing distribution-content verification command to the release
  checklist.
- Added a standalone Blender VSE control package and CLI.
- Revision-safe read, patch, acknowledge, and verify workflow.
- A four-tool local MCP server with explicit project-root authorization.
- A context-efficient Agent Skill with bounded reads and resume capsules.
- Codex, Claude Code, and DSH installation paths.
- A `uv`-managed Python 3.12 runtime bootstrap; plugin users do not need a
  system Python installation.
- Bilingual English and Chinese documentation.
