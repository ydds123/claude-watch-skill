"""claude-watch orchestrator — runs the full pipeline and prints a manifest block."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# When invoked as `python scripts/watch.py` the repo root is not automatically
# on sys.path.  Insert it so that `from scripts import …` works correctly
# regardless of how the script is launched.
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import library as lib
from scripts import resolve as resolve_mod
from scripts import download as download_mod
from scripts import transcribe as transcribe_mod
from scripts import scenes as scenes_mod
from scripts import frames as frames_mod
from scripts import setup as setup_mod
from scripts import whisper
from scripts import bailian
from scripts import product as product_mod


def _parse_ts(s: str) -> float:
    """Accept SS, MM:SS, or HH:MM:SS."""
    parts = s.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"bad timestamp: {s}")


def _focus_range(args) -> tuple[float, float] | None:
    if args.start is None and args.end is None:
        return None
    s = _parse_ts(args.start) if args.start else 0.0
    e = _parse_ts(args.end) if args.end else 1e12  # clamped later by duration
    return (s, e)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="watch")
    p.add_argument("source", help="URL or local path")
    p.add_argument("--start", help="focus start (SS, MM:SS, or HH:MM:SS)")
    p.add_argument("--end", help="focus end (SS, MM:SS, or HH:MM:SS)")
    p.add_argument("--max-frames", type=int, default=80)
    p.add_argument("--resolution", type=int, default=512, help="frame width in px")
    p.add_argument("--scene-threshold", type=float, default=0.30)
    p.add_argument("--max-gap", type=float, default=45.0, help="coverage floor seconds")
    p.add_argument("--whisper", choices=["groq", "openai"], help="force Whisper backend")
    p.add_argument(
        "--transcriber",
        choices=["bailian", "groq", "openai"],
        help="force transcription backend (default: Bailian when authenticated)",
    )
    p.add_argument("--asr-model", default=bailian.DEFAULT_MODEL, help="Bailian ASR model")
    p.add_argument("--language", default="zh", help="ASR language hint")
    p.add_argument("--no-whisper", action="store_true", help="disable Whisper fallback")
    p.add_argument("--out-dir", help="library root (default: ~/claude-watch/library)")
    p.add_argument(
        "--mode",
        choices=["notes", "product-guide", "external-manual"],
        default="notes",
        help=(
            "output workflow; product-guide and external-manual also build evidence "
            "and operation-frame candidates"
        ),
    )
    p.add_argument(
        "--no-stable-frames",
        action="store_true",
        help="skip stable-frame extraction for product modes (plateau-selected stills)",
    )
    p.add_argument(
        "--gap-threshold",
        type=float,
        default=60.0,
        help="minimum transcript gap to report in product-guide mode",
    )
    p.add_argument(
        "--max-product-anchors",
        type=int,
        default=24,
        help="maximum operation anchors used for product-guide frame bursts",
    )
    args = p.parse_args(argv)

    if args.out_dir:
        lib.LIBRARY_ROOT = Path(args.out_dir).expanduser().resolve()
    lib.LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)

    # ---- Stage 1: resolve ----
    focus = _focus_range(args)
    meta = resolve_mod.resolve_source(args.source, focus_range=focus)
    meta["watched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = lib.slug_for(meta)
    work = lib.LIBRARY_ROOT / slug
    work.mkdir(parents=True, exist_ok=True)

    # Cache check — skip download/transcribe/scenes if same source_hash
    cached = lib.cache_lookup(slug, meta["source_hash"])

    # ---- Stage 2: download ----
    src_dir = work / "source"
    if cached and (src_dir.glob("video.*")):
        video = next(iter(src_dir.glob("video.*")))
    else:
        if meta["is_url"]:
            video = download_mod.download_video(meta["source"], src_dir, basename="video")
        else:
            video = download_mod.copy_local(Path(meta["source"]), src_dir, basename="video")

    # ---- Stage 3: transcribe ----
    transcript_path = work / "transcript.json"
    if cached and transcript_path.exists():
        transcript = json.loads(transcript_path.read_text())
    else:
        transcript: list[dict] = []
        if meta["is_url"]:
            vtt = transcribe_mod.fetch_native_captions(meta["source"], work / "subs")
            if vtt:
                transcript = transcribe_mod.dedupe_cues(
                    transcribe_mod.parse_vtt(vtt.read_text())
                )
                # Keep the raw VTT alongside transcript.json for grepability
                (work / "transcript.vtt").write_bytes(vtt.read_bytes())
        transcript_backend = None
        if not transcript and not args.no_whisper:
            env = setup_mod._read_env()
            forced_backend = args.transcriber or args.whisper
            if forced_backend == "bailian" or (forced_backend is None and bailian.is_authenticated()):
                backend = "bailian"
            else:
                backend = whisper.pick_backend(
                    groq_key=env.get("GROQ_API_KEY"),
                    openai_key=env.get("OPENAI_API_KEY"),
                    forced=forced_backend,
                )
            if backend:
                audio = work / "audio.m4a"
                transcribe_mod.extract_audio_for_whisper(video, audio)
                try:
                    if backend == "bailian":
                        transcript = bailian.transcribe(
                            audio,
                            raw_result_path=work / "transcript.bailian.raw.json",
                            model=args.asr_model,
                            language=args.language,
                        )
                    else:
                        transcript = transcribe_mod.transcribe_via_whisper(
                            audio,
                            backend=backend,
                            groq_key=env.get("GROQ_API_KEY"),
                            openai_key=env.get("OPENAI_API_KEY"),
                        )
                    transcript_backend = backend
                except (bailian.BailianError, whisper.WhisperError) as e:
                    print(f"Transcription failed ({backend}): {e}", file=sys.stderr)
        transcript = transcribe_mod.insert_speaker_breaks(transcript)
        transcript_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))

    if focus:
        transcript_for_window = transcribe_mod.slice_to_window(
            transcript, start_s=focus[0], end_s=focus[1]
        )
    else:
        transcript_for_window = transcript

    # ---- Stage 4: detect_scenes (within window if focused) ----
    scenes_path = work / "scenes.json"
    if cached and scenes_path.exists() and not focus:
        raw_scenes = [
            scenes_mod.Scene(t=s["t"], score=s["score"], kind=s["kind"])
            for s in json.loads(scenes_path.read_text())
        ]
    else:
        raw_scenes = scenes_mod.detect_scenes(video, threshold=args.scene_threshold)

    if focus:
        s0, s1 = focus
        s1 = min(s1, meta["duration_s"])
        raw_scenes = [s for s in raw_scenes if s0 <= s.t <= s1]
        if not raw_scenes or raw_scenes[0].t > s0:
            raw_scenes.insert(0, scenes_mod.Scene(t=s0, score=1.0, kind="detected"))
        max_gap = min(args.max_gap, 15.0)  # focus mode: denser coverage
        duration_for_floor = s1
    else:
        max_gap = args.max_gap
        duration_for_floor = meta["duration_s"]

    floored = scenes_mod.apply_coverage_floor(
        raw_scenes, duration_s=duration_for_floor, max_gap_s=max_gap
    )
    capped = scenes_mod.apply_budget_cap(floored, max_frames=args.max_frames)

    if not focus:
        scenes_path.write_text(json.dumps(
            [{"t": s.t, "score": s.score, "kind": s.kind} for s in capped],
            indent=2,
        ))

    # ---- Stage 5+6: extract frames ----
    frames_dir = work / "frames"
    # Wipe any prior frames so re-runs don't accumulate orphans.
    if frames_dir.exists():
        for f in frames_dir.iterdir():
            f.unlink()
    raw_frame_records = frames_mod.extract_frames(
        video, capped, out_dir=frames_dir, width_px=args.resolution
    )
    # `extract_frames` returns `path` relative to `out_dir` (just the basename).
    # The manifest expects paths relative to the library directory (i.e. with
    # the `frames/` subdir prefix), so prepend it here.
    frame_records = [
        {**fr, "path": f"frames/{fr['path']}"} for fr in raw_frame_records
    ]

    # Pages seen: cluster tab strips of already-extracted frames (no extra decode).
    pages_seen: list[dict] = []
    if args.mode in {"product-guide", "external-manual"}:
        try:
            from scripts.find_pages import cluster_frames

            pages_seen = cluster_frames([frames_dir / fr["path"] for fr in raw_frame_records])
            (work / "pages-seen.json").write_text(
                json.dumps(pages_seen, ensure_ascii=False, indent=2)
            )
        except Exception:  # noqa: BLE001 - page scan is best-effort
            pages_seen = []

    # Product recordings need evidence around actions, not only at scene cuts.
    product_evidence_path = None
    product_candidate_records: list[dict] = []
    stable_frame_records: list[dict] = []
    product_modes = {"product-guide", "external-manual"}
    if args.mode in product_modes:
        anchors = product_mod.find_action_anchors(
            transcript_for_window, max_anchors=args.max_product_anchors
        )
        candidate_dir = work / "frame-candidates"
        if candidate_dir.exists():
            for candidate in candidate_dir.iterdir():
                if candidate.is_file():
                    candidate.unlink()
        if anchors:
            product_candidate_records = product_mod.extract_frame_bursts(
                video,
                anchors,
                out_dir=candidate_dir,
                width_px=max(args.resolution, 1024),
            )
        if anchors and not args.no_stable_frames:
            stable_dir = work / "frame-stable"
            if stable_dir.exists():
                for stale in stable_dir.iterdir():
                    if stale.is_file():
                        stale.unlink()
            stable_frame_records = frames_mod.extract_stable_frames(
                video,
                [float(anchor["t"]) for anchor in anchors],
                out_dir=stable_dir,
                width_px=max(args.resolution, 1024),
            )
        product_evidence = product_mod.build_evidence(
            transcript_for_window,
            duration_s=min(focus[1], meta["duration_s"]) if focus else meta["duration_s"],
            start_s=focus[0] if focus else 0.0,
            transcript_path=(
                "transcript.window.json" if focus else "transcript.json"
            ),
            frames_path="frames/",
            candidate_frames_path="frame-candidates/" if anchors else None,
            gap_threshold_s=args.gap_threshold,
            max_anchors=args.max_product_anchors,
            mode=args.mode,
        )
        product_evidence["candidate_frames"] = product_candidate_records
        product_evidence["stable_frames"] = stable_frame_records
        product_evidence_path = work / "product-evidence.json"
        product_mod.write_evidence(product_evidence_path, product_evidence)

    # ---- Stage 7: emit manifest + meta + structured stdout block ----
    transcript_window_path = work / "transcript.window.json"
    if focus:
        transcript_window_path.write_text(
            json.dumps(transcript_for_window, indent=2, ensure_ascii=False)
        )
        transcript_consumer_path = "transcript.window.json"
    else:
        transcript_consumer_path = "transcript.json"

    (work / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    lib.write_manifest(
        path=work / "manifest.json",
        meta=meta,
        scenes=[{"t": s.t, "score": s.score, "kind": s.kind} for s in capped],
        frames=frame_records,
        transcript_path=transcript_consumer_path,
        focus_range=focus,
    )

    # Stdout: the contract Claude consumes
    duration_str = f"{int(meta['duration_s']) // 60:02d}:{int(meta['duration_s']) % 60:02d}"
    focus_str = "full" if focus is None else f"{args.start or '0:00'}–{args.end or 'end'}"
    transcript_kind = (
        "captions" if (work / "transcript.vtt").exists()
        else "bailian" if (work / "transcript.bailian.raw.json").exists() and transcript
        else "whisper" if transcript
        else "none"
    )
    print("=== claude-watch manifest ===")
    print(f"title: {meta['title']!r}")
    print(f"source: {meta['source']}")
    print(f"duration: {duration_str}")
    print(f"focus: {focus_str}")
    print(f"transcript_source: {transcript_kind}")
    print(f"scenes_detected: {sum(1 for s in capped if s.kind == 'detected')}")
    print(f"frames_extracted: {len(capped)}")
    if args.mode in product_modes:
        print(f"product_evidence: {product_evidence_path}")
        print(f"product_frame_candidates: {len(product_candidate_records)}")
        print(f"stable_frames_extracted: {len(stable_frame_records)}")
        if stable_frame_records:
            print(f"stable_frames_dir: {work / 'frame-stable'}")
        print(f"pages_seen: {len(pages_seen)} (pages-seen.json)")
        print("capture_check: confirm every page needed for the deliverable appears above; "
              "missing page → check tab/menu/transcript, else record a gap (never invent a screenshot)")
    print(f"library_dir: {work}")
    print()
    print("=== frames ===")
    for fr in frame_records:
        mm = int(fr["t"]) // 60
        ss = int(fr["t"]) % 60
        print(f"{fr['index']:04d}  t={mm:02d}:{ss:02d}  {fr['path']}  ({fr['kind']})")
    print()
    print("=== transcript ===")
    print(f"{work / transcript_consumer_path}  (load this — too long to inline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
