"""Main entry point — CLI, hotkey system, and pipeline orchestrator."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

from prompt_pulse.config import AppConfig, init_config_dir, load_config

app = typer.Typer(
    name="prompt-pulse",
    help="Voice-activated terminal-aware prompt enhancer for AI coding assistants.",
    no_args_is_help=True,
)
console = Console()

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


async def run_pipeline(
    config: AppConfig,
    voice: bool = True,
    clipboard_input: bool = False,
) -> str | None:
    """Execute the full enhancement pipeline.

    1. Capture terminal context (auto-detects backend)
    2. Capture voice input (or read clipboard)
    3. Build context payload
    4. Enhance prompt via LLM
    5. Deliver result
    """
    from prompt_pulse.delivery.clipboard import deliver_to_clipboard, read_from_clipboard
    from prompt_pulse.delivery.notification import (
        notify_enhanced_prompt,
        notify_error,
        notify_fallback,
        notify_listening,
    )
    from prompt_pulse.enhancer.llm_client import enhance_prompt
    from prompt_pulse.enhancer.prompt_builder import (
        build_fallback_prompt,
        build_meta_prompt,
    )
    from prompt_pulse.terminal.context import ContextBuilder
    from prompt_pulse.terminal.monitor import TerminalState, create_backend
    from prompt_pulse.voice.capture import VoiceCapture
    from prompt_pulse.voice.transcribe import create_engine

    logger = logging.getLogger(__name__)

    # --- Step 1: Terminal context ---
    terminal_state = TerminalState()
    try:
        backend = create_backend(
            backend_type=config.terminal.backend,
            screen_buffer_lines=config.terminal.screen_buffer_lines,
        )
        console.print(f"[dim]Terminal backend: {backend.name}[/]")
        terminal_state = await backend.snapshot()
    except Exception as e:
        logger.warning("Terminal context capture failed: %s (continuing without it)", e)

    # --- Step 2: Voice / clipboard input ---
    transcript = ""
    if voice:
        await notify_listening()
        capture = VoiceCapture(
            silence_threshold_sec=config.voice.silence_threshold_sec,
            max_duration_sec=config.voice.max_duration_sec,
            vad_aggressiveness=config.voice.vad_aggressiveness,
        )
        console.print("[bold cyan]Listening...[/] Speak now (press Ctrl+C to cancel)")
        wav_bytes = await capture.capture()

        if wav_bytes:
            console.print("[dim]Transcribing...[/]")
            engine = create_engine(
                engine_type=config.voice.engine,
                model_size=config.voice.whisper_model,
                api_key=config.llm.resolve_api_key(),
            )
            result = await engine.transcribe(wav_bytes)
            transcript = result.text
            console.print(f"[green]Heard:[/] {transcript}")
        else:
            console.print("[yellow]No speech detected.[/]")
            await notify_error("No speech detected")
            return None
    elif clipboard_input:
        transcript = await read_from_clipboard()
        if not transcript.strip():
            console.print("[yellow]Clipboard is empty.[/]")
            return None
        console.print(f"[green]Clipboard:[/] {transcript[:80]}...")

    # --- Step 3: Build context ---
    builder = ContextBuilder()
    context = builder.build(terminal_state, voice_transcript=transcript)
    summary = builder.build_summary(context)

    # --- Step 4: Enhance via LLM ---
    console.print("[dim]Enhancing prompt...[/]")
    meta_prompt = build_meta_prompt(context, summary)
    fallback = build_fallback_prompt(summary)

    try:
        result = await enhance_prompt(meta_prompt, config.llm, fallback_text=fallback)
        enhanced = result.text
        if result.used_fallback:
            console.print(f"[yellow]LLM unavailable ({result.error}), using template fallback.[/]")
            await notify_fallback(result.error or "unknown error")
    except Exception:
        logger.warning("LLM unavailable, using template fallback")
        enhanced = fallback

    # --- Step 5: Deliver ---
    console.print(Panel(enhanced, title="Enhanced Prompt", border_style="green"))

    if config.delivery.method == "clipboard":
        await deliver_to_clipboard(enhanced)

    if config.delivery.show_notification:
        await notify_enhanced_prompt(
            enhanced, preview_chars=config.delivery.notification_preview_chars
        )

    return enhanced


# ---------------------------------------------------------------------------
# Hotkey Daemon
# ---------------------------------------------------------------------------


async def run_hotkey_daemon(config: AppConfig) -> None:
    """Start the global hotkey listener daemon."""
    from pynput import keyboard

    logger = logging.getLogger(__name__)
    console.print("[bold green]PromptPulse started[/]")
    console.print(f"  Backend:      {config.terminal.backend}")
    console.print(f"  Activate:     {config.hotkeys.activate}")
    console.print(f"  Context only: {config.hotkeys.context_only}")
    console.print(f"  Re-enhance:   {config.hotkeys.re_enhance}")
    console.print(f"  Cancel:       {config.hotkeys.cancel}")
    console.print()
    console.print("[dim]Press Ctrl+C to stop.[/]")

    loop = asyncio.get_event_loop()
    pipeline_task: asyncio.Task | None = None

    def _parse_hotkey(hotkey_str: str):
        """Parse a hotkey string like 'ctrl+shift+p' into pynput format."""
        parts = hotkey_str.lower().split("+")
        combo = set()
        for part in parts:
            part = part.strip()
            if part in ("ctrl", "control"):
                combo.add(keyboard.Key.ctrl)
            elif part in ("shift",):
                combo.add(keyboard.Key.shift)
            elif part in ("alt", "option"):
                combo.add(keyboard.Key.alt)
            elif part in ("cmd", "command", "super"):
                combo.add(keyboard.Key.cmd)
            elif part == "escape":
                combo.add(keyboard.Key.esc)
            elif len(part) == 1:
                combo.add(keyboard.KeyCode.from_char(part))
            else:
                logger.warning("Unknown key in hotkey: %s", part)
        return frozenset(combo)

    activate_combo = _parse_hotkey(config.hotkeys.activate)
    context_combo = _parse_hotkey(config.hotkeys.context_only)
    cancel_combo = _parse_hotkey(config.hotkeys.cancel)

    current_keys: set = set()

    def on_press(key):
        nonlocal pipeline_task
        current_keys.add(key)

        pressed = frozenset(current_keys)

        if activate_combo.issubset(pressed):
            logger.info("Hotkey: activate")
            if pipeline_task is None or pipeline_task.done():
                pipeline_task = asyncio.run_coroutine_threadsafe(
                    run_pipeline(config, voice=True), loop
                )

        elif context_combo.issubset(pressed):
            logger.info("Hotkey: context_only")
            if pipeline_task is None or pipeline_task.done():
                pipeline_task = asyncio.run_coroutine_threadsafe(
                    run_pipeline(config, voice=False, clipboard_input=True), loop
                )

        elif cancel_combo.issubset(pressed):
            logger.info("Hotkey: cancel")

    def on_release(key):
        current_keys.discard(key)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        listener.stop()


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------


@app.command()
def start(
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
):
    """Start the PromptPulse daemon with global hotkeys."""
    _setup_logging(verbose)
    config = load_config(config_file)
    try:
        asyncio.run(run_hotkey_daemon(config))
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")


@app.command()
def enhance(
    text: str | None = typer.Argument(None, help="Text to enhance (or omit for voice)"),
    config_file: Path | None = typer.Option(None, "--config", "-c"),
    voice: bool = typer.Option(False, "--voice", help="Use voice input"),
    clipboard: bool = typer.Option(False, "--clipboard", help="Enhance clipboard contents"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run a single enhancement (no daemon)."""
    _setup_logging(verbose)
    config = load_config(config_file)

    if text:
        # Direct text enhancement
        async def _run():
            from prompt_pulse.delivery.clipboard import deliver_to_clipboard
            from prompt_pulse.enhancer.llm_client import enhance_prompt as do_enhance
            from prompt_pulse.enhancer.prompt_builder import (
                build_fallback_prompt,
                build_meta_prompt,
            )
            from prompt_pulse.terminal.context import ContextBuilder
            from prompt_pulse.terminal.monitor import TerminalState, create_backend

            # Try to get terminal context even in text mode
            terminal_state = TerminalState()
            try:
                backend = create_backend(
                    backend_type=config.terminal.backend,
                    screen_buffer_lines=config.terminal.screen_buffer_lines,
                )
                terminal_state = await backend.snapshot()
            except Exception:
                pass

            builder = ContextBuilder()
            ctx = builder.build(terminal_state, voice_transcript=text)
            summary = builder.build_summary(ctx)
            meta = build_meta_prompt(ctx, summary)
            fallback = build_fallback_prompt(summary)

            try:
                res = await do_enhance(meta, config.llm, fallback_text=fallback)
                enhanced = res.text
                if res.used_fallback:
                    console.print(
                        f"[yellow]LLM unavailable ({res.error}), using template fallback.[/]"
                    )
            except Exception:
                enhanced = fallback

            console.print(Panel(enhanced, title="Enhanced Prompt", border_style="green"))
            await deliver_to_clipboard(enhanced)

        asyncio.run(_run())
    elif voice:
        asyncio.run(run_pipeline(config, voice=True))
    elif clipboard:
        asyncio.run(run_pipeline(config, voice=False, clipboard_input=True))
    else:
        console.print("[yellow]Provide text, --voice, or --clipboard[/]")
        raise typer.Exit(1)


@app.command()
def context(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of screen buffer lines"),
    backend: str = typer.Option("auto", "--backend", "-b", help="Terminal backend"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Capture and display current terminal context (no enhancement)."""
    _setup_logging(verbose)

    async def _run():
        from prompt_pulse.terminal.context import ContextBuilder
        from prompt_pulse.terminal.monitor import create_backend

        try:
            be = create_backend(backend_type=backend, screen_buffer_lines=lines)
            console.print(f"[dim]Using backend: {be.name}[/]")
            state = await be.snapshot()
        except Exception as e:
            console.print(f"[red]Failed to capture terminal context:[/] {e}")
            raise typer.Exit(1)

        builder = ContextBuilder()
        ctx = builder.build(state)
        summary = builder.build_summary(ctx)

        console.print(
            Panel(
                "\n".join(
                    f"[cyan]{k}:[/] {v}" for k, v in summary.items() if k != "screen_buffer_last_50"
                ),
                title=f"Terminal Context (backend: {be.name})",
                border_style="blue",
            )
        )
        if state.screen_buffer:
            console.print(
                Panel(
                    state.screen_buffer[-2000:],
                    title="Screen Buffer (last lines)",
                    border_style="dim",
                )
            )
        if summary.get("detected_errors") != "none detected":
            console.print(
                Panel(
                    summary["detected_errors"],
                    title="Detected Errors",
                    border_style="red",
                )
            )

    asyncio.run(_run())


@app.command()
def install_hook(
    shell: str = typer.Option(
        "",
        "--shell",
        help="Shell type (zsh/bash/fish). Auto-detects if empty.",
    ),
):
    """Install the shell hook for terminal state capture.

    This adds a lightweight precmd/preexec hook to your shell that writes
    CWD, last command, and exit code to a state file. Works with any terminal.
    """
    from prompt_pulse.terminal.monitor import ShellHookBackend

    hook_file = ShellHookBackend.install_hook(shell)
    console.print(f"[green]Shell hook installed:[/] {hook_file}")
    console.print("[dim]Restart your shell or run:[/]")
    console.print(f"  source {hook_file}")


@app.command()
def init():
    """Initialize configuration directory (~/.prompt-pulse/)."""
    config_dir = init_config_dir()
    console.print(f"[green]Config directory initialized:[/] {config_dir}")
    console.print(f"[dim]Edit config at:[/] {config_dir / 'config.yaml'}")
    console.print()
    console.print("[dim]Recommended next step — install the shell hook:[/]")
    console.print("  prompt-pulse install-hook")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


if __name__ == "__main__":
    app()
