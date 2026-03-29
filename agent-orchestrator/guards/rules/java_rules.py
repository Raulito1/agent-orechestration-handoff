"""Java Spring Boot-specific convention guard rules.

Each rule is a pure function: (file_path: str, content: str) -> list[Violation].
Rules return an empty list if the file is not applicable to that rule.
"""
from __future__ import annotations

import re

from guards import Violation

# ---------------------------------------------------------------------------
# CRITICAL rules
# ---------------------------------------------------------------------------


def check_no_block_in_webflux(file_path: str, content: str) -> list[Violation]:
    """Java files must not call .block() — blocks the reactive thread pool."""
    if not file_path.endswith(".java"):
        return []

    violations: list[Violation] = []
    for i, line in enumerate(content.splitlines(), start=1):
        # Match .block() possibly followed by () or nothing
        if re.search(r"\.\s*block\s*\(\s*\)", line):
            violations.append(
                Violation(
                    rule_id="no-block-in-webflux",
                    severity="CRITICAL",
                    file_path=file_path,
                    line_number=i,
                    message=".block() call found — blocks the reactive thread pool",
                    suggestion="Use .subscribe(), flatMap(), or return the Mono/Flux to the caller",
                )
            )
    return violations


def check_security_annotation_on_controller(file_path: str, content: str) -> list[Violation]:
    """@RestController/@Controller classes must have a Spring Security annotation."""
    if not file_path.endswith(".java"):
        return []

    controller_pattern = re.compile(
        r"@(RestController|Controller)\b", re.MULTILINE
    )
    if not controller_pattern.search(content):
        return []

    security_annotations = {"@PreAuthorize", "@Secured", "@SecurityRequirement"}
    has_security = any(ann in content for ann in security_annotations)

    if has_security:
        return []

    # Find the line number of the first @RestController or @Controller
    for i, line in enumerate(content.splitlines(), start=1):
        if re.search(r"@(RestController|Controller)\b", line):
            return [
                Violation(
                    rule_id="security-annotation-on-controller",
                    severity="CRITICAL",
                    file_path=file_path,
                    line_number=i,
                    message="Controller class missing Spring Security annotation",
                    suggestion=(
                        "Add @PreAuthorize, @Secured, or @SecurityRequirement "
                        "to the class or all public methods"
                    ),
                )
            ]

    return []


def check_liquibase_migration_has_rollback(file_path: str, content: str) -> list[Violation]:
    """Liquibase migration YAML files must include a rollback section."""
    if not file_path.endswith(".yaml") and not file_path.endswith(".yml"):
        return []

    # Only inspect files that look like Liquibase changelogs
    if not re.search(r"changeSet|databaseChangeLog", content):
        return []

    if re.search(r"\brollback\b", content, re.IGNORECASE):
        return []

    return [
        Violation(
            rule_id="liquibase-migration-has-rollback",
            severity="CRITICAL",
            file_path=file_path,
            line_number=1,
            message="Liquibase migration missing rollback section",
            suggestion="Add a rollback: block to every changeSet in this migration file",
        )
    ]


# ---------------------------------------------------------------------------
# WARNING rules
# ---------------------------------------------------------------------------


def check_todo_fixme(file_path: str, content: str) -> list[Violation]:
    """Flag any TODO or FIXME comment in Java files."""
    if not file_path.endswith(".java"):
        return []

    violations: list[Violation] = []
    for i, line in enumerate(content.splitlines(), start=1):
        if re.search(r"//.*\b(TODO|FIXME)\b|/\*.*\b(TODO|FIXME)\b", line, re.IGNORECASE):
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


def check_method_too_long(file_path: str, content: str) -> list[Violation]:
    """Flag any method longer than 50 lines."""
    if not file_path.endswith(".java"):
        return []

    lines = content.splitlines()
    violations: list[Violation] = []

    # Find method declarations: access modifier + return type + name + (
    method_pattern = re.compile(
        r"^\s*(public|private|protected)\s+[\w<>\[\],\s]+\s+\w+\s*\("
    )

    method_start: int | None = None
    method_name: str = ""
    brace_depth: int = 0
    in_method: bool = False

    for i, line in enumerate(lines):
        if not in_method:
            match = method_pattern.match(line)
            if match:
                method_start = i
                # Extract method name: last word before (
                name_match = re.search(r"(\w+)\s*\(", line)
                method_name = name_match.group(1) if name_match else "unknown"
                brace_depth = 0
                in_method = True

        if in_method:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0 and method_start is not None:
                length = i - method_start + 1
                if length > 50:
                    violations.append(
                        Violation(
                            rule_id="method-too-long",
                            severity="WARNING",
                            file_path=file_path,
                            line_number=method_start + 1,
                            message=f"Method '{method_name}' is {length} lines long (limit: 50)",
                            suggestion="Extract logic into smaller private helper methods",
                        )
                    )
                in_method = False
                method_start = None
                brace_depth = 0

    return violations


def check_missing_mapstruct_mapper(file_path: str, content: str) -> list[Violation]:
    """DTO classes should have a corresponding MapStruct Mapper interface."""
    if not file_path.endswith(".java"):
        return []

    # Check if this file defines a DTO class (class name ends in Dto or DTO)
    dto_match = re.search(r"\bclass\s+(\w+(?:Dto|DTO))\b", content)
    if not dto_match:
        return []

    dto_name = dto_match.group(1)

    # Check if a mapper is referenced (import or annotation in same file or companion)
    if re.search(r"@Mapper\b|import.*MapStruct|import.*Mapper", content):
        return []

    line_no = 1
    for i, line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bclass\s+\w+(?:Dto|DTO)\b", line):
            line_no = i
            break

    return [
        Violation(
            rule_id="missing-mapstruct-mapper",
            severity="WARNING",
            file_path=file_path,
            line_number=line_no,
            message=f"DTO class '{dto_name}' may be missing a MapStruct Mapper interface",
            suggestion=f"Create a {dto_name.replace('Dto', 'Mapper').replace('DTO', 'Mapper')} interface annotated with @Mapper",
        )
    ]


# ---------------------------------------------------------------------------
# Rule registry — all rules in execution order
# ---------------------------------------------------------------------------

ALL_RULES = [
    check_no_block_in_webflux,
    check_security_annotation_on_controller,
    check_liquibase_migration_has_rollback,
    check_todo_fixme,
    check_method_too_long,
    check_missing_mapstruct_mapper,
]
