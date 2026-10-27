"""Per-scene frame extraction via ffmpeg."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.scenes import Scene


def format_filename(index: int, t: float) -> str:
    """`NNNN_tMM-SS.jpg`. MM may exceed 59 for videos > 1h — that's intentional
    so filenames sort naturally."""
    total = round(t)
    mm, ss = divmod(total, 60)
    return f"{index:04d}_t{mm:02d}-{ss:02d}.jpg"


def extract_frames(
    video: Path,
    scenes: list[Scene],
    *,
    out_dir: Path,
    width_px: int = 512,
) -> list[dict]:
    """For each scene, run a single-frame ffmpeg seek + extract.

    Returns: [{"index": int, "t": float, "path": str (relative to out_dir), "kind": str}]
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for i, scene in enumerate(scenes, start=1):
        name = format_filename(i, scene.t)
        out_path = out_dir / name
        # `-ss` before `-i` is fast (key-frame seek) and accurate enough for our purposes.
        # `-frames:v 1` writes exactly one frame; `scale=W:-2` keeps aspect, even-height.
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-y",
            "-ss", f"{scene.t:.3f}",
            "-i", str(video),
            "-frames:v", "1",
            "-vf", f"scale={width_px}:-2",
            "-q:v", "3",  # JPEG quality (2 best, 31 worst); 3 is a good balance
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            stderr_text = (
                e.stderr.decode("utf-8", errors="replace")
                if isinstance(e.stderr, (bytes, bytearray))
                else (e.stderr or "")
            )
            raise RuntimeError(
                f"ffmpeg failed extracting frame {i} at t={scene.t:.3f}s "
                f"(exit {e.returncode}): {stderr_text.strip()}"
            ) from e
        results.append({
            "index": i,
            "t": scene.t,
            "path": name,
            "kind": scene.kind,
        })
    return results


def extract_stable_frames(
    video: Path,
    times: list[float],
    *,
    out_dir: Path,
    window: float = 3.0,
    fps: int = 6,
    width_px: int = 1024,
    threshold: float = 1.2,
) -> list[dict]:
    """Extract plateau-selected frames around each timestamp.

    For each time, grab a short burst, pick the middle of the most stable
    plateau, and save that still. Returns records including plateau evidence so
    published screenshots can be traced back to a stable UI state.
    """
    from PIL import Image

    from scripts.stable_frame import choose_plateau, diff_series, grab, gray_vec

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for index, t in enumerate(times, start=1):
        start = max(0.0, float(t) - window / 2)
        tmpdir = tempfile.mkdtemp(prefix="watch-stable-")
        try:
            frames = grab(str(video), start, window, fps, tmpdir)
            if len(frames) < 2:
                continue
            vecs = [gray_vec(f) for f in frames]
            picked = choose_plateau(diff_series(vecs), threshold)
            chosen = frames[picked["chosen_index"]]
            name = f"{index:04d}_t{int(t) // 60:02d}-{int(t) % 60:02d}.jpg"
            image = Image.open(chosen).convert("RGB")
            if image.width > width_px:
                height = max(1, int(image.height * width_px / image.width))
                image = image.resize((width_px, height), Image.LANCZOS)
            image.save(out_dir / name, "JPEG", quality=90)
            results.append({
                "index": index,
                "t": float(t),
                "path": name,
                "kind": "stable",
                "plateau": picked["plateau"],
            })
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return results
