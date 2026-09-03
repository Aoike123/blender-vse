from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "integration" / "smoke_workflow.py"
    spec = importlib.util.spec_from_file_location("smoke_workflow_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failed_smoke_cleans_only_its_own_clean_launch(monkeypatch) -> None:
    smoke = _module()
    calls = []
    monkeypatch.setattr(
        smoke.live_session,
        "_shutdown_hidden_session",
        lambda state: calls.append(state) or True,
    )
    result = {
        "session": {
            "launched": True,
            "last_observation": {"filepath": "", "is_dirty": False, "pid": 42},
        }
    }
    assert smoke.cleanup_failed_launch(result) is True
    assert calls[0]["pid"] == 42


def test_failed_smoke_never_closes_dirty_or_foreign_session(monkeypatch, tmp_path) -> None:
    smoke = _module()
    monkeypatch.setattr(
        smoke.live_session,
        "_shutdown_hidden_session",
        lambda _state: (_ for _ in ()).throw(AssertionError("must not close")),
    )
    assert not smoke.cleanup_failed_launch(
        {
            "session": {
                "launched": True,
                "last_observation": {"filepath": "", "is_dirty": True},
            }
        }
    )
    assert not smoke.cleanup_failed_launch(
        {
            "session": {
                "launched": True,
                "last_observation": {
                    "filepath": str(tmp_path / "human.blend"),
                    "is_dirty": False,
                },
            }
        }
    )
