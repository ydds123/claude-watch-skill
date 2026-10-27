"""Evidence helpers for B2B product screen-recording guides."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable


KEYWORDS = {
    "configuration": ("配置", "新增", "编辑", "修改", "导入", "字段", "关联", "维护"),
    "application": ("选择", "填写", "提交", "审批", "签字", "确认", "保存"),
    "output": ("查看", "预览", "打印", "导出", "报表", "结果"),
    "issue": ("异常", "报错", "问题", "没有显示", "不显示", "空白", "失败"),
}


def detect_transcript_gaps(
    cues: list[dict],
    *,
    duration_s: float,
    min_gap_s: float = 60.0,
    start_s: float = 0.0,
) -> list[dict]:
    """Return internal/start/end gaps where no transcript cue is present."""
    if duration_s < 0:
        raise ValueError("duration_s must be non-negative")
    if start_s < 0 or start_s > duration_s:
        raise ValueError("start_s must be within duration_s")
    if min_gap_s <= 0:
        raise ValueError("min_gap_s must be positive")
    ordered = sorted(cues, key=lambda c: float(c.get("t_start", 0.0)))
    gaps: list[dict] = []
    cursor = start_s
    for cue in ordered:
        start = max(0.0, float(cue.get("t_start", 0.0)))
        end = max(start, float(cue.get("t_end", start)))
        if start - cursor >= min_gap_s:
            gaps.append({"t_start": cursor, "t_end": start, "duration_s": start - cursor})
        cursor = max(cursor, end)
    if duration_s - cursor >= min_gap_s:
        gaps.append({"t_start": cursor, "t_end": duration_s, "duration_s": duration_s - cursor})
    return gaps


def find_action_anchors(
    cues: list[dict], *, min_separation_s: float = 8.0, max_anchors: int = 30
) -> list[dict]:
    """Find timestamped product-operation cues without interpreting them as facts."""
    anchors: list[dict] = []
    last_by_category: dict[str, float] = {}
    for cue in sorted(cues, key=lambda c: float(c.get("t_start", 0.0))):
        text = str(cue.get("text", "")).strip()
        if not text:
            continue
        t = float(cue.get("t_start", 0.0))
        for category, words in KEYWORDS.items():
            hits = [word for word in words if word in text]
            if not hits:
                continue
            if t - last_by_category.get(category, -1e12) < min_separation_s:
                continue
            anchors.append({"t": t, "category": category, "keywords": hits, "text": text})
            last_by_category[category] = t
            if len(anchors) >= max_anchors:
                return anchors
    return anchors


def _dedupe_times(values: Iterable[float], *, tolerance_s: float = 0.4) -> list[float]:
    result: list[float] = []
    for value in sorted(max(0.0, float(v)) for v in values):
        if not result or value - result[-1] > tolerance_s:
            result.append(value)
    return result


def extract_frame_bursts(
    video: Path,
    anchors: list[dict],
    *,
    out_dir: Path,
    offsets: tuple[float, ...] = (-2.0, 0.0, 1.0, 3.0, 5.0),
    width_px: int = 1024,
) -> list[dict]:
    """Extract before/after candidates around product-operation anchors."""
    out_dir.mkdir(parents=True, exist_ok=True)
    times = _dedupe_times(anchor["t"] + offset for anchor in anchors for offset in offsets)
    records: list[dict] = []
    for index, t in enumerate(times, 1):
        name = f"{index:04d}_t{int(t)//60:02d}-{int(t)%60:02d}.jpg"
        out_path = out_dir / name
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
            "-vf", f"scale={width_px}:-2", "-q:v", "3", str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        records.append({"index": index, "t": t, "path": str(out_path.name)})
    return records


def build_evidence(
    transcript: list[dict],
    *,
    duration_s: float,
    transcript_path: str,
    frames_path: str,
    candidate_frames_path: str | None,
    gap_threshold_s: float = 60.0,
    max_anchors: int = 30,
    start_s: float = 0.0,
    mode: str = "product-guide",
) -> dict:
    requirements = {
        "configuration": ["ledger_list", "create_or_edit_form"],
        "application": ["before_action", "key_form", "result"],
        "output": ["entry", "final_preview"],
        "issue": ["error_or_incorrect_result"],
    }
    if mode == "external-manual":
        # External manuals reuse the evidence model, then finish every
        # published screenshot (see references/external-manual.md).
        requirements["finishing"] = [
            "clean_crop",
            "deidentify",
            "numbered_callout",
            "optional_inset_zoom",
        ]
    return {
        "mode": mode,
        "transcript_gaps": detect_transcript_gaps(
            transcript,
            duration_s=duration_s,
            min_gap_s=gap_threshold_s,
            start_s=start_s,
        ),
        "action_anchors": find_action_anchors(transcript, max_anchors=max_anchors),
        "screenshot_requirements": requirements,
        "source_files": {
            "transcript": transcript_path,
            "scene_frames": frames_path,
            "candidate_frames": candidate_frames_path,
        },
    }


def write_evidence(path: Path, evidence: dict) -> None:
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
