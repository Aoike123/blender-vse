# Testing

[Chinese version](testing_zh-CN.md)

## One plan, nine profiles

[`tests/test-plan.json`](../tests/test-plan.json) is the canonical test manifest.
[`tests/run.py`](../tests/run.py) reads it, applies per-suite environment policy,
enforces timeouts, generates synthetic fixtures once, and reports durations.
Each pytest invocation gets a unique ignored `.tmp` base directory containing
the profile, Python version, process ID, and timestamp; the runner cleans it
afterward. This avoids both operating-system temp collisions and reuse across
matrix jobs, concurrent runs, or different local identities.
Missing pytest, JSON Schema validation, MCP, uv, coverage, Blender, or FFmpeg
prerequisites fail during preflight instead of after a partial profile run.

| Profile | Runs | Blender GUI | Target / hard timeout |
| --- | --- | --- | ---: |
| `fast` | Core unit + contract tests, excluding MCP SDK tests | No | 3 / 10 s |
| `coverage` | Same core tests with branch coverage | No | 5 / 15 s |
| `mcp` | Security boundary, four tools, coverage + real stdio | No | 4 / 10 s |
| `plugin` | Exact `.mcp.json` command and four-tool discovery | No | 60 / 180 s |
| `harness` | Real Claude manifest validation plus DSH Skill/Cordis composition | No | 60 / 180 s |
| `stateful` | Scenario replay + 250-cycle context/compaction eval | No | 5 / 15 s |
| `blender-headless` | Native media inspector | No | 15 / 60 s |
| `blender-smoke` | One public API workflow | Yes | 120 / 240 s |
| `blender-full` | Smoke plus every registered integration script | Yes | 900 / 1200 s |

```bash
python tests/run.py list
python tests/run.py fast
python tests/run.py coverage
python tests/run.py mcp
python tests/run.py plugin
python tests/run.py harness
python tests/run.py stateful
python tests/run.py blender-smoke
```

Script profiles stop on the first failure to save time. Pass `--keep-going`
when collecting a complete regression report. Use `--dry-run` to inspect exact
commands without starting Blender.

The target is a performance signal; crossing it is reported as slow. The hard
timeout is the safety boundary that terminates a stuck process. Keeping these
separate prevents normal CI jitter from becoming a false failure.

The headless profile explicitly disables optional live-consistency checks, so a
bridge that happens to be running cannot turn it into a GUI test.

The plugin profile may provision a local uv environment on first run, so its
60-second target includes dependency resolution. It only lists MCP tools and
does not open Blender or mutate a project. After the checkout launch warms the
cache, the extracted-bundle launch is forced offline.

The Harness profile is an explicit release gate rather than a pull-request CI
job. It strictly validates and installs the plugin with a pinned Claude Code
CLI, persists the required directory option, connects the plugin MCP server,
and composes DSH Skill/Cordis state with the installed DSH CLI. All client state
is isolated under repository temporary storage; npm access may be required on
the first run, and the user's Claude or DSH configuration is not edited.

GUI profiles must run from a process attached to the same interactive desktop
as Blender. Service, sandbox, and isolated desktop sessions correctly fail with
`gui_not_visible` even when they can enumerate a Blender window; do not weaken
that check to make hosted automation pass.

## What the fast gate proves

The fast gate is Blender-free and subprocess-free but broader than ordinary
unit tests. Together with the separate MCP gate, it checks:

- all public operation names route and belong to exactly one family;
- adapter, router, Schema, read-only policy, headless policy, internal
  primitives, and removed-operation errors stay synchronized;
- revision API success, rollback, stale-base, checkpoint, and session failures;
- summary/range/detail filtering, pagination, stale cursors, UTF-8 byte
  truncation, and hard response budgets;
- exact four-tool MCP discovery, generated input guards, in-memory protocol
  calls, allowed-root rejection, and per-project serialization;
- Skill command-index drift, example schemas, exact MCP surface, dependency
  metadata, reference links, and instruction/index byte bounds;
- plugin manifest/version/path integrity, approval policy, environment
  allowlist, deterministic marketplace archive, and bundled file allowlist;
- resume-capsule Schema/budgets/history digests plus stateful scenario corpus
  integrity; the separate stateful gate measures 250 edit cycles;
- portable cross-client configuration, version/protocol parity, and
  deterministic source, wheel, and plugin archives;
- bridge framing, fragmented socket reads, loopback policy, and project identity;
- runner mode selection, timeouts, result parsing, and temporary-script cleanup;
- proxy manifest hashes, path containment, required fields, and stale sources;
- every local Markdown link, package version, licenses, source manifest, and
  test-plan/context-policy entry.

Parameterized catalog tests cover every public operation without launching 140
Blender processes. Behavioral rendering and persistence remain in the Blender
profiles where mocks would not be meaningful.

## Coverage scope

The coverage profile measures deterministic host-side Python and branch
behavior. Fixed bpy template bodies, the vendored in-Blender bridge, and the
platform/GUI-specific live-session state machine are excluded from the core
numeric threshold. Dependency-free MCP authorization tests remain in core
coverage, while the optional protocol server has its own profile enforcing a
stricter 85% branch threshold on both supported-version edges. The Blender
exclusions still have focused protocol/safety contracts and real Blender
profiles; forcing every embedded script and OS branch through mocks would raise
the number while reducing confidence. The thresholds and exclusions live in
`pyproject.toml` and `tests/test-plan.json`.

## Integration safety

- Fixtures are generated from color and sine-wave filters; no opaque media is
  committed.
- Projects and renders stay under ignored repository directories.
- Test-generated Blender scripts and logs use the repository's ignored `.tmp`
  directory instead of shared user state.
- GUI profiles are sequential because one visible Blender session owns the
  timeline. Do not parallelize them.
- The session guard refuses to switch away from a different open human project.
- If initial GUI proof fails, the smoke harness closes only a clean blank or
  exact test project that it launched; it never closes dirty or foreign work.
- `BLENDER_VSE_ALLOW_DIRECT_MUTATION=1` is applied only to named legacy suites;
  the public smoke workflow never uses it.
- Keep personal Blender projects closed before a full run.

## CI layout

CI runs six independent jobs in parallel:

1. fast tests on the minimum and maximum supported Python versions;
2. one coverage run on the primary Python version;
3. the complete MCP contract plus one real stdio subprocess discovery on the
   minimum and maximum Python versions;
4. the exact uv-backed plugin launch on one Python version;
5. deterministic stateful/compaction scenario evals;
6. one source/wheel/plugin build plus archive and CLI smoke checks.

The MCP suite is isolated from core fast and coverage collection, so importing
the optional SDK and starting stdio are not repeated in unrelated jobs.
Building once avoids the former repeated build in every Python matrix job.
Blender profiles remain explicit release gates because hosted runners do not
provide the required visible desktop proof.

## Adding tests

- Put pure behavior tests in `tests/unit`.
- Put synchronization, Schema, documentation, packaging, and test-plan checks
  in `tests/contract`.
- Put real Blender behavior in `tests/integration` and register every new script
  in `blender-full`.
- Add only the smallest representative workflow to `blender-smoke`.
- Keep the `fast` target at three seconds; prefer parameterization and fakes over
  process startup.
