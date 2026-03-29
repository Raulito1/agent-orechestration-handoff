"""Integration tests for convention_guard.py using a mock connector."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from guards import GuardResult
from guards.convention_guard import _format_pr_comment, format_terminal_output, run_guard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_connector(files_by_repo: dict[str, dict[str, str]]) -> MagicMock:
    """Build a mock connector that serves given files per repo.

    Args:
        files_by_repo: mapping of repo_id → {file_path: content}
    """
    connector = MagicMock()

    async def list_files(repo_id: str, directory: str, extension: str | None = None) -> list[str]:
        repo_files = files_by_repo.get(repo_id, {})
        return list(repo_files.keys())

    async def get_file(repo_id: str, file_path: str) -> str | None:
        return files_by_repo.get(repo_id, {}).get(file_path)

    async def post_pr_comment(repo_id: str, pr_id: str, body: str) -> bool:
        return True

    connector.list_files = list_files
    connector.get_file = get_file
    connector.post_pr_comment = AsyncMock(side_effect=post_pr_comment)
    return connector


FASTAPI_APP = {
    "id": "new-hire",
    "name": "New Hire Experience",
    "stack": "fastapi-react",
}

JAVA_APP = {
    "id": "peekr",
    "name": "Peekr",
    "stack": "java-react",
}


# ---------------------------------------------------------------------------
# FastAPI stack — clean run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fastapi_guard_passes_clean_codebase():
    files = {
        "new-hire-api": {
            "queries/user.sql": "WITH rbac AS (SELECT id FROM rbac)\nSELECT * FROM users",
        },
        "new-hire-web": {
            "src/components/UserCard.tsx": "export function UserCard() { return <Stack>hi</Stack>; }",
        },
    }
    connector = make_mock_connector(files)
    result = await run_guard(FASTAPI_APP, connector)

    assert isinstance(result, GuardResult)
    assert result.app_id == "new-hire"
    assert result.passed is True
    assert result.critical_violations == []
    assert result.files_scanned == 2


# ---------------------------------------------------------------------------
# FastAPI stack — critical violation (missing RBAC CTE)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fastapi_guard_fails_missing_rbac_cte():
    files = {
        "new-hire-api": {
            "queries/user.sql": "SELECT * FROM users WHERE id = :id",
        },
        "new-hire-web": {},
    }
    connector = make_mock_connector(files)
    result = await run_guard(FASTAPI_APP, connector)

    assert result.passed is False
    assert len(result.critical_violations) == 1
    assert result.critical_violations[0].rule_id == "rbac-cte-present"


# ---------------------------------------------------------------------------
# Java stack — critical violation (.block() call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_java_guard_fails_block_call():
    files = {
        "peekr-api": {
            "src/UserService.java": "public User get() { return repo.findById('1').block(); }",
        },
        "peekr-web": {},
    }
    connector = make_mock_connector(files)
    result = await run_guard(JAVA_APP, connector)

    assert result.passed is False
    critical_ids = [v.rule_id for v in result.critical_violations]
    assert "no-block-in-webflux" in critical_ids


# ---------------------------------------------------------------------------
# React violations appear regardless of stack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_warnings_appear_on_fastapi_stack():
    files = {
        "new-hire-api": {},
        "new-hire-web": {
            "src/components/UserCard.tsx": (
                'export function UserCard() {\n'
                '    const { data } = useGetUsersQuery();\n'
                '    return <div>hello</div>;\n'
                '}'
            ),
        },
    }
    connector = make_mock_connector(files)
    result = await run_guard(FASTAPI_APP, connector)

    # Missing AsyncBoundary is a WARNING, so guard still passes
    assert result.passed is True
    warning_ids = [v.rule_id for v in result.warning_violations]
    assert "missing-async-boundary" in warning_ids


# ---------------------------------------------------------------------------
# PR comment posted when pr_id is provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr_comment_posted_when_pr_id_given():
    files = {
        "new-hire-api": {
            "queries/user.sql": "SELECT * FROM users",  # missing RBAC CTE
        },
        "new-hire-web": {},
    }
    connector = make_mock_connector(files)
    result = await run_guard(FASTAPI_APP, connector, pr_id="99")

    # post_pr_comment should have been called at least once
    assert connector.post_pr_comment.called
    # The comment body should mention Convention Guard
    call_args = connector.post_pr_comment.call_args_list
    assert any("Convention Guard" in str(args) for args in call_args)


@pytest.mark.asyncio
async def test_pr_comment_not_posted_without_pr_id():
    files = {
        "new-hire-api": {
            "queries/user.sql": "SELECT * FROM users",
        },
        "new-hire-web": {},
    }
    connector = make_mock_connector(files)
    await run_guard(FASTAPI_APP, connector)  # no pr_id

    connector.post_pr_comment.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown repos are skipped gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_handles_missing_repo_gracefully():
    # Only web repo exists; api repo is absent from connector
    files = {
        "new-hire-web": {
            "src/App.tsx": "export function App() { return <Stack>ok</Stack>; }",
        },
    }
    connector = make_mock_connector(files)

    # Should not raise, even though new-hire-api is not in files_by_repo
    result = await run_guard(FASTAPI_APP, connector)
    assert isinstance(result, GuardResult)


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def test_format_pr_comment_passed():
    result = GuardResult(app_id="new-hire", files_scanned=10)
    comment = _format_pr_comment("New Hire Experience", result)
    assert "PASSED" in comment
    assert "Convention Guard" in comment
    assert "New Hire Experience" in comment


def test_format_pr_comment_failed():
    from guards import Violation

    result = GuardResult(
        app_id="new-hire",
        critical_violations=[
            Violation(
                rule_id="rbac-cte-present",
                severity="CRITICAL",
                file_path="queries/user.sql",
                line_number=1,
                message="SQL file missing RBAC CTE pattern",
                suggestion="Add WITH rbac AS ...",
            )
        ],
        files_scanned=5,
    )
    comment = _format_pr_comment("New Hire Experience", result)
    assert "FAILED" in comment
    assert "rbac-cte-present" in comment
    assert "queries/user.sql" in comment


def test_format_terminal_output_failed():
    from guards import Violation

    result = GuardResult(
        app_id="peekr",
        critical_violations=[
            Violation(
                rule_id="no-block-in-webflux",
                severity="CRITICAL",
                file_path="src/UserService.java",
                line_number=34,
                message=".block() call found",
                suggestion="Use subscribe() instead",
            )
        ],
        files_scanned=3,
    )
    output = format_terminal_output("Peekr", result)
    assert "FAILED" in output
    assert "no-block-in-webflux" in output
    assert "src/UserService.java:34" in output


def test_format_terminal_output_passed():
    result = GuardResult(app_id="peekr", files_scanned=20)
    output = format_terminal_output("Peekr", result)
    assert "PASSED" in output
    assert "Files scanned: 20" in output
