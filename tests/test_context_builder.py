"""Tests for the context builder."""

from prompt_pulse.terminal.context import ContextBuilder
from prompt_pulse.terminal.monitor import CommandRecord, TerminalState


def test_build_context_with_errors():
    state = TerminalState(
        screen_buffer="src/app.ts(10,1): error TS1005: ';' expected.\nnpm ERR! code 1",
        cwd="/tmp/test-project",
        shell="/bin/zsh",
        last_commands=[CommandRecord(command="npm run build", exit_code=1)],
    )
    builder = ContextBuilder()
    ctx = builder.build(state, voice_transcript="fix the build error")
    assert ctx.voice_transcript == "fix the build error"
    assert len(ctx.detected_errors) >= 1
    assert ctx.detected_errors[0].code == "TS1005"


def test_build_summary():
    state = TerminalState(
        screen_buffer="all tests passed",
        cwd="/home/user/project",
        shell="/bin/zsh",
        last_commands=[CommandRecord(command="pytest", exit_code=0)],
        git_branch="main",
    )
    builder = ContextBuilder()
    ctx = builder.build(state, voice_transcript="run the linter")
    summary = builder.build_summary(ctx)
    assert summary["voice_transcript"] == "run the linter"
    assert summary["cwd"] == "/home/user/project"
    assert summary["git_branch"] == "main"
    assert "$ pytest (exit 0)" in summary["last_commands"]
    assert summary["detected_errors"] == "none detected"


def test_empty_context():
    builder = ContextBuilder()
    ctx = builder.build(TerminalState())
    summary = builder.build_summary(ctx)
    assert summary["cwd"] == ""
    assert summary["detected_errors"] == "none detected"
