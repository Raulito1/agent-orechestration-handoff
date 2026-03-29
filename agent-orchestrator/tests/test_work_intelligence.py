"""Tests for intelligence/work_intelligence.py — all Anthropic calls are mocked."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from intelligence.work_intelligence import (
    BugAnalysis,
    PromotionRecommendation,
    WorkIntelligence,
    append_work_item,
    get_work_item,
    next_item_id,
    read_pattern_index,
    read_work_log,
    today,
    update_work_item,
    upsert_pattern,
    write_pattern_index,
    write_work_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_knowledge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all JSON storage to a temporary directory for each test."""
    import intelligence.work_intelligence as wi

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    guards_dir = tmp_path / "guards"
    guards_dir.mkdir()

    monkeypatch.setattr(wi, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(wi, "WORK_LOG_PATH", knowledge_dir / "work_log.json")
    monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", knowledge_dir / "pattern_index.json")
    monkeypatch.setattr(wi, "PROMOTED_RULES_PATH", guards_dir / "promoted_rules.json")


def _make_mock_client(response_text: str) -> MagicMock:
    """Build a mock anthropic.Anthropic client that returns the given text."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


# ---------------------------------------------------------------------------
# analyze_new_bug
# ---------------------------------------------------------------------------


def test_analyze_new_bug_returns_bug_analysis() -> None:
    payload = json.dumps(
        {
            "pattern_tag": "rbac_cte_missing",
            "severity": "CRITICAL",
            "similar_bugs": [],
            "suggested_fix": None,
            "is_known_pattern": False,
        }
    )
    client = _make_mock_client(payload)
    intel = WorkIntelligence(client=client)

    result = intel.analyze_new_bug(
        description="RBAC CTE missing from SQL loader",
        app="peekr",
        layer="fastapi",
    )

    assert isinstance(result, BugAnalysis)
    assert result.pattern_tag == "rbac_cte_missing"
    assert result.severity == "CRITICAL"
    assert result.similar_bugs == []
    assert result.suggested_fix is None
    assert result.is_known_pattern is False


def test_analyze_new_bug_with_known_pattern() -> None:
    payload = json.dumps(
        {
            "pattern_tag": "rbac_cte_missing",
            "severity": "CRITICAL",
            "similar_bugs": ["bug-0001"],
            "suggested_fix": "Add WITH rbac AS (...) to top of query",
            "is_known_pattern": True,
        }
    )
    client = _make_mock_client(payload)
    intel = WorkIntelligence(client=client)

    result = intel.analyze_new_bug("RBAC CTE missing again", "new-hire", "fastapi")

    assert result.is_known_pattern is True
    assert "bug-0001" in result.similar_bugs
    assert result.suggested_fix is not None


def test_analyze_new_bug_strips_markdown_fences() -> None:
    payload = (
        "```json\n"
        + json.dumps(
            {
                "pattern_tag": "auth_missing",
                "severity": "WARNING",
                "similar_bugs": [],
                "suggested_fix": None,
                "is_known_pattern": False,
            }
        )
        + "\n```"
    )
    client = _make_mock_client(payload)
    intel = WorkIntelligence(client=client)

    result = intel.analyze_new_bug("Auth missing on endpoint", "agm", "java")
    assert result.pattern_tag == "auth_missing"


# ---------------------------------------------------------------------------
# check_prior_history
# ---------------------------------------------------------------------------


def test_check_prior_history_returns_empty_when_no_items() -> None:
    client = _make_mock_client("[]")
    intel = WorkIntelligence(client=client)

    results = intel.check_prior_history("some bug", "peekr")
    assert results == []
    # API should NOT be called when log is empty
    client.messages.create.assert_not_called()


def test_check_prior_history_finds_similar() -> None:
    write_work_log(
        {
            "items": [
                {
                    "id": "bug-0001",
                    "type": "BUG",
                    "status": "RESOLVED",
                    "app": "peekr",
                    "description": "RBAC CTE missing from user_query.sql",
                    "pattern_tag": "rbac_cte_missing",
                    "last_updated": "2026-02-14",
                },
                {
                    "id": "bug-0002",
                    "type": "BUG",
                    "status": "OPEN",
                    "app": "new-hire",
                    "description": "Missing auth header validation",
                    "pattern_tag": "auth_missing",
                    "last_updated": "2026-03-01",
                },
            ]
        }
    )

    client = _make_mock_client('["bug-0001"]')
    intel = WorkIntelligence(client=client)

    results = intel.check_prior_history("RBAC CTE missing from loader", "peekr")
    assert len(results) == 1
    assert results[0]["id"] == "bug-0001"


def test_check_prior_history_returns_sorted_by_recency() -> None:
    write_work_log(
        {
            "items": [
                {
                    "id": "bug-0001",
                    "type": "BUG",
                    "app": "peekr",
                    "description": "RBAC CTE missing v1",
                    "last_updated": "2026-01-01",
                },
                {
                    "id": "bug-0003",
                    "type": "BUG",
                    "app": "peekr",
                    "description": "RBAC CTE missing v3",
                    "last_updated": "2026-03-01",
                },
            ]
        }
    )

    client = _make_mock_client('["bug-0001", "bug-0003"]')
    intel = WorkIntelligence(client=client)

    results = intel.check_prior_history("RBAC CTE missing", "peekr")
    assert results[0]["id"] == "bug-0003"  # most recent first


# ---------------------------------------------------------------------------
# should_promote_to_guard
# ---------------------------------------------------------------------------


def test_should_promote_not_triggered_with_one_failed_attempt() -> None:
    write_work_log(
        {
            "items": [
                {
                    "id": "bug-0001",
                    "type": "BUG",
                    "status": "PERSISTING",
                    "app": "peekr",
                    "description": "RBAC CTE missing",
                    "pattern_tag": "rbac_cte_missing",
                    "attempts": [
                        {
                            "attempt": 1,
                            "date": "2026-03-01",
                            "fix_applied": "Added CTE",
                            "resolved": False,
                            "resolved_date": None,
                        }
                    ],
                    "promoted_to_guard": False,
                    "promotion_declined": False,
                }
            ]
        }
    )
    write_pattern_index(
        {
            "patterns": {
                "rbac_cte_missing": {
                    "tag": "rbac_cte_missing",
                    "occurrences": 1,
                    "apps_affected": ["peekr"],
                    "item_ids": ["bug-0001"],
                    "promoted_to_guard": False,
                    "guard_rule_id": None,
                }
            }
        }
    )

    client = MagicMock()
    intel = WorkIntelligence(client=client)

    rec = intel.should_promote_to_guard("bug-0001")
    assert rec.should_promote is False


def test_should_promote_triggered_with_two_failed_attempts() -> None:
    write_work_log(
        {
            "items": [
                {
                    "id": "bug-0001",
                    "type": "BUG",
                    "status": "PERSISTING",
                    "app": "peekr",
                    "description": "RBAC CTE missing",
                    "pattern_tag": "rbac_cte_missing",
                    "attempts": [
                        {
                            "attempt": 1,
                            "date": "2026-03-01",
                            "fix_applied": "Fix attempt 1",
                            "resolved": False,
                            "resolved_date": None,
                        },
                        {
                            "attempt": 2,
                            "date": "2026-03-05",
                            "fix_applied": "Fix attempt 2",
                            "resolved": False,
                            "resolved_date": None,
                        },
                    ],
                    "promoted_to_guard": False,
                    "promotion_declined": False,
                }
            ]
        }
    )
    write_pattern_index({"patterns": {}})

    client = MagicMock()
    intel = WorkIntelligence(client=client)

    rec = intel.should_promote_to_guard("bug-0001")
    assert rec.should_promote is True
    assert "2 failed" in rec.reason
    assert rec.suggested_rule_id is not None


def test_should_promote_triggered_by_pattern_frequency() -> None:
    write_work_log(
        {
            "items": [
                {
                    "id": "bug-0005",
                    "type": "BUG",
                    "status": "OPEN",
                    "app": "new-hire",
                    "description": "RBAC CTE missing",
                    "pattern_tag": "rbac_cte_missing",
                    "attempts": [],
                    "promoted_to_guard": False,
                    "promotion_declined": False,
                }
            ]
        }
    )
    write_pattern_index(
        {
            "patterns": {
                "rbac_cte_missing": {
                    "tag": "rbac_cte_missing",
                    "occurrences": 3,
                    "apps_affected": ["peekr", "new-hire", "agm"],
                    "item_ids": ["bug-0001", "bug-0003", "bug-0005"],
                    "promoted_to_guard": False,
                    "guard_rule_id": None,
                }
            }
        }
    )

    client = MagicMock()
    intel = WorkIntelligence(client=client)

    rec = intel.should_promote_to_guard("bug-0005")
    assert rec.should_promote is True
    assert "rbac_cte_missing" in rec.reason


def test_should_promote_skipped_when_declined() -> None:
    write_work_log(
        {
            "items": [
                {
                    "id": "bug-0001",
                    "type": "BUG",
                    "status": "PERSISTING",
                    "app": "peekr",
                    "description": "RBAC CTE missing",
                    "pattern_tag": "rbac_cte_missing",
                    "attempts": [
                        {"attempt": 1, "resolved": False},
                        {"attempt": 2, "resolved": False},
                    ],
                    "promoted_to_guard": False,
                    "promotion_declined": True,
                }
            ]
        }
    )
    write_pattern_index({"patterns": {}})

    client = MagicMock()
    intel = WorkIntelligence(client=client)

    rec = intel.should_promote_to_guard("bug-0001")
    assert rec.should_promote is False


def test_should_promote_returns_false_for_missing_bug() -> None:
    write_work_log({"items": []})
    client = MagicMock()
    intel = WorkIntelligence(client=client)

    rec = intel.should_promote_to_guard("bug-9999")
    assert rec.should_promote is False
