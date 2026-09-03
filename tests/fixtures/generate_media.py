"""Generate deterministic, copyright-free integration fixtures with FFmpeg."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


OUTPUT = Path(__file__).resolve().parent / "media"


def _run(arguments: list[str]) -> None:
    print("ffmpeg " + " ".join(arguments))
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=True,
    )


def generate(force: bool = False) -> Path:
    """Create two synthetic video clips and one synthetic music bed."""

    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is required to generate integration fixtures")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    clip_a = OUTPUT / "clip_a.mp4"
    clip_b = OUTPUT / "clip_b.mp4"
    music = OUTPUT / "music.mp3"

    if force or not clip_a.is_file():
        _run(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=0x2667ff:s=1280x720:r=30:d=5",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=5",
                "-shortest",
                "-c:v",
                "mpeg4",
                "-q:v",
                "5",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ac",
                "1",
                str(clip_a),
            ]
        )
    if force or not clip_b.is_file():
        _run(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=0xff8a26:s=1280x720:r=30:d=4",
                "-c:v",
                "mpeg4",
                "-q:v",
                "5",
                "-pix_fmt",
                "yuv420p",
                str(clip_b),
            ]
        )
    if force or not music.is_file():
        _run(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=220:sample_rate=48000:duration=3.04",
                "-c:a",
                "libmp3lame",
                "-ac",
                "1",
                str(music),
            ]
        )
    return OUTPUT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(generate(force=args.force))


if __name__ == "__main__":
    main()
