---
name: blender-vse
description: >-
  Low-context, focused Blender video editing and verification through the four
  revision-safe Blender MCP tools. Use for .blend timeline, strip, subtitle,
  audio, proxy, render, checkpoint, or continuation tasks; pair with creation
  Skills when generating source media, and do not use for one-off FFmpeg-only
  edits or arbitrary Blender Python.
---

[Chinese version](SKILL_zh-CN.md)

# Blender VSE

Treat the named `.blend` file as the editable source of truth. Use only
`blender_read`, `blender_patch`, `blender_acknowledge`, and `blender_verify`.
Never substitute raw `bpy`, shell-driven Blender scripts, or a hidden headless
editor for these tools.

## Establish the boundary

- Do not treat a fresh installation as ready until the user has confirmed an
  absolute project directory through `BLENDER_VSE_PROJECTS_DIR`. If it is not
  configured, ask where editable `.blend` projects should live before creating
  one. Never choose a plugin cache, marketplace checkout, or temporary clone.
- Prefer `<workspace>/blender-vse-projects` for projects and referenced media.
  If no workspace is available, recommend opening one first. If the user picks
  a directory outside it, explain the sandbox/portability trade-off and obtain
  explicit confirmation; never relocate existing files implicitly.
- Require an explicit `.blend` path. Do not scan the filesystem for projects.
- If the four tools are unavailable, stop and explain that the local MCP server
  must be installed and configured. Do not imitate it with arbitrary Python.
- A path outside configured roots is an authorization/configuration issue. Do
  not move or copy the project to evade it.
- Set `create_if_missing=true` only when the user asked to create that exact
  project. Inspection and continuation never create a missing file implicitly.

## Choose the workflow

- For inspection, explanation, or diagnosis, read only; do not patch or
  acknowledge unless the user also asked to change/adopt state.
- For creation or editing, use the observed edit loop below.
- For continuation after a pause, handoff, compaction, or uncertain state,
  assume prior observations are expired and begin with a new summary read.
- For a failure, read [recovery.md](references/recovery.md) only after the error
  identifies the relevant recovery branch.

## Observed edit loop

1. Call `blender_read` on the exact project with `view="summary"`.
2. Read only the area needed for the task:
   - `range` requires `frame_range` and is best for a bounded timeline span.
   - `detail` requires strip IDs, channels, strip types, or a frame range and is
     best before touching named strips.
   - Add only the required `include` groups: `text`, `source`, `transform`,
     `audio`, `proxy`, or `metadata`.
   - Follow `next_cursor` with the identical query while `has_more` is true.
3. Understand the observed timeline and form one coherent command batch. When
   constructing commands, read [commands.md](references/commands.md), then look
   up only the required operations in
   [command-index.json](references/command-index.json).
4. Call `blender_patch` with the same explicit project and the fresh read's
   `revision`, `timeline_hash`, and `observation_id`. Generate one stable unique
   `patch_id`; reuse it only to retry that identical batch.
5. Call `blender_read` again. Never build a second patch from a patch receipt or
   reuse an observation ID.
6. Repeat targeted read -> patch -> read only while needed. Finish changed work
   with `blender_verify`, optionally supplying expected strip counts when they
   are known.

Use `view="full"` only for explicit legacy/debugging requests when bounded
views cannot answer the question. Do not use it as routine preparation for an
edit.

## Manual edits

A changed timeline belongs to the user. Read and understand the new state
before doing anything else. If it is compatible with the requested work,
`blender_acknowledge` may adopt that exact observation, followed by another
read. If it conflicts with the user's intent or the correct choice is unclear,
stop and ask. Never acknowledge unseen state or use acknowledgement to bypass a
stale patch.

## Context state

The Agent host owns growing conversation context; the MCP server does not.
Maintain only a compact resume capsule:

- explicit project path and current user intent;
- last confirmed revision and timeline hash;
- bounded recent patch IDs, completed actions, relevant stable strip IDs, and
  verified outputs, with total counts and digests for older history;
- unresolved editorial decisions and the next targeted read.

Do not retain observation IDs, cursors, full strip dumps, raw logs, or window
diagnostics across compaction or handoff. Resume with a summary read and obtain
a new targeted observation before any mutation.

## Completion

An edit is complete only when a post-patch read matches the intended timeline
and `blender_verify` confirms persistence. Report the project path, applied
editorial changes, final verified revision/hash when returned, output paths,
and any warnings or unresolved choices. An API success alone is not evidence
that a requested visual result or render is correct.
