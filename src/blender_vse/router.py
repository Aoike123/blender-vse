"""Route typed edit commands to the Blender VSE adapter."""

from __future__ import annotations

from .catalog import (
    HEADLESS_OPERATIONS,
    PROJECT_OPTIONAL_OPERATIONS,
    PUBLIC_OPERATIONS,
    REMOVED_OPERATIONS,
    operation_catalog,
)

# Compatibility aliases retained for existing integrations.
BLENDER_OPS = set(PUBLIC_OPERATIONS)
HEADLESS_ALLOWED_BLENDER_OPS = set(HEADLESS_OPERATIONS)
PROJECT_OPTIONAL_BLENDER_OPS = set(PROJECT_OPTIONAL_OPERATIONS)
REMOVED_BLENDER_OPS = {
    name: details["message"] for name, details in REMOVED_OPERATIONS.items()
}


class RoutingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def route(op: str, params: dict) -> dict:
    """Return the selected adapter or raise a stable routing error."""

    removed = REMOVED_OPERATIONS.get(op)
    if removed:
        raise RoutingError(removed["code"], removed["message"])
    if op in PUBLIC_OPERATIONS:
        if op not in PROJECT_OPTIONAL_OPERATIONS and not params.get("project"):
            raise RoutingError(
                "invalid_args",
                f"blender op '{op}' requires 'project' (.blend path)",
            )
        return {"adapter": "blender"}
    raise RoutingError("unsupported", f"unknown op: {op}")


def router_execute(op: str, params: dict) -> dict:
    """Validate and execute a public edit command through Blender."""

    from .blender import blender_execute

    try:
        route(op, params)
    except RoutingError as error:
        return {
            "ok": False,
            "op": op,
            "adapter": "router",
            "error": {"code": error.code, "message": error.message},
        }
    return blender_execute(op, params)


def available_ops_report() -> dict:
    """Return the catalog plus the concrete adapter implementation list."""

    from .blender import available_ops

    report = operation_catalog()
    report["adapter"] = sorted(available_ops())
    # Compatibility keys used by the original embedded integration.
    report["blender"] = report["adapter"]
    report["router"] = report["operations"]
    report["blender_live_session"] = sorted(
        PUBLIC_OPERATIONS - HEADLESS_OPERATIONS
    )
    report["blender_headless_allowed"] = report["headless"]
    return report
