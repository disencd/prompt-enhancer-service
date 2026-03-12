"""Meta-prompt template engine — constructs the LLM prompt from context."""

from __future__ import annotations

from prompt_enhancer.terminal.context import ContextPayload

META_PROMPT_TEMPLATE = """\
You are a prompt engineer specializing in developer productivity. Given a user's raw \
voice command and their terminal context, rewrite the command into a precise, actionable \
prompt suitable for an AI coding assistant.

Rules:
1. Include specific file paths, error codes, and line numbers from the terminal context
2. Reference the exact error messages visible in the terminal output
3. Mention the current working directory and project type
4. Keep the enhanced prompt concise but complete (max ~200 words)
5. Preserve the user's original intent — do NOT add new tasks they didn't request
6. If the terminal shows a specific technology stack, mention it
7. If there are no errors, focus on the CWD, recent commands, and the user's request
8. Write in second person ("Fix the..." not "The user wants...")

---

RAW VOICE COMMAND:
{voice_transcript}

---

TERMINAL CONTEXT:
- Working directory: {cwd}
- Project type: {project_type} ({project_name})
- Git branch: {git_branch}
- Shell: {shell}
- Running process: {running_process}

Recent commands:
{last_commands}

Detected errors:
{detected_errors}

Terminal output (last 50 lines):
```
{screen_buffer_last_50}
```

---

OUTPUT: Write ONLY the enhanced prompt. No explanation, no preamble."""


def build_meta_prompt(context: ContextPayload, summary: dict) -> str:
    """Render the meta-prompt template with context data."""
    return META_PROMPT_TEMPLATE.format(**summary)


def build_context_only_prompt(summary: dict) -> str:
    """Build a prompt when there's no voice input — enhance clipboard text."""
    merged = {
        **summary,
        "voice_transcript": summary.get("voice_transcript", "(from clipboard)"),
    }
    return META_PROMPT_TEMPLATE.format(**merged)


# Simplified fallback template for when LLM is unavailable
FALLBACK_TEMPLATE = """\
{voice_transcript}

Context:
- CWD: {cwd}
- Branch: {git_branch}
- Last commands: {last_commands}
- Errors: {detected_errors}"""


def build_fallback_prompt(summary: dict) -> str:
    """Build a template-based enhanced prompt without LLM (fallback)."""
    return FALLBACK_TEMPLATE.format(**summary).strip()
