# Changelog

[Chinese version](CHANGELOG_zh-CN.md)

## 0.2.0 - 2026-10-25

- The MCP server now carries the `blender-vse` Skill: its core rules are the
  server instructions, the full Skill is the `blender-vse` prompt, and every
  Skill file is a `blender-vse://skill/...` resource. Wheels bundle the Skill,
  so one-line installs get it without a plugin.
- The Skill now uses workspace-relative project paths throughout and points to
  `sample_frame` for numeric visual checks.
- Added one-line installers, `install.sh` for Linux/macOS and `install.ps1` for
  Windows. They install uv when missing and the `blender-vse-mcp` command with
  `uv tool`; registering the server is left to the MCP host.
- Projects now always live in `<workspace>/blender-vse-projects`, where the
  workspace is the folder the MCP host starts the server in, and tools accept
  paths relative to it such as `demo.blend`. Removed `BLENDER_VSE_PROJECTS_DIR`,
  `VP_PROJECTS_DIR`, and `BLENDER_VSE_ALLOWED_ROOTS`; `BLENDER_VSE_WORKSPACE`
  covers hosts that start servers elsewhere.
- Removed the Agent-guided installation contract (`install-contract.json`,
  `blender_vse.installation`, the DSH installer, config printers, the Claude
  `projects_dir` option, and client compatibility docs).
- Relicensed the project from AGPL-3.0-only to the MIT License. The vendored
  Blender MCP Bridge keeps its original MIT notice.
- Fixed the Blender >= 5 sequencer preview drawing TEXT strips with an unset
  font as scaled, flipped glyph garbage while final renders stayed correct:
  `add_text` and `add_subtitle_track` now always assign an explicit loadable
  font, preferring Blender's bundled Inter / Noto Sans CJK fonts (located
  through Blender's resource paths) and reusing already-loaded fonts, and report
  `font_fallback_warning` when no candidate loads so preview and render agree.
- Linux visible-session checks now collect native window evidence for the
  Blender process through `xprop` on X11, failing closed to the previous
  behavior when X11 evidence is unavailable.
- Added `sample_frame`: renders one frame and returns a bounded numeric RGB
  grid (up to 16x16 cells, rows top to bottom) plus min/max/mean luminance and
  the scene view transform, so agents verify timeline visuals numerically
  instead of eyeballing screenshots.
- `generate_contact_sheet` now steps frames with `scene.frame_set()` instead
  of assigning `frame_current` directly, keeping the visible preview and
  depsgraph in sync across its render loop.
- Documented how to pair Blender VSE Control with a director or
  production-orchestration Skill for end-to-end automation, with explicit
  ownership boundaries for creative planning, source media, timeline execution,
  and persistence verification.

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
