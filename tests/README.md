# Test layout

[Chinese version](README_zh-CN.md)

- `unit/`: isolated host-side behavior; no Blender process.
- `contract/`: operation catalog, schemas, docs, packaging, and test-plan drift.
- `integration/`: real Blender scripts; never collected by default pytest.
- `plugin/`: the exact packaged stdio launch contract; does not open Blender.
- `clients/`: real Claude and DSH packaging/configuration validation in isolated state.
- `evals/`: state-transition and long-session context/compaction evaluation.
- `fixtures/generate_media.py`: deterministic local media generation.
- `test-plan.json`: profile membership, dependencies, timeouts, and budgets.
- `run.py`: cross-platform profile runner.

Use `python tests/run.py fast` during development, `python tests/run.py mcp`
after MCP boundary changes, and `python tests/run.py plugin` after plugin
manifest or launch-command changes. Read the [testing guide](../docs/testing.md)
before running a GUI profile. Run `python tests/run.py harness` after changing
Claude or DSH packaging. Run `python tests/run.py stateful` after changing
context budgets, resume rules, or Skill state transitions.
