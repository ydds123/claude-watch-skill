---
name: claude-watch
description: Turn tutorials, lectures, and product screen recordings into timestamped notes, evidence-backed B2B product guides, or external-facing operation manuals with cleaned, de-identified and annotated screenshots. Uses Alibaba Cloud Bailian by default when authenticated, with legacy Whisper fallbacks.
allowed-tools: Bash, Read, Write, AskUserQuestion
license: MIT
metadata:
  homepage: https://github.com/devinilabs/claude-watch
  repository: https://github.com/devinilabs/claude-watch
---

# /claude-watch — turn video into notes, product guides, or customer manuals

One viewing becomes a saved artifact; product modes also produce evidence-backed screenshots.

## When to use

- tutorial / lecture / talk URL → notes
- local screen recording → notes or product guide
- product demo recording → customer manual
- not for: video editing, one-off transcript summaries, slide design

## Modes

| mode | deliverable | reference |
|---|---|---|
| `notes` | timestamped `notes.md` | [references/notes-template.md](references/notes-template.md) |
| `product-guide` | evidence-backed internal guide | [references/product-guide.md](references/product-guide.md) + [evidence-model.md](references/evidence-model.md) |
| `external-manual` | customer manual, A-grade screenshots | [references/external-manual.md](references/external-manual.md) + [frame-integrity.md](references/frame-integrity.md) |

## Pipeline

0. Preflight: `python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" --check`; non-zero → installer. See [setup-and-operations.md](references/setup-and-operations.md).
1. Run: `python3 "${CLAUDE_SKILL_DIR}/scripts/watch.py" "<source>" [--mode …]`. Flags: `--start/--end`, `--max-frames`, `--resolution`, `--no-whisper`.
2. Verify frames: keep only stable post-action frames; reject black/blank/loading/transition/duplicate. Product modes write plateau-selected stills to `frame-stable/` by default; re-pick with `stable_frame.py` and keep its JSON evidence. Read `transcript.json` / `product-evidence.json` next.
3. Synthesize per the mode reference. Notes keeps its strict template; product modes order content by user task.
4. External manual finishing: `annotate.py` (crop → mask → annotate → inset) with `--qa`; then `check_images.py` (references/resolution/title sheet) and `doc_lint.py` (manifest hash, page_id, versioned refs). All three must pass.
5. Print a 3-line summary (title+slug, sections, artifact path). Never delete the library dir.

## Invariants (all modes)

- Every published image is traceable: source video + timestamp + extraction evidence + sha256 in `assets/manifest.json`.
- Version every regenerated image (`-vN`), update references, delete stale files; never overwrite a published filename.
- A screenshot's caption must match the on-screen page identity (`page_id`: tab or dialog title).
- `external-manual`: default de-identification = company name only (plus internal IPs / phones / share watermark); dialogs that are the subject must be fully rendered and opaque; callouts only on operation points, ≤2 per figure, 2–8 char labels with arrows.
- Gate: `check_images.py` + `doc_lint.py` both `ok`. Missing footage → gap entry (“视频未演示”), never an empty reference or invented screenshot.

## Failure modes & output risks

See [failure-modes.md](references/failure-modes.md) and [reports/output-risk-profile.md](reports/output-risk-profile.md).
