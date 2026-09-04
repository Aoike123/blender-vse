# Python and CLI API

[Chinese version](api_zh-CN.md)

## Recommended Python boundary

`BlenderVSE` exposes four collaboration methods:

| Method | Purpose | Side effect |
| --- | --- | --- |
| `read` | Return the revision, timeline hash, single-use observation ID, and selected timeline projection | May create a project, but only with `create_if_missing=True` |
| `patch` | Validate the observed base and atomically apply typed commands | Modifies and saves the `.blend` |
| `acknowledge` | Adopt a manual edit that the caller has explicitly observed and understood | Advances the accepted revision |
| `verify` | Reopen in a fresh Blender process and verify persisted strip counts | Read-only for timeline content |

`BlenderVSE.execute` is a low-level escape hatch for typed operations. The
adapter still rejects direct editing primitives unless an internal integration
harness explicitly enables them. Applications should use `patch` for all
mutations.

## Bounded reads

`read` defaults to `view="summary"`. It accepts:

```python
controller.read(
    "demo.blend",
    view="detail",                 # summary | range | detail | full
    frame_range=(1, 300),           # required for range
    strip_ids=("clip-id",),        # stable IDs, names also accepted
    channels=(1, 3),
    strip_types=("MOVIE", "TEXT"),
    include=("text", "source"),
    cursor=None,
    limit=50,
)
```

`summary` returns no strips. `range` and `detail` return bounded pages and place
the next cursor in `context.next_cursor`. A cursor is valid only for the same
revision, timeline hash, selectors, include groups, and limit. `full` is an
explicit compatibility mode and is unsuitable for a long-running Agent
context.

Use the observation ID from the final targeted read immediately before a
patch. Never carry an observation ID through compaction or handoff.

## Resume capsule helper

`build_resume_capsule(...)` creates a deterministic context and handoff record
with a hard 4 KB limit. It accepts durable project intent, a confirmed revision
and hash, recent relevant history, blockers, outputs, and the next action.
Observation IDs and cursors are deliberately excluded.

```python
from blender_vse import build_resume_capsule

capsule = build_resume_capsule(
    project="/projects/demo.blend",
    objective="Finish subtitle timing",
    last_verified_revision=12,
    last_verified_timeline_hash="...",
    patch_ids=["subtitle-011", "subtitle-012"],
    relevant_strip_ids=["subtitle-42"],
    next_action="read summary, then subtitle-42 detail",
)
```

History fields retain a bounded set of recent entries, plus a digest and count
for omitted history. The serialization contract is
[`resume-capsule.schema.json`](../src/blender_vse/schemas/resume-capsule.schema.json).

## Result envelope

Methods return dictionaries that can cross JSON-oriented tool boundaries:

```json
{
  "ok": false,
  "op": "patch",
  "error": {
    "code": "stale_base",
    "message": "Timeline changed after it was read."
  }
}
```

Success receipts from `patch`, `acknowledge`, and `verify`, as well as error
envelopes, are byte-bounded by `context-policy.json`. A patch receipt is not a
new observation; its `next_action` instructs the caller to read again.

Do not branch on message text. Branch on `ok` and the stable `error.code`.
Relevant recovery groups are:

- `project_not_found`, `input_missing`: resolve an explicit local path.
- `session_not_ready`, `project_mismatch`: restore the visible Blender session
  without switching away from unsaved human work.
- `stale_base`, `revision_mismatch`, `invalid_read_token`,
  `stale_observation`: read again before deciding whether to acknowledge or
  rebuild the patch.
- `patch_rolled_back`: inspect command inputs; the timeline was not partially
  committed.
- `invalid_read_query`, `invalid_cursor`: correct the selectors or restart
  pagination at page one.
- `stale_cursor`: the timeline changed between pages; discard collected pages
  and start a new bounded read.
- `context_budget_exceeded`: request fewer optional groups or a narrower range.
- `invalid_proxy_manifest`, `stale_proxy_source`: rebuild and re-verify the
  external proxy manifest.

## CLI

```text
blender-vse status
blender-vse context-policy
blender-vse ops [--family FAMILY]
blender-vse read PROJECT [--create] [--resolution W H] [--fps FPS] \
    [--view summary|range|detail|full] [--frame-range START END] \
    [--strip-id ID] [--channel N] [--type TYPE] [--include GROUP] \
    [--cursor CURSOR] [--limit N]
blender-vse patch PROJECT --base-revision N --base-timeline-hash HASH \
    --read-token TOKEN --patch-id ID --commands JSON_OR_@FILE
blender-vse acknowledge PROJECT --observed-revision N \
    --observed-hash HASH --read-token TOKEN
blender-vse verify PROJECT [--expected JSON_OR_@FILE]
blender-vse execute OP [--project PROJECT] [--params JSON_OR_@FILE]
```

All commands print JSON and return a nonzero exit code on failure. In scripts,
prefer `@file.json` inputs to avoid shell-specific quoting.

## Schemas

- [Edit command](../src/blender_vse/schemas/edit-command.schema.json)
- [Operation result](../src/blender_vse/schemas/operation-result.schema.json)
- [Timeline state](../src/blender_vse/schemas/timeline-state.schema.json)
- [Media information](../src/blender_vse/schemas/media-info.schema.json)
- [External proxy manifest](../src/blender_vse/schemas/proxy-manifest.schema.json)
- [Bounded read query](../src/blender_vse/schemas/read-query.schema.json)
- [Bounded read result](../src/blender_vse/schemas/read-result.schema.json)
- [Resume capsule](../src/blender_vse/schemas/resume-capsule.schema.json)
- [Context policy](../src/blender_vse/context-policy.json)
