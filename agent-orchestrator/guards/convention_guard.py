"""Convention Guard — orchestrates rule checks across an app's repos.

Usage:
    result = await run_guard(app_config, connector)
    result = await run_guard(app_config, connector, pr_id="42")
"""
from __future__ import annotations

import logging

from connectors.base_connector import BaseConnector
from guards import GuardResult, Violation
from guards.rules import fastapi_rules, java_rules, react_rules

logger = logging.getLogger(__name__)


async def run_guard(
    app_config: dict,
    connector: BaseConnector,
    pr_id: str | None = None,
) -> GuardResult:
    """Run all applicable guard rules for an app and return the result.

    Args:
        app_config: The app dict from apps.yaml (id, name, stack, …).
        connector: A BaseConnector instance (local or Bitbucket).
        pr_id: If provided, post a formatted PR comment via the connector.

    Returns:
        GuardResult with violations separated by severity.
    """
    app_id: str = app_config["id"]
    app_name: str = app_config.get("name", app_id)
    stack: str = app_config.get("stack", "")

    all_violations: list[Violation] = []
    files_scanned = 0

    api_repo_id = f"{app_id}-api"
    web_repo_id = f"{app_id}-web"

    # --- Scan API repo ---
    api_files = await _list_all_files(connector, api_repo_id)
    for file_path in api_files:
        content = await connector.get_file(api_repo_id, file_path)
        if content is None:
            continue
        files_scanned += 1

        if stack == "fastapi-react":
            for rule in fastapi_rules.ALL_RULES:
                all_violations.extend(rule(file_path, content))
        elif stack == "java-react":
            for rule in java_rules.ALL_RULES:
                all_violations.extend(rule(file_path, content))

    # --- Scan Web repo ---
    web_files = await _list_all_files(connector, web_repo_id)
    for file_path in web_files:
        content = await connector.get_file(web_repo_id, file_path)
        if content is None:
            continue
        files_scanned += 1

        for rule in react_rules.ALL_RULES:
            all_violations.extend(rule(file_path, content))

    critical = [v for v in all_violations if v.severity == "CRITICAL"]
    warnings = [v for v in all_violations if v.severity == "WARNING"]

    result = GuardResult(
        app_id=app_id,
        critical_violations=critical,
        warning_violations=warnings,
        files_scanned=files_scanned,
    )

    if pr_id is not None:
        comment = _format_pr_comment(app_name, result)
        # Post to both repos so the comment appears on the PR
        for repo_id in (api_repo_id, web_repo_id):
            await connector.post_pr_comment(repo_id, pr_id, comment)

    return result


async def _list_all_files(connector: BaseConnector, repo_id: str) -> list[str]:
    """List all files in the root of a repo, gracefully ignoring unknown repos."""
    try:
        return await connector.list_files(repo_id, ".")
    except KeyError:
        logger.debug("Repo '%s' not found in connector — skipping.", repo_id)
        return []


# ---------------------------------------------------------------------------
# PR comment formatter
# ---------------------------------------------------------------------------


def _format_pr_comment(app_name: str, result: GuardResult) -> str:
    """Render a Bitbucket-ready markdown PR comment."""
    lines: list[str] = []

    lines.append(f"## \U0001f6e1 Convention Guard \u2014 {app_name}")
    lines.append("")

    if result.passed:
        lines.append("**Result: \u2705 PASSED** \u2014 no critical violations.")
    else:
        lines.append(
            f"**Result: \u274c FAILED** \u2014 {len(result.critical_violations)} "
            "critical violation(s) must be resolved before merge."
        )

    if result.critical_violations:
        lines.append("")
        lines.append("### \U0001f534 Critical (build blocking)")
        lines.append("")
        lines.append("| File | Rule | Message |")
        lines.append("|------|------|---------|")
        for v in result.critical_violations:
            loc = f"{v.file_path}:{v.line_number}" if v.line_number else v.file_path
            lines.append(f"| {loc} | {v.rule_id} | {v.message} |")

    if result.warning_violations:
        lines.append("")
        lines.append("### \U0001f7e1 Warnings (non-blocking)")
        lines.append("")
        lines.append("| File | Rule | Message |")
        lines.append("|------|------|---------|")
        for v in result.warning_violations:
            loc = f"{v.file_path}:{v.line_number}" if v.line_number else v.file_path
            lines.append(f"| {loc} | {v.rule_id} | {v.message} |")

    lines.append("")
    lines.append("---")
    lines.append(
        f"*Run locally: `python cli.py guard --app {result.app_id}`*"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Terminal output formatter
# ---------------------------------------------------------------------------


def format_terminal_output(app_name: str, result: GuardResult) -> str:
    """Render the human-readable terminal report."""
    sep = "\u2500" * 42
    lines: list[str] = []

    lines.append(f"Guard: {app_name}")
    lines.append(sep)
    lines.append(f"Files scanned: {result.files_scanned}")

    if result.critical_violations:
        lines.append("")
        lines.append(f"CRITICAL ({len(result.critical_violations)})")
        for v in result.critical_violations:
            loc = f"{v.file_path}:{v.line_number}" if v.line_number else v.file_path
            lines.append(f"  \u2717 [{v.rule_id}] {loc}")
            lines.append(f"    {v.message}")
            lines.append(f"    \u2192 {v.suggestion}")

    if result.warning_violations:
        lines.append("")
        lines.append(f"WARNING ({len(result.warning_violations)})")
        for v in result.warning_violations:
            loc = f"{v.file_path}:{v.line_number}" if v.line_number else v.file_path
            lines.append(f"  \u26a0 [{v.rule_id}] {loc}")
            lines.append(f"    {v.message}")
            lines.append(f"    \u2192 {v.suggestion}")

    lines.append("")
    lines.append(sep)
    if result.passed:
        total_warnings = len(result.warning_violations)
        if total_warnings:
            lines.append(f"Result: PASSED \u2014 {total_warnings} warning(s)")
        else:
            lines.append("Result: PASSED \u2014 no violations")
    else:
        lines.append(
            f"Result: FAILED \u2014 {len(result.critical_violations)} critical violation(s)"
        )

    return "\n".join(lines)
