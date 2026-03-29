"""Tests for monitors/health_monitor.py.

All Anthropic API calls and connector I/O are mocked.
No real API calls or file system I/O outside of tmp_path.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from monitors.health_monitor import (
    AppGuardSummary,
    BugActivitySummary,
    HealthDigest,
    PatternSummary,
    _analyse_work_log,
    _get_top_patterns,
    _synthesize_insight,
    post_to_slack,
    run_health_monitor,
    write_output_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_digest() -> HealthDigest:
    return HealthDigest(
        run_date="2026-03-28",
        guard_summaries=[
            AppGuardSummary("new-hire", "New Hire Experience", 0, 0),
            AppGuardSummary("new-client", "New Client Experience", 0, 2),
            AppGuardSummary("agm", "AGM", 0, 0),
            AppGuardSummary("peekr", "Peekr", 1, 0),
        ],
        bug_activity=BugActivitySummary(
            opened_this_week=3,
            resolved_this_week=2,
            open_by_app={"peekr": 1},
            persisting_bugs=[
                {
                    "id": "bug-0012",
                    "app": "peekr",
                    "pattern_tag": "rbac-cte-missing",
                    "attempts": [{"attempt": 1, "resolved": False}, {"attempt": 2, "resolved": False}],
                    "status": "PERSISTING",
                }
            ],
        ),
        top_patterns=[
            PatternSummary("rbac_cte_missing", 4, True, "rbac_cte_missing"),
            PatternSummary("jwt_claim_extraction", 2, False, None),
            PatternSummary("rtk_cache_stale", 2, False, None),
        ],
        insight="Peekr is showing critical RBAC violations that need immediate attention.",
    )


@pytest.fixture()
def work_log_data() -> dict:
    today = date.today().isoformat()
    return {
        "items": [
            {
                "id": "bug-0001",
                "type": "BUG",
                "status": "OPEN",
                "app": "new-hire",
                "first_seen": today,
                "last_updated": today,
                "pattern_tag": "rbac_cte_missing",
                "attempts": [],
            },
            {
                "id": "bug-0002",
                "type": "BUG",
                "status": "PERSISTING",
                "app": "peekr",
                "first_seen": today,
                "last_updated": today,
                "pattern_tag": "rbac_cte_missing",
                "attempts": [
                    {"attempt": 1, "resolved": False, "resolved_date": None},
                    {"attempt": 2, "resolved": False, "resolved_date": None},
                ],
            },
            {
                "id": "bug-0003",
                "type": "BUG",
                "status": "RESOLVED",
                "app": "agm",
                "first_seen": today,
                "last_updated": today,
                "pattern_tag": "jwt_claim_extraction",
                "attempts": [
                    {"attempt": 1, "resolved": True, "resolved_date": today},
                ],
            },
            {
                "id": "feat-0001",
                "type": "FEATURE",
                "status": "IN_PROGRESS",
                "app": "new-hire",
                "first_seen": today,
                "last_updated": today,
            },
        ]
    }


@pytest.fixture()
def pattern_index_data() -> dict:
    return {
        "patterns": {
            "rbac_cte_missing": {
                "tag": "rbac_cte_missing",
                "description": "SQL file missing RBAC CTE",
                "occurrences": 4,
                "apps_affected": ["new-hire", "peekr"],
                "item_ids": ["bug-0001", "bug-0002"],
                "promoted_to_guard": True,
                "guard_rule_id": "rbac_cte_missing",
            },
            "jwt_claim_extraction": {
                "tag": "jwt_claim_extraction",
                "description": "JWT claim extraction error",
                "occurrences": 2,
                "apps_affected": ["agm"],
                "item_ids": ["bug-0003"],
                "promoted_to_guard": False,
                "guard_rule_id": None,
            },
            "rtk_cache_stale": {
                "tag": "rtk_cache_stale",
                "description": "RTK Query cache not invalidated",
                "occurrences": 1,
                "apps_affected": ["new-client"],
                "item_ids": [],
                "promoted_to_guard": False,
                "guard_rule_id": None,
            },
        }
    }


# ---------------------------------------------------------------------------
# Digest formatting
# ---------------------------------------------------------------------------


class TestHealthDigestFormatting:
    def test_slack_text_contains_all_sections(self, sample_digest: HealthDigest) -> None:
        text = sample_digest.to_slack_text()
        assert "Daily Health Digest" in text
        assert "Guard Summary" in text
        assert "Bug Activity" in text
        assert "Top Patterns" in text
        assert "Weekly Insight" in text

    def test_slack_text_includes_app_names(self, sample_digest: HealthDigest) -> None:
        text = sample_digest.to_slack_text()
        assert "New Hire Experience" in text
        assert "Peekr" in text

    def test_slack_text_includes_bug_counts(self, sample_digest: HealthDigest) -> None:
        text = sample_digest.to_slack_text()
        assert "Opened: 3" in text
        assert "Resolved: 2" in text
        assert "Persisting: 1" in text

    def test_slack_text_includes_persisting_bug_detail(self, sample_digest: HealthDigest) -> None:
        text = sample_digest.to_slack_text()
        assert "bug-0012" in text

    def test_slack_text_includes_patterns(self, sample_digest: HealthDigest) -> None:
        text = sample_digest.to_slack_text()
        assert "rbac_cte_missing" in text
        assert "promoted to guard" in text

    def test_slack_text_includes_insight(self, sample_digest: HealthDigest) -> None:
        text = sample_digest.to_slack_text()
        assert "Peekr" in text
        assert "RBAC" in text

    def test_slack_text_includes_manual_run_hint(self, sample_digest: HealthDigest) -> None:
        text = sample_digest.to_slack_text()
        assert "python cli.py health" in text


# ---------------------------------------------------------------------------
# AppGuardSummary status icons
# ---------------------------------------------------------------------------


class TestAppGuardSummary:
    def test_clean_app(self) -> None:
        gs = AppGuardSummary("app", "App", 0, 0)
        assert gs.status_icon == "✅"
        assert gs.status_label == "Clean"

    def test_warning_app(self) -> None:
        gs = AppGuardSummary("app", "App", 0, 2)
        assert gs.status_icon == "⚠"
        assert "warning" in gs.status_label

    def test_critical_app(self) -> None:
        gs = AppGuardSummary("app", "App", 1, 0)
        assert gs.status_icon == "🔴"
        assert "critical" in gs.status_label

    def test_scan_error_app(self) -> None:
        gs = AppGuardSummary("app", "App", 0, 0, scan_error="connection refused")
        assert gs.status_icon == "⚠"
        assert "scan error" in gs.status_label


# ---------------------------------------------------------------------------
# Work log analysis
# ---------------------------------------------------------------------------


class TestAnalyseWorkLog:
    def test_opened_and_resolved_this_week(
        self, tmp_path: Path, work_log_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wl_path = tmp_path / "work_log.json"
        wl_path.write_text(json.dumps(work_log_data))

        import intelligence.work_intelligence as wi
        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)

        summary = _analyse_work_log()
        assert summary.opened_this_week >= 1
        assert summary.resolved_this_week >= 1

    def test_persisting_bugs_detected(
        self, tmp_path: Path, work_log_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wl_path = tmp_path / "work_log.json"
        wl_path.write_text(json.dumps(work_log_data))

        import intelligence.work_intelligence as wi
        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)

        summary = _analyse_work_log()
        assert len(summary.persisting_bugs) >= 1
        assert summary.persisting_bugs[0]["id"] == "bug-0002"

    def test_features_excluded_from_bug_counts(
        self, tmp_path: Path, work_log_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wl_path = tmp_path / "work_log.json"
        wl_path.write_text(json.dumps(work_log_data))

        import intelligence.work_intelligence as wi
        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)

        summary = _analyse_work_log()
        # FEATURE items should not appear in open_by_app (only BUGs)
        assert "feat-0001" not in str(summary.open_by_app)

    def test_empty_work_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wl_path = tmp_path / "work_log.json"
        wl_path.write_text(json.dumps({"items": []}))

        import intelligence.work_intelligence as wi
        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)

        summary = _analyse_work_log()
        assert summary.opened_this_week == 0
        assert summary.persisting_bugs == []


# ---------------------------------------------------------------------------
# Top patterns
# ---------------------------------------------------------------------------


class TestGetTopPatterns:
    def test_returns_top_3_by_occurrences(
        self, tmp_path: Path, pattern_index_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pi_path = tmp_path / "pattern_index.json"
        pi_path.write_text(json.dumps(pattern_index_data))

        import intelligence.work_intelligence as wi
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)

        patterns = _get_top_patterns(n=3)
        assert len(patterns) == 3
        assert patterns[0].tag == "rbac_cte_missing"
        assert patterns[0].occurrences == 4

    def test_promoted_flag_set(
        self, tmp_path: Path, pattern_index_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pi_path = tmp_path / "pattern_index.json"
        pi_path.write_text(json.dumps(pattern_index_data))

        import intelligence.work_intelligence as wi
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)

        patterns = _get_top_patterns(n=3)
        assert patterns[0].promoted is True
        assert patterns[1].promoted is False

    def test_empty_pattern_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pi_path = tmp_path / "pattern_index.json"
        pi_path.write_text(json.dumps({"patterns": {}}))

        import intelligence.work_intelligence as wi
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)

        patterns = _get_top_patterns()
        assert patterns == []


# ---------------------------------------------------------------------------
# Anthropic synthesis
# ---------------------------------------------------------------------------


class TestSynthesizeInsight:
    def test_returns_insight_text(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Peekr has a critical RBAC issue. Focus on SQL layer.")]
        )

        guard_summaries = [AppGuardSummary("peekr", "Peekr", 1, 0)]
        bug_activity = BugActivitySummary(1, 0, {"peekr": 1}, [])
        top_patterns = [PatternSummary("rbac_cte_missing", 4, True, "rbac_cte_missing")]

        insight = _synthesize_insight(guard_summaries, bug_activity, top_patterns, mock_client)
        assert "Peekr" in insight or len(insight) > 5

    def test_anthropic_called_with_system_prompt(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="All good.")]
        )

        _synthesize_insight([], BugActivitySummary(0, 0, {}, []), [], mock_client)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert "system" in call_kwargs
        assert "health analyst" in call_kwargs["system"]


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


class TestWriteOutputFile:
    def test_writes_to_correct_path(
        self, tmp_path: Path, sample_digest: HealthDigest, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import monitors.health_monitor as hm
        monkeypatch.setattr(hm, "OUTPUT_DIR", tmp_path / "health")

        out_path = write_output_file(sample_digest)

        assert out_path.exists()
        assert out_path.name == "2026-03-28.md"
        content = out_path.read_text()
        assert "Daily Health Digest" in content

    def test_creates_output_dir_if_missing(
        self, tmp_path: Path, sample_digest: HealthDigest, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import monitors.health_monitor as hm
        output_dir = tmp_path / "new" / "nested" / "health"
        monkeypatch.setattr(hm, "OUTPUT_DIR", output_dir)

        write_output_file(sample_digest)
        assert output_dir.exists()


# ---------------------------------------------------------------------------
# run_health_monitor integration
# ---------------------------------------------------------------------------


class TestRunHealthMonitor:
    def _make_mock_guard_result(self, critical: int = 0, warnings: int = 0):
        from guards import GuardResult, Violation
        return GuardResult(
            app_id="test-app",
            critical_violations=[
                Violation("r1", "CRITICAL", "f.py", 1, "msg", "fix")
                for _ in range(critical)
            ],
            warning_violations=[
                Violation("r2", "WARNING", "f.py", 2, "msg", "fix")
                for _ in range(warnings)
            ],
            files_scanned=5,
        )

    def test_digest_contains_all_sections(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Patch paths
        import intelligence.work_intelligence as wi
        import monitors.health_monitor as hm

        wl_path = tmp_path / "work_log.json"
        pi_path = tmp_path / "pattern_index.json"
        wl_path.write_text(json.dumps({"items": []}))
        pi_path.write_text(json.dumps({"patterns": {}}))

        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)
        monkeypatch.setattr(hm, "OUTPUT_DIR", tmp_path / "health")

        # Mock guard
        guard_result = self._make_mock_guard_result()
        monkeypatch.setattr(
            hm,
            "_scan_app_guard",
            AsyncMock(return_value=AppGuardSummary("new-hire", "New Hire Experience", 0, 0)),
        )

        # Mock Anthropic
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Everything looks good this week.")]
        )

        # Mock BaseOrchestrator
        mock_base = MagicMock()
        mock_base._apps = [{"id": "new-hire", "name": "New Hire Experience", "stack": "fastapi-react"}]
        mock_base.connector = MagicMock()

        with patch("monitors.health_monitor.BaseOrchestrator", return_value=mock_base):
            digest = run_health_monitor(no_slack=True, client=mock_client)

        assert digest.run_date is not None
        assert len(digest.guard_summaries) == 1
        assert digest.bug_activity is not None
        assert digest.top_patterns is not None
        assert "Everything looks good" in digest.insight

    def test_slack_not_called_when_no_slack_flag(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import intelligence.work_intelligence as wi
        import monitors.health_monitor as hm

        wl_path = tmp_path / "work_log.json"
        pi_path = tmp_path / "pattern_index.json"
        wl_path.write_text(json.dumps({"items": []}))
        pi_path.write_text(json.dumps({"patterns": {}}))

        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)
        monkeypatch.setattr(hm, "OUTPUT_DIR", tmp_path / "health")
        monkeypatch.setattr(
            hm,
            "_scan_app_guard",
            AsyncMock(return_value=AppGuardSummary("new-hire", "New Hire Experience", 0, 0)),
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Insight.")]
        )

        mock_base = MagicMock()
        mock_base._apps = [{"id": "new-hire", "name": "New Hire Experience", "stack": "fastapi-react"}]
        mock_base.connector = MagicMock()

        slack_called = []

        def fake_post(text: str, url: str) -> bool:
            slack_called.append(True)
            return True

        monkeypatch.setattr(hm, "post_to_slack", fake_post)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake")

        with patch("monitors.health_monitor.BaseOrchestrator", return_value=mock_base):
            run_health_monitor(no_slack=True, client=mock_client)

        assert slack_called == [], "Slack should not be called when --no-slack is set"

    def test_slack_not_called_when_webhook_url_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import intelligence.work_intelligence as wi
        import monitors.health_monitor as hm

        wl_path = tmp_path / "work_log.json"
        pi_path = tmp_path / "pattern_index.json"
        wl_path.write_text(json.dumps({"items": []}))
        pi_path.write_text(json.dumps({"patterns": {}}))

        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)
        monkeypatch.setattr(hm, "OUTPUT_DIR", tmp_path / "health")
        monkeypatch.setattr(
            hm,
            "_scan_app_guard",
            AsyncMock(return_value=AppGuardSummary("new-hire", "New Hire Experience", 0, 0)),
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Insight.")]
        )

        mock_base = MagicMock()
        mock_base._apps = [{"id": "new-hire", "name": "New Hire Experience", "stack": "fastapi-react"}]
        mock_base.connector = MagicMock()

        slack_called = []

        def fake_post(text: str, url: str) -> bool:
            slack_called.append(True)
            return True

        monkeypatch.setattr(hm, "post_to_slack", fake_post)
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

        with patch("monitors.health_monitor.BaseOrchestrator", return_value=mock_base):
            run_health_monitor(no_slack=False, client=mock_client)

        assert slack_called == [], "Slack should not be called when webhook URL is not set"

    def test_output_file_written(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import intelligence.work_intelligence as wi
        import monitors.health_monitor as hm

        wl_path = tmp_path / "work_log.json"
        pi_path = tmp_path / "pattern_index.json"
        wl_path.write_text(json.dumps({"items": []}))
        pi_path.write_text(json.dumps({"patterns": {}}))

        health_output = tmp_path / "health"
        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)
        monkeypatch.setattr(hm, "OUTPUT_DIR", health_output)
        monkeypatch.setattr(
            hm,
            "_scan_app_guard",
            AsyncMock(return_value=AppGuardSummary("new-hire", "New Hire Experience", 0, 0)),
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Insight.")]
        )

        mock_base = MagicMock()
        mock_base._apps = [{"id": "new-hire", "name": "New Hire Experience", "stack": "fastapi-react"}]
        mock_base.connector = MagicMock()

        with patch("monitors.health_monitor.BaseOrchestrator", return_value=mock_base):
            digest = run_health_monitor(no_slack=True, client=mock_client)

        expected_file = health_output / f"{digest.run_date}.md"
        assert expected_file.exists()
        assert "Daily Health Digest" in expected_file.read_text()

    def test_guard_scan_error_does_not_crash(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import intelligence.work_intelligence as wi
        import monitors.health_monitor as hm

        wl_path = tmp_path / "work_log.json"
        pi_path = tmp_path / "pattern_index.json"
        wl_path.write_text(json.dumps({"items": []}))
        pi_path.write_text(json.dumps({"patterns": {}}))

        monkeypatch.setattr(wi, "WORK_LOG_PATH", wl_path)
        monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", pi_path)
        monkeypatch.setattr(hm, "OUTPUT_DIR", tmp_path / "health")

        # Simulate scan error
        monkeypatch.setattr(
            hm,
            "_scan_app_guard",
            AsyncMock(
                return_value=AppGuardSummary("new-hire", "New Hire Experience", 0, 0, scan_error="connection refused")
            ),
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Insight.")]
        )

        mock_base = MagicMock()
        mock_base._apps = [{"id": "new-hire", "name": "New Hire Experience", "stack": "fastapi-react"}]
        mock_base.connector = MagicMock()

        with patch("monitors.health_monitor.BaseOrchestrator", return_value=mock_base):
            digest = run_health_monitor(no_slack=True, client=mock_client)

        # Scan error should appear in digest without crashing
        text = digest.to_slack_text()
        assert "scan error" in text
