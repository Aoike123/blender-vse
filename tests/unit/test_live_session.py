from __future__ import annotations

import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from blender_vse.blender import config, live_session


class FakeSocket:
    def __init__(self, response: dict, chunk_size: int = 3):
        body = json.dumps(response).encode("utf-8")
        self.buffer = struct.pack("!I", len(body)) + body
        self.chunk_size = chunk_size
        self.sent = b""
        self.connected = None
        self.timeout = None
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, endpoint):
        self.connected = endpoint

    def sendall(self, payload):
        self.sent += payload

    def recv(self, size):
        count = min(size, self.chunk_size, len(self.buffer))
        result, self.buffer = self.buffer[:count], self.buffer[count:]
        return result

    def close(self):
        self.closed = True


def test_bridge_protocol_handles_fragmented_frames(monkeypatch) -> None:
    fake = FakeSocket({"status": "success", "result": {"pong": True}})
    monkeypatch.setattr(live_session.socket, "socket", lambda *_args: fake)
    response = live_session._send_cmd({"type": "ping"}, timeout=7)
    assert response["result"]["pong"] is True
    assert fake.connected == (live_session.BRIDGE_HOST, live_session.BRIDGE_PORT)
    assert fake.timeout == 7 and fake.closed
    body_size = struct.unpack("!I", fake.sent[:4])[0]
    assert json.loads(fake.sent[4 : 4 + body_size]) == {"type": "ping"}


def test_bridge_protocol_wraps_connection_errors(monkeypatch) -> None:
    fake = FakeSocket({})

    def fail(_endpoint):
        raise ConnectionRefusedError("no bridge")

    fake.connect = fail
    monkeypatch.setattr(live_session.socket, "socket", lambda *_args: fake)
    with pytest.raises(live_session.LiveSessionError) as caught:
        live_session._send_cmd({"type": "ping"})
    assert caught.value.code == "bridge_unreachable"
    assert fake.closed


def test_execute_code_unwraps_bridge_result(monkeypatch) -> None:
    monkeypatch.setattr(
        live_session,
        "_send_cmd",
        lambda *_args, **_kwargs: {
            "status": "success",
            "result": {"success": True, "output": "ok", "error": None},
        },
    )
    assert live_session.execute_code("pass") == {
        "success": True,
        "output": "ok",
        "error": None,
    }


def test_project_match_protects_a_different_open_file(tmp_path: Path) -> None:
    wanted = tmp_path / "wanted.blend"
    other = tmp_path / "other.blend"
    mismatch = live_session._check_project_match(
        {"connected": True, "filepath": str(other)}, wanted
    )
    assert mismatch["ready"] is False
    assert mismatch["code"] == "project_mismatch"
    matched = live_session._check_project_match(
        {"connected": True, "filepath": str(wanted)}, wanted
    )
    assert matched["ready"] is True


def test_blank_session_can_adopt_a_requested_project(tmp_path: Path) -> None:
    result = live_session._check_project_match(
        {"connected": True, "filepath": ""}, tmp_path / "new.blend"
    )
    assert "ready" not in result
    assert result["requested_project"].endswith("new.blend")


def test_launch_capability_is_observational(monkeypatch, tmp_path: Path) -> None:
    blender = tmp_path / "blender"
    bootstrap = tmp_path / "bootstrap.py"
    blender.touch()
    bootstrap.touch()
    monkeypatch.setattr(config, "find_blender", lambda: str(blender))
    monkeypatch.setattr(live_session, "_GUI_BOOTSTRAP", bootstrap)
    monkeypatch.setattr(live_session, "SESSION_AUTOSTART", True)
    monkeypatch.setattr(live_session, "ping", lambda: False)
    result = live_session.launch_capability()
    assert result["launchable"] is True
    assert result["connected"] is False


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"code": "gui_not_visible", "pid": 5, "filepath": "demo.blend"}, True),
        (
            {
                "code": "gui_not_visible",
                "pid": 5,
                "filepath": "demo.blend",
                "is_dirty": True,
            },
            False,
        ),
        ({"code": "project_mismatch", "pid": 5, "filepath": "demo.blend"}, False),
    ],
)
def test_hidden_session_repair_is_fail_closed(monkeypatch, state, expected) -> None:
    monkeypatch.setattr(live_session, "SESSION_AUTOSTART", True)
    assert live_session._can_repair_hidden_session(state, "demo.blend") is expected


def test_disconnected_status_is_compact(monkeypatch) -> None:
    monkeypatch.setattr(live_session, "ping", lambda: False)
    result = live_session.check_live_session()
    assert result["live_session"] is False
    assert result["mode"] == "not_ready"
    assert "No live Blender GUI bridge" in result["hint"]


def test_new_project_launch_uses_existing_runtime_directory(monkeypatch, tmp_path: Path) -> None:
    blender = tmp_path / "blender.exe"
    bootstrap = tmp_path / "bootstrap.py"
    runtime = tmp_path / "runtime"
    blender.touch()
    bootstrap.touch()
    requested = tmp_path / "missing-parent" / "new.blend"
    calls = []

    monkeypatch.setattr(config, "find_blender", lambda: str(blender))
    monkeypatch.setattr(live_session, "_GUI_BOOTSTRAP", bootstrap)
    monkeypatch.setattr(live_session, "runtime_tmp_dir", lambda: runtime)

    def popen(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(pid=42)

    monkeypatch.setattr(live_session.subprocess, "Popen", popen)
    process = live_session._launch_blender_gui(requested)
    assert process.pid == 42
    assert Path(calls[0][1]["cwd"]) == runtime
    assert runtime.is_dir()
    assert str(requested) not in calls[0][0]
