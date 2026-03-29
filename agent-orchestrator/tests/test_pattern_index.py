"""Tests for pattern_index.json helpers in work_intelligence.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from intelligence.work_intelligence import (
    mark_pattern_promoted,
    read_pattern_index,
    upsert_pattern,
    write_pattern_index,
)


@pytest.fixture(autouse=True)
def isolated_knowledge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import intelligence.work_intelligence as wi

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    monkeypatch.setattr(wi, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(wi, "PATTERN_INDEX_PATH", knowledge_dir / "pattern_index.json")


# ---------------------------------------------------------------------------
# upsert_pattern
# ---------------------------------------------------------------------------


def test_upsert_pattern_creates_new_entry() -> None:
    write_pattern_index({"patterns": {}})
    upsert_pattern("rbac_cte_missing", "SQL file missing RBAC CTE", "bug-0001", "peekr")

    index = read_pattern_index()
    assert "rbac_cte_missing" in index["patterns"]
    entry = index["patterns"]["rbac_cte_missing"]
    assert entry["occurrences"] == 1
    assert "peekr" in entry["apps_affected"]
    assert "bug-0001" in entry["item_ids"]
    assert entry["promoted_to_guard"] is False


def test_upsert_pattern_increments_existing() -> None:
    write_pattern_index(
        {
            "patterns": {
                "rbac_cte_missing": {
                    "tag": "rbac_cte_missing",
                    "description": "SQL file missing RBAC CTE",
                    "occurrences": 1,
                    "apps_affected": ["peekr"],
                    "item_ids": ["bug-0001"],
                    "promoted_to_guard": False,
                    "guard_rule_id": None,
                }
            }
        }
    )
    upsert_pattern("rbac_cte_missing", "SQL file missing RBAC CTE", "bug-0002", "new-hire")

    index = read_pattern_index()
    entry = index["patterns"]["rbac_cte_missing"]
    assert entry["occurrences"] == 2
    assert "new-hire" in entry["apps_affected"]
    assert "bug-0002" in entry["item_ids"]
    assert len(entry["apps_affected"]) == 2


def test_upsert_pattern_does_not_duplicate_app() -> None:
    write_pattern_index({"patterns": {}})
    upsert_pattern("auth_missing", "Auth not enforced", "bug-0001", "peekr")
    upsert_pattern("auth_missing", "Auth not enforced", "bug-0002", "peekr")  # same app

    index = read_pattern_index()
    entry = index["patterns"]["auth_missing"]
    assert entry["apps_affected"].count("peekr") == 1  # no duplicates


def test_upsert_pattern_does_not_duplicate_item_id() -> None:
    write_pattern_index({"patterns": {}})
    upsert_pattern("auth_missing", "Auth not enforced", "bug-0001", "peekr")
    upsert_pattern("auth_missing", "Auth not enforced", "bug-0001", "peekr")  # same id

    index = read_pattern_index()
    entry = index["patterns"]["auth_missing"]
    assert entry["item_ids"].count("bug-0001") == 1


def test_upsert_multiple_distinct_patterns() -> None:
    write_pattern_index({"patterns": {}})
    upsert_pattern("rbac_cte_missing", "RBAC CTE", "bug-0001", "peekr")
    upsert_pattern("auth_missing", "Auth missing", "bug-0002", "agm")
    upsert_pattern("block_call_in_webflux", "Blocking call", "bug-0003", "agm")

    index = read_pattern_index()
    assert len(index["patterns"]) == 3


# ---------------------------------------------------------------------------
# mark_pattern_promoted
# ---------------------------------------------------------------------------


def test_mark_pattern_promoted_sets_flags() -> None:
    write_pattern_index(
        {
            "patterns": {
                "rbac_cte_missing": {
                    "tag": "rbac_cte_missing",
                    "description": "SQL file missing RBAC CTE",
                    "occurrences": 3,
                    "apps_affected": ["peekr", "new-hire"],
                    "item_ids": ["bug-0001", "bug-0002", "bug-0003"],
                    "promoted_to_guard": False,
                    "guard_rule_id": None,
                }
            }
        }
    )
    mark_pattern_promoted("rbac_cte_missing", "rbac_cte_present")

    index = read_pattern_index()
    entry = index["patterns"]["rbac_cte_missing"]
    assert entry["promoted_to_guard"] is True
    assert entry["guard_rule_id"] == "rbac_cte_present"


def test_mark_pattern_promoted_noop_for_unknown_tag() -> None:
    write_pattern_index({"patterns": {}})
    # Should not raise
    mark_pattern_promoted("nonexistent_tag", "some_rule")
    index = read_pattern_index()
    assert len(index["patterns"]) == 0


# ---------------------------------------------------------------------------
# Persistence — read / write round-trip
# ---------------------------------------------------------------------------


def test_pattern_index_round_trip() -> None:
    original = {
        "patterns": {
            "my_pattern": {
                "tag": "my_pattern",
                "description": "A test pattern",
                "occurrences": 5,
                "apps_affected": ["peekr"],
                "item_ids": ["bug-0001"],
                "promoted_to_guard": False,
                "guard_rule_id": None,
            }
        }
    }
    write_pattern_index(original)
    loaded = read_pattern_index()
    assert loaded == original


def test_read_pattern_index_returns_empty_when_missing() -> None:
    # File does not exist in the tmp_path
    index = read_pattern_index()
    assert index == {"patterns": {}}
