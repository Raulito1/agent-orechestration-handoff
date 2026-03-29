"""Tests for work_log.json helpers in work_intelligence.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from intelligence.work_intelligence import (
    append_work_item,
    get_work_item,
    next_item_id,
    read_work_log,
    today,
    update_work_item,
    write_work_log,
)


@pytest.fixture(autouse=True)
def isolated_knowledge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import intelligence.work_intelligence as wi

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    monkeypatch.setattr(wi, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(wi, "WORK_LOG_PATH", knowledge_dir / "work_log.json")


# ---------------------------------------------------------------------------
# next_item_id
# ---------------------------------------------------------------------------


def test_next_item_id_first_bug() -> None:
    write_work_log({"items": []})
    assert next_item_id("BUG") == "bug-0001"


def test_next_item_id_increments() -> None:
    write_work_log(
        {
            "items": [
                {"id": "bug-0001", "type": "BUG"},
                {"id": "bug-0002", "type": "BUG"},
            ]
        }
    )
    assert next_item_id("BUG") == "bug-0003"


def test_next_item_id_type_isolation() -> None:
    write_work_log(
        {
            "items": [
                {"id": "bug-0001", "type": "BUG"},
                {"id": "feat-0001", "type": "FEATURE"},
            ]
        }
    )
    assert next_item_id("FEATURE") == "feat-0002"
    assert next_item_id("BUG") == "bug-0002"


def test_next_item_id_prefixes() -> None:
    write_work_log({"items": []})
    assert next_item_id("ENHANCEMENT").startswith("enh-")
    assert next_item_id("SPIKE").startswith("spike-")
    assert next_item_id("CHORE").startswith("chore-")


def test_next_item_id_zero_padded_four_digits() -> None:
    write_work_log({"items": []})
    item_id = next_item_id("BUG")
    _, num = item_id.split("-")
    assert len(num) == 4
    assert num == "0001"


# ---------------------------------------------------------------------------
# append_work_item
# ---------------------------------------------------------------------------


def test_append_work_item_adds_to_empty_log() -> None:
    write_work_log({"items": []})
    item = {"id": "bug-0001", "type": "BUG", "description": "test bug"}
    append_work_item(item)
    log = read_work_log()
    assert len(log["items"]) == 1
    assert log["items"][0]["id"] == "bug-0001"


def test_append_work_item_preserves_existing() -> None:
    write_work_log({"items": [{"id": "bug-0001", "type": "BUG"}]})
    append_work_item({"id": "bug-0002", "type": "BUG"})
    log = read_work_log()
    assert len(log["items"]) == 2


def test_append_multiple_items() -> None:
    write_work_log({"items": []})
    for i in range(1, 4):
        append_work_item({"id": f"bug-{i:04d}", "type": "BUG"})
    log = read_work_log()
    assert len(log["items"]) == 3


# ---------------------------------------------------------------------------
# get_work_item / update_work_item
# ---------------------------------------------------------------------------


def test_get_work_item_returns_correct_item() -> None:
    write_work_log(
        {
            "items": [
                {"id": "bug-0001", "type": "BUG", "status": "OPEN"},
                {"id": "bug-0002", "type": "BUG", "status": "RESOLVED"},
            ]
        }
    )
    item = get_work_item("bug-0002")
    assert item is not None
    assert item["status"] == "RESOLVED"


def test_get_work_item_returns_none_for_missing() -> None:
    write_work_log({"items": []})
    assert get_work_item("bug-9999") is None


def test_update_work_item_modifies_in_place() -> None:
    write_work_log(
        {"items": [{"id": "bug-0001", "type": "BUG", "status": "OPEN"}]}
    )
    item = get_work_item("bug-0001")
    assert item is not None
    item["status"] = "RESOLVED"
    update_work_item("bug-0001", item)

    updated = get_work_item("bug-0001")
    assert updated is not None
    assert updated["status"] == "RESOLVED"


def test_update_work_item_returns_false_for_missing() -> None:
    write_work_log({"items": []})
    result = update_work_item("bug-9999", {"id": "bug-9999"})
    assert result is False


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def test_bug_status_transitions() -> None:
    """BUG items follow OPEN → PERSISTING → RESOLVED path."""
    write_work_log({"items": []})
    item = {
        "id": "bug-0001",
        "type": "BUG",
        "status": "OPEN",
        "attempts": [],
        "app": "peekr",
        "description": "test",
        "first_seen": today(),
        "last_updated": today(),
    }
    append_work_item(item)

    # Simulate first failed attempt → PERSISTING
    item["attempts"].append(
        {"attempt": 1, "date": today(), "fix_applied": "try 1", "resolved": False}
    )
    item["status"] = "PERSISTING"
    item["last_updated"] = today()
    update_work_item("bug-0001", item)
    assert get_work_item("bug-0001")["status"] == "PERSISTING"

    # Simulate resolution → RESOLVED
    item["attempts"].append(
        {"attempt": 2, "date": today(), "fix_applied": "try 2", "resolved": True, "resolved_date": today()}
    )
    item["status"] = "RESOLVED"
    update_work_item("bug-0001", item)
    assert get_work_item("bug-0001")["status"] == "RESOLVED"
