# Releasing

[Chinese version](RELEASING_zh-CN.md)

## 1. Metadata and documentation

- [ ] Replace `Unreleased` in both `CHANGELOG.md` and `CHANGELOG_zh-CN.md` with
  the release date.
- [ ] Keep `pyproject.toml` and `src/blender_vse/__init__.py` versions equal.
- [ ] Confirm that neither documentation index contains broken local links.
- [ ] Record exact Blender/OS combinations actually verified.
- [ ] Review both security policies and both third-party notices.

## 2. Automated gates

```bash
python tests/run.py fast
python tests/run.py coverage
python tests/run.py mcp
python tests/run.py plugin
python tests/run.py harness
python tests/run.py stateful
python tests/run.py blender-headless
python tests/run.py blender-smoke
```

```bash
python skills/blender-vse/scripts/generate_command_index.py --check
python scripts/build_plugin.py
python scripts/build_plugin.py --check
```

- [ ] Run the `skill-creator` copy of `quick_validate.py` bundled with the active
  host against `skills/blender-vse`.
- [ ] Run the `plugin-creator` copy of `validate_plugin.py` bundled with the
  active host against the repository root.

- [ ] Confirm that no command reaches its hard timeout. Investigate and record
  any target overrun the runner reports against the limits in `tests/test-plan.json`.
- [ ] Run `python tests/run.py blender-full` for changes to bpy templates,
  revision hashing, timeline persistence, or Blender version support.
- [ ] Confirm the public smoke workflow runs without direct-mutation bypass.
- [ ] Run GUI profiles from the same interactive desktop as Blender, not a
  service or isolated automation desktop.

## 3. Build and inspect

```bash
python -m build
python tests/verify_distribution.py dist
```

- [ ] The source distribution contains bilingual documentation, tests, the test
  plan JSON, licenses, the validated Skill, and the generated command index.
- [ ] The wheel contains every packaged Schema, the context policy, and the
  bundled Bridge and MCP adapter runtime.
- [ ] Both Python distributions contain the AGPL, the Bridge MIT license, and
  `THIRD_PARTY_NOTICES.md`.
- [ ] Install the wheel into a clean environment and run `blender-vse ops` and
  `blender-vse status`.
- [ ] Install the wheel with its `mcp` extra and confirm MCP discovery exposes
  exactly the four documented tools.
- [ ] Unpack the deterministic plugin archive, validate its marketplace layout,
  and install and test it from a fresh Codex task.

## 4. Publish

- [ ] Commit the release state.
- [ ] Create an annotated `vX.Y.Z` tag.
- [ ] Publish a release on the hosting platform, including the compatibility
  results.
- [ ] Publish Python artifacts only after confirming the distribution name and
  maintainer account on the selected package index.
- [ ] Verify the published hashes and installation instructions.
