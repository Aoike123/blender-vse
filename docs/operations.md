# Operation catalog

[Chinese version](operations_zh-CN.md)

The operation catalog is generated from `src/blender_vse/catalog.py`. Use the
CLI instead of copying the complete list into application code:

```bash
blender-vse ops
blender-vse ops --family subtitles
blender-vse ops --family render
```

The JSON response includes:

- `operations`: all public low-level operation names;
- `families`: each public operation assigned to exactly one functional family;
- `read_only`: operations that never save timeline changes;
- `headless`: operations permitted in a background Blender process;
- `project_optional`: operations such as native media inspection that do not
  require a `.blend` path;
- `control_plane`: high-level patch commands such as checkpoint restore;
- `internal`: implementation primitives hidden from the public router;
- `removed`: old operations with stable migration errors;
- `error_codes`: the complete stable error-code vocabulary accepted by the
  operation-result schema.

## Public versus control-plane operations

Most timeline-changing operations appear as public *command names*, but they
must still be applied through a revision-guarded `BlenderVSE.patch`.
`restore_checkpoint` is different: it must be the only command in a patch
because the controller closes the matching GUI project, replaces the file,
reopens it, verifies visibility, and finalizes a new revision.

`validate_checkpoint_restore` and `finalize_checkpoint_restore` are internal.
They exist in the adapter implementation but not in the public router.

## Externalized responsibilities

The host application owns proxy generation and the project-wide asset registry.
This package accepts verified proxy manifests and asset bindings; it does not
manage either system.

## Adding an operation

1. Add a fixed, typed script template to `blender/vse_ops.py`.
2. Assign the name to exactly one family in `catalog.py`.
3. Mark it correctly in the catalog's read-only/headless/project-optional sets.
4. Add it to the edit-command schema.
5. Add fast validation and at least one relevant Blender integration-test assertion.
6. Run `python tests/run.py fast`; catalog contract tests reject missing,
   duplicated, or inconsistently classified operations.
