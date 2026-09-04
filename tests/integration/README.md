# Blender integration tests

[Chinese version](README_zh-CN.md)

These scripts exercise real Blender behavior and are deliberately excluded from
default pytest collection. Run them through the profile runner so that fixtures,
execution policy, timeouts, and direct-mutation exceptions remain bounded:

```bash
python tests/run.py blender-headless
python tests/run.py blender-smoke
python tests/run.py blender-full
```

`blender-smoke` is the standard pre-release GUI gate. It performs one public
read/patch/read/patch/read/verify workflow without an internal mutation bypass.
`blender-full` also runs every registered integration workflow.

Synthetic media is generated once with FFmpeg. Projects are written only under
the ignored `projects/` directory. Keep personal projects closed: the session
guard rejects a different open `.blend`, but the full profile is deliberately
mutation-heavy and runs sequentially.

See [Testing](../../docs/testing.md) for profile budgets and CI responsibilities.
