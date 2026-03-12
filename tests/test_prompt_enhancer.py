"""Tests for the prompt builder templates."""

from prompt_enhancer.enhancer.prompt_builder import (
    build_fallback_prompt,
    build_meta_prompt,
)
from prompt_enhancer.terminal.context import ContextPayload


def _make_summary(**overrides):
    """Helper to build a summary dict."""
    defaults = {
        "voice_transcript": "fix the error",
        "cwd": "/home/user/project",
        "shell": "/bin/zsh",
        "git_branch": "main",
        "running_process": None,
        "last_commands": "$ npm run build (exit 1)",
        "detected_errors": "typescript_compilation TS2345 at src/app.ts:10 — type mismatch",
        "screen_buffer_last_50": "error TS2345: type mismatch",
        "project_type": "typescript",
        "project_name": "my-project",
    }
    defaults.update(overrides)
    return defaults


def test_meta_prompt_contains_voice_transcript():
    summary = _make_summary()
    prompt = build_meta_prompt(ContextPayload(), summary)
    assert "fix the error" in prompt
    assert "TS2345" in prompt
    assert "/home/user/project" in prompt


def test_meta_prompt_contains_context():
    summary = _make_summary(
        cwd="/app/backend",
        git_branch="feature/auth",
        project_type="python",
    )
    prompt = build_meta_prompt(ContextPayload(), summary)
    assert "/app/backend" in prompt
    assert "feature/auth" in prompt
    assert "python" in prompt


def test_fallback_prompt():
    summary = _make_summary()
    fallback = build_fallback_prompt(summary)
    assert "fix the error" in fallback
    assert "/home/user/project" in fallback
    assert "TS2345" in fallback


def test_fallback_prompt_no_errors():
    summary = _make_summary(detected_errors="none detected")
    fallback = build_fallback_prompt(summary)
    assert "none detected" in fallback
