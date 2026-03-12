"""Context builder — aggregates terminal state, voice transcript, and error analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from prompt_pulse.terminal.error_patterns import DetectedError, ErrorDetectionEngine
from prompt_pulse.terminal.monitor import TerminalState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectInfo:
    """Detected project metadata from the working directory."""

    project_type: str | None = None  # nodejs, python, rust, go, etc.
    project_name: str | None = None
    config_file: str | None = None


@dataclass(frozen=True)
class ContextPayload:
    """Complete context payload sent to the prompt enhancement engine."""

    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    voice_transcript: str = ""
    terminal: TerminalState = field(default_factory=TerminalState)
    detected_errors: list[DetectedError] = field(default_factory=list)
    project: ProjectInfo = field(default_factory=ProjectInfo)


# Project type detection rules: (marker_file, project_type)
_PROJECT_MARKERS: list[tuple[str, str, str]] = [
    ("package.json", "nodejs", "package.json"),
    ("tsconfig.json", "typescript", "tsconfig.json"),
    ("Cargo.toml", "rust", "Cargo.toml"),
    ("go.mod", "go", "go.mod"),
    ("pyproject.toml", "python", "pyproject.toml"),
    ("setup.py", "python", "setup.py"),
    ("requirements.txt", "python", "requirements.txt"),
    ("Gemfile", "ruby", "Gemfile"),
    ("pom.xml", "java", "pom.xml"),
    ("build.gradle", "java", "build.gradle"),
    ("Makefile", "make", "Makefile"),
    ("CMakeLists.txt", "cpp", "CMakeLists.txt"),
    ("docker-compose.yml", "docker", "docker-compose.yml"),
    ("Dockerfile", "docker", "Dockerfile"),
    ("terraform.tf", "terraform", "terraform.tf"),
]


def detect_project(cwd: str) -> ProjectInfo:
    """Detect project type from the current working directory."""
    if not cwd:
        return ProjectInfo()

    path = Path(cwd)
    # Check current dir and walk up
    for check_dir in [path, *path.parents]:
        for marker_file, project_type, config_file in _PROJECT_MARKERS:
            if (check_dir / marker_file).exists():
                return ProjectInfo(
                    project_type=project_type,
                    project_name=check_dir.name,
                    config_file=str(check_dir / config_file),
                )
        # Don't go above home directory
        if check_dir == Path.home():
            break

    return ProjectInfo()


class ContextBuilder:
    """Builds a complete ContextPayload from terminal state and voice input."""

    def __init__(self, extra_error_patterns: list[dict] | None = None):
        self._error_engine = ErrorDetectionEngine(extra_patterns=extra_error_patterns)

    def build(
        self,
        terminal_state: TerminalState,
        voice_transcript: str = "",
    ) -> ContextPayload:
        """Aggregate terminal data, detect errors, and build context payload."""
        # Detect errors in screen buffer
        detected_errors = self._error_engine.detect(terminal_state.screen_buffer)

        # Also check last command output for errors
        for cmd in terminal_state.last_commands:
            if cmd.exit_code and cmd.exit_code != 0:
                logger.debug("Command '%s' exited with code %d", cmd.command, cmd.exit_code)

        # Detect project type
        project = detect_project(terminal_state.cwd)

        return ContextPayload(
            voice_transcript=voice_transcript,
            terminal=terminal_state,
            detected_errors=detected_errors,
            project=project,
        )

    def build_summary(self, context: ContextPayload) -> dict:
        """Build a human-readable summary dict for template rendering."""
        error_summaries = []
        for e in context.detected_errors:
            parts = [e.error_type]
            if e.code:
                parts.append(e.code)
            if e.file:
                loc = e.file
                if e.line:
                    loc += f":{e.line}"
                parts.append(f"at {loc}")
            if e.message:
                parts.append(f"— {e.message}")
            error_summaries.append(" ".join(parts))

        cmd_summaries = []
        for cmd in context.terminal.last_commands:
            status = f"(exit {cmd.exit_code})" if cmd.exit_code is not None else ""
            cmd_summaries.append(f"$ {cmd.command} {status}".strip())

        return {
            "voice_transcript": context.voice_transcript,
            "cwd": context.terminal.cwd,
            "shell": context.terminal.shell,
            "git_branch": context.terminal.git_branch or "unknown",
            "running_process": context.terminal.running_process,
            "last_commands": "\n".join(cmd_summaries) or "none",
            "screen_buffer_last_50": "\n".join(context.terminal.screen_buffer.split("\n")[-50:]),
            "detected_errors": "\n".join(error_summaries) or "none detected",
            "project_type": context.project.project_type or "unknown",
            "project_name": context.project.project_name or "unknown",
        }
