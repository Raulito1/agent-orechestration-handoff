"""Tests for Slack posting logic in monitors/health_monitor.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from monitors.health_monitor import post_to_slack


class TestPostToSlack:
    def test_posts_correct_payload(self) -> None:
        """Verify the correct JSON payload is sent to the webhook URL."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch("monitors.health_monitor.httpx.post", return_value=mock_response) as mock_post:
            result = post_to_slack("Hello Slack!", "https://hooks.slack.com/fake")

        assert result is True
        mock_post.assert_called_once_with(
            "https://hooks.slack.com/fake",
            json={"text": "Hello Slack!"},
            timeout=10.0,
        )

    def test_returns_true_on_success(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch("monitors.health_monitor.httpx.post", return_value=mock_response):
            result = post_to_slack("msg", "https://hooks.slack.com/fake")

        assert result is True

    def test_returns_false_on_http_error(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("monitors.health_monitor.httpx.post", return_value=mock_response):
            result = post_to_slack("msg", "https://hooks.slack.com/fake")

        assert result is False

    def test_returns_false_on_connection_error(self) -> None:
        with patch(
            "monitors.health_monitor.httpx.post",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            result = post_to_slack("msg", "https://hooks.slack.com/fake")

        assert result is False

    def test_does_not_raise_on_any_exception(self) -> None:
        with patch(
            "monitors.health_monitor.httpx.post",
            side_effect=Exception("unexpected error"),
        ):
            # Should return False, not raise
            result = post_to_slack("msg", "https://hooks.slack.com/fake")

        assert result is False


class TestSlackSkipBehavior:
    """Verify graceful skip when webhook URL is not set."""

    def test_no_slack_post_when_url_empty(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import monitors.health_monitor as hm
        import intelligence.work_intelligence as wi
        from unittest.mock import AsyncMock, patch
        from monitors.health_monitor import AppGuardSummary

        wl_path = tmp_path / "work_log.json"
        pi_path = tmp_path / "pattern_index.json"
        import json
        wl_path.write_text(json.dumps({"items": []}))
        pi_path.write_text(json.dumps({"patterns": {}}))

        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)
        monkeypatch.setattr(hm, "OUTPUT_DIR", tmp_path / "health")
        monkeypatch.setattr(
            hm,
            "_scan_app_guard",
            AsyncMock(return_value=AppGuardSummary("app", "App", 0, 0)),
        )
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Insight.")]
        )

        mock_base = MagicMock()
        mock_base._apps = [{"id": "app", "name": "App", "stack": "fastapi-react"}]
        mock_base.connector = MagicMock()

        http_calls = []

        def fake_http_post(*args, **kwargs):
            http_calls.append(args)
            return MagicMock(raise_for_status=lambda: None)

        with patch("monitors.health_monitor.BaseOrchestrator", return_value=mock_base):
            with patch("monitors.health_monitor.httpx.post", side_effect=fake_http_post):
                hm.run_health_monitor(no_slack=False, client=mock_client)

        assert http_calls == [], "httpx.post should not be called when webhook URL is not set"
