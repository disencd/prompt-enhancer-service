# Architecture — PromptPulse

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                      macOS / Linux Host                              │
│                                                                      │
│  ┌─────────────┐    ┌──────────────────────────────────────────┐    │
│  │  Terminal    │◄──►│      prompt-pulse (daemon)    │    │
│  │  (Any:      │    │                                          │    │
│  │   tmux,     │    │  ┌────────────┐    ┌─────────────────┐   │    │
│  │   iTerm2,   │    │  │  Terminal   │    │  Voice Capture  │   │    │
│  │   any+hook, │    │  │  Monitor    │    │  (Microphone)   │   │    │
│  │   generic)  │    │  │            │    │                 │   │    │
│  └─────────────┘    │  │ ┌────────┐ │    └──────┬──────────┘   │    │
│                      │  │ │Backend │ │           │              │    │
│                      │  │ │Detector│ │           │              │    │
│                      │  │ │        │ │           │              │    │
│                      │  │ │ tmux   │ │           │              │    │
│                      │  │ │ iterm2 │ │           │              │    │
│                      │  │ │ hook   │ │           │              │    │
│                      │  │ │ generic│ │           │              │    │
│                      │  │ └────────┘ │           │              │    │
│                      │  └─────┬──────┘    ┌──────┘              │    │
│                      │        │           │                     │    │
│                      │        ▼           ▼                     │    │
│                      │  ┌─────────────────────────────────┐     │    │
│                      │  │       Context Builder            │     │    │
│                      │  │  (merge terminal + voice data)   │     │    │
│                      │  └──────────────┬──────────────────┘     │    │
│                      │                 │                         │    │
│                      │                 ▼                         │    │
│                      │  ┌─────────────────────────────────┐     │    │
│                      │  │       PromptPulse            │     │    │
│                      │  │  (LLM: Ollama / OpenAI / Claude) │     │    │
│                      │  └──────────────┬──────────────────┘     │    │
│                      │                 │                         │    │
│                      │                 ▼                         │    │
│                      │  ┌─────────────────────────────────┐     │    │
│                      │  │       Delivery Engine            │     │    │
│                      │  │  (Clipboard / Paste / API / File)│     │    │
│                      │  └─────────────────────────────────┘     │    │
│                      └──────────────────────────────────────────┘    │
│                                                                      │
│  ┌──────────────┐                                                   │
│  │  Global       │── Ctrl+Shift+P ──► Triggers pipeline             │
│  │  Hotkey       │                                                   │
│  │  Listener     │                                                   │
│  └──────────────┘                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Component Detail

### 1. Terminal Monitor

```
┌──────────────────────────────────────────────────────────┐
│              Terminal Monitor (Multi-Backend)              │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │ Backend Detector (auto mode)                      │    │
│  │ Probe order: tmux → iterm2 → shell_hook → generic │    │
│  └──────────┬───────────────────────────────────────┘    │
│             │ selects                                     │
│             ▼                                             │
│  ┌──────────────────────────────────────────────────┐    │
│  │ TerminalBackend ABC                               │    │
│  │  snapshot() → TerminalState                       │    │
│  │  get_cwd() → str                                  │    │
│  │  get_screen_buffer() → str | None                 │    │
│  └──────────────────────────────────────────────────┘    │
│             │ implemented by                              │
│  ┌──────────┴──────────┬───────────┬──────────────┐      │
│  │                     │           │              │      │
│  ▼                     ▼           ▼              ▼      │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐  │
│  │  tmux    │ │  iterm2  │ │shell_hook │ │ generic  │  │
│  │          │ │(optional)│ │           │ │          │  │
│  │capture-  │ │Python API│ │precmd/    │ │~/.zsh_   │  │
│  │pane,     │ │async get │ │preexec    │ │history,  │  │
│  │display-  │ │screen,   │ │state file │ │/proc/cwd │  │
│  │message   │ │variables │ │(JSON)     │ │or lsof   │  │
│  └──────────┘ └──────────┘ └───────────┘ └──────────┘  │
│  macOS+Linux  macOS only   macOS+Linux   macOS+Linux    │
│                                                          │
│  ┌────────────────┐                                      │
│  │ State Cache    │                                      │
│  │ - screen_buf   │                                      │
│  │ - cwd          │                                      │
│  │ - last_cmds[]  │                                      │
│  │ - exit_codes[] │                                      │
│  │ - git_branch   │                                      │
│  │ - job_name     │                                      │
│  └────────────────┘                                      │
│                                                          │
│  Polling: 2s idle / immediate on trigger                 │
└──────────────────────────────────────────────────────────┘
```

**Backend detection lifecycle**:
1. On startup, `BackendDetector` probes available backends in order: tmux → iterm2 → shell_hook → generic
2. The first backend that reports `is_available() == True` is selected
3. User can override with `--backend <name>` CLI flag or `terminal.backend` config
4. Selected backend's `snapshot()` is called on each poll cycle
5. Maintain a `TerminalState` dataclass with latest data
6. On `snapshot()` call, return a frozen copy of current state

**Backend-specific notes**:
- **tmux**: Checks `$TMUX` env var. Uses `tmux capture-pane -p` for screen buffer, `tmux display-message -p '#{pane_current_path}'` for CWD.
- **iterm2**: Requires `iterm2` pip package (optional extra). Connects via `iterm2.Connection`. Only works on macOS with iTerm2 running + Python API enabled.
- **shell_hook**: Reads `~/.prompt-pulse/shell_state.json` written by shell hooks. No screen buffer, but provides CWD, last command, and exit code.
- **generic**: Always available. Reads shell history files and infers CWD via `/proc/PID/cwd` (Linux) or `lsof -p PID` (macOS).

---

### 2. Voice Capture

```
┌────────────────────────────────────────────┐
│            Voice Capture Pipeline            │
│                                             │
│  Microphone                                 │
│      │                                      │
│      ▼                                      │
│  ┌──────────┐   ┌───────┐   ┌───────────┐ │
│  │ Audio    │──►│  VAD  │──►│ Whisper   │ │
│  │ Stream   │   │(Silero)│   │ Transcribe│ │
│  │ 16kHz    │   │       │   │           │ │
│  │ mono     │   │detect │   │ text out  │ │
│  └──────────┘   │speech │   └───────────┘ │
│                  │end    │                  │
│                  └───────┘                  │
│                                             │
│  States: IDLE → LISTENING → PROCESSING     │
│                    │                        │
│                    ▼                        │
│          Audio frames accumulated           │
│          until silence > 1s detected        │
└────────────────────────────────────────────┘
```

---

### 3. Context Builder

```
┌────────────────────────────────────────────────┐
│              Context Builder                     │
│                                                  │
│  Input:                                          │
│  ├── TerminalState (from Monitor)                │
│  └── voice_transcript (from Voice Capture)       │
│                                                  │
│  Processing:                                     │
│  ├── 1. Truncate screen buffer to last N lines   │
│  ├── 2. Run Error Detection Engine               │
│  │       ├── Regex pattern matching              │
│  │       ├── Extract: type, code, file, line     │
│  │       └── Classify severity                   │
│  ├── 3. Detect project type from CWD             │
│  │       ├── package.json → Node/TS              │
│  │       ├── Cargo.toml → Rust                   │
│  │       ├── go.mod → Go                         │
│  │       └── pyproject.toml → Python             │
│  ├── 4. Extract git metadata                     │
│  └── 5. Build ContextPayload dataclass           │
│                                                  │
│  Output: ContextPayload (frozen, serializable)   │
└────────────────────────────────────────────────┘
```

---

### 4. PromptPulse

```
┌─────────────────────────────────────────────┐
│            PromptPulse                    │
│                                              │
│  Input: ContextPayload                       │
│                                              │
│  ┌──────────────────────────────────┐       │
│  │  Meta-Prompt Template Engine     │       │
│  │                                  │       │
│  │  Render template with:          │       │
│  │  - voice_transcript             │       │
│  │  - cwd, last_commands           │       │
│  │  - screen_buffer (truncated)    │       │
│  │  - detected_errors              │       │
│  │  - project_type, git_branch     │       │
│  └──────────┬───────────────────────┘       │
│             │                                │
│             ▼                                │
│  ┌──────────────────────────────────┐       │
│  │  LLM Client (via litellm)       │       │
│  │                                  │       │
│  │  ┌─────────┬─────────┬────────┐ │       │
│  │  │ Ollama  │ OpenAI  │Anthropic│ │       │
│  │  │ (local) │ (cloud) │(cloud) │ │       │
│  │  └─────────┴─────────┴────────┘ │       │
│  └──────────┬───────────────────────┘       │
│             │                                │
│             ▼                                │
│  Output: enhanced_prompt (string)            │
└─────────────────────────────────────────────┘
```

---

### 5. Delivery Engine

```
┌────────────────────────────────────────────┐
│           Delivery Engine                    │
│                                             │
│  Input: enhanced_prompt (string)            │
│                                             │
│  Strategy (from config):                    │
│  ┌──────────────┐                          │
│  │clipboard     │──► pbcopy (macOS)         │
│  │              │    xclip/xsel/wl-copy (L) │
│  │              │    pyperclip (fallback)    │
│  ├──────────────┤                          │
│  │terminal_paste│──► iterm2 send_text()     │
│  │              │    tmux send-keys          │
│  ├──────────────┤                          │
│  │api           │──► HTTP POST to target    │
│  ├──────────────┤                          │
│  │file          │──► Write to pipe file     │
│  └──────────────┘                          │
│                                             │
│  Always: notification with preview          │
│  (osascript on macOS, notify-send on Linux) │
└────────────────────────────────────────────┘
```

---

## Data Flow (Sequence)

```
User          Hotkey       VoiceCapture    BackendDetector  TerminalBackend  ContextBuilder   Enhancer     Delivery
  │             │              │                │                │              │              │             │
  │──press──────►              │                │                │              │              │             │
  │             │──activate───►│                │                │              │             │             │
  │             │              │──listen──►     │                │              │              │             │
  │──speak─────────────────────►               │                │              │              │             │
  │             │              │                │                │              │              │             │
  │             │              │◄─silence───    │                │              │              │             │
  │             │              │──transcribe──► │                │              │              │             │
  │             │              │  (parallel)    │                │              │              │             │
  │             │              │                │◄─detect()──    │              │              │             │
  │             │              │                │──select────►   │              │              │             │
  │             │              │                │  (tmux/iterm2/ │              │              │             │
  │             │              │                │   hook/generic)│              │              │             │
  │             │              │                │                │◄─snapshot()  │              │             │
  │             │              │                │                │──state──────►│              │             │
  │             │              │───transcript──────────────────────────────────►│              │             │
  │             │              │                │                │              │──context────►│             │
  │             │              │                │                │              │              │──LLM call──►│
  │             │              │                │                │              │              │◄─enhanced───│
  │             │              │                │                │              │              │──deliver───►│
  │◄─────────────────────────────────notification + clipboard──────────────────────────────────────────────│
  │                                                                                                         │
```

---

## Error Handling Strategy

| Component | Failure Mode | Recovery |
|-----------|-------------|----------|
| Backend Detection | No backend available | Fall through to generic (always available). Log warning. |
| tmux Backend | Not inside tmux session | `is_available()` returns False; detector moves to next backend. |
| iterm2 Backend | iTerm2 not running / API disabled / `iterm2` not installed | `is_available()` returns False; detector moves to next backend. |
| shell_hook Backend | Hook not installed / state file missing | `is_available()` returns False; detector falls to generic. User prompted to run `prompt-pulse install-hook`. |
| generic Backend | No shell history found | Return empty history. CWD detection via `/proc` (Linux) or `lsof` (macOS). |
| Voice Capture | No microphone permission | Show OS permission prompt. Log error. |
| Voice Capture | No speech detected (timeout) | Cancel gracefully. Show "No speech detected" notification. |
| Whisper | Model not downloaded | Auto-download on first use. Show progress notification. |
| LLM (Ollama) | Ollama not running | Fall back to cloud LLM if configured. Otherwise return raw transcript. |
| LLM (Cloud) | API error / rate limit | Retry 2x. Fall back to template-based enhancement (no LLM). |
| Delivery | Clipboard failure | Fall back to file pipe + notification. |

---

## Performance Budget

| Step | Target Latency | Notes |
|------|---------------|-------|
| Hotkey detection | < 50ms | Native event loop |
| Terminal snapshot | < 200ms | tmux/iterm2: fast local calls. shell_hook: file read. generic: history parse + /proc or lsof. |
| Voice capture | User-dependent | Ends on silence detection |
| Transcription | < 2s | Whisper base.en on Apple Silicon |
| Context building | < 100ms | Pure CPU, regex matching |
| LLM enhancement | < 3s (local) / < 2s (cloud) | Ollama on M-series is fast |
| Delivery | < 100ms | Clipboard is instant |
| **Total (excl. speech)** | **< 5.5s** | End-to-end after speech ends |
