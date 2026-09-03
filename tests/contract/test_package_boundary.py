from __future__ import annotations

from importlib import resources
from pathlib import Path

import blender_vse


def test_package_has_no_host_application_imports() -> None:
    package_root = Path(blender_vse.__file__).parent
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in package_root.rglob("*.py")
        if "bridge_addon" not in path.name
    )
    assert "from tools." not in source
    assert "import tools." not in source
    assert "from adapters" not in source
    assert "import adapters" not in source


def test_schemas_are_packaged() -> None:
    schema_root = resources.files("blender_vse.schemas")
    assert schema_root.joinpath("edit-command.schema.json").is_file()
    assert schema_root.joinpath("timeline-state.schema.json").is_file()
    assert schema_root.joinpath("read-query.schema.json").is_file()
    assert schema_root.joinpath("read-result.schema.json").is_file()
    assert schema_root.joinpath("resume-capsule.schema.json").is_file()
    assert resources.files("blender_vse").joinpath("context-policy.json").is_file()
