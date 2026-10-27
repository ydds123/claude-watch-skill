# Changelog

All notable changes to `claude-watch` are documented here.

## [0.1.0] — 2026-05-03

### Added
- `/claude-watch <url-or-path> [topic]` slash command that produces structured study notes.
- Scene-aware frame extraction: ffmpeg scene detection (default threshold 0.30) with a coverage floor (synthetic boundaries every 45s across long static gaps) and a budget cap (default 80 frames, drops lowest-scoring detected scenes first; floor boundaries are always preserved).
- Persistent library at `~/claude-watch/library/<slug>/` with cached download, transcript, and scenes — re-runs only regenerate frames + notes.
- Slug rule `YYYY-MM-DD-<title>-<sha1(source+focus)[:4]>` so chronological + collision-safe across focus-range re-watches.
- Native caption pull via yt-dlp (manual + auto-subs) with VTT dedupe.
- Whisper fallback: Groq `whisper-large-v3` (preferred), OpenAI `whisper-1` (alt). Stdlib HTTP clients — no SDKs.
- `--start`/`--end` focused mode with denser coverage floor (15s vs 45s default).
- `setup.py` preflight (`--check` / `--json`) with cross-platform installer (`brew` on macOS auto-runs; `apt`/`dnf`/`winget`/`pip` commands printed elsewhere).
- Three-surface distribution: Claude Code plugin, claude.ai `.skill` bundle (built by `scripts/build-skill.sh`), Codex skill.
- SessionStart hook prints a one-liner only when remediation is needed.
- Strict notes template baked into SKILL.md: TLDR, Key Concepts, per-scene Notes (On screen + Said + Synthesis), Code & Commands, Diagrams Referenced, Open Questions.

## 2026-10-26 — frame integrity + lean entrypoint

### Added
- `agents/interface.yaml`: input/output contract, boundaries, stop conditions.
- `references/frame-integrity.md`: stable-frame selection (burst → plateau → state assertion), versioned assets + manifest, `page_id` consistency, popup decision tree, callout policy, default de-identification, missing-image self-check.
- `references/failure-modes.md`, `references/setup-and-operations.md`, `references/notes-template.md`: moved out of `SKILL.md`.
- `reports/output-risk-profile.md`: wrong capture / stale asset / mismatch / over-annotation risks and guards.
- `scripts/stable_frame.py`: burst + plateau + optional state assertion; writes evidence JSON.
- `scripts/doc_lint.py`: document-vs-manifest lint (missing refs, sha256 mismatch, unversioned names, `page_id`, unreferenced images).
- `scripts/find_pages.py`: tab-strip scan sheets to locate pages across a recording.
- Tests for `doc_lint` and `find_pages` helpers.

### Changed
- `SKILL.md` slimmed to the routing/pipeline layer (references hold details), satisfying the production context budget.
- External-manual gate now includes `doc_lint.py`; every figure must be traceable to a stable frame.

### Fixed
- Screenshots taken from transition frames (translucent dialogs) → stable-frame selection with state assertion.
- Old image shown after regeneration (same filename cache) → versioned filenames + manifest hash.
- Missing screenshots blocking delivery → tab-strip scan and documented gap entries.

## 2026-10-26 — P1 integration (stable frames, page clustering, caption gate)

### Added
- `frames.extract_stable_frames`: burst → plateau → save still, with plateau evidence; product modes now write `frame-stable/` by default (`--no-stable-frames` to skip) and record `stable_frames` in `product-evidence.json`.
- `stable_frame.choose_plateau` / `diff_series` / `plateau_runs`: reusable pure helpers (unit-tested).
- `find_pages`: average-hash + Hamming clustering → `unique-pages.jpg` and `unique-pages.csv` listing distinct pages and their first timestamps.
- `check_images`: optional `--manifest` → per-figure `page_id`; caption vs `page_id` warnings; `--require-page-id` failure mode.

### Tests
- `test_stable_frame.py` (plateau helpers), `test_find_pages.py` (hash/cluster), `test_check_images.py` caption/page_id cases.

## 2026-10-26 — page identity + colleague guide

### Added
- `find_pages` OCR modes: `detect_active_tab` / `_tab_candidates` / `suggest_page_ids` — fills `page_id` from the curated filename slug, keeps OCR text as evidence, and writes `page-id-suggestions.csv` for review.
- `doc_lint --annotations`: callout policy gate (consecutive badges, label 2–8 chars, ≤3 callouts, unreferenced jobs).
- `check_images --manifest` / `--require-page-id` / `--ocr-check`: page_id presence, caption consistency, optional OCR-evidence cross-check.
- `watch.py` page scan: writes `pages-seen.json` and prints a capture-checklist line for product modes.
- `docs/使用说明与录制规范.md`: colleague-facing usage + recording standards (video spec, operation pacing, narration, transcription, delivery checklist).

### Tests
- `test_find_pages`: active-tab detection, page-id assignment, clustering; `test_check_images`: OCR evidence; `test_doc_lint`: annotation policy.

## 2026-10-27 — external manuals exclude acceptance checklists

### Changed
- ``references/external-manual.md``: external mode structure ends with 常见问题; 验收检查表/验收场景 are internal content and must not appear in customer manuals.
- De-identification default clarified: only the company name is masked by default; internal IPs / phone numbers / share watermark are masked when present; names/farm IDs follow project policy.
- Callout policy aligned: only operation points, ≤2 per figure (max 3), result/report pages unannotated.
- ``examples/dual-prevention-external-manual``: manual updated (9 acceptance-check sections removed), companion gate docs synced, gate reports regenerated.
