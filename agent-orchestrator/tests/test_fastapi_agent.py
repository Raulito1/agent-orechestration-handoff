"""Tests for FastAPI agent — mocks Anthropic calls."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.fastapi_agent import BackendGenerationResult, FastAPIAgent, _parse_contract, _parse_files


MOCK_RESPONSE = """\
## router.py
```python
from fastapi import APIRouter, Depends
router = APIRouter()

@router.get("/api/v1/users/{user_id}/export")
async def export_user(user_id: str, current_user=Depends(get_current_user)):
    pass
```

## service.py
```python
class UserExportService:
    def export(self, user_id: str):
        return {}
```

## repository.py
```python
class UserExportRepository:
    def get(self, user_id: str):
        return {}
```

## sql
```sql
WITH rbac AS (
    SELECT user_id FROM permissions WHERE user_id = %(user_id)s
)
SELECT * FROM users u JOIN rbac r ON u.id = r.user_id;
```

## request_model.py
```python
from pydantic import BaseModel
class UserExportRequest(BaseModel):
    user_id: str
```

## response_model.py
```python
from pydantic import BaseModel
class UserExportResponse(BaseModel):
    csv_data: str
    filename: str
```

<contract>
{
  "app_id": "new-hire",
  "feature_description": "Add CSV export to user profiles",
  "generated_at": "2026-03-28T10:00:00Z",
  "endpoints": [
    {
      "method": "GET",
      "path": "/api/v1/users/{user_id}/export",
      "auth_required": true,
      "rbac_required": true,
      "request_params": [{"name": "user_id", "type": "str", "location": "path"}],
      "request_body": null,
      "response_model": "UserExportResponse",
      "response_fields": [
        {"name": "csv_data", "type": "str"},
        {"name": "filename", "type": "str"}
      ]
    }
  ],
  "models": [
    {
      "name": "UserExportResponse",
      "fields": [
        {"name": "csv_data", "type": "str", "description": "CSV file content"},
        {"name": "filename", "type": "str", "description": "Suggested filename"}
      ]
    }
  ],
  "stack": "fastapi-react"
}
</contract>
"""


def _make_mock_client(text: str) -> MagicMock:
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=text)]
    mock_client.messages.create.return_value = mock_message
    return mock_client


class TestFastAPIAgent:
    def test_generate_returns_backend_generation_result(self):
        agent = FastAPIAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "New Hire Experience")
        assert isinstance(result, BackendGenerationResult)

    def test_contract_is_parsed(self):
        agent = FastAPIAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "New Hire Experience")
        assert result.contract["app_id"] == "new-hire"
        assert len(result.contract["endpoints"]) == 1
        assert len(result.contract["models"]) == 1

    def test_files_keys_present(self):
        agent = FastAPIAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "New Hire Experience")
        for key in ["router", "service", "repository", "sql", "request_model", "response_model"]:
            assert key in result.files

    def test_router_file_has_content(self):
        agent = FastAPIAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "New Hire Experience")
        assert "APIRouter" in result.files["router"]

    def test_sql_has_rbac_cte(self):
        agent = FastAPIAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "New Hire Experience")
        assert "rbac" in result.files["sql"].lower()

    def test_calls_correct_model(self):
        mock_client = _make_mock_client(MOCK_RESPONSE)
        agent = FastAPIAgent(client=mock_client)
        agent.generate("test", "TestApp")
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-opus-4-5"

    def test_empty_contract_on_missing_tags(self):
        agent = FastAPIAgent(client=_make_mock_client("No contract here"))
        result = agent.generate("test", "TestApp")
        assert result.contract == {}


class TestParseContract:
    def test_parses_valid_contract(self):
        text = '<contract>\n{"app_id": "x"}\n</contract>'
        result = _parse_contract(text)
        assert result["app_id"] == "x"

    def test_handles_whitespace(self):
        text = '<contract>  \n  \n{"app_id": "y"}  \n  </contract>'
        result = _parse_contract(text)
        assert result["app_id"] == "y"

    def test_handles_fenced_json(self):
        text = "<contract>\n```json\n{\"app_id\": \"z\"}\n```\n</contract>"
        result = _parse_contract(text)
        assert result["app_id"] == "z"

    def test_returns_empty_on_missing(self):
        assert _parse_contract("no contract here") == {}

    def test_returns_empty_on_invalid_json(self):
        assert _parse_contract("<contract>not json</contract>") == {}


class TestParseFiles:
    def test_all_file_types_present(self):
        files = _parse_files(MOCK_RESPONSE)
        for key in ["router", "service", "repository", "sql", "request_model", "response_model"]:
            assert key in files

    def test_router_content_extracted(self):
        files = _parse_files(MOCK_RESPONSE)
        assert "APIRouter" in files["router"]

    def test_missing_sections_get_placeholder(self):
        files = _parse_files("## router.py\n```python\npass\n```")
        # service, repository, etc should get placeholders
        assert "service" in files
        assert "not generated" in files["service"]
