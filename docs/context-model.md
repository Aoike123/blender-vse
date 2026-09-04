# Context model

[Chinese version](context-model_zh-CN.md)

Status: Accepted for Context Protocol 1.1.

## Decision

Blender VSE Control supports long-running, stateful Agent workflows without
letting raw timeline and diagnostic output expand the conversation
indefinitely. The `.blend` remains the durable source of truth. Model context
contains only the current objective, compact project observations, relevant
stable IDs, and recent tool outcomes.

The machine-readable policy is
[`context-policy.json`](../src/blender_vse/context-policy.json). Code and tests
consume that file directly; this document explains the decisions rather than
duplicating every field.

Inspect the effective packaged policy with `blender-vse context-policy`.

## Read escalation

`BlenderVSE.read` defaults to `summary`:

| View | Purpose | Bound |
| --- | --- | ---: |
| `summary` | Revision, timeline hash, observation ID, project shape, counts, channels, bounds, warnings | 8 KB |
| `range` | Strips overlapping a frame interval, paged | 16 KB |
| `detail` | Strips selected by stable ID, channel, type, or interval, paged | 16 KB |
| `full` | Explicit compatibility/debugging response | Unbounded |

Other model-facing results are also bounded:

| Result | Bound |
| --- | ---: |
| patch receipt | 4 KB |
| acknowledge receipt | 4 KB |
| persistence verification | 8 KB |
| error envelope | 4 KB |

Patch receipts summarize command outcomes and return bounded payload previews;
they never replay raw payload history. Verify receipts replace per-strip proxy
status with counts and bounded warnings. Session failures omit raw window trees
and point to the local diagnostic log when available.

Each data projection reserves 512 bytes for the surrounding tool and transport
envelope. The advertised maximum therefore applies to the complete
model-facing result, not just its inner data object.

An Agent should escalate reads only as needed:

```text
summary
  → range or detail for the intended edit
  → patch using the newest observation_id
  → summary to confirm the new revision
```

`range` and `detail` have an opaque cursor bound to the revision, timeline hash,
query selectors, include groups, and page limit. A changed timeline produces
`stale_cursor`; a changed query produces `invalid_cursor`. Restart pagination
from page one instead of combining pages from different timeline states.

## Field disclosure

Every bounded strip includes stable targeting and timing fields. Optional groups
are requested explicitly:

- `text`: text and editable text presentation;
- `source`: resolved source path;
- `transform`: transform and blend fields;
- `audio`: volume;
- `proxy`: proxy state;
- `metadata`: host metadata.

Large strings and objects are truncated by UTF-8 byte count and reported in
`_truncated_fields`. Pagination also shrinks a page when necessary. If a single
strip still cannot fit, the request fails with `context_budget_exceeded`; the
server never emits a cursor that makes no progress.

## Compaction boundary

After a major milestone, preserve:

- project path and user objective;
- completed actions;
- last verified revision and timeline hash;
- relevant strip IDs;
- recent applied patch IDs and verified output paths;
- user constraints, blockers, and next action.

Discard:

- observation IDs;
- complete timelines and raw tool history;
- raw Blender logs and expired diagnostics;
- detailed reasoning for completed work.

After compaction or task handoff, call `read summary`, then perform a targeted
`range/detail` read and use only the newly returned observation ID. This makes
compaction recovery deterministic without treating conversation memory as
project state.

### Bounded resume capsule

`build_resume_capsule` turns the preserved state into a deterministic JSON
capsule capped at 4 KB. Long histories retain recent entries, the total and
omitted counts, and a SHA-256 digest of the complete sequence. The digest
detects changes to older history without replaying it into model context.
Per-field and recent-item limits are machine-readable under
`compaction.capsule` in the context policy.

The capsule never accepts observation IDs or cursors. Even when a capsule
contains a last confirmed revision and hash, the first resumed action remains a
new summary read followed by a targeted detail read.

## Compatibility

`view="full"` remains available for explicit legacy callers. It is marked
`bounded=false`, cannot be paged or filtered, and is not used by the Skill or
MCP default path.

## Non-goals

- The core library does not compact model conversations.
- The core library does not persist prompts or reasoning.
- The MCP server and Skill do not retain conversation history between calls.
- `changes_since_revision` requires a bounded change journal and is deferred to
  a later protocol version.

## Related guidance

- [Skills and progressive workflow instructions](https://developers.openai.com/plugins/concepts/skills)
- [MCP tools and structured results](https://developers.openai.com/plugins/concepts/mcp-server)
- [Compaction for long-running tool workflows](https://developers.openai.com/api/docs/guides/latest-model)
