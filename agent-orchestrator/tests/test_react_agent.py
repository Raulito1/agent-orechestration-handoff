"""Tests for React agent — mocks Anthropic calls."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.react_agent import ReactAgent, ReactGenerationResult, _parse_react_files


MOCK_CONTRACT = {
    "app_id": "new-hire",
    "feature_description": "Add CSV export to user profiles",
    "endpoints": [
        {
            "method": "GET",
            "path": "/api/v1/users/{user_id}/export",
            "auth_required": True,
            "response_model": "UserExportResponse",
            "response_fields": [
                {"name": "csv_data", "type": "str"},
                {"name": "filename", "type": "str"},
            ],
        }
    ],
    "models": [
        {
            "name": "UserExportResponse",
            "fields": [
                {"name": "csv_data", "type": "str"},
                {"name": "filename", "type": "str"},
            ],
        }
    ],
    "stack": "fastapi-react",
}

MOCK_RESPONSE = """\
## rtk_endpoint (apiSlice.ts)
```typescript
import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

export const userExportApi = createApi({
  reducerPath: 'userExportApi',
  baseQuery: fetchBaseQuery({ baseUrl: '/api/v1' }),
  endpoints: (builder) => ({
    exportUser: builder.query<UserExportResponse, string>({
      query: (userId) => `/users/${userId}/export`,
    }),
  }),
});

export const { useExportUserQuery } = userExportApi;
```

## ts_types (types.ts)
```typescript
export interface UserExportResponse {
  csv_data: string;
  filename: string;
}
```

## component (.tsx)
```tsx
import React from 'react';
import { Stack, AsyncBoundary } from '@uix/primitives';
import { useExportUserQuery } from './apiSlice';

interface Props {
  userId: string;
}

const UserExportComponent: React.FC<Props> = ({ userId }) => {
  const { data, isLoading, error } = useExportUserQuery(userId);
  return (
    <AsyncBoundary loading={isLoading} error={error}>
      <Stack>
        {data && <span>{data.filename}</span>}
      </Stack>
    </AsyncBoundary>
  );
};

export default UserExportComponent;
```
"""


def _make_mock_client(text: str) -> MagicMock:
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=text)]
    mock_client.messages.create.return_value = mock_message
    return mock_client


class TestReactAgent:
    def test_generate_returns_react_generation_result(self):
        agent = ReactAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate(MOCK_CONTRACT)
        assert isinstance(result, ReactGenerationResult)

    def test_files_keys_present(self):
        agent = ReactAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate(MOCK_CONTRACT)
        for key in ["rtk_endpoint", "ts_types", "component"]:
            assert key in result.files

    def test_rtk_endpoint_has_content(self):
        agent = ReactAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate(MOCK_CONTRACT)
        assert "createApi" in result.files["rtk_endpoint"]

    def test_ts_types_has_interface(self):
        agent = ReactAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate(MOCK_CONTRACT)
        assert "interface" in result.files["ts_types"]

    def test_component_uses_async_boundary(self):
        agent = ReactAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate(MOCK_CONTRACT)
        assert "AsyncBoundary" in result.files["component"]

    def test_calls_correct_model(self):
        mock_client = _make_mock_client(MOCK_RESPONSE)
        agent = ReactAgent(client=mock_client)
        agent.generate(MOCK_CONTRACT)
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-sonnet-4-6"

    def test_receives_contract_not_backend_files(self):
        """React agent prompt must include contract JSON, not raw code."""
        mock_client = _make_mock_client(MOCK_RESPONSE)
        agent = ReactAgent(client=mock_client)
        agent.generate(MOCK_CONTRACT)
        call_args = mock_client.messages.create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "app_id" in user_content  # contract field present
        assert "router.py" not in user_content  # no backend files


class TestParseReactFiles:
    def test_all_keys_present(self):
        files = _parse_react_files(MOCK_RESPONSE)
        for key in ["rtk_endpoint", "ts_types", "component"]:
            assert key in files

    def test_rtk_content_extracted(self):
        files = _parse_react_files(MOCK_RESPONSE)
        assert "createApi" in files["rtk_endpoint"]

    def test_missing_sections_get_placeholder(self):
        files = _parse_react_files("## rtk_endpoint\n```typescript\nconst x = 1;\n```")
        assert "ts_types" in files
        assert "not generated" in files["ts_types"]
