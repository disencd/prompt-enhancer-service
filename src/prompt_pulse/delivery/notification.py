"""Cross-platform notification delivery.

- macOS: osascript (AppleScript)
- Linux: notify-send (libnotify)
- Fallback: console print
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess

logger = logging.getLogger(__name__)


async def show_notification(
    title: str,
    message: str,
    subtitle: str | None = None,
    sound: bool = True,
) -> bool:
    """Show a desktop notification (cross-platform)."""
    system = platform.system()

    if system == "Darwin":
        return _notify_macos(title, message, subtitle, sound)
    elif system == "Linux":
        return _notify_linux(title, message, subtitle)
    else:
        # Fallback: just log it
        logger.info("Notification: %s — %s", title, message)
        return True


def _notify_macos(title: str, message: str, subtitle: str | None, sound: bool) -> bool:
    """macOS notification via osascript."""
    try:
        title_esc = title.replace('"', '\\"')
        message_esc = message.replace('"', '\\"')

        script = f'display notification "{message_esc}" with title "{title_esc}"'
        if subtitle:
            subtitle_esc = subtitle.replace('"', '\\"')
            script = (
                f'display notification "{message_esc}" '
                f'with title "{title_esc}" '
                f'subtitle "{subtitle_esc}"'
            )
        if sound:
            script += ' sound name "Glass"'

        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
        logger.debug("macOS notification shown: %s", title)
        return True

    except subprocess.TimeoutExpired:
        logger.warning("macOS notification timed out")
        return False
    except FileNotFoundError:
        logger.warning("osascript not available")
        return False
    except Exception:
        logger.exception("Failed to show macOS notification")
        return False


def _notify_linux(title: str, message: str, subtitle: str | None) -> bool:
    """Linux notification via notify-send (libnotify)."""
    if not shutil.which("notify-send"):
        logger.debug("notify-send not available, skipping notification")
        return False

    try:
        body = message
        if subtitle:
            body = f"{subtitle}\n{message}"

        subprocess.run(
            [
                "notify-send",
                "--app-name=PromptPulse",
                "--expire-time=5000",
                title,
                body,
            ],
            capture_output=True,
            timeout=5,
        )
        logger.debug("Linux notification shown: %s", title)
        return True

    except subprocess.TimeoutExpired:
        logger.warning("notify-send timed out")
        return False
    except Exception:
        logger.exception("Failed to show Linux notification")
        return False


async def notify_enhanced_prompt(enhanced_prompt: str, preview_chars: int = 100) -> bool:
    """Show a notification that the prompt has been enhanced."""
    preview = enhanced_prompt[:preview_chars]
    if len(enhanced_prompt) > preview_chars:
        preview += "..."

    return await show_notification(
        title="Prompt Enhanced",
        subtitle="Copied to clipboard",
        message=preview,
    )


async def notify_error(error_message: str) -> bool:
    """Show an error notification."""
    return await show_notification(
        title="PromptPulse",
        subtitle="Error",
        message=error_message,
        sound=True,
    )


async def notify_fallback(error_message: str) -> bool:
    """Notify the user that the LLM failed and a fallback was used."""
    return await show_notification(
        title="PromptPulse",
        subtitle="LLM unavailable — used template fallback",
        message=error_message,
        sound=True,
    )


async def notify_listening() -> bool:
    """Show a notification that the service is listening."""
    return await show_notification(
        title="PromptPulse",
        message="Listening... speak now",
        sound=False,
    )
