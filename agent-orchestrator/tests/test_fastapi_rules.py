"""Tests for FastAPI convention guard rules.

Each rule has a passing case (no violations) and a failing case (violations found).
Rules are pure functions — no file system or I/O needed.
"""
import pytest
from guards.rules.fastapi_rules import (
    check_auth_dependency_present,
    check_function_too_long,
    check_missing_pydantic_response_model,
    check_no_raw_sql_in_service,
    check_rbac_cte_present,
    check_todo_fixme,
)


# ---------------------------------------------------------------------------
# check_rbac_cte_present
# ---------------------------------------------------------------------------


def test_rbac_cte_present_passes_with_cte():
    content = "WITH rbac AS (SELECT id FROM rbac_users)\nSELECT * FROM users"
    result = check_rbac_cte_present("queries/user.sql", content)
    assert result == []


def test_rbac_cte_present_passes_lowercase():
    content = "with rbac as (select id from rbac_users)\nselect * from users"
    result = check_rbac_cte_present("queries/user.sql", content)
    assert result == []


def test_rbac_cte_present_fails_missing_cte():
    content = "SELECT * FROM users WHERE id = :id"
    result = check_rbac_cte_present("queries/user.sql", content)
    assert len(result) == 1
    assert result[0].rule_id == "rbac-cte-present"
    assert result[0].severity == "CRITICAL"


def test_rbac_cte_present_ignores_non_sql_files():
    content = "SELECT * FROM users"  # no CTE, but not a .sql file
    result = check_rbac_cte_present("services/user_service.py", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_auth_dependency_present
# ---------------------------------------------------------------------------


def test_auth_dependency_passes_with_depends():
    content = """\
from fastapi import APIRouter, Depends
from auth import get_current_user

router = APIRouter()

@router.get("/users")
async def get_users(current_user=Depends(get_current_user)):
    return []
"""
    result = check_auth_dependency_present("routers/users.py", content)
    assert result == []


def test_auth_dependency_fails_missing_depends():
    content = """\
from fastapi import APIRouter

router = APIRouter()

@router.get("/users")
async def get_users():
    return []
"""
    result = check_auth_dependency_present("routers/users.py", content)
    assert len(result) == 1
    assert result[0].rule_id == "auth-dependency-present"
    assert result[0].severity == "CRITICAL"


def test_auth_dependency_ignores_non_py_files():
    content = "@router.get('/users')\ndef get_users():\n    pass"
    result = check_auth_dependency_present("routers/users.txt", content)
    assert result == []


def test_auth_dependency_ignores_files_without_router():
    content = """\
def plain_function():
    return 42
"""
    result = check_auth_dependency_present("services/calc.py", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_no_raw_sql_in_service
# ---------------------------------------------------------------------------


def test_no_raw_sql_in_service_passes_clean():
    content = """\
from repositories.user_repo import UserRepository

async def get_user(user_id: int):
    return await UserRepository.find_by_id(user_id)
"""
    result = check_no_raw_sql_in_service("services/user_service.py", content)
    assert result == []


def test_no_raw_sql_in_service_fails_raw_sql():
    content = """\
async def get_user(user_id: int):
    query = "SELECT * FROM users WHERE id = :id"
    return await db.execute(query, {"id": user_id})
"""
    result = check_no_raw_sql_in_service("services/user_service.py", content)
    assert len(result) >= 1
    assert result[0].rule_id == "no-raw-sql-in-service"
    assert result[0].severity == "CRITICAL"


def test_no_raw_sql_in_service_ignores_non_service_files():
    content = 'query = "SELECT * FROM users"'
    result = check_no_raw_sql_in_service("repositories/user_repo.py", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_todo_fixme
# ---------------------------------------------------------------------------


def test_todo_fixme_passes_no_comments():
    content = """\
def calculate():
    return 42
"""
    result = check_todo_fixme("utils/calc.py", content)
    assert result == []


def test_todo_fixme_fails_todo_comment():
    content = """\
def calculate():
    # TODO: implement proper logic
    return 42
"""
    result = check_todo_fixme("utils/calc.py", content)
    assert len(result) == 1
    assert result[0].rule_id == "todo-fixme-in-new-code"
    assert result[0].severity == "WARNING"
    assert result[0].line_number == 2


def test_todo_fixme_fails_fixme_comment():
    content = """\
def calculate():
    # FIXME: this breaks with large inputs
    return 42
"""
    result = check_todo_fixme("utils/calc.py", content)
    assert len(result) == 1
    assert result[0].rule_id == "todo-fixme-in-new-code"


def test_todo_fixme_ignores_non_py_files():
    content = "# TODO: fix this"
    result = check_todo_fixme("README.md", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_function_too_long
# ---------------------------------------------------------------------------


def test_function_too_long_passes_short_function():
    lines = ["def short_func():", "    return 42"]
    result = check_function_too_long("utils/calc.py", "\n".join(lines))
    assert result == []


def test_function_too_long_fails_long_function():
    body = ["    pass"] * 55
    content = "def long_func():\n" + "\n".join(body)
    result = check_function_too_long("utils/calc.py", content)
    assert len(result) == 1
    assert result[0].rule_id == "function-too-long"
    assert result[0].severity == "WARNING"


def test_function_too_long_passes_exactly_50_lines():
    body = ["    pass"] * 49
    content = "def boundary_func():\n" + "\n".join(body)
    result = check_function_too_long("utils/calc.py", content)
    assert result == []


def test_function_too_long_ignores_non_py_files():
    body = ["pass"] * 60
    content = "def long_func():\n" + "\n".join(body)
    result = check_function_too_long("utils/calc.js", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_missing_pydantic_response_model
# ---------------------------------------------------------------------------


def test_missing_response_model_passes_with_response_model():
    content = """\
@router.get("/users", response_model=list[UserResponse])
async def get_users():
    return []
"""
    result = check_missing_pydantic_response_model("routers/users.py", content)
    assert result == []


def test_missing_response_model_fails_without_response_model():
    content = """\
@router.get("/users")
async def get_users():
    return []
"""
    result = check_missing_pydantic_response_model("routers/users.py", content)
    assert len(result) == 1
    assert result[0].rule_id == "missing-pydantic-response-model"
    assert result[0].severity == "WARNING"


def test_missing_response_model_ignores_non_py_files():
    content = '@router.get("/users")\ndef get_users(): pass'
    result = check_missing_pydantic_response_model("routers/users.txt", content)
    assert result == []
