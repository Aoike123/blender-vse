# Recovery and resume

[Chinese version](recovery_zh-CN.md)

Read only the branch that matches the structured error code. Preserve the
original user intent, and do not broaden access or silently change execution
mode just to make an operation pass.

## Observation and cursor failures

| Codes | Action |
| --- | --- |
| `stale_base`, `revision_mismatch` | The timeline changed after the observed base. Discard the observation used for the patch, read a summary, then inspect the affected strips. |
| `invalid_read_token`, `stale_observation` | The observation was missing, consumed, or no longer identifies the current state. Never retry it; read again. |
| `invalid_cursor`, `stale_cursor` | Discard the cursor and restart the same targeted query from its first page. |
| `invalid_read_query` | Correct the view/selector combination; do not widen directly to `full`. |
| `context_budget_exceeded` | Narrow the frame range, strip IDs, channels, types, include groups, or page limit. |

When a manual edit caused the stale state, first understand the fresh read. Use
`blender_acknowledge` to adopt it only when continuing from that content matches
the user's intent. Then read once more before patching.

## Project and session failures

| Codes | Action |
| --- | --- |
| `project_not_allowed` | Use a path relative to the workspace `blender-vse-projects` folder; do not relocate the file as a workaround. |
| `project_not_found` | Confirm the exact path. Use `create_if_missing` only for an explicitly requested new project. |
| `project_mismatch` | Stop. Do not switch away from or close an unrelated human project. |
| `gui_not_visible`, `vse_not_visible`, `gui_not_stable` | Report the visible-session blocker. Do not fall back to hidden/headless editing. |
| `session_not_ready`, `bridge_not_ready`, `bridge_unreachable` | Retry only after the local Blender/Bridge state has materially changed; repeated blind calls are not recovery. |
| `vse_scene_mismatch`, `vse_visible_strip_mismatch`, `vse_current_frame_empty` | Stop and report the exact proof that failed; do not declare the timeline usable. |

Missing MCP tools or a server that fails to start indicate a setup problem, not
a reason to use raw `bpy`. Direct the user to the repository's local MCP setup
guide.

## Patch and persistence failures

| Codes | Action |
| --- | --- |
| `invalid_args`, `unsupported` | Check the exact operation in `command-index.json`, fix only the rejected command, then obtain a fresh read before a new patch. |
| `input_missing` | Ask for or resolve the exact missing asset/manifest path; do not search unrelated directories. |
| `patch_rolled_back` | Treat the batch as uncommitted. Inspect the bounded error details, read again, and construct a new patch ID after correcting it. |
| `checkpoint_not_found` | Confirm the intended checkpoint name from the known project context; never guess a filename. |
| `checkpoint_reopen_failed`, `session_close_failed` | Preserve the reported backup path and stop for user action; do not repeat replacement blindly. |
| `validation_failed`, `vse_media_missing` | Read the affected region/source fields and repair or report missing media before completion. |
| proxy warnings or `stale_proxy_source` | Rebuild the proxy externally and attach a newly verified manifest; the final render still uses the original media. |

After any successful corrective patch, read again and run `blender_verify`. Do
not infer persistence from rollback or recovery metadata.

## Compaction or handoff

Preserve this compact resume capsule:

```text
project: .blend path relative to blender-vse-projects
intent: current user-approved editorial outcome
confirmed: last revision + timeline hash
applied: bounded recent patch IDs/actions/outputs + total counts and digests
pending: unresolved choices and next targeted read
```

Discard observation IDs, cursors, full timeline pages, raw tool responses, and
GUI diagnostic trees. On resume, call `blender_read(view="summary")`, compare it
with the capsule, and obtain a fresh observation from a targeted read before any
write.
