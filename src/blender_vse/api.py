"""Revision-safe public API for Blender's Video Sequence Editor.

The low-level adapter exposes many fixed operations.  This module provides the
small collaboration boundary applications should normally use:

    read -> patch -> read -> patch -> verify

Each patch consumes a single-use observation token returned by ``read``.  A
manual edit made in Blender therefore causes a stale-base error instead of
being silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .blender import blender_execute, live_session
from .context import (
    CONTEXT_POLICY,
    ContextQueryError,
    ReadQuery,
    project_acknowledge_result,
    project_patch_result,
    project_read_result,
    project_session_failure,
    project_verify_result,
)

CONTRACT_VERSION = "1.3.0"
SESSION_CONTEXT_MAX_FIELDS = 32
SESSION_CONTEXT_MAX_BYTES = 1536
SESSION_CONTEXT_FORBIDDEN_KEYS = frozenset(
    {
        "area_types",
        "window_candidates",
        "ui_errors",
        "missing_current_media",
        "stability_samples",
        "observed_states",
        "screenshot",
        "traceback",
    }
)


def _failure(op: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    for key in ("session", "restore_session"):
        value = extra.get(key)
        if (
            isinstance(value, Mapping)
            and (value.get("context") or {}).get("view") != "error"
        ):
            extra[key] = project_session_failure(value)
    policy = CONTEXT_POLICY["tool_results"]["error"]
    encoded_message = str(message).encode("utf-8")
    message_limit = int(policy["message_bytes"])
    bounded_message = encoded_message[:message_limit].decode("utf-8", errors="ignore")
    result: dict[str, Any] = {
        "ok": False,
        "op": op,
        "error": {
            "code": code,
            "message": bounded_message,
            "truncated": len(encoded_message) > message_limit,
        },
        "context": {
            "protocol_version": CONTEXT_POLICY["version"],
            "view": "error",
            "bounded": True,
            "max_bytes": int(policy["max_bytes"]),
            "response_bytes": 0,
        },
    }
    result.update(extra)
    for _ in range(3):
        result["context"]["response_bytes"] = len(
            json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
    for key in ("data", "restore_session", "session"):
        if result["context"]["response_bytes"] <= result["context"]["max_bytes"]:
            break
        if key in result:
            result.pop(key)
            result[f"{key}_omitted"] = True
            for _ in range(3):
                result["context"]["response_bytes"] = len(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                )
    return result


def _error_parts(result: Mapping[str, Any]) -> tuple[str, str]:
    error = result.get("error")
    if isinstance(error, Mapping):
        return str(error.get("code") or "execution_failed"), str(
            error.get("message") or error
        )
    return "execution_failed", str(error or "operation failed")


def _session_projection(session: Mapping[str, Any]) -> dict[str, Any]:
    """Return bounded proof that the requested project is visible and usable."""

    proof = session.get("session_proof") or {}
    discovery = session.get("discovery") or {}
    projection = {
        "ready": True,
        "state": "ready",
        "pid": proof.get("pid") or session.get("pid"),
        "gui_visible": bool(proof.get("gui_visible")),
        "window_handles": proof.get("window_handles", []),
        "project": proof.get("filepath") or session.get("filepath") or "",
        "workspace": proof.get("workspace") or session.get("workspace"),
        "vse_area_count": proof.get("vse_area_count")
        or session.get("vse_area_count", 0),
        "scene": proof.get("scene"),
        "strip_owner_scene": proof.get("strip_owner_scene"),
        "window_scene": proof.get("window_scene"),
        "sequencer_scene": proof.get("sequencer_scene"),
        "scene_binding_match": bool(proof.get("scene_binding_match")),
        "strip_count": proof.get("strip_count", 0),
        "internal_strip_count": proof.get("internal_strip_count", 0),
        "visible_strip_count": proof.get("visible_strip_count", 0),
        "visible_strip_match": bool(proof.get("visible_strip_match")),
        "playhead": proof.get("playhead"),
        "timeline_bounds": proof.get("timeline_bounds"),
        "timeline_view_count": proof.get("timeline_view_count", 0),
        "preview_view_count": proof.get("preview_view_count", 0),
        "timeline_framed_count": proof.get("timeline_framed_count", 0),
        "preview_fitted_count": proof.get("preview_fitted_count", 0),
        "current_frame_visual_count": proof.get("current_frame_visual_count", 0),
        "content_display_ready": bool(proof.get("content_display_ready")),
        "layout_profile_version": proof.get("layout_profile_version", 0),
        "layout_profile_current": bool(proof.get("layout_profile_current")),
        "launched": bool(session.get("launched")),
        "discovery_waited_seconds": discovery.get("waited_seconds", 0.0),
        "discovery_attempts": discovery.get("attempts", 0),
    }
    forbidden = SESSION_CONTEXT_FORBIDDEN_KEYS.intersection(projection)
    encoded_size = len(
        json.dumps(
            projection,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )
    if (
        len(projection) > SESSION_CONTEXT_MAX_FIELDS
        or encoded_size > SESSION_CONTEXT_MAX_BYTES
        or forbidden
    ):
        raise RuntimeError(
            "session_context_budget_exceeded: "
            f"fields={len(projection)}/{SESSION_CONTEXT_MAX_FIELDS}, "
            f"bytes={encoded_size}/{SESSION_CONTEXT_MAX_BYTES}, "
            f"forbidden={sorted(forbidden)}"
        )
    return projection


class BlenderVSE:
    """High-level controller enforcing revision-safe timeline collaboration."""

    contract_version = CONTRACT_VERSION

    @staticmethod
    def execute(op: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one allowlisted low-level operation.

        Timeline mutations are rejected by the adapter unless they are wrapped
        in :meth:`patch`; this method does not expose arbitrary Python.
        """

        return blender_execute(op, dict(params))

    @staticmethod
    def _ensure_live(project: str | Path) -> dict[str, Any]:
        session = live_session.ensure_live_session(str(project))
        if session.get("ready"):
            return session
        return _failure(
            "session",
            str(session.get("code") or "session_not_ready"),
            "Blender session is not ready: "
            + str(session.get("message") or session.get("code") or "unknown error"),
            session=session,
        )

    def read(
        self,
        project: str | Path,
        *,
        create_if_missing: bool = False,
        resolution: tuple[int, int] = (1920, 1080),
        fps: int = 30,
        view: str = "summary",
        frame_range: Iterable[int] | None = None,
        strip_ids: Iterable[str] | None = None,
        channels: Iterable[int] | None = None,
        strip_types: Iterable[str] | None = None,
        include: Iterable[str] | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Read a revision token plus a bounded timeline projection.

        ``summary`` is the context-safe default. Use ``range`` or ``detail``
        before a targeted patch. ``full`` is an explicit compatibility mode and
        is intentionally not context bounded.
        """

        try:
            query = ReadQuery.create(
                view=view,
                frame_range=frame_range,
                strip_ids=strip_ids,
                channels=channels,
                strip_types=strip_types,
                include=include,
                cursor=cursor,
                limit=limit,
            )
        except ContextQueryError as error:
            return _failure("read", error.code, error.message)

        project_path = Path(project).expanduser().resolve()
        if not project_path.is_file() and not create_if_missing:
            return _failure(
                "read",
                "project_not_found",
                f"Blender project not found: {project_path}",
            )

        session = self._ensure_live(project_path)
        if not session.get("ready"):
            return session

        if not project_path.is_file():
            created = self.execute(
                "create_project",
                {
                    "project": str(project_path),
                    "resolution": list(resolution),
                    "fps": fps,
                },
            )
            if not created.get("ok"):
                code, message = _error_parts(created)
                return _failure("read", code, f"create_project failed: {message}")

        revision = self.execute("get_revision", {"project": str(project_path)})
        if not revision.get("ok"):
            code, message = _error_parts(revision)
            return _failure("read", code, f"get_revision failed: {message}")
        timeline = self.execute(
            "list_strips",
            {"project": str(project_path), "with_text": query.with_text},
        )
        if not timeline.get("ok"):
            code, message = _error_parts(timeline)
            return _failure("read", code, f"list_strips failed: {message}")

        base = {
            **(revision.get("data") or {}),
            "project": str(project_path),
            "session": _session_projection(session),
        }
        try:
            data = project_read_result(
                base=base,
                timeline=timeline.get("data") or {},
                query=query,
            )
        except ContextQueryError as error:
            return _failure("read", error.code, error.message)
        return {"ok": True, "op": "read", "data": data}

    def patch(
        self,
        project: str | Path,
        *,
        base_revision: int,
        base_timeline_hash: str,
        read_token: str,
        patch_id: str,
        commands: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Atomically apply commands against a fresh observed timeline base."""

        project_path = Path(project).expanduser().resolve()
        if not project_path.is_file():
            return _failure(
                "patch",
                "project_not_found",
                f"Blender project not found: {project_path}",
            )
        raw_commands = list(commands)
        max_commands = int(CONTEXT_POLICY["tool_results"]["patch"]["max_commands"])
        if len(raw_commands) > max_commands:
            return _failure(
                "patch",
                "invalid_args",
                f"commands accepts at most {max_commands} items",
            )
        if any(not isinstance(command, Mapping) for command in raw_commands):
            return _failure(
                "patch", "invalid_args", "every command must be a JSON object"
            )
        command_list = [dict(command) for command in raw_commands]
        missing = [
            name
            for name, value in {
                "base_revision": base_revision,
                "base_timeline_hash": base_timeline_hash,
                "read_token": read_token,
                "patch_id": patch_id,
            }.items()
            if value is None or value == ""
        ]
        if missing:
            return _failure(
                "patch",
                "read_required",
                "patch requires values from a fresh read: " + ", ".join(missing),
            )
        if not command_list:
            return _failure("patch", "invalid_args", "commands must not be empty")
        if any(not command.get("op") for command in command_list):
            return _failure("patch", "invalid_args", "every command must contain an op")

        restores = [c for c in command_list if c.get("op") == "restore_checkpoint"]
        if restores and (len(command_list) != 1 or len(restores) != 1):
            return _failure(
                "patch",
                "invalid_args",
                "restore_checkpoint must be the only command in a patch",
            )

        session = self._ensure_live(project_path)
        if not session.get("ready"):
            return session
        if restores:
            restored = self._restore_checkpoint(
                project_path,
                restores[0],
                base_revision=base_revision,
                base_timeline_hash=base_timeline_hash,
                read_token=read_token,
                patch_id=patch_id,
            )
            if not restored.get("ok"):
                return restored
            raw = restored.get("data") or {}
            try:
                receipt = project_patch_result(
                    raw,
                    session=raw.get("session") or {},
                )
            except ContextQueryError as error:
                return _failure("patch", error.code, error.message)
            return {"ok": True, "op": "patch", "data": receipt}

        result = self.execute(
            "apply_patch",
            {
                "project": str(project_path),
                "base_revision": base_revision,
                "base_timeline_hash": base_timeline_hash,
                "read_token": read_token,
                "patch_id": patch_id,
                "commands": command_list,
            },
        )
        if not result.get("ok"):
            code, message = _error_parts(result)
            if code in {
                "stale_base",
                "revision_mismatch",
                "invalid_read_token",
                "stale_observation",
            } or any(
                marker in message
                for marker in (
                    "stale_base",
                    "revision_mismatch",
                    "invalid_read_token",
                    "stale_observation",
                )
            ):
                return _failure(
                    "patch",
                    code,
                    "Timeline changed after it was read. Read again, understand or "
                    "acknowledge the change, then build a new patch.",
                    detail=message,
                )
            return _failure("patch", code, f"apply_patch failed: {message}")

        data = dict(result.get("data") or {})
        session_projection = _session_projection(session)
        if data.get("status") != "already_applied" and not data.get("applied"):
            try:
                receipt = project_patch_result(data, session=session_projection)
            except ContextQueryError as error:
                return _failure("patch", error.code, error.message)
            return _failure(
                "patch",
                "patch_rolled_back",
                f"patch commands failed and were rolled back: {data.get('error')}",
                data=receipt,
            )
        try:
            receipt = project_patch_result(data, session=session_projection)
        except ContextQueryError as error:
            return _failure("patch", error.code, error.message)
        return {"ok": True, "op": "patch", "data": receipt}

    def acknowledge(
        self,
        project: str | Path,
        *,
        observed_revision: int,
        observed_hash: str,
        read_token: str,
    ) -> dict[str, Any]:
        """Adopt a manual Blender edit after explicitly observing it."""

        project_path = Path(project).expanduser().resolve()
        missing = [
            name
            for name, value in {
                "observed_revision": observed_revision,
                "observed_hash": observed_hash,
                "read_token": read_token,
            }.items()
            if value is None or value == ""
        ]
        if missing:
            return _failure(
                "acknowledge",
                "read_required",
                "acknowledge requires values from a fresh read: " + ", ".join(missing),
            )
        if not project_path.is_file():
            return _failure(
                "acknowledge",
                "project_not_found",
                f"Blender project not found: {project_path}",
            )
        session = self._ensure_live(project_path)
        if not session.get("ready"):
            return session
        result = self.execute(
            "acknowledge_revision",
            {
                "project": str(project_path),
                "observed_revision": observed_revision,
                "observed_hash": observed_hash,
                "read_token": read_token,
            },
        )
        if not result.get("ok"):
            code, message = _error_parts(result)
            return _failure("acknowledge", code, message)
        try:
            data = project_acknowledge_result(
                result.get("data") or {},
                session=_session_projection(session),
            )
        except ContextQueryError as error:
            return _failure("acknowledge", error.code, error.message)
        return {"ok": True, "op": "acknowledge", "data": data}

    def verify(
        self,
        project: str | Path,
        *,
        expected: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        """Reopen a project in a fresh Blender process and verify persistence."""

        project_path = Path(project).expanduser().resolve()
        if not project_path.is_file():
            return _failure(
                "verify",
                "project_not_found",
                f"Blender project not found: {project_path}",
            )
        session = self._ensure_live(project_path)
        if not session.get("ready"):
            return session
        params: dict[str, Any] = {"project": str(project_path)}
        if expected:
            params["expected"] = dict(expected)
        result = self.execute("verify_persistence", params)
        if not result.get("ok"):
            code, message = _error_parts(result)
            return _failure("verify", code, message)
        try:
            data = project_verify_result(
                result.get("data") or {},
                session=_session_projection(session),
            )
        except ContextQueryError as error:
            return _failure("verify", error.code, error.message)
        return {"ok": True, "op": "verify", "data": data}

    def _restore_checkpoint(
        self,
        project: Path,
        command: Mapping[str, Any],
        *,
        base_revision: int,
        base_timeline_hash: str,
        read_token: str,
        patch_id: str,
    ) -> dict[str, Any]:
        name = str(command.get("name") or command.get("checkpoint_name") or "").strip()
        if not name or Path(name).name != name or name in {".", ".."}:
            return _failure(
                "patch",
                "invalid_args",
                "restore_checkpoint requires a simple checkpoint name",
            )
        checkpoint = project.parent / "checkpoints" / f"{name}.blend"
        guard = self.execute(
            "validate_checkpoint_restore",
            {
                "project": str(project),
                "base_revision": base_revision,
                "base_timeline_hash": base_timeline_hash,
                "read_token": read_token,
                "patch_id": patch_id,
            },
        )
        if not guard.get("ok"):
            code, message = _error_parts(guard)
            return _failure(
                "patch", code, f"checkpoint base validation failed: {message}"
            )
        guard_data = dict(guard.get("data") or {})
        if guard_data.get("status") == "already_applied":
            current = self._ensure_live(project)
            if not current.get("ready"):
                return current
            guard_data["session"] = _session_projection(current)
            return {"ok": True, "op": "patch", "data": guard_data}
        if not checkpoint.is_file():
            return _failure(
                "patch", "checkpoint_not_found", f"checkpoint not found: {checkpoint}"
            )

        backup_tag = hashlib.sha256(patch_id.encode("utf-8")).hexdigest()[:12]
        backup = project.parent / "checkpoints" / f"pre_restore_{backup_tag}.blend"
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project, backup)
        except OSError as exc:
            return _failure(
                "patch", "backup_failed", f"could not create pre-restore backup: {exc}"
            )

        closed = live_session.shutdown_live_session_for_restore(project)
        if not closed.get("closed"):
            return _failure(
                "patch",
                "session_close_failed",
                "checkpoint restore could not close the visible project: "
                + str(closed.get("message") or closed.get("code")),
                backup=str(backup),
                session=closed,
            )
        try:
            shutil.copy2(checkpoint, project)
        except OSError as exc:
            live_session.ensure_live_session(project)
            return _failure(
                "patch",
                "checkpoint_copy_failed",
                f"checkpoint replacement failed after GUI close: {exc}",
                backup=str(backup),
            )

        reopened = live_session.ensure_live_session(project)
        if not reopened.get("ready"):
            rollback: dict[str, Any]
            if not live_session.ping():
                shutil.copy2(backup, project)
                original = live_session.ensure_live_session(project)
                rollback = {"restored_original": bool(original.get("ready"))}
            else:
                rollback = {
                    "restored_original": False,
                    "reason": "a Blender process still owns the restored file",
                }
            return _failure(
                "patch",
                "checkpoint_reopen_failed",
                "checkpoint was copied but visible-GUI rediscovery failed; a safe "
                "rollback was attempted",
                backup=str(backup),
                restore_session=reopened,
                rollback=rollback,
            )

        finalized = self.execute(
            "finalize_checkpoint_restore",
            {
                "project": str(project),
                "next_revision": int(base_revision) + 1,
                "patch_id": patch_id,
                "checkpoint_name": name,
            },
        )
        if not finalized.get("ok"):
            code, message = _error_parts(finalized)
            return _failure(
                "patch",
                code,
                f"checkpoint reopened but revision finalization failed: {message}",
                backup=str(backup),
            )
        final_session = self._ensure_live(project)
        if not final_session.get("ready"):
            return final_session
        data = dict(finalized.get("data") or {})
        data.update(
            {
                "checkpoint_path": str(checkpoint),
                "pre_restore_backup": str(backup),
                "gui_reloaded": True,
                "session": _session_projection(final_session),
            }
        )
        return {"ok": True, "op": "patch", "data": data}
