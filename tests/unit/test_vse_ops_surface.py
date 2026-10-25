"""Fast template-generation tests for the visible-frame tooling surface.

Covers the explicit-font guarantee for TEXT strips (preview/render parity on
Blender >= 5), preview-safe frame stepping in the contact sheet, and the
bounded numeric grid emitted by ``sample_frame``.
"""
from __future__ import annotations

import pytest

from blender_vse.blender import vse_ops
from blender_vse.blender.runner import BlenderRunnerError


PROJECT = "/tmp/test-project.blend"


def test_add_text_assigns_explicit_font() -> None:
    script = vse_ops.add_text(project=PROJECT, text="Hello",
                              font="/tmp/MyFont.ttf")
    assert "_vp_ensure_font" in script
    assert "/tmp/MyFont.ttf" in script
    assert "font_fallback_warning" in script


def test_add_text_without_font_still_ensures_one() -> None:
    script = vse_ops.add_text(project=PROJECT, text="Hello")
    assert "_vp_ensure_font(s, None, s.text)" in script


def test_ensure_font_resolves_bundled_fonts_via_blender_resources() -> None:
    script = vse_ops.add_text(project=PROJECT, text="Hello")
    assert "bpy.utils.system_resource('DATAFILES', path=\"fonts\")" in script
    assert '"Inter.woff2"' in script
    assert '"Noto Sans CJK Regular.woff2"' in script


def test_ensure_font_reuses_loaded_font_datablocks() -> None:
    script = vse_ops.add_text(project=PROJECT, text="Hello")
    assert "bpy.data.fonts.load(_p, check_existing=True)" in script
    assert "bpy.data.fonts.load(explicit_path, check_existing=True)" in script


def test_add_subtitle_track_ensures_fonts_per_strip() -> None:
    script = vse_ops.add_subtitle_track(
        project=PROJECT,
        segments=[{"start_seconds": 0.0, "end_seconds": 1.0, "text": "hi"}],
    )
    assert "_vp_ensure_font(_s, None, _s.text)" in script
    assert "font_fallback_warning" in script


def test_contact_sheet_steps_frames_via_frame_set() -> None:
    script = vse_ops.generate_contact_sheet(
        project=PROJECT, output_path="/tmp/sheet.png", frames=[1, 2]
    )
    assert "scene.frame_set(int(_f))" in script
    assert "scene.frame_current = int(_f)" not in script


def test_sample_frame_builds_bounded_grid_script() -> None:
    script = vse_ops.sample_frame(project=PROJECT, frame=42, grid=(8, 4))
    assert "use_sequencer = True" in script
    assert "scene.frame_set(int(_f))" in script
    assert "_gx, _gy = 8, 4" in script
    assert "_vp_result(frame=int(_f), grid=[_gx, _gy]" in script
    assert "view_transform=_view" in script


def test_sample_frame_reads_pixels_in_bulk_top_down() -> None:
    script = vse_ops.sample_frame(project=PROJECT)
    assert "_img.pixels.foreach_get(_buf)" in script
    assert "_px[" not in script
    assert "[::-1, :, :3]" in script


def test_sample_frame_uses_private_temp_file() -> None:
    script = vse_ops.sample_frame(project=PROJECT)
    assert "tempfile.mkstemp(" in script
    assert "vse_sample_frame.png" not in script


def test_sample_frame_honors_frame_zero() -> None:
    script = vse_ops.sample_frame(project=PROJECT, frame=0)
    assert "_f = 0\nif _f is None:" in script
    assert " or scene.frame_current" not in script


def test_sample_frame_guards_media_type_for_blender_4() -> None:
    script = vse_ops.sample_frame(project=PROJECT)
    assert 'hasattr(_settings, "media_type")' in script


def test_sample_frame_rejects_non_integer_frame() -> None:
    with pytest.raises(BlenderRunnerError) as exc:
        vse_ops.sample_frame(project=PROJECT, frame="abc")
    assert exc.value.code == "invalid_args"


@pytest.mark.parametrize("grid", [(0, 4), (8, 0), (17, 4), (8, 99)])
def test_sample_frame_rejects_out_of_bounds_grid(grid) -> None:
    with pytest.raises(BlenderRunnerError) as exc:
        vse_ops.sample_frame(project=PROJECT, grid=grid)
    assert exc.value.code == "invalid_args"
