"""FastAPI-specific convention guard rules.

Each rule is a pure function: (file_path: str, content: str) -> list[Violation].
Rules return an empty list if the file is not applicable to that rule.
"""
from __future__ import annotations

import re

from guards import Violation

# ---------------------------------------------------------------------------
# CRITICAL rules
# ---------------------------------------------------------------------------


def check_rbac_cte_present(file_path: str, content: str) -> list[Violation]:
    """Every .sql file must contain the RBAC CTE pattern."""
    if not file_path.endswith(".sql"):
        return []

    if re.search(r"with\s+rbac\s+as", content, re.IGNORECASE):
        return []

    return [
        Violation(
            rule_id="rbac-cte-present",
            severity="CRITICAL",
            file_path=file_path,
            line_number=1,
            message="SQL file missing RBAC CTE pattern",
            suggestion="Add: WITH rbac AS (SELECT ...) at top of query",
        )
    ]


def check_auth_dependency_present(file_path: str, content: str) -> list[Violation]:
    """Router files must use a FastAPI Depends() auth dependency on every route."""
    if not file_path.endswith(".py"):
        return []

    route_pattern = re.compile(
        r"^(\s*)@router\.(get|post|put|delete|patch)\s*\(", re.MULTILINE
    )
    route_matches = list(route_pattern.finditer(content))
    if not route_matches:
        return []

    violations: list[Violation] = []
    lines = content.splitlines()

    for match in route_matches:
        # Find the def line that follows this decorator
        decorator_line_no = content[: match.start()].count("\n")
        # Scan forward from the decorator to find the function definition
        func_def_line_no: int | None = None
        for i in range(decorator_line_no, min(decorator_line_no + 10, len(lines))):
            if re.match(r"\s*async\s+def\s+|^\s*def\s+", lines[i]):
                func_def_line_no = i
                break

        if func_def_line_no is None:
            continue

        # Collect the full function signature (may span multiple lines until `:`)
        sig_lines: list[str] = []
        for i in range(func_def_line_no, min(func_def_line_no + 20, len(lines))):
            sig_lines.append(lines[i])
            if ":" in lines[i] and not lines[i].strip().endswith(","):
                break
        signature = "\n".join(sig_lines)

        if "Depends(" not in signature:
            violations.append(
                Violation(
                    rule_id="auth-dependency-present",
                    severity="CRITICAL",
                    file_path=file_path,
                    line_number=decorator_line_no + 1,
                    message="Route missing auth Depends() parameter",
                    suggestion="Add a Depends(get_current_user) parameter to the route function",
                )
            )

    return violations


def check_no_raw_sql_in_service(file_path: str, content: str) -> list[Violation]:
    """Service layer files must not contain raw SQL strings."""
    if not file_path.endswith(".py"):
        return []
    if "service" not in file_path.lower():
        return []

    # Match SQL keywords inside string literals (single, double, triple quotes)
    raw_sql_pattern = re.compile(
        r"""(?:'''|\"\"\"|\"|').*?\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE)\b""",
        re.IGNORECASE | re.DOTALL,
    )

    violations: list[Violation] = []
    lines = content.splitlines()
    for i, line in enumerate(lines, start=1):
        if re.search(
            r"""(?:'|").*?\b(SELECT|INSERT|UPDATE|DELETE)\b""", line, re.IGNORECASE
        ):
            violations.append(
                Violation(
                    rule_id="no-raw-sql-in-service",
                    severity="CRITICAL",
                    file_path=file_path,
                    line_number=i,
                    message="Raw SQL found in service layer",
                    suggestion="Move SQL to a loader or repository file",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# WARNING rules
# ---------------------------------------------------------------------------


def check_todo_fixme(file_path: str, content: str) -> list[Violation]:
    """Flag any TODO or FIXME comment in Python files."""
    if not file_path.endswith(".py"):
        return []

    violations: list[Violation] = []
    for i, line in enumerate(content.splitlines(), start=1):
        if re.search(r"#.*\b(TODO|FIXME)\b", line, re.IGNORECASE):
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


def check_function_too_long(file_path: str, content: str) -> list[Violation]:
    """Flag any function longer than 50 lines."""
    if not file_path.endswith(".py"):
        return []

    lines = content.splitlines()
    violations: list[Violation] = []
    func_start: int | None = None
    func_name: str = ""
    func_indent: int = 0

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        def_match = re.match(r"(async\s+)?def\s+(\w+)", stripped)
        if def_match:
            # Close previous function if at same or lower indent
            if func_start is not None and indent <= func_indent:
                length = i - func_start
                if length > 50:
                    violations.append(
                        Violation(
                            rule_id="function-too-long",
                            severity="WARNING",
                            file_path=file_path,
                            line_number=func_start + 1,
                            message=f"Function '{func_name}' is {length} lines long (limit: 50)",
                            suggestion="Break the function into smaller, focused helpers",
                        )
                    )
            func_start = i
            func_name = def_match.group(2)
            func_indent = indent

    # Check last function
    if func_start is not None:
        length = len(lines) - func_start
        if length > 50:
            violations.append(
                Violation(
                    rule_id="function-too-long",
                    severity="WARNING",
                    file_path=file_path,
                    line_number=func_start + 1,
                    message=f"Function '{func_name}' is {length} lines long (limit: 50)",
                    suggestion="Break the function into smaller, focused helpers",
                )
            )

    return violations


def check_missing_pydantic_response_model(file_path: str, content: str) -> list[Violation]:
    """Router endpoints should declare a response_model= argument."""
    if not file_path.endswith(".py"):
        return []

    route_pattern = re.compile(
        r"^(\s*)@router\.(get|post|put|delete|patch)\s*\(([^)]*)\)",
        re.MULTILINE | re.DOTALL,
    )

    violations: list[Violation] = []
    for match in route_pattern.finditer(content):
        decorator_body = match.group(3)
        if "response_model" not in decorator_body:
            line_no = content[: match.start()].count("\n") + 1
            violations.append(
                Violation(
                    rule_id="missing-pydantic-response-model",
                    severity="WARNING",
                    file_path=file_path,
                    line_number=line_no,
                    message="Route decorator missing response_model= argument",
                    suggestion="Add response_model=YourResponseSchema to the route decorator",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Rule registry — all rules in execution order
# ---------------------------------------------------------------------------

ALL_RULES = [
    check_rbac_cte_present,
    check_auth_dependency_present,
    check_no_raw_sql_in_service,
    check_todo_fixme,
    check_function_too_long,
    check_missing_pydantic_response_model,
]
