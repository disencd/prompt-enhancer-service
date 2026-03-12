"""iTerm2 paste delivery — inject enhanced prompt directly into a session.

This module is optional and only works on macOS with iTerm2 installed.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def deliver_to_iterm(
    text: str,
    session_id: str | None = None,
) -> bool:
    """Paste text into an iTerm2 session.

    If session_id is None, uses the currently active session.
    Returns False if iTerm2 is not available.
    """
    try:
        import iterm2
    except ImportError:
        logger.error("iterm2 package not installed — cannot paste to iTerm2")
        return False

    try:
        delivered = False

        async def _paste(connection: iterm2.Connection):
            nonlocal delivered
            app = await iterm2.async_get_app(connection)

            if session_id:
                session = app.get_session_by_id(session_id)
            else:
                window = app.current_terminal_window
                if not window:
                    logger.error("No active iTerm2 window")
                    return
                session = window.current_tab.current_session

            if not session:
                logger.error("No iTerm2 session found")
                return

            await session.async_send_text(text)
            logger.info("Enhanced prompt pasted into iTerm2 session %s", session.session_id)
            delivered = True

        iterm2.run_until_complete(_paste)
        return delivered

    except Exception:
        logger.exception("Failed to paste into iTerm2")
        return False
