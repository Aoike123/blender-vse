from __future__ import annotations

import json
import re

from blender_vse.catalog import (
    CONTROL_PLANE_COMMANDS,
    ERROR_CODES,
    HEADLESS_OPERATIONS,
    INTERNAL_OPERATIONS,
    OPERATION_FAMILIES,
    PROJECT_OPTIONAL_OPERATIONS,
    PUBLIC_OPERATIONS,
    READ_ONLY_OPERATIONS,
    REMOVED_OPERATIONS,
    duplicate_family_members,
    operation_catalog,
)
from blender_vse.blender.runner import HEADLESS_ALLOWED_OPS
from blender_vse.blender.vse_ops import (
    OPS,
    READ_ONLY_OPS,
    REMOVED_OPS,
    _op_families,
    available_ops,
)


def test_every_public_operation_has_exactly_one_family() -> None:
    family_members = {
        operation
        for operations in OPERATION_FAMILIES.values()
        for operation in operations
    }
    assert family_members == PUBLIC_OPERATIONS
    assert not duplicate_family_members()
    assert len(PUBLIC_OPERATIONS) >= 140


def test_catalog_names_are_stable_snake_case() -> None:
    all_names = (
        PUBLIC_OPERATIONS
        | CONTROL_PLANE_COMMANDS
        | INTERNAL_OPERATIONS
        | set(REMOVED_OPERATIONS)
    )
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in all_names)


def test_adapter_exactly_implements_public_and_internal_operations() -> None:
    assert set(available_ops()) == PUBLIC_OPERATIONS | INTERNAL_OPERATIONS
    assert not (PUBLIC_OPERATIONS & INTERNAL_OPERATIONS)


def test_decorator_and_catalog_agree_on_read_only_behavior() -> None:
    implemented = set(available_ops())
    expected = READ_ONLY_OPERATIONS | {"validate_checkpoint_restore"}
    assert READ_ONLY_OPS & implemented == expected
    assert all(
        bool(getattr(OPS[name], "read_only", False)) == (name in READ_ONLY_OPS)
        for name in implemented
    )


def test_execution_policy_comes_from_the_same_catalog() -> None:
    assert HEADLESS_ALLOWED_OPS == HEADLESS_OPERATIONS
    assert HEADLESS_OPERATIONS < PUBLIC_OPERATIONS
    assert PROJECT_OPTIONAL_OPERATIONS <= HEADLESS_OPERATIONS


def test_removed_operations_are_consistent_and_unreachable() -> None:
    assert REMOVED_OPS == REMOVED_OPERATIONS
    assert not (set(REMOVED_OPERATIONS) & set(available_ops()))
    assert CONTROL_PLANE_COMMANDS <= set(REMOVED_OPERATIONS)


def test_blender_operation_families_are_complete() -> None:
    assert _op_families() == {
        family: sorted(operations)
        for family, operations in OPERATION_FAMILIES.items()
    }


def test_catalog_is_json_serializable() -> None:
    payload = operation_catalog()
    assert json.loads(json.dumps(payload)) == payload
    assert set(payload["operations"]) == PUBLIC_OPERATIONS
    assert set(payload["error_codes"]) == ERROR_CODES
