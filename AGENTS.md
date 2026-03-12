# PromptPulse — Development Guide

## Prerequisites

- **macOS or Linux**
- **Python 3.11+**
- **uv** (recommended) or pip for package management

### Optional (for specific backends)
- **tmux** — recommended for best terminal context (screen buffer capture)
- **iTerm2 3.3+** (macOS) — with Python API enabled for `iterm2` backend
- **xclip/xsel/wl-clipboard** (Linux) — for clipboard support

## Quick Start

```bash
cd prompt-pulse

# Install dependencies
uv sync

# Initialize config directory
uv run prompt-pulse init

# Install the shell hook (for terminal state capture)
uv run prompt-pulse install-hook
# Then restart your shell or: source ~/.prompt-pulse/hook.zsh

# Run a single enhancement (text mode, no voice/terminal needed)
uv run prompt-pulse enhance "fix the build error"

# Run with voice input
uv run prompt-pulse enhance --voice

# Start the daemon with global hotkeys
uv run prompt-pulse start
```

## Terminal Backends

The service auto-detects the best backend for your environment:

| Backend | Screen Buffer | CWD | Commands | Exit Code | Setup |
|---------|:---:|:---:|:---:|:---:|-------|
| **tmux** | Yes | Yes | Yes | Via hook | Be inside tmux |
| **iterm2** | Yes | Yes | Yes | Yes | `uv sync --extra iterm2` + enable API |
| **shell_hook** | No | Yes | Yes | Yes | `prompt-pulse install-hook` |
| **generic** | No | Yes | Partial (history) | No | None |

Auto-detection priority: `tmux` > `iterm2` > `shell_hook` > `generic`

Override in config: `terminal.backend: tmux`

### Shell Hook Installation

The shell hook is a lightweight precmd/preexec addition to your shell that writes CWD, last command, and exit code to a state file. Supports **zsh**, **bash**, and **fish**.

```bash
# Auto-detect and install
prompt-pulse install-hook

# Or specify shell explicitly
prompt-pulse install-hook --shell bash
prompt-pulse install-hook --shell fish
```

## Build & Test

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest tests/ -v

# Run linter
uv run ruff check src/ tests/

# Format code
uv run ruff format src/ tests/
```

## Project Structure

```
src/prompt_pulse/
├── main.py              # CLI entry point (typer) + hotkey daemon + pipeline
├── config.py            # Pydantic config models + YAML loader
├── terminal/
│   ├── monitor.py       # Multi-backend terminal capture
│   │                    #   TerminalBackend (ABC)
│   │                    #   ├── TmuxBackend
│   │                    #   ├── ITerm2Backend
│   │                    #   ├── ShellHookBackend
│   │                    #   └── GenericBackend
│   ├── context.py       # Context aggregation + project detection
│   └── error_patterns.py # Regex error detection engine
├── voice/
│   ├── capture.py       # Microphone recording + energy-based VAD
│   └── transcribe.py    # Whisper / Apple Speech / API backends
├── enhancer/
│   ├── prompt_builder.py # Meta-prompt templates
│   └── llm_client.py    # LiteLLM wrapper (Ollama/OpenAI/Anthropic)
└── delivery/
    ├── clipboard.py     # Cross-platform: pbcopy / xclip / xsel / wl-copy
    ├── iterm_paste.py   # iTerm2 session paste (optional)
    └── notification.py  # Cross-platform: osascript / notify-send
```

## Configuration

Config file: `~/.prompt-pulse/config.yaml`

See `config.example.yaml` for all available options.

### Terminal Backends

```yaml
terminal:
  backend: auto  # auto | tmux | iterm2 | shell_hook | generic
```

### LLM Providers

| Provider | Setup | Config |
|----------|-------|--------|
| **Ollama** (default) | `brew install ollama && ollama pull llama3.2:8b` | `provider: ollama` |
| **OpenAI** | Set `OPENAI_API_KEY` env var | `provider: openai`, `model: gpt-4o-mini` |
| **Anthropic** | Set `ANTHROPIC_API_KEY` env var | `provider: anthropic`, `model: claude-3.5-haiku` |

### Voice Engines

| Engine | Setup | Config |
|--------|-------|--------|
| **faster-whisper** (default) | `pip install faster-whisper` | `engine: whisper_local` |
| **OpenAI Whisper API** | Set `OPENAI_API_KEY` | `engine: whisper_api` |
| **Apple Speech** (macOS) | `pip install pyobjc-framework-Speech` | `engine: apple_speech` |

## Platform-Specific Notes

### macOS
- Clipboard: `pbcopy` / `pbpaste` (built-in)
- Notifications: `osascript` (built-in)
- CWD detection: `lsof` (built-in)
- Hotkeys: Requires Accessibility permission for the terminal app
- Microphone: macOS will prompt for Microphone permission

### Linux
- Clipboard: Install `xclip`, `xsel`, or `wl-clipboard` (Wayland)
- Notifications: Install `libnotify` (`notify-send`)
- CWD detection: `/proc/<pid>/cwd` (built-in)
- Hotkeys: Requires X11 or Wayland support via `pynput`
- Microphone: May need PulseAudio/PipeWire permissions

## Key Hotkeys (daemon mode)

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+P` | Voice capture -> enhance -> clipboard |
| `Ctrl+Shift+L` | Enhance clipboard text with terminal context |
| `Ctrl+Shift+R` | Re-enhance last prompt |
| `Esc` | Cancel voice capture |

## CLI Commands

| Command | Description |
|---------|-------------|
| `prompt-pulse start` | Start daemon with hotkeys |
| `prompt-pulse enhance "text"` | Enhance text directly |
| `prompt-pulse enhance --voice` | Voice input mode |
| `prompt-pulse enhance --clipboard` | Enhance clipboard contents |
| `prompt-pulse context` | Show current terminal context |
| `prompt-pulse context --backend tmux` | Use specific backend |
| `prompt-pulse install-hook` | Install shell hook |
| `prompt-pulse init` | Create config directory |

## Troubleshooting

- **"No terminal context"**: Install the shell hook (`prompt-pulse install-hook`) or use tmux
- **"Cannot connect to iTerm2"**: Enable Python API in iTerm2 Settings > General > Magic
- **"No speech detected"**: Check microphone permissions in System Settings
- **"LLM unavailable"**: For Ollama, ensure it's running (`ollama serve`). For cloud, check API keys
- **"Clipboard not working" (Linux)**: Install `xclip` or `xsel`: `sudo apt install xclip`
- **"Notifications not showing" (Linux)**: Install `libnotify`: `sudo apt install libnotify-bin`
- **Hotkeys not working**: macOS needs Accessibility permission; Linux needs X11/Wayland
