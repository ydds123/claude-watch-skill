"""Alibaba Cloud Model Studio transcription through the official Bailian CLI."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


DEFAULT_MODEL = "qwen-audio-3.1-asr-flash-filetrans"


class BailianError(Exception):
    pass


def cli_path() -> str | None:
    return shutil.which("bl")


def is_authenticated() -> bool:
    cli = cli_path()
    if not cli:
        return False
    try:
        proc = subprocess.run(
            [cli, "auth", "status", "--output", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if proc.returncode != 0:
            return False
        return bool(json.loads(proc.stdout).get("authenticated"))
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False


def parse_result(payload: dict) -> list[dict]:
    """Convert Bailian millisecond sentence timestamps to claude-watch cues."""
    cues: list[dict] = []
    for transcript in payload.get("transcripts") or []:
        for sentence in transcript.get("sentences") or []:
            text = str(sentence.get("text") or "").strip()
            if not text:
                continue
            cues.append(
                {
                    "t_start": float(sentence["begin_time"]) / 1000.0,
                    "t_end": float(sentence["end_time"]) / 1000.0,
                    "text": text,
                }
            )
    cues.sort(key=lambda cue: (cue["t_start"], cue["t_end"]))
    return cues


def transcribe(
    audio: Path,
    *,
    raw_result_path: Path,
    model: str = DEFAULT_MODEL,
    language: str = "zh",
    timeout_s: int = 7200,
) -> list[dict]:
    """Upload a local audio file via Bailian CLI, wait, and return normalized cues."""
    cli = cli_path()
    if not cli:
        raise BailianError("Bailian CLI 'bl' is not installed")
    if not is_authenticated():
        raise BailianError("Bailian CLI is not authenticated; run: bl auth login --console")

    raw_result_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        cli,
        "speech",
        "recognize",
        "--url",
        str(audio),
        "--model",
        model,
        "--language",
        language,
        "--out",
        str(raw_result_path),
        "--output",
        "json",
        "--quiet",
        "--timeout",
        str(timeout_s),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s + 60,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[-1000:]
        raise BailianError(f"Bailian transcription failed ({proc.returncode}): {detail}")
    try:
        payload = json.loads(raw_result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BailianError(f"Cannot read Bailian result: {exc}") from exc
    cues = parse_result(payload)
    if not cues:
        raise BailianError("Bailian returned no timestamped sentences")
    return cues
