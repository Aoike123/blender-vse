from __future__ import annotations

import pytest

from blender_vse.catalog import PUBLIC_OPERATIONS, REMOVED_OPERATIONS
from blender_vse import blender as blender_module
from blender_vse.router import (
    BLENDER_OPS,
    HEADLESS_ALLOWED_BLENDER_OPS,
    RoutingError,
    available_ops_report,
    route,
    router_execute,
)


def test_known_operation_routes_to_blender() -> None:
    assert route("list_strips", {"project": "demo.blend"}) == {
        "adapter": "blender"
    }


@pytest.mark.parametrize("operation", sorted(PUBLIC_OPERATIONS))
def test_every_public_operation_is_routable(operation: str) -> None:
    assert route(operation, {"project": "demo.blend"}) == {"adapter": "blender"}


def test_project_is_required() -> None:
    with pytest.raises(RoutingError) as caught:
        route("list_strips", {})
    assert caught.value.code == "invalid_args"


def test_native_media_inspection_does_not_require_a_blend_project() -> None:
    assert route("inspect_media", {"media_path": "clip.mp4"}) == {
        "adapter": "blender"
    }


def test_removed_proxy_builder_has_actionable_error() -> None:
    with pytest.raises(RoutingError) as caught:
        route("generate_proxy", {"project": "demo.blend"})
    assert caught.value.code == "proxy_generation_externalized"
    assert "attach_proxy" in caught.value.message


def test_host_asset_registry_operations_are_not_claimed() -> None:
    with pytest.raises(RoutingError) as caught:
        route("list_assets", {"project": "demo.blend"})
    assert caught.value.code == "operation_externalized"


@pytest.mark.parametrize(
    ("operation", "code"),
    [(name, details["code"]) for name, details in sorted(REMOVED_OPERATIONS.items())],
)
def test_every_removed_operation_returns_its_migration_error(
    operation: str,
    code: str,
) -> None:
    with pytest.raises(RoutingError) as caught:
        route(operation, {"project": "demo.blend"})
    assert caught.value.code == code


def test_headless_operations_are_registered() -> None:
    assert HEADLESS_ALLOWED_BLENDER_OPS < BLENDER_OPS


def test_unknown_operation_is_structured() -> None:
    result = router_execute("not_real", {"project": "demo.blend"})
    assert result["ok"] is False
    assert result["adapter"] == "router"
    assert result["error"]["code"] == "unsupported"


def test_router_delegates_valid_operation(monkeypatch) -> None:
    monkeypatch.setattr(
        blender_module,
        "blender_execute",
        lambda operation, params: {"ok": True, "op": operation, "data": params},
    )
    result = router_execute("list_strips", {"project": "demo.blend"})
    assert result["ok"]
    assert result["data"]["project"] == "demo.blend"


def test_available_report_separates_public_and_internal_operations() -> None:
    report = available_ops_report()
    assert set(report["router"]) == PUBLIC_OPERATIONS
    assert set(report["adapter"]) >= PUBLIC_OPERATIONS
    assert "validate_checkpoint_restore" in report["internal"]
