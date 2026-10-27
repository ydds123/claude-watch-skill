# Output risk profile — claude-watch

Predictable failure modes of the final user-facing artifact and the guard for each.

## Artifact families

- timestamped notes (Markdown)
- internal product guide (Markdown + evidence index + screenshots)
- customer-facing operation manual (Markdown + versioned screenshots + gate reports)

## Top output risks

| Risk | Why it happens | Guard |
|---|---|---|
| Wrong capture: transition/blank/loading frame | single-point extraction around animated UI | `stable_frame.py` plateau + state assertion; reject duplicates/blank frames |
| Translucent or half-expanded dialog | dialog fade-in captured mid-animation | state assertion on the dialog region; refuse frame if assertion fails |
| Stale screenshot after a fix | same filename overwritten, viewer cache | versioned filenames (`-vN`), manifest hash, delete stale files |
| Caption/page mismatch | frame picked from the wrong page or step | `page_id` in manifest; caption must match tab/dialog title |
| Missing figures for described steps | page never demonstrated in the recording | gap table entry “视频未演示”; no empty image references, no invented screenshots |
| Over-annotation | no rule for what deserves a callout | operation points only, ≤2 per figure, 2–8 char labels + arrows |
| Under/over de-identification | policy applied ad hoc | default = company name only; project override recorded in the gate |
| Claims not supported by footage | model fills gaps with probability | evidence-first rule: mark “未演示/不确定” as gap, never as product rule |
| Manual leaks internal context | timestamps, recording gaps, internal issues | external-manual mode forbids timestamps, demo limits, and internal problems |

## Evidence requirements

- Every published image: source video + timestamp + extraction evidence (`plateau`, `state_assert`) in `assets/manifest.json`.
- Gate reports: `image-gate.json`, title strip, `doc-lint.json`.
- Category B/C evidence must be labeled or excluded; only A-grade evidence ships in customer-facing manual.
