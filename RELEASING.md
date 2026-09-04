# Releasing

[Chinese version](RELEASING_zh-CN.md)

## 1. Metadata and documentation

- [ ] Replace `Unreleased` in `CHANGELOG.md` with the release date.
- [ ] Keep `pyproject.toml` and `src/blender_vse/__init__.py` versions equal.
- [ ] Confirm the documentation index has no broken local links.
- [ ] Record exact Blender/OS combinations actually verified.
- [ ] Review `SECURITY.md` and third-party notices.

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

- [ ] Run the active host's bundled `skill-creator` `quick_validate.py` against
  `skills/blender-vse`.
- [ ] Run the active host's bundled `plugin-creator` `validate_plugin.py`
  against the repository root.

- [ ] No command reaches its hard timeout; investigate and record any target
  overrun reported from `tests/test-plan.json`.
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

- [ ] The source archive contains bilingual docs, tests, test-plan JSON,
  licenses, the validated Skill, and the generated command index.
- [ ] The wheel contains every packaged Schema, the context policy, and the
  bundled bridge and MCP adapter runtime.
- [ ] Both archives contain AGPL, the bridge MIT license, and
  `THIRD_PARTY_NOTICES.md`.
- [ ] Install the wheel into a clean environment and run `blender-vse ops` and
  `blender-vse status`.
- [ ] Install the wheel with its `mcp` extra and confirm MCP discovery exposes
  exactly the four documented tools.
- [ ] Unpack the deterministic plugin archive, validate its marketplace layout,
  and install/test it from a new Codex task.

## 4. Publish

- [ ] Commit the release state.
- [ ] Create an annotated `vX.Y.Z` tag.
- [ ] Publish the hosting-platform release with compatibility results.
- [ ] Publish Python artifacts only after confirming the distribution name and
  maintainer account on the selected package index.
- [ ] Verify the published hashes and installation instructions.
