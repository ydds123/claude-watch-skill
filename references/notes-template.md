# Notes template (non-negotiable structure)

```markdown
# <Video Title>

**Source:** <URL or path>  ·  **Duration:** MM:SS  ·  **Watched:** YYYY-MM-DD

## TLDR
<3-4 sentences: what the video is about and the single most important takeaway.>

## Key Concepts
- **<concept>** — <one-line definition> · `[t=MM:SS]`
- ...

## Notes

### [t=00:04] <Section title you derive from on-screen + spoken content>

![](frames/0001_t00-04.jpg)

**On screen:** <Transcribe / describe the slide, code, diagram. If code, transcribe verbatim.>

**Said:** <Relevant transcript excerpt for this scene, lightly cleaned.>

**Synthesis:** <Your connection — what this section is teaching, how it links to prior section.>

### [t=00:31] <next section>
...

## Code & Commands
<every code-on-screen frame's content as a runnable fenced block, language-tagged, with [t=MM:SS] back-link>

```python
# [t=03:45]
def forward(x):
    return x @ W + b
```

## Diagrams Referenced
- `[t=02:10]` — <one-line description of the diagram in frame 0008>
- ...

## Open Questions
- <things mentioned but not fully covered, or follow-ups to explore>
```

## Rules baked into the template

These rules apply to `notes` mode. Product modes follow their own references.

- **One scene = one section.** Use the `t=MM:SS` from each frame as the section anchor.
- **Adjacent scenes that are clearly the same topic** can be merged; mention it parenthetically: *(merged scenes at t=02:10 and t=02:42)*.
- **Code blocks must be fenced** with the right language tag, transcribed verbatim from the frame.
- **The "On screen" block is required even for title slides.** Keeps the structure parallel.
- **Timestamps are absolute** (real video timeline) — for YouTube sources, a viewer can paste `<URL>&t=<seconds>` to jump there.
