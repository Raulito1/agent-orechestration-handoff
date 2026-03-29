import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from connectors.bitbucket_connector import BitbucketConnector, _MAX_RETRIES

_APPS = [
    {
        "id": "peekr",
        "bitbucket": {
            "workspace": "workspace-b",
            "api_repo": "peekr-api",
            "web_repo": "peekr-web",
        },
    }
]


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("BITBUCKET_BASE_URL", "https://api.bitbucket.org/2.0")
    monkeypatch.setenv("BITBUCKET_USERNAME", "test-user")
    monkeypatch.setenv("BITBUCKET_APP_PASSWORD", "test-pass")


@pytest.fixture()
def connector():
    return BitbucketConnector(_APPS)


def _make_response(status_code: int, text: str = "", json_data: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# get_file
# ---------------------------------------------------------------------------


async def test_get_file_success(connector):
    mock_resp = _make_response(200, text="def foo(): pass")
    with patch.object(connector, "_get_with_retry", new=AsyncMock(return_value=mock_resp)):
        result = await connector.get_file("peekr-api", "src/main.py")
    assert result == "def foo(): pass"


async def test_get_file_returns_none_on_404(connector):
    with patch.object(connector, "_get_with_retry", new=AsyncMock(return_value=None)):
        result = await connector.get_file("peekr-api", "missing.py")
    assert result is None


# ---------------------------------------------------------------------------
# post_pr_comment
# ---------------------------------------------------------------------------


async def test_post_pr_comment_success(connector):
    mock_resp = _make_response(201)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
        result = await connector.post_pr_comment("peekr-api", "7", "Looks good!")
    assert result is True


async def test_post_pr_comment_failure(connector):
    mock_resp = _make_response(403, text="Forbidden")
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
        result = await connector.post_pr_comment("peekr-api", "7", "Looks good!")
    assert result is False


# ---------------------------------------------------------------------------
# retry logic
# ---------------------------------------------------------------------------


async def test_retry_on_rate_limit_then_success(connector):
    """Should retry on 429 and succeed on the last attempt."""
    rate_limited = _make_response(429)
    success = _make_response(200, text="ok")

    call_count = 0

    async def fake_get(url: str) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count < _MAX_RETRIES:
            return rate_limited
        return success

    async with connector._make_client() as client:
        with patch.object(client, "get", side_effect=fake_get):
            with patch("asyncio.sleep", new=AsyncMock()):
                response = await connector._get_with_retry(client, "http://example.com")

    assert response is success
    assert call_count == _MAX_RETRIES


async def test_retry_exhausted_returns_none(connector):
    """After _MAX_RETRIES all 429s, should return None."""
    rate_limited = _make_response(429)

    async with connector._make_client() as client:
        with patch.object(client, "get", new=AsyncMock(return_value=rate_limited)):
            with patch("asyncio.sleep", new=AsyncMock()):
                response = await connector._get_with_retry(client, "http://example.com")

    assert response is None


async def test_404_returns_none_immediately(connector):
    not_found = _make_response(404)

    async with connector._make_client() as client:
        with patch.object(client, "get", new=AsyncMock(return_value=not_found)):
            response = await connector._get_with_retry(client, "http://example.com")

    assert response is None
