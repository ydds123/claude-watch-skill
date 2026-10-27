# Failure modes and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| Setup preflight non-zero | missing binary / API key | run `setup.py`; ask for key via `AskUserQuestion` |
| No transcript | backend failed or captions absent | `transcript_source: none`; generate frames-only notes and say so |
| Long video sparse-scan warning | coverage floor too low for duration | re-run with `--start` / `--end` on the relevant slice |
| Bailian failure | auth expired or quota | `bl auth status --output json`; never expose the unmasked key; fall back to Groq/OpenAI |
| Legacy Whisper failure | provider outage | retry with the other configured provider |
| Screenshot looks translucent / half-loaded | single-point extraction hit a transition frame | re-extract with `scripts/stable_frame.py` (burst → plateau → state assertion); if no opaque frame exists in the footage, record “needs re-record” |
| Document still shows the old image | same filename overwritten, viewer cache | version the filename (`-vN`), update references, delete stale files, keep `assets/manifest.json` |
| Caption does not match the screen | frame taken from the wrong page/step | verify tab title / dialog title / column headers; record `page_id` in manifest; fix caption or swap the frame |
| Missing image for a chapter | page never opened in the recording | triage: tab strip seen? menu opened? transcript mentioned? if absent, record a gap “视频未演示”; never invent |
| Annotation “for the sake of annotating” | no policy for what deserves a callout | only operation points; ≤2 per figure; 2–8 char labels + arrows; result/report pages unannotated |
| De-identification scope keeps flip-flopping | no default policy | default = company name only (plus internal IPs / phone numbers / share watermark); project overrides documented in the gate record |
| Gate passes but delivery is wrong | gate checks only existence/resolution | run `doc_lint.py` too: manifest hash match, page_id match, versioned references |
