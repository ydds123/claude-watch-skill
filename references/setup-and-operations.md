# Setup, transcription, operations, security

## Preflight

Run on every invocation:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" --check
```

- `0` ready (silent, proceed)
- `2` missing binaries → run `setup.py`
- `3` missing API key → run `setup.py`, then ask via `AskUserQuestion`
- `4` both

Installer: `python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py"`. On macOS it brew-installs `ffmpeg` + `yt-dlp`; on Linux/Windows it prints commands. It scaffolds `~/.config/claude-watch/.env` (mode 0600).

## Transcription backends

- Default: Alibaba Cloud Bailian. Install `bailian-cli`, authenticate with `bl auth login --console`. The CLI keeps credentials in its own config and uploads local audio to temporary storage. Never print or copy its API key.
- Legacy fallbacks: Groq / OpenAI (`--whisper groq|openai`), or force via `--transcriber`.
- When the user already holds a transcript, pass it and use `--no-whisper`; do not re-call a paid ASR provider.

## Re-runs

The script reuses cached download, transcript, and scenes. Only frames + notes regenerate. Force full re-run by deleting `<library_dir>/meta.json`. Never delete the library dir — it is the artifact.

## Token budget

Frames dominate cost (~50–80k input tokens for 60 frames at 512 px). Transcripts are cheap. `--resolution 1024` quadruples per-frame cost — only when tiny on-screen text must be read.

Follow-up questions about an already watched video: do not re-run; re-`Read` only needed frames from the library dir.

## Security

- Runs `yt-dlp`, `ffmpeg`, `ffprobe` locally.
- Sends extracted mono 16 kHz audio to the selected backend when captions are missing. Bailian CLI uploads to temporary storage; Groq/OpenAI optional.
- Reads/writes `~/.config/claude-watch/.env` (mode 0600).
- Persists artifacts to `~/claude-watch/library/<slug>/`.
- Does NOT log or transmit API keys, video files, or the original URL outside the audio call.
