"""Filesystem and concurrency boundary for the local MCP adapter."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from blender_vse.api import BlenderVSE
from blender_vse.blender.config import PROJECTS_DIRNAME, projects_dir
from blender_vse.context import CONTEXT_POLICY

LOGGER = logging.getLogger(__name__)


class ProjectAccessError(ValueError):
    """A stable rejection raised before Blender or its bridge is contacted."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _normalized_path_key(path: Path) -> str:
    return os.path.normcase(str(path))


class ProjectBoundary:
    """Resolve ``.blend`` paths inside the workspace project directory.

    Relative paths such as ``demo.blend`` resolve against the first root, so
    callers never need to know where the workspace lives on disk.
    """

    def __init__(self, roots: Iterable[str | Path]):
        normalized: list[Path] = []
        seen: set[str] = set()
        for raw_root in roots:
            try:
                root = Path(raw_root).expanduser().resolve(strict=False)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ValueError(f"invalid allowed project root: {raw_root!r}") from exc
            if root.exists() and not root.is_dir():
                raise ValueError(f"allowed project root is not a directory: {root}")
            key = _normalized_path_key(root)
            if key not in seen:
                normalized.append(root)
                seen.add(key)
        if not normalized:
            raise ValueError("at least one allowed project root is required")
        self._roots = tuple(normalized)

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> ProjectBoundary:
        """Confine projects to ``<workspace>/blender-vse-projects``."""

        return cls([projects_dir(environ=environ, cwd=cwd)])

    @property
    def roots(self) -> tuple[Path, ...]:
        """Return immutable canonical allowed roots for diagnostics."""

        return self._roots

    def resolve(self, project: str | Path) -> Path:
        """Resolve and authorize one Blender project path."""

        if not isinstance(project, (str, Path)) or not str(project).strip():
            raise ProjectAccessError(
                "invalid_project_path", "project must be a non-empty path"
            )
        try:
            candidate = Path(project).expanduser()
            if not candidate.is_absolute():
                candidate = self._roots[0] / candidate
            candidate = candidate.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProjectAccessError(
                "invalid_project_path", "project path could not be resolved"
            ) from exc
        if candidate.suffix.lower() != ".blend":
            raise ProjectAccessError(
                "invalid_project_path", "project must name a .blend file"
            )
        if candidate.exists() and not candidate.is_file():
            raise ProjectAccessError(
                "invalid_project_path", "project must name a file, not a directory"
            )
        if not any(candidate.is_relative_to(root) for root in self._roots):
            raise ProjectAccessError(
                "project_not_allowed",
                f"project must be inside the workspace {PROJECTS_DIRNAME} folder",
            )
        return candidate


class ProjectLockRegistry:
    """Serialize projects through a bounded set of deterministic lock stripes."""

    def __init__(self, stripes: int = 64) -> None:
        if not 1 <= stripes <= 1024:
            raise ValueError("lock stripes must be between 1 and 1024")
        self._locks = tuple(threading.Lock() for _ in range(stripes))

    def lock_for(self, project: Path) -> threading.Lock:
        key = _normalized_path_key(project).encode("utf-8")
        index = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % len(
            self._locks
        )
        return self._locks[index]


def _encoded_size(value: Mapping[str, Any]) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _bounded_failure(op: str, code: str, message: str) -> dict[str, Any]:
    policy = CONTEXT_POLICY["tool_results"]["error"]
    message_bytes = str(message).encode("utf-8")
    message_limit = int(policy["message_bytes"])
    result: dict[str, Any] = {
        "ok": False,
        "op": op,
        "error": {
            "code": code,
            "message": message_bytes[:message_limit].decode("utf-8", errors="ignore"),
            "truncated": len(message_bytes) > message_limit,
        },
        "context": {
            "protocol_version": CONTEXT_POLICY["version"],
            "view": "error",
            "bounded": True,
            "max_bytes": int(policy["max_bytes"]),
            "response_bytes": 0,
        },
    }
    for _ in range(3):
        result["context"]["response_bytes"] = _encoded_size(result)
    return result


class MCPAdapter:
    """Thread-safe adapter from MCP tool arguments to :class:`BlenderVSE`."""

    def __init__(
        self,
        *,
        controller: BlenderVSE | None = None,
        boundary: ProjectBoundary | None = None,
        locks: ProjectLockRegistry | None = None,
    ) -> None:
        self.controller = controller if controller is not None else BlenderVSE()
        self.boundary = (
            boundary if boundary is not None else ProjectBoundary.from_environment()
        )
        self.locks = locks if locks is not None else ProjectLockRegistry()

    def _invoke(
        self,
        op: str,
        project: str | Path,
        callback: Callable[[Path], dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            resolved = self.boundary.resolve(project)
        except ProjectAccessError as exc:
            return _bounded_failure(op, exc.code, exc.message)
        except (OSError, RuntimeError, ValueError):
            LOGGER.exception("Project authorization failed")
            return _bounded_failure(
                op,
                "invalid_project_path",
                "project authorization failed",
            )
        lock = self.locks.lock_for(resolved)
        try:
            with lock:
                return callback(resolved)
        except Exception as exc:  # pragma: no cover - defensive host boundary
            LOGGER.exception("Unhandled %s failure for %s", op, resolved)
            return _bounded_failure(
                op,
                "internal_error",
                f"{type(exc).__name__}: {exc}",
            )

    def read(self, project: str | Path, **kwargs: Any) -> dict[str, Any]:
        return self._invoke(
            "read", project, lambda resolved: self.controller.read(resolved, **kwargs)
        )

    def patch(self, project: str | Path, **kwargs: Any) -> dict[str, Any]:
        return self._invoke(
            "patch",
            project,
            lambda resolved: self.controller.patch(resolved, **kwargs),
        )

    def acknowledge(self, project: str | Path, **kwargs: Any) -> dict[str, Any]:
        return self._invoke(
            "acknowledge",
            project,
            lambda resolved: self.controller.acknowledge(resolved, **kwargs),
        )

    def verify(self, project: str | Path, **kwargs: Any) -> dict[str, Any]:
        return self._invoke(
            "verify",
            project,
            lambda resolved: self.controller.verify(resolved, **kwargs),
        )


__all__ = [
    "MCPAdapter",
    "ProjectAccessError",
    "ProjectBoundary",
    "ProjectLockRegistry",
]
