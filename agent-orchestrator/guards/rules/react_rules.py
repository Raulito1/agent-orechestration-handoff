"""React-specific convention guard rules.

Each rule is a pure function: (file_path: str, content: str) -> list[Violation].
Rules return an empty list if the file is not applicable to that rule.
"""
from __future__ import annotations

import re

from guards import Violation

# UIX primitives that are allowed to carry raw Tailwind classes
_UIX_PRIMITIVES = {"Stack", "Inline", "PageShell", "AsyncBoundary"}

# Tailwind utility patterns that signal raw Tailwind usage
_TAILWIND_PATTERNS = re.compile(
    r'\b(?:flex|grid|p-|m-|text-|bg-|border-|w-|h-|items-|justify-|gap-|rounded|shadow|overflow)'
)

# RTK Query hook patterns
_RTK_HOOK_PATTERN = re.compile(r'\buse(?:Get\w+Query|Post\w+Mutation|Put\w+Mutation|Delete\w+Mutation|Patch\w+Mutation)\b')


def _is_react_file(file_path: str) -> bool:
    return file_path.endswith(".tsx") or file_path.endswith(".jsx")


# ---------------------------------------------------------------------------
# WARNING rules
# ---------------------------------------------------------------------------


def check_no_raw_tailwind(file_path: str, content: str) -> list[Violation]:
    """Flag raw Tailwind utility classes outside UIX primitive components."""
    if not _is_react_file(file_path):
        return []

    violations: list[Violation] = []
    lines = content.splitlines()

    # Match className= on any JSX element
    class_name_pattern = re.compile(r'<(\w+)[^>]*\bclassName\s*=\s*["\'{`]([^"\'`>]*)["\'}]')

    for i, line in enumerate(lines, start=1):
        for match in class_name_pattern.finditer(line):
            element_name = match.group(1)
            class_value = match.group(2)

            # Allow className on UIX primitives
            if element_name in _UIX_PRIMITIVES:
                continue

            if _TAILWIND_PATTERNS.search(class_value):
                violations.append(
                    Violation(
                        rule_id="no-raw-tailwind",
                        severity="WARNING",
                        file_path=file_path,
                        line_number=i,
                        message=f"Raw Tailwind class found on <{element_name}> outside UIX primitive",
                        suggestion="Wrap in <Stack>, <Inline>, or use an existing UIX primitive instead",
                    )
                )

    return violations


def check_missing_async_boundary(file_path: str, content: str) -> list[Violation]:
    """Components using RTK Query hooks should contain an <AsyncBoundary>."""
    if not _is_react_file(file_path):
        return []

    if not _RTK_HOOK_PATTERN.search(content):
        return []

    if "<AsyncBoundary" in content:
        return []

    # Find the line of the first RTK hook usage
    for i, line in enumerate(content.splitlines(), start=1):
        if _RTK_HOOK_PATTERN.search(line):
            return [
                Violation(
                    rule_id="missing-async-boundary",
                    severity="WARNING",
                    file_path=file_path,
                    line_number=i,
                    message="Component uses RTK Query hook but has no <AsyncBoundary>",
                    suggestion="Wrap the data-dependent JSX in <AsyncBoundary> to handle loading/error states",
                )
            ]

    return []


def check_todo_fixme(file_path: str, content: str) -> list[Violation]:
    """Flag any TODO or FIXME comment in React files."""
    if not _is_react_file(file_path):
        return []

    violations: list[Violation] = []
    for i, line in enumerate(content.splitlines(), start=1):
        if re.search(r"(?://|/\*).*\b(TODO|FIXME)\b", line, re.IGNORECASE):
            violations.append(
                Violation(
                    rule_id="todo-fixme-in-new-code",
                    severity="WARNING",
                    file_path=file_path,
                    line_number=i,
                    message="TODO/FIXME comment found",
                    suggestion="Resolve the TODO/FIXME or log it as a tracked work item",
                )
            )
    return violations


# ---------------------------------------------------------------------------
# Rule registry — all rules in execution order
# ---------------------------------------------------------------------------

ALL_RULES = [
    check_no_raw_tailwind,
    check_missing_async_boundary,
    check_todo_fixme,
]
