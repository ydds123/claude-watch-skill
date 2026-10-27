"""从视频连拍中挑选“稳定态”帧：状态平台期检测。

原理：截图要表达的是某个稳定 UI 状态，而视频是连续动画流。
单点抽帧可能落在弹窗淡入、页面切换、数据加载的过渡区间；
正确做法是在目标时间区间内连拍，找出连续帧几乎不变（平台期），
取平台期中段帧，并输出稳定性证据（平台长度、帧间差异）。

用法：
  python stable_frame.py --video 视频.mp4 --time 00:11:40 \
      --window 4 --fps 6 --out chosen.png --report stable.json \
      --reference 当前帧.png
"""
import argparse
import json
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image


def to_seconds(value: str) -> float:
    parts = value.strip().split(":")
    parts = [float(p) for p in parts]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def grab(video: str, start: float, duration: float, fps: int, outdir: str) -> list[str]:
    pattern = os.path.join(outdir, "f%03d.png")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video,
        "-vf", f"fps={fps}", pattern,
    ]
    subprocess.run(cmd, check=True)
    return sorted(os.path.join(outdir, n) for n in os.listdir(outdir) if n.endswith(".png"))


def gray_vec(path: str, width: int = 240):
    im = Image.open(path).convert("L").resize((width, 135), Image.LANCZOS)
    return np.asarray(im, dtype=np.float32)


def diff_series(vecs) -> list[float]:
    """Mean absolute difference between consecutive gray frames."""
    return [float(np.abs(vecs[i + 1] - vecs[i]).mean()) for i in range(len(vecs) - 1)]


def plateau_runs(diffs: list[float], threshold: float) -> list[tuple[int, int]]:
    """Consecutive index ranges whose frame-to-frame diff stays under threshold."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, d in enumerate(diffs):
        stable = d <= threshold
        if stable and start is None:
            start = i
        if (not stable or i == len(diffs) - 1) and start is not None:
            runs.append((start, i if not stable else i + 1))
            start = None
    return runs or [(0, max(0, len(diffs) - 1))]


def choose_plateau(diffs: list[float], threshold: float = 1.2) -> dict:
    """Pick the longest/lowest-diff plateau; return plateau evidence + chosen frame index."""
    runs = plateau_runs(diffs, threshold)

    def score(run: tuple[int, int]) -> tuple[int, float]:
        a, b = run
        mean_diff = float(np.mean(diffs[a:b])) if b > a else 0.0
        return (b - a + 1, -mean_diff)

    a, b = max(runs, key=score)
    return {
        "plateau": {
            "start_frame": a + 1,
            "end_frame": b + 1,
            "length": b - a + 1,
            "mean_diff": round(float(np.mean(diffs[a:b])), 3) if b > a else 0.0,
        },
        "chosen_index": (a + b) // 2,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--time", required=True, help="目标时间点 HH:MM:SS")
    ap.add_argument("--window", type=float, default=4.0, help="连拍窗口（秒）")
    ap.add_argument("--fps", type=int, default=6)
    ap.add_argument("--threshold", type=float, default=1.2, help="平台期帧差阈值")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--reference", default=None, help="当前帧，用于判断其稳定性")
    ap.add_argument("--assert-region", default=None, help="状态断言区域 x1,y1,x2,y2（目标 UI 区域）")
    ap.add_argument("--assert-white-min", type=float, default=0.0, help="断言区域近白像素占比下限")
    args = ap.parse_args()

    target = to_seconds(args.time)
    start = max(0.0, target - args.window / 2)
    with tempfile.TemporaryDirectory() as tmp:
        frames = grab(args.video, start, args.window, args.fps, tmp)
        if len(frames) < 2:
            raise SystemExit("连拍帧不足")
        vecs = [gray_vec(f) for f in frames]
        diffs = diff_series(vecs)
        picked = choose_plateau(diffs, args.threshold)
        chosen_index = picked["chosen_index"]
        chosen = frames[chosen_index]

        report = {
            "video": args.video,
            "time": args.time,
            "window": [start, start + args.window],
            "fps": args.fps,
            "frames": len(frames),
            "plateau": picked["plateau"],
            "chosen_frame": chosen_index + 1,
            "chosen_time_offset": round(start + (chosen_index + 1) / args.fps, 3),
            "all_diffs": [round(d, 3) for d in diffs],
        }
        if args.reference and os.path.isfile(args.reference):
            ref = gray_vec(args.reference)
            report["reference_diff"] = round(float(np.abs(ref - vecs[chosen_index]).mean()), 3)
            report["reference_is_transition"] = bool(report["reference_diff"] > args.threshold)

        if args.assert_region:
            x1, y1, x2, y2 = [int(v) for v in args.assert_region.split(",")]
            frame_img = Image.open(chosen).convert("L")
            patch = np.asarray(frame_img.crop((x1, y1, x2, y2)), dtype=np.float32)
            white = float((patch > 235).mean())
            report["state_assert"] = {
                "region": [x1, y1, x2, y2],
                "white_share": round(white, 3),
                "white_min": args.assert_white_min,
                "passed": bool(white >= args.assert_white_min),
            }
            if white < args.assert_white_min:
                print("STATE_ASSERT_FAILED", file=__import__("sys").stderr)

        Image.open(chosen).save(args.out)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
