# Contributing

[Chinese version](CONTRIBUTING_zh-CN.md)

Contributions are welcome. Keep the package independent of agent frameworks,
production data stores, downloaders, and media providers.

## Development setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python tests/run.py fast
```

The `fast` gate is the normal development loop and is designed to finish within
three seconds. Run `python tests/run.py list` before selecting a Blender
profile.

## Where a change belongs

- Public API and collaboration policy: `src/blender_vse/api.py`
- Operation names and classification: `src/blender_vse/catalog.py`
- Fixed `bpy` operation templates: `src/blender_vse/blender/vse_ops.py`
- Execution and session policy: `src/blender_vse/blender/runner.py` and
  `live_session.py`
- Serialized data contracts: `src/blender_vse/schemas`
- Context views and budgets: `src/blender_vse/context.py` and
  `context-policy.json`
- Context-compaction capsules: `src/blender_vse/resume.py`
- MCP tools and authorization boundaries: `src/blender_vse/mcp`
- Agent workflow and generated command index: `skills/blender-vse`
- Local plugin metadata and launch contract: `.codex-plugin/plugin.json` and
  `.mcp.json`
- Deterministic plugin archive: `scripts/build_plugin.py`
- Portable client configuration: `scripts/print_mcp_config.py`
- Test profiles and budgets: `tests/test-plan.json`
- User documentation: `docs`, linked through `docs/index.md`

## Change checklist

1. Start with a focused unit or contract regression test.
2. Keep new `bpy` operations fixed, typed, and JSON-encoded; never expose
   arbitrary Python.
3. Register every public operation in exactly one catalog family, and update
   the edit-command schema.
4. Keep bounded-read output within the machine-readable context policy, and
   never introduce a cursor that makes no progress.
5. Add coverage against real Blender only when a host-side test cannot establish
   the behavior.
6. Keep the public smoke profile small; put broader scripts in `blender-full`.
7. Run `python tests/run.py fast` and `python tests/run.py coverage`.
8. After changing a command signature, run
   `python skills/blender-vse/scripts/generate_command_index.py` and commit the
   generated index.
9. When behavior changes, update the public documentation and both
   `CHANGELOG.md` and `CHANGELOG_zh-CN.md`.

Changes to plugin metadata or the stdio launch command also require
`python tests/run.py plugin` and the `plugin-creator` validator bundled with the
active Codex installation.

Changes to context budgets, compaction state, observation transitions, or Skill
recovery rules require `python tests/run.py stateful`. If behavior changes
intentionally, update the model-ready scenario corpus as well.

Pull requests that affect session identity, persistence, checkpoint restore,
proxy validation, or the direct-mutation policy should also run
`python tests/run.py blender-smoke` on a visible desktop Blender installation.

See [Testing](docs/testing.md) for profile boundaries and safety rules.
