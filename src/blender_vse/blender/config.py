"""Environment detection and configuration for Blender VSE Control.

Preferred settings use the ``BLENDER_VSE_*`` prefix. The legacy ``VP_*``
names remain aliases so existing deployments and `.blend` projects can move to
the standalone package without a flag day.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

MANAGED_PYTHON_VERSION = "3.12"
UV_INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"
BLENDER_INSTALL_URL = "https://www.blender.org/download/"
FFMPEG_INSTALL_URL = "https://ffmpeg.org/download.html"


def env_value(
    name: str,
    legacy: str | None = None,
    default: str | None = None,
) -> str | None:
    """Return a preferred setting, then its legacy alias, then a default."""

    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    if legacy:
        value = os.environ.get(legacy)
        if value not in (None, ""):
            return value
    return default


def _default_state_dir() -> Path:
    configured = env_value("BLENDER_VSE_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "blender-vse"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "blender-vse"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "blender-vse"


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = PACKAGE_ROOT / "schemas"
STATE_DIR = _default_state_dir()
TEST_MEDIA_DIR = Path(
    env_value("BLENDER_VSE_TEST_MEDIA_DIR", default=str(STATE_DIR / "test-media"))
    or STATE_DIR / "test-media"
).expanduser()


def runtime_tmp_dir() -> Path:
    return Path(
        env_value("BLENDER_VSE_TMP_DIR", "VP_TMP_DIR", str(STATE_DIR / "tmp"))
        or STATE_DIR / "tmp"
    ).expanduser()


PROJECTS_DIRNAME = "blender-vse-projects"
WORKSPACE_ENV = "BLENDER_VSE_WORKSPACE"


def workspace_root(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> Path:
    """Return the workspace folder the host launched the server in.

    MCP hosts start stdio servers inside the user's working folder, so the
    process working directory is the workspace. ``BLENDER_VSE_WORKSPACE`` only
    exists for hosts that launch servers somewhere else.
    """

    values = os.environ if environ is None else environ
    override = values.get(WORKSPACE_ENV, "").strip()
    base = Path(override).expanduser() if override else Path(cwd or Path.cwd())
    return base.resolve(strict=False)


def projects_dir(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> Path:
    """Editable ``.blend`` projects always live in ``<workspace>/blender-vse-projects``."""

    return workspace_root(environ=environ, cwd=cwd) / PROJECTS_DIRNAME


def _blender_candidates() -> list[str]:
    configured = env_value(
        "BLENDER_VSE_BLENDER_EXECUTABLE",
        "VP_BLENDER_EXECUTABLE",
        os.environ.get("BLENDER_EXECUTABLE", ""),
    )
    return [
        configured or "",
        r"D:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        r"D:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/Applications/Blender.app/Contents/MacOS/Blender",
    ]


def find_blender() -> str | None:
    """Return the configured or discoverable Blender executable."""

    for candidate in _blender_candidates():
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return shutil.which("blender")


def blender_version(executable: str | None = None) -> str | None:
    """Return a Blender version string such as ``5.1.0``."""

    blender = executable or find_blender()
    if not blender:
        return None
    try:
        result = subprocess.run(
            [blender, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout.splitlines()[0].replace("Blender ", "").split()[0]


def blender_python(executable: str | None = None) -> str | None:
    """Return Blender's bundled Python when it can be found without launching it."""

    blender = executable or find_blender()
    if not blender:
        return None
    exe = Path(blender)
    version = blender_version(blender)
    roots = [exe.parent]
    if sys.platform == "darwin" and len(exe.parents) >= 2:
        roots.append(exe.parents[1] / "Resources")
    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        version_dirs = [root / version] if version else []
        version_dirs.extend(
            item
            for item in root.iterdir()
            if item.is_dir() and item.name.replace(".", "").isdigit()
        )
        for version_dir in version_dirs:
            bin_dir = version_dir / "python" / "bin"
            candidates.extend(
                [bin_dir / "python.exe", bin_dir / "python3", bin_dir / "python"]
            )
            if bin_dir.is_dir():
                candidates.extend(sorted(bin_dir.glob("python3.*")))
    return next((str(path) for path in candidates if path.is_file()), None)


DEFAULT_EXECUTION = (
    env_value("BLENDER_VSE_EXECUTION", "VP_BLENDER_EXECUTION", "live_session")
    or "live_session"
)


def execution_policy() -> str:
    """Return ``live_session`` or ``headless``."""

    return (
        env_value("BLENDER_VSE_EXECUTION", "VP_BLENDER_EXECUTION", DEFAULT_EXECUTION)
        or DEFAULT_EXECUTION
    )


def live_session_available() -> bool:
    """Return true only for a visible GUI session with a visible VSE area."""

    from .live_session import check_live_session

    state = check_live_session()
    return bool(
        state.get("live_session")
        and state.get("gui_visible")
        and int(state.get("vse_area_count") or 0) > 0
    )


def find_ffmpeg() -> str | None:
    configured = env_value("BLENDER_VSE_FFMPEG", "VP_FFMPEG")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    for path in (
        Path(r"D:\Program Files\ffmpeg\ffmpeg.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
    ):
        if path.is_file():
            return str(path)
    return None


def find_ffprobe() -> str | None:
    configured = env_value("BLENDER_VSE_FFPROBE", "VP_FFPROBE")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ffprobe")
    if found:
        return found
    for path in (
        Path(r"D:\Program Files\ffmpeg\ffprobe.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffprobe.exe"),
    ):
        if path.is_file():
            return str(path)
    return None


def _version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or result.stderr).strip()
    return value.splitlines()[0] if result.returncode == 0 and value else None


def environment_report() -> dict:
    """Return a structured local runtime capability report."""

    blender = find_blender()
    from .live_session import check_live_session

    live = check_live_session()
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    uv = shutil.which("uv")
    node = _version(["node", "--version"])
    workspace = workspace_root()
    media_tools_available = ffmpeg is not None and ffprobe is not None
    setup_next_actions = []
    if uv is None:
        setup_next_actions.append("install_uv_with_user_approval")
    if blender is None:
        setup_next_actions.append("install_blender")
    if not media_tools_available:
        setup_next_actions.append("install_ffmpeg")
    return {
        "os": sys.platform,
        "blender": {
            "executable": blender,
            "version": blender_version(blender),
            "bundled_python": blender_python(blender),
            "available": blender is not None,
        },
        "blender_execution": {
            "policy": execution_policy(),
            "live_session": live.get("live_session", False),
            "gui_visible": live.get("gui_visible", False),
            "workspace": live.get("workspace"),
            "vse_area_count": live.get("vse_area_count", 0),
            "bridge_host": live.get("bridge_host"),
            "bridge_port": live.get("bridge_port"),
            "mode": live.get("mode"),
            "hint": live.get("hint"),
        },
        "ffmpeg": {
            "executable": ffmpeg,
            "ffprobe": ffprobe,
            "available": media_tools_available,
        },
        "node": {"version": node, "available": node is not None},
        "python": {"executable": sys.executable, "version": sys.version.split()[0]},
        "state_dir": str(STATE_DIR),
        "workspace": str(workspace),
        "projects_dir": str(workspace / PROJECTS_DIRNAME),
        "setup": {
            "python": {
                "strategy": "uv-managed",
                "managed_version": MANAGED_PYTHON_VERSION,
                "system_python_required": False,
                "uv_preinstalled_required": False,
                "bootstrap": "request_permission_then_install_uv",
                "uv_available": uv is not None,
                "uv_executable": uv,
                "install_url": UV_INSTALL_URL,
            },
            "blender": {
                "required_for_editing": True,
                "available": blender is not None,
                "install_url": BLENDER_INSTALL_URL,
            },
            "ffmpeg": {
                "required_for": ["proxy generation", "media test fixtures"],
                "available": media_tools_available,
                "install_url": FFMPEG_INSTALL_URL,
            },
            "installation_ready_for_editing": bool(uv is not None and blender),
            "installation_ready_for_full_features": bool(
                uv is not None and blender and media_tools_available
            ),
            "next_actions": setup_next_actions,
        },
    }


if __name__ == "__main__":
    print(json.dumps(environment_report(), indent=2, ensure_ascii=False))
