# prompt-pulse

[![CI](https://github.com/disencd/prompt-pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/disencd/prompt-pulse/actions/workflows/ci.yml)
[![Security](https://github.com/disencd/prompt-pulse/actions/workflows/security.yml/badge.svg)](https://github.com/disencd/prompt-pulse/actions/workflows/security.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

A voice-activated, terminal-aware prompt enhancer for AI coding assistants.
It runs as a lightweight daemon on macOS and Linux, monitoring your terminal
in real-time. When you speak a vague command like *"fix the error"*, it
captures your full terminal context — screen buffer, working directory,
recent commands, detected error patterns, git branch — and rewrites it into
a precise, actionable prompt that any AI assistant can act on immediately.

## Why

AI coding assistants work best when prompts are specific. But when you are
deep in a debugging session, you don't want to manually copy error messages,
file paths, and line numbers into a prompt. This service does that
automatically: you speak (or type) a rough instruction, and it produces a
context-rich prompt ready for Devin, Copilot, ChatGPT, or any other tool.

## How It Works

```
You say: "fix the error"

The service captures:
  - Screen buffer showing: error TS2345 in src/auth/middleware.ts:42
  - CWD: ~/project/backend
  - Last command: npm run build (exit code 1)
  - Git branch: feature/auth-refactor

Enhanced prompt:
  "Fix the TypeScript compilation error TS2345 in src/auth/middleware.ts:42 —
   Argument of type 'string' is not assignable to parameter of type 'AuthToken'.
   The last command `npm run build` failed with exit code 1.
   CWD: ~/project/backend, branch: feature/auth-refactor"
```

## Features

### Terminal Context Capture

Four pluggable backends auto-detected at startup (tmux > iTerm2 > shell hook > generic):

| Backend | Screen Buffer | CWD | Commands | Exit Code | Setup |
|---------|:---:|:---:|:---:|:---:|-------|
| **tmux** | Yes | Yes | Yes | Via hook | Be inside tmux |
| **iterm2** | Yes | Yes | Yes | Yes | `pip install .[iterm2]` |
| **shell_hook** | No | Yes | Yes | Yes | `prompt-pulse install-hook` |
| **generic** | No | Yes | History | No | None (always available) |

- Polls every 2 s in idle mode; captures immediately on hotkey trigger
- Detects project type from manifest files (package.json, Cargo.toml, go.mod, pyproject.toml)
- Reads git branch from the working directory

### Error Detection

A regex engine scans the terminal output and extracts structured error
info (type, code, file, line, message) for 12+ pattern families:

- **Build errors** — TypeScript (`TS*`), ESLint, Rust (`cargo`), Go, Python
- **Runtime errors** — Node.js stack traces, Python tracebacks, segfaults
- **Test failures** — Jest, pytest, `cargo test`
- **Git conflicts** — merge conflict markers
- **Permission errors** — EACCES, sudo prompts

### Voice Capture and Transcription

- Records from the microphone with energy-based voice activity detection (VAD)
- Auto-calibrates a noise floor from the first 0.5 s, then ends on 1 s of silence
- Three transcription backends (auto-fallback):
  - **faster-whisper** (local, offline, private) — default
  - **OpenAI Whisper API** (cloud, most accurate for jargon)
  - **Apple Speech Framework** (macOS native, lowest latency)

### Prompt Enhancement

- Merges the voice transcript with terminal context into a meta-prompt
- Sends it to an LLM via `litellm` — supports **Ollama** (local, default),
  **OpenAI**, and **Anthropic**
- Falls back to a template-based prompt if the LLM is unavailable

### Delivery

- **Clipboard** — `pbcopy` (macOS), `xclip` / `xsel` / `wl-copy` (Linux)
- **Terminal paste** — iTerm2 `send_text()`, tmux `send-keys`
- **File pipe** — writes to `~/.prompt-pulse/last-prompt.txt`
- **Notification** — `osascript` (macOS), `notify-send` (Linux)

### Global Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+P` | Voice capture, enhance, deliver |
| `Ctrl+Shift+L` | Enhance last clipboard text with terminal context (no voice) |
| `Ctrl+Shift+R` | Re-enhance last prompt with updated terminal context |
| `Esc` | Cancel ongoing voice capture |

### CLI

```
prompt-pulse start          # Start the daemon with global hotkeys
prompt-pulse enhance "..."  # One-shot: enhance a text prompt
prompt-pulse context        # Show current terminal context
prompt-pulse install-hook   # Install shell hook (zsh/bash/fish)
prompt-pulse init           # Generate default config
```

### Security

- Screen buffer is held in memory only, never persisted to disk
- All transcription is local by default (Whisper); cloud APIs are opt-in
- Local Ollama is the default LLM; cloud providers require explicit config
- API keys are referenced via environment variables (`${VAR}` syntax in config)
- Configurable redaction patterns for secrets in terminal output

## Quick Start

```bash
pip install prompt-pulse

# Generate default config at ~/.prompt-pulse/config.yaml
prompt-pulse init

# Install shell hook for terminal state capture (zsh/bash/fish)
prompt-pulse install-hook

# One-shot: enhance a prompt with current terminal context
prompt-pulse enhance "fix the build error"

# Or start the daemon with global hotkeys
prompt-pulse start
```

### Configuration

All settings live in `~/.prompt-pulse/config.yaml`:

```yaml
terminal:
  backend: auto          # auto | tmux | iterm2 | shell_hook | generic

voice:
  engine: whisper_local  # whisper_local | whisper_api | apple_speech
  whisper_model: base.en

llm:
  provider: ollama       # ollama | openai | anthropic
  model: llama3.2:8b
  api_key: ${OPENAI_API_KEY}

delivery:
  method: clipboard      # clipboard | iterm_paste | api | file
  show_notification: true
```

## Documentation

| Document | Description |
|----------|-------------|
| [SPEC.md](SPEC.md) | Full technical specification — problem statement, requirements, API design, data models, and implementation plan |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture — ASCII diagrams, module layout, data flow, backend selection logic, and extension points |
| [AGENTS.md](AGENTS.md) | Development guide — prerequisites, build/test/lint commands, cross-platform notes, and contribution workflow |

## Development

```bash
git clone https://github.com/disencd/prompt-pulse.git
cd prompt-pulse
uv sync --extra dev
uv run ruff check src/ tests/
uv run pytest tests/ -v
```

## Releasing

```bash
# 1. Update version in pyproject.toml
# 2. Commit and tag
git tag v0.1.0
git push origin v0.1.0
# CI/CD handles: test -> build -> PyPI publish -> GitHub Release -> Docker image
```

## Branch Protection (Recommended)

Configure in GitHub Settings > Branches > `main`:
- Require status check **"CI Pass"** before merging
- Require PR reviews (1+)
- Require branches to be up to date
- Do not allow force pushes

## License

MIT
