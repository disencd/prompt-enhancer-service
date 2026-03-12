"""Terminal monitor — multi-backend terminal state capture.

Supports:
  - shell_hook: Universal — installs precmd/preexec hook, reads state file
  - tmux: For tmux users — capture-pane + display-message
  - iterm2: macOS iTerm2 Python API (optional)
  - generic: Fallback — reads shell history + CWD via /proc or lsof
  - auto: Auto-detect the best backend for the current environment
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

BackendType = Literal["auto", "shell_hook", "tmux", "iterm2", "generic"]

# Shared state file location for the shell hook
STATE_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "prompt-enhancer"
STATE_FILE_PATTERN = "state-{pid}.json"

# ---------------------------------------------------------------------------
# Data classes (shared across all backends)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommandRecord:
    """A single command from the session history."""

    command: str
    exit_code: int | None = None
    working_directory: str | None = None
    timestamp: str | None = None


@dataclass(frozen=True)
class TerminalState:
    """Frozen snapshot of the current terminal state."""

    screen_buffer: str = ""
    cwd: str = ""
    shell: str = ""
    last_commands: list[CommandRecord] = field(default_factory=list)
    running_process: str | None = None
    git_branch: str | None = None
    hostname: str | None = None
    username: str | None = None
    session_id: str | None = None
    backend: str = ""
    captured_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------

class TerminalBackend(ABC):
    """Abstract base for terminal state capture backends."""

    name: str = "base"

    def __init__(self, screen_buffer_lines: int = 100):
        self._buffer_lines = screen_buffer_lines

    @abstractmethod
    async def snapshot(self) -> TerminalState:
        """Capture and return the current terminal state."""
        ...

    def is_available(self) -> bool:
        """Check if this backend can work in the current environment."""
        return True

    async def _detect_git_branch(self, cwd: str | None) -> str | None:
        """Detect the current git branch by reading the .git/HEAD file."""
        if not cwd:
            return None
        try:
            for check_dir in [Path(cwd), *Path(cwd).parents]:
                git_head = check_dir / ".git" / "HEAD"
                if git_head.exists():
                    content = git_head.read_text().strip()
                    if content.startswith("ref: refs/heads/"):
                        return content.removeprefix("ref: refs/heads/")
                    return content[:12]  # detached HEAD — return short hash
                if check_dir == Path.home():
                    break
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Shell history reader (shared utility)
# ---------------------------------------------------------------------------

def _read_shell_history(shell: str = "", max_commands: int = 10) -> list[CommandRecord]:
    """Read recent commands from the shell history file."""
    history_files = []

    shell_name = Path(shell).name if shell else os.environ.get("SHELL", "")
    shell_name = Path(shell_name).name

    if "zsh" in shell_name:
        history_files.append(Path.home() / ".zsh_history")
    elif "bash" in shell_name:
        history_files.append(Path.home() / ".bash_history")
    elif "fish" in shell_name:
        history_files.append(
            Path.home() / ".local" / "share" / "fish" / "fish_history"
        )

    # Fallback: try common locations
    if not history_files:
        for name in [".zsh_history", ".bash_history"]:
            p = Path.home() / name
            if p.exists():
                history_files.append(p)
                break

    commands: list[CommandRecord] = []
    for hfile in history_files:
        if not hfile.exists():
            continue
        try:
            raw = hfile.read_bytes()
            # Try UTF-8, fall back to latin-1
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = raw.decode("latin-1")

            lines = text.strip().split("\n")
            for line in lines[-max_commands * 2:]:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # zsh extended history format: `: 1234567890:0;command`
                zsh_match = re.match(r"^:\s*(\d+):\d+;(.+)", line)
                if zsh_match:
                    ts = zsh_match.group(1)
                    cmd = zsh_match.group(2).strip()
                    commands.append(CommandRecord(command=cmd, timestamp=ts))
                # Fish history format: `- cmd: command`
                elif line.startswith("- cmd:"):
                    cmd = line.removeprefix("- cmd:").strip()
                    commands.append(CommandRecord(command=cmd))
                else:
                    # Plain history line (bash)
                    commands.append(CommandRecord(command=line))
            break  # Use first available history file
        except Exception:
            logger.debug("Failed to read history file: %s", hfile)

    return commands[-max_commands:]


# ---------------------------------------------------------------------------
# Backend: Shell Hook (universal, works on any terminal)
# ---------------------------------------------------------------------------

SHELL_HOOK_ZSH = r'''
# prompt-enhancer shell hook (zsh)
__prompt_enhancer_state_dir="${XDG_RUNTIME_DIR:-/tmp}/prompt-enhancer"
mkdir -p "$__prompt_enhancer_state_dir"
__prompt_enhancer_state_file="$__prompt_enhancer_state_dir/state-$$.json"

__prompt_enhancer_preexec() {
    __prompt_enhancer_cmd="$1"
    __prompt_enhancer_cmd_start=$(date +%s)
}

__prompt_enhancer_precmd() {
    local exit_code=$?
    printf '{"pid":%d,"cwd":"%s","shell":"%s","last_command":"%s","exit_code":%d,"timestamp":%d,"hostname":"%s","username":"%s"}\n' \
        "$$" "$PWD" "$SHELL" \
        "$(echo "$__prompt_enhancer_cmd" | sed 's/"/\\"/g')" \
        "$exit_code" "$(date +%s)" "$(hostname -s)" "$USER" \
        > "$__prompt_enhancer_state_file"
    unset __prompt_enhancer_cmd
}

autoload -Uz add-zsh-hook
add-zsh-hook preexec __prompt_enhancer_preexec
add-zsh-hook precmd __prompt_enhancer_precmd
'''

SHELL_HOOK_BASH = r'''
# prompt-enhancer shell hook (bash)
__prompt_enhancer_state_dir="${XDG_RUNTIME_DIR:-/tmp}/prompt-enhancer"
mkdir -p "$__prompt_enhancer_state_dir"
__prompt_enhancer_state_file="$__prompt_enhancer_state_dir/state-$$.json"

__prompt_enhancer_trap_debug() {
    __prompt_enhancer_cmd="$BASH_COMMAND"
}
trap '__prompt_enhancer_trap_debug' DEBUG

__prompt_enhancer_prompt_command() {
    local exit_code=$?
    printf '{"pid":%d,"cwd":"%s","shell":"%s","last_command":"%s","exit_code":%d,"timestamp":%d,"hostname":"%s","username":"%s"}\n' \
        "$$" "$PWD" "$SHELL" \
        "$(echo "$__prompt_enhancer_cmd" | sed 's/"/\\"/g')" \
        "$exit_code" "$(date +%s)" "$(hostname -s)" "$USER" \
        > "$__prompt_enhancer_state_file"
}

PROMPT_COMMAND="__prompt_enhancer_prompt_command${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
'''

SHELL_HOOK_FISH = r'''
# prompt-enhancer shell hook (fish)
set -g __prompt_enhancer_state_dir (test -n "$XDG_RUNTIME_DIR"; and echo "$XDG_RUNTIME_DIR"; or echo "/tmp")"/prompt-enhancer"
mkdir -p $__prompt_enhancer_state_dir
set -g __prompt_enhancer_state_file "$__prompt_enhancer_state_dir/state-%self.json"

function __prompt_enhancer_postexec --on-event fish_postexec
    set -l exit_code $status
    printf '{"pid":%d,"cwd":"%s","shell":"fish","last_command":"%s","exit_code":%d,"timestamp":%d,"hostname":"%s","username":"%s"}\n' \
        %self "$PWD" \
        (string replace -a '"' '\\"' -- "$argv") \
        $exit_code (date +%s) (hostname -s) "$USER" \
        > $__prompt_enhancer_state_file
end
'''


class ShellHookBackend(TerminalBackend):
    """Universal backend using shell precmd/preexec hooks.

    Reads state from a JSON file written by the shell hook, plus shell history.
    """

    name = "shell_hook"

    def __init__(self, screen_buffer_lines: int = 100, shell_pid: int | None = None):
        super().__init__(screen_buffer_lines)
        self._shell_pid = shell_pid

    def is_available(self) -> bool:
        """Available if any state files exist."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if self._shell_pid:
            return (STATE_DIR / STATE_FILE_PATTERN.format(pid=self._shell_pid)).exists()
        return any(STATE_DIR.glob("state-*.json"))

    async def snapshot(self) -> TerminalState:
        state_file = self._find_state_file()
        if not state_file:
            logger.debug("No shell hook state file found")
            return TerminalState(backend=self.name)

        try:
            data = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Failed to read state file: %s", e)
            return TerminalState(backend=self.name)

        cwd = data.get("cwd", "")
        shell = data.get("shell", "")
        last_cmd = data.get("last_command", "")
        exit_code = data.get("exit_code")

        # Build last commands from state file + history
        commands = []
        if last_cmd:
            commands.append(
                CommandRecord(
                    command=last_cmd,
                    exit_code=exit_code,
                    working_directory=cwd,
                    timestamp=str(data.get("timestamp", "")),
                )
            )
        # Supplement with shell history
        history = _read_shell_history(shell, max_commands=5)
        seen = {last_cmd} if last_cmd else set()
        for cmd in reversed(history):
            if cmd.command not in seen:
                commands.append(cmd)
                seen.add(cmd.command)
            if len(commands) >= 5:
                break

        git_branch = await self._detect_git_branch(cwd)

        return TerminalState(
            cwd=cwd,
            shell=shell,
            last_commands=commands,
            git_branch=git_branch,
            hostname=data.get("hostname"),
            username=data.get("username"),
            session_id=f"pid:{data.get('pid', '')}",
            backend=self.name,
        )

    def _find_state_file(self) -> Path | None:
        """Find the most recent state file."""
        if self._shell_pid:
            f = STATE_DIR / STATE_FILE_PATTERN.format(pid=self._shell_pid)
            return f if f.exists() else None

        # Find the most recently modified state file
        state_files = list(STATE_DIR.glob("state-*.json"))
        if not state_files:
            return None
        return max(state_files, key=lambda p: p.stat().st_mtime)

    @staticmethod
    def get_hook_script(shell: str = "") -> str:
        """Return the appropriate shell hook script for installation."""
        shell_name = Path(shell or os.environ.get("SHELL", "zsh")).name
        if "fish" in shell_name:
            return SHELL_HOOK_FISH
        elif "bash" in shell_name:
            return SHELL_HOOK_BASH
        return SHELL_HOOK_ZSH

    @staticmethod
    def install_hook(shell: str = "") -> Path:
        """Install the shell hook to the user's shell config."""
        shell_name = Path(shell or os.environ.get("SHELL", "zsh")).name

        if "fish" in shell_name:
            hook_dir = Path.home() / ".config" / "fish" / "conf.d"
            hook_dir.mkdir(parents=True, exist_ok=True)
            hook_file = hook_dir / "prompt_enhancer.fish"
            hook_file.write_text(SHELL_HOOK_FISH)
        elif "bash" in shell_name:
            hook_file = Path.home() / ".prompt-enhancer" / "hook.bash"
            hook_file.parent.mkdir(parents=True, exist_ok=True)
            hook_file.write_text(SHELL_HOOK_BASH)
            # Add source line to .bashrc if not present
            bashrc = Path.home() / ".bashrc"
            source_line = f'[ -f "{hook_file}" ] && source "{hook_file}"'
            if bashrc.exists() and source_line not in bashrc.read_text():
                with open(bashrc, "a") as f:
                    f.write(f"\n{source_line}\n")
        else:
            # zsh
            hook_file = Path.home() / ".prompt-enhancer" / "hook.zsh"
            hook_file.parent.mkdir(parents=True, exist_ok=True)
            hook_file.write_text(SHELL_HOOK_ZSH)
            # Add source line to .zshrc if not present
            zshrc = Path.home() / ".zshrc"
            source_line = f'[ -f "{hook_file}" ] && source "{hook_file}"'
            if zshrc.exists() and source_line not in zshrc.read_text():
                with open(zshrc, "a") as f:
                    f.write(f"\n{source_line}\n")

        logger.info("Shell hook installed at %s", hook_file)
        return hook_file


# ---------------------------------------------------------------------------
# Backend: tmux
# ---------------------------------------------------------------------------

class TmuxBackend(TerminalBackend):
    """Backend for tmux users — capture-pane, display-message, etc."""

    name = "tmux"

    def is_available(self) -> bool:
        return bool(os.environ.get("TMUX")) and shutil.which("tmux") is not None

    async def snapshot(self) -> TerminalState:
        loop = asyncio.get_event_loop()

        # Run tmux commands in parallel
        capture_task = loop.run_in_executor(None, self._tmux_capture_pane)
        info_task = loop.run_in_executor(None, self._tmux_session_info)
        history_task = loop.run_in_executor(None, lambda: _read_shell_history(max_commands=5))

        screen_buffer, info, history = await asyncio.gather(
            capture_task, info_task, history_task, return_exceptions=True
        )

        if isinstance(screen_buffer, Exception):
            screen_buffer = ""
        if isinstance(info, Exception):
            info = {}
        if isinstance(history, Exception):
            history = []

        cwd = info.get("pane_current_path", "")
        shell = os.environ.get("SHELL", "")

        # Build command list from history
        commands = list(history) if isinstance(history, list) else []

        git_branch = await self._detect_git_branch(cwd)

        return TerminalState(
            screen_buffer=screen_buffer,
            cwd=cwd,
            shell=shell,
            last_commands=commands,
            running_process=info.get("pane_current_command"),
            git_branch=git_branch,
            hostname=platform.node(),
            username=os.environ.get("USER"),
            session_id=f"tmux:{info.get('session_name', '')}:{info.get('pane_id', '')}",
            backend=self.name,
        )

    def _tmux_capture_pane(self) -> str:
        """Capture the visible pane content."""
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-S", f"-{self._buffer_lines}"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.rstrip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _tmux_session_info(self) -> dict:
        """Get session metadata via tmux display-message."""
        info = {}
        format_vars = {
            "session_name": "#{session_name}",
            "pane_id": "#{pane_id}",
            "pane_current_path": "#{pane_current_path}",
            "pane_current_command": "#{pane_current_command}",
            "pane_pid": "#{pane_pid}",
        }
        for key, fmt in format_vars.items():
            try:
                result = subprocess.run(
                    ["tmux", "display-message", "-p", fmt],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    info[key] = result.stdout.strip()
            except Exception:
                pass
        return info


# ---------------------------------------------------------------------------
# Backend: iTerm2 (macOS only, optional)
# ---------------------------------------------------------------------------

class ITerm2Backend(TerminalBackend):
    """macOS iTerm2 backend using the iTerm2 Python API."""

    name = "iterm2"

    def is_available(self) -> bool:
        if platform.system() != "Darwin":
            return False
        try:
            import iterm2  # noqa: F401
            return True
        except ImportError:
            return False

    async def snapshot(self) -> TerminalState:
        import iterm2

        state = TerminalState(backend=self.name)

        async def _capture(connection: iterm2.Connection):
            nonlocal state
            app = await iterm2.async_get_app(connection)
            window = app.current_terminal_window
            if not window:
                logger.warning("No active iTerm2 window")
                return

            session = window.current_tab.current_session
            if not session:
                logger.warning("No active iTerm2 session")
                return

            # Gather data concurrently
            screen_task = session.async_get_screen_contents()
            var_tasks = {
                "cwd": session.async_get_variable("path"),
                "shell": session.async_get_variable("shell"),
                "job": session.async_get_variable("jobName"),
                "hostname": session.async_get_variable("hostname"),
                "username": session.async_get_variable("username"),
            }

            screen_contents, *var_values = await asyncio.gather(
                screen_task, *var_tasks.values(), return_exceptions=True
            )

            vars_resolved = {}
            for key, val in zip(var_tasks.keys(), var_values):
                vars_resolved[key] = val if not isinstance(val, Exception) else None

            # Screen buffer
            buffer_lines: list[str] = []
            if not isinstance(screen_contents, Exception):
                for i in range(screen_contents.number_of_lines):
                    try:
                        line = screen_contents.line(i)
                        buffer_lines.append(line.string)
                    except Exception:
                        break
            buffer_lines = buffer_lines[-self._buffer_lines:]

            # Command history via prompt marks
            commands: list[CommandRecord] = []
            try:
                prompt = await iterm2.async_get_last_prompt(connection, session.session_id)
                if prompt and prompt.command:
                    commands.append(
                        CommandRecord(
                            command=prompt.command,
                            exit_code=prompt.status,
                            working_directory=prompt.working_directory,
                        )
                    )
            except Exception:
                logger.debug("Could not get prompt marks (shell integration may be off)")

            # Supplement with shell history
            cwd = vars_resolved.get("cwd") or ""
            shell = vars_resolved.get("shell") or ""
            history = _read_shell_history(shell, max_commands=5)
            seen = {c.command for c in commands}
            for cmd in reversed(history):
                if cmd.command not in seen:
                    commands.append(cmd)
                    seen.add(cmd.command)
                if len(commands) >= 5:
                    break

            git_branch = await self._detect_git_branch(cwd)

            state = TerminalState(
                screen_buffer="\n".join(buffer_lines),
                cwd=cwd,
                shell=shell,
                last_commands=commands,
                running_process=vars_resolved.get("job"),
                git_branch=git_branch,
                hostname=vars_resolved.get("hostname"),
                username=vars_resolved.get("username"),
                session_id=session.session_id,
                backend=self.name,
            )

        try:
            iterm2.run_until_complete(_capture)
        except Exception as e:
            logger.warning("iTerm2 connection failed: %s", e)

        return state


# ---------------------------------------------------------------------------
# Backend: Generic (fallback — shell history + CWD detection)
# ---------------------------------------------------------------------------

class GenericBackend(TerminalBackend):
    """Fallback backend — reads shell history, detects CWD via /proc or lsof."""

    name = "generic"

    def is_available(self) -> bool:
        return True  # Always available as fallback

    async def snapshot(self) -> TerminalState:
        loop = asyncio.get_event_loop()

        shell = os.environ.get("SHELL", "")
        cwd = os.getcwd()

        # Read shell history
        history = await loop.run_in_executor(
            None, lambda: _read_shell_history(shell, max_commands=10)
        )

        # Try to detect parent shell's CWD (the terminal session that launched us)
        ppid = os.getppid()
        parent_cwd = await loop.run_in_executor(None, lambda: self._get_process_cwd(ppid))
        if parent_cwd:
            cwd = parent_cwd

        git_branch = await self._detect_git_branch(cwd)

        return TerminalState(
            cwd=cwd,
            shell=shell,
            last_commands=history[-5:],
            git_branch=git_branch,
            hostname=platform.node(),
            username=os.environ.get("USER"),
            session_id=f"pid:{ppid}",
            backend=self.name,
        )

    @staticmethod
    def _get_process_cwd(pid: int) -> str | None:
        """Get the CWD of a process. Uses /proc on Linux, lsof on macOS."""
        system = platform.system()

        if system == "Linux":
            proc_cwd = Path(f"/proc/{pid}/cwd")
            try:
                return str(proc_cwd.resolve())
            except (OSError, PermissionError):
                pass

        elif system == "Darwin":
            try:
                result = subprocess.run(
                    ["lsof", "-p", str(pid), "-Fn"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if line.startswith("n") and line.startswith("n/"):
                            # lsof output: "n/path/to/cwd"
                            path = line[1:]
                            if Path(path).is_dir():
                                return path
            except Exception:
                pass

        return None


# ---------------------------------------------------------------------------
# Auto-detection and factory
# ---------------------------------------------------------------------------

def detect_backend(screen_buffer_lines: int = 100) -> TerminalBackend:
    """Auto-detect the best available terminal backend.

    Priority order:
    1. tmux (if inside a tmux session — gives us screen buffer)
    2. iterm2 (if on macOS with iTerm2 API available — gives screen buffer)
    3. shell_hook (if hook state files exist — gives command/CWD data)
    4. generic (always available — reads shell history)
    """
    candidates: list[TerminalBackend] = [
        TmuxBackend(screen_buffer_lines),
        ITerm2Backend(screen_buffer_lines),
        ShellHookBackend(screen_buffer_lines),
        GenericBackend(screen_buffer_lines),
    ]

    for backend in candidates:
        if backend.is_available():
            logger.info("Auto-detected terminal backend: %s", backend.name)
            return backend

    # Should never reach here since GenericBackend is always available
    return GenericBackend(screen_buffer_lines)


def create_backend(
    backend_type: BackendType = "auto",
    screen_buffer_lines: int = 100,
    **kwargs,
) -> TerminalBackend:
    """Factory: create a specific backend or auto-detect."""
    if backend_type == "auto":
        return detect_backend(screen_buffer_lines)

    backends = {
        "tmux": TmuxBackend,
        "iterm2": ITerm2Backend,
        "shell_hook": ShellHookBackend,
        "generic": GenericBackend,
    }

    cls = backends.get(backend_type)
    if not cls:
        raise ValueError(f"Unknown backend: {backend_type}. Options: {list(backends)}")

    backend = cls(screen_buffer_lines, **kwargs)
    if not backend.is_available():
        logger.warning(
            "Backend '%s' is not available, falling back to auto-detect", backend_type
        )
        return detect_backend(screen_buffer_lines)

    return backend
