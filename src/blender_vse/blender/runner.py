"""Blender execution runner — live GUI session preferred, headless only for batch ops.

Execution policy (default: ``live_session``):

  live_session (DEFAULT for interactive VSE editing)
      MCP -> blender_session -> Blender MCP Bridge addon -> the RUNNING GUI Blender
      The bridge addon executes allowlisted bpy scripts on Blender's main thread,
      so edits appear live in the user's open VSE timeline + preview.

  headless (ONLY allowed for)
      - batch render / final render        (render_preview, render_final)
      - native media inspection            (inspect_media)
      - fresh persistence verification     (verify_persistence)
      - dry-run validation (never persists, so it is not an interactive edit)

If live_session is required (interactive VSE editing) and no bridge is reachable,
the runner FAILS with a clear hint — it NEVER silently launches another Blender.

Session lifecycle is handled one layer above by ``ensure_live_session``. The
runner itself never spawns a replacement GUI during an operation. Security:
runner only executes scripts produced by vse_ops.py templates; it never accepts
arbitrary Python from an Agent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..catalog import HEADLESS_OPERATIONS
from .config import execution_policy, find_blender, runtime_tmp_dir
from . import live_session

DEFAULT_TIMEOUT = 300  # seconds (renders can be slow)
RENDER_TIMEOUT = 3600

# Runtime scripts belong in user state, never in an installed package directory.
TMP_DIR = runtime_tmp_dir()

# Blender ops that are batch/unattended and therefore ALLOWED to run headless.
# Everything else in BLENDER_OPS is interactive VSE editing -> MUST use live_session.
# verify_persistence must ALWAYS run in a fresh process (reopen the .blend from
# disk) — that is its entire purpose.
HEADLESS_ALLOWED_OPS = set(HEADLESS_OPERATIONS)


class BlenderRunnerError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass
class BlenderResult:
    success: bool
    output: str = ""
    error: str | None = None
    payload: Any = None
    mode: str = "headless"  # live | headless | dry_run


@dataclass
class RunnerConfig:
    blender_executable: str | None = None
    headless: bool = True
    timeout: int = DEFAULT_TIMEOUT
    execution: str | None = None  # None -> configured execution policy

    def __post_init__(self):
        if not self.blender_executable:
            self.blender_executable = find_blender()
        if self.execution is None:
            self.execution = execution_policy()


class BlenderRunner:
    """Runs allowlisted bpy scripts against a persistent .blend file.

    Execution mode is decided per call:
      - live_session policy + interactive VSE op  -> live GUI bridge (required)
      - live_session policy + batch/render op     -> headless subprocess
      - headless policy                           -> headless subprocess
      - dry_run                                   -> headless temp-copy validation
    """

    def __init__(self, config: RunnerConfig | None = None):
        self.config = config or RunnerConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_script(
        self,
        script: str,
        *,
        project: str | None = None,
        save: bool = True,
        dry_run: bool = False,
        timeout: int | None = None,
        script_name: str = "op",
        args: list[str] | None = None,
        refresh_after: bool = False,
    ) -> BlenderResult:
        """Run a fixed bpy script.

        Args:
            script: Blender Python source (from vse_ops templates only).
            project: .blend path. None = in-memory factory session (no save).
            save: whether to save the .blend after execution.
            dry_run: validate + compute only; never write or save.
            args: extra argv passed to the script after '--' (headless only).
            refresh_after: live mode only — after a mutating VSE edit, redraw the
                sequencer areas + refresh the current frame/preview so the user's
                open GUI updates immediately.
        """
        policy = self.config.execution or "live_session"

        # dry-run is validation, never a persisted interactive edit -> headless temp copy.
        if dry_run:
            return self._run_headless(script, project=project, save=False, dry_run=True,
                                      timeout=timeout, script_name=script_name, args=args)

        is_batch_op = script_name in HEADLESS_ALLOWED_OPS

        if policy == "headless":
            if not is_batch_op:
                # Governance: interactive VSE editing is ONLY allowed in a live
                # GUI session. Explicitly refuse headless — this is a rule with
                # NO escape hatch. Functional tests run against a live bridge;
                # dry_run is the only GUI-free validation path (it never
                # persists and never launches a real interactive edit).
                return BlenderResult(
                    False,
                    error=(
                        f"op '{script_name}' is an INTERACTIVE VSE edit and is NOT "
                        "allowed to run headless. Only "
                        f"{sorted(HEADLESS_ALLOWED_OPS)} may run in a headless "
                        "Blender subprocess. Set BLENDER_VSE_EXECUTION=live_session "
                        "(default) and run with a live Blender GUI bridge, or use "
                        "dry_run=True for validation-only."
                    ),
                    mode="headless",
                )
            return self._run_headless(script, project=project, save=save, dry_run=False,
                                      timeout=timeout, script_name=script_name, args=args)

        # policy == live_session
        if is_batch_op:
            # Batch/final render, media inspection, and fresh verify may run headless.
            return self._run_headless(script, project=project, save=save, dry_run=False,
                                      timeout=timeout or RENDER_TIMEOUT, script_name=script_name,
                                      args=args)

        # Interactive VSE editing -> live GUI session REQUIRED.
        return self._run_live(script, project=project, save=save, timeout=timeout,
                              script_name=script_name, refresh_after=refresh_after)

    # ------------------------------------------------------------------
    # Live GUI session execution (default for interactive editing)
    # ------------------------------------------------------------------

    def _run_live(self, script, *, project, save, timeout, script_name, refresh_after=False) -> BlenderResult:
        # Hard boundary: TCP reachability is not enough.  Every interactive op
        # goes through the same mandatory discovery state machine and cannot
        # execute until the native window, requested project, and visible VSE
        # area are all proven ready.  This protects even internal adapter calls
        # that did not come through the public revision-safe controller.
        session = live_session.ensure_live_session(project)
        if not session.get("ready"):
            return BlenderResult(
                False,
                error=(
                    "live_session gate refused the operation: "
                    + str(session.get("message") or session.get("code") or "not ready")
                ),
                payload={"session": session},
                mode="live",
            )

        wrapped = self._wrap_live(script, script_name)
        if save and project:
            wrapped += self._live_save_script(project)
        # After every mutating VSE edit: refresh timeline state + current
        # frame/preview + request UI redraw so the open GUI updates live.
        if refresh_after:
            wrapped += live_session.refresh_ui_script()

        try:
            result = live_session.execute_code(wrapped, timeout=timeout or self.config.timeout)
        except live_session.LiveSessionError as e:
            return BlenderResult(False, error=f"live bridge error: {e}", mode="live")

        if not result["success"]:
            err = result.get("error") or "live bridge execution failed"
            return BlenderResult(False, error=str(err)[-2000:], mode="live")

        output = result.get("output", "")
        payload = None
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("VP_RESULT:"):
                try:
                    payload = json.loads(line[len("VP_RESULT:"):])
                except Exception:
                    payload = {"raw": line[len("VP_RESULT:"):]}
                break

        err_line = next((l for l in output.splitlines() if l.strip().startswith("VP_ERROR:")), None)
        if err_line:
            return BlenderResult(False, error=err_line[len("VP_ERROR:"):].strip(),
                                 payload=payload, mode="live")

        return BlenderResult(True, output=output, payload=payload, mode="live")

    @staticmethod
    def _wrap_live(script: str, script_name: str) -> str:
        """Wrap a fixed op script for execution inside the live GUI Blender.

        The bridge executes code with only ``bpy`` in globals and captures stdout,
        so ``_vp_result`` is defined here and printed (captured by the bridge).
        No sys.exit — the bridge reports execution errors itself.
        """
        return f'''
import sys, traceback, json

def _vp_result(**kw):
    print("VP_RESULT:" + json.dumps(kw, ensure_ascii=False, default=str))

try:
{BlenderRunner._indent(script, 4)}
except Exception as _vp_e:
    print("VP_ERROR: " + str(_vp_e))
    traceback.print_exc()
'''

    @staticmethod
    def _live_save_script(project: str) -> str:
        """Save the .blend the GUI has open; fall back to ``project`` if unsaved."""
        return f'''
import bpy
_vp_target = bpy.data.filepath or {json.dumps(str(project))}
bpy.ops.wm.save_as_mainfile(filepath=_vp_target)
'''

    # ------------------------------------------------------------------
    # Headless subprocess execution (batch render / tests / dry-run)
    # ------------------------------------------------------------------

    def _run_headless(self, script, *, project, save, dry_run, timeout, script_name, args) -> BlenderResult:
        exe = self.config.blender_executable
        if not exe:
            return BlenderResult(False, error="blender not found")

        # Wrap script with error reporting.
        wrapped = self._wrap(script, script_name)

        if project and save and not dry_run:
            # Source of truth: persist the SAME .blend the user will open.
            wrapped = wrapped + f"\nbpy.ops.wm.save_as_mainfile(filepath={json.dumps(str(project))})\n"

        # Sandbox note: TemporaryDirectory cleanup (recursive delete) can be
        # denied; use a fixed tmp dir with a unique filename instead.
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        script_path = TMP_DIR / f"vp_{script_name}_{os.getpid()}_{int(time.time() * 1000)}.py"
        try:
            script_path.write_text(wrapped, encoding="utf-8")
            cmd = [exe]
            if self.config.headless:
                cmd.append("--background")
            cmd += ["--factory-startup", "--enable-autoexec"]
            if project and Path(project).is_file():
                cmd.append(str(project))
            cmd += ["--python", str(script_path), "--"]
            if args:
                cmd += args

            env = os.environ.copy()
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout or self.config.timeout,
                    env=env,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired:
                return BlenderResult(False, error=f"Blender timed out after {timeout or self.config.timeout}s")

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""

            # Parse result payload (JSON between markers).
            payload = None
            for line in stdout.splitlines():
                line = line.strip()
                if line.startswith("VP_RESULT:"):
                    try:
                        payload = json.loads(line[len("VP_RESULT:"):])
                    except Exception:
                        payload = {"raw": line[len("VP_RESULT:"):]}
                    break

            if proc.returncode != 0 and "VP_ERROR:" not in stdout:
                return BlenderResult(False, error=f"blender exit {proc.returncode}: {stderr[-2000:]}")

            # Extract explicit error if the script raised.
            err_line = next((l for l in stdout.splitlines() if l.strip().startswith("VP_ERROR:")), None)
            if err_line:
                return BlenderResult(False, error=err_line[len("VP_ERROR:"):].strip(), payload=payload)

            return BlenderResult(True, output=stdout, payload=payload,
                                 mode="dry_run" if dry_run else "headless")
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except Exception:
                pass

    @staticmethod
    def _wrap(script: str, script_name: str) -> str:
        """Wrap a fixed op script with uniform result/error reporting."""
        return f'''
import sys, traceback, json
try:
    import bpy
except Exception:
    print("VP_ERROR: bpy not available (not running inside Blender)")
    sys.exit(1)

def _vp_result(**kw):
    print("VP_RESULT:" + json.dumps(kw, ensure_ascii=False, default=str))

try:
{BlenderRunner._indent(script, 4)}
except Exception as _vp_e:
    print("VP_ERROR: " + str(_vp_e))
    traceback.print_exc()
    sys.exit(1)
'''

    @staticmethod
    def _indent(text: str, spaces: int) -> str:
        indent = " " * spaces
        return "\n".join(f"{indent}{line}" if line.strip() else line for line in text.split("\n"))
