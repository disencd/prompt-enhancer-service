"""Regex-based error detection engine for terminal output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class DetectedError:
    """A single error extracted from terminal output."""

    error_type: str
    code: str | None = None
    file: str | None = None
    line: int | None = None
    column: int | None = None
    message: str = ""
    severity: str = "error"  # error | warning | info


@dataclass
class ErrorPattern:
    """A compiled regex pattern for detecting errors."""

    name: str
    regex: re.Pattern
    error_type: str
    extract_map: dict[str, str]  # group_name -> field_name

    def match(self, text: str) -> list[DetectedError]:
        errors = []
        for m in self.regex.finditer(text):
            groups = m.groupdict()
            line_num = groups.get("line")
            col_num = groups.get("column")
            errors.append(
                DetectedError(
                    error_type=self.error_type,
                    code=groups.get("code"),
                    file=groups.get("file"),
                    line=int(line_num) if line_num else None,
                    column=int(col_num) if col_num else None,
                    message=groups.get("message", m.group(0)).strip(),
                )
            )
        return errors


class ErrorDetectionEngine:
    """Runs a set of error patterns against terminal output."""

    BUILTIN_PATTERNS: ClassVar[list[dict]] = [
        # TypeScript / tsc
        {
            "name": "typescript",
            "regex": r"(?P<file>[^\s]+\.tsx?)\((?P<line>\d+),(?P<column>\d+)\):\s+error\s+(?P<code>TS\d+):\s+(?P<message>.+)",
            "error_type": "typescript_compilation",
        },
        # ESLint
        {
            "name": "eslint",
            "regex": r"(?P<file>[^\s]+)\s+(?P<line>\d+):(?P<column>\d+)\s+error\s+(?P<message>.+?)\s+(?P<code>\S+)$",
            "error_type": "eslint",
        },
        # Python traceback
        {
            "name": "python_traceback",
            "regex": r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<message>\S+))?',
            "error_type": "python_traceback",
        },
        # Python exception line (e.g., "ValueError: something went wrong")
        {
            "name": "python_exception",
            "regex": r"^(?P<code>[A-Z]\w*(?:Error|Exception|Warning)):\s+(?P<message>.+)",
            "error_type": "python_exception",
        },
        # Rust / cargo
        {
            "name": "rust",
            "regex": r"error\[(?P<code>E\d+)\]:\s+(?P<message>.+)\n\s+-->\s+(?P<file>[^:]+):(?P<line>\d+):(?P<column>\d+)",
            "error_type": "rust_compilation",
        },
        # Go compiler
        {
            "name": "go",
            "regex": r"(?P<file>[^\s]+\.go):(?P<line>\d+):(?P<column>\d+):\s+(?P<message>.+)",
            "error_type": "go_compilation",
        },
        # Node.js error with stack trace
        {
            "name": "nodejs",
            "regex": r"at\s+(?P<message>\S+)\s+\((?P<file>[^:]+):(?P<line>\d+):(?P<column>\d+)\)",
            "error_type": "nodejs_runtime",
        },
        # Jest / test failure
        {
            "name": "jest",
            "regex": r"●\s+(?P<message>.+)\n\n\s+expect\(",
            "error_type": "jest_test_failure",
        },
        # pytest failure
        {
            "name": "pytest",
            "regex": r"FAILED\s+(?P<file>[^\s:]+)::(?P<message>\S+)",
            "error_type": "pytest_failure",
        },
        # Generic "error:" pattern
        {
            "name": "generic_error",
            "regex": r"(?i)^(?:error|fatal):\s+(?P<message>.+)",
            "error_type": "generic",
        },
        # Git merge conflict
        {
            "name": "git_conflict",
            "regex": r"^(?:CONFLICT|error: Failed to merge)\s+.+?:\s+(?P<message>.+)",
            "error_type": "git_conflict",
        },
        # Permission denied
        {
            "name": "permission",
            "regex": r"(?:EACCES|Permission denied|Operation not permitted)(?:.*?:\s*(?P<message>.+))?",
            "error_type": "permission_error",
        },
    ]

    def __init__(self, extra_patterns: list[dict] | None = None):
        self._patterns: list[ErrorPattern] = []
        for p in self.BUILTIN_PATTERNS:
            self._add_pattern(p)
        for p in extra_patterns or []:
            self._add_pattern(p)

    def _add_pattern(self, spec: dict) -> None:
        """Compile and add a pattern from a dict spec."""
        try:
            compiled = re.compile(spec["regex"], re.MULTILINE)
        except re.error:
            logger_msg = f"Invalid regex in error pattern '{spec.get('name', '?')}'"
            import logging

            logging.getLogger(__name__).warning(logger_msg)
            return

        # Build extract map from named groups
        extract_map = {g: g for g in compiled.groupindex}
        self._patterns.append(
            ErrorPattern(
                name=spec["name"],
                regex=compiled,
                error_type=spec.get("error_type", spec["name"]),
                extract_map=extract_map,
            )
        )

    def detect(self, text: str) -> list[DetectedError]:
        """Run all patterns against the given text and return detected errors."""
        all_errors: list[DetectedError] = []
        seen: set[tuple] = set()
        for pattern in self._patterns:
            for error in pattern.match(text):
                key = (error.error_type, error.file, error.line, error.code)
                if key not in seen:
                    seen.add(key)
                    all_errors.append(error)
        return all_errors
