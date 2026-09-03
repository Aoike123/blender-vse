# Contributing

[Chinese version](CONTRIBUTING_zh-CN.md)

Contributions are welcome. Keep the package independent of agent frameworks,
production databases, downloaders, and media providers.

## Development setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python tests/run.py fast
```

The fast gate is the normal inner loop and has a three-second target. Run
`python tests/run.py list` before choosing a Blender profile.

## Where a change belongs

- Public API and collaboration policy: `src/blender_vse/api.py`
- Operation names and classification: `src/blender_vse/catalog.py`
- Fixed bpy templates: `src/blender_vse/blender/vse_ops.py`
- Execution and session policy: `src/blender_vse/blender/runner.py` and
  `live_session.py`
- Serialized contracts: `src/blender_vse/schemas`
- Context views and budgets: `src/blender_vse/context.py` and
  `context-policy.json`
- Compaction capsule construction: `src/blender_vse/resume.py`
- MCP tool and authorization boundary: `src/blender_vse/mcp`
- Agent workflow and generated command index: `skills/blender-vse`
- Local plugin metadata and launch contract: `.codex-plugin/plugin.json` and
  `.mcp.json`
- Deterministic plugin archive: `scripts/build_plugin.py`
- Portable client configuration: `scripts/print_mcp_config.py`
- Test profiles and budgets: `tests/test-plan.json`
- User documentation: `docs`, linked through `docs/index.md`

## Change checklist

1. Add a focused unit or contract regression first.
2. Keep new bpy operations fixed and type/JSON encoded; never expose arbitrary
   Python.
3. Register each public operation in exactly one catalog family and update the
   edit-command Schema.
4. Keep bounded read output within the machine-readable context policy; never
   introduce a zero-progress cursor.
5. Add real Blender coverage only where a host-side test cannot prove behavior.
6. Keep the public smoke profile small; register broader scripts in
   `blender-full`.
7. Run `python tests/run.py fast` and `python tests/run.py coverage`.
8. After command-signature changes, run
   `python skills/blender-vse/scripts/generate_command_index.py` and commit the
   generated index.
9. Update public docs and `CHANGELOG.md` when behavior changes.

Changes to plugin metadata or the stdio launch command must also run
`python tests/run.py plugin` and the active Codex installation's bundled
`plugin-creator` validator.

Changes to context budgets, compaction state, observation transitions, or Skill
recovery rules must run `python tests/run.py stateful` and update the model-ready
scenario corpus when behavior intentionally changes.

Pull requests that touch session identity, persistence, checkpoint restore,
proxy validation, or direct-mutation policy should also run
`python tests/run.py blender-smoke` on a visible desktop Blender installation.

See [Testing](docs/testing.md) for profile boundaries and safety rules.
