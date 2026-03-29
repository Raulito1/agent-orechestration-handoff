"""Work Intelligence — Anthropic-powered reasoning agent for work item tracking.

This is the only file in Phase 3 that calls the Anthropic API.
It uses claude-sonnet-4-6 for all intelligence calls.

JSON files are the single source of truth. All reads/writes are atomic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import anthropic

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
KNOWLEDGE_DIR = _PROJECT_ROOT / "knowledge"
WORK_LOG_PATH = KNOWLEDGE_DIR / "work_log.json"
PATTERN_INDEX_PATH = KNOWLEDGE_DIR / "pattern_index.json"
PROMOTED_RULES_PATH = _PROJECT_ROOT / "guards" / "promoted_rules.json"

# ---------------------------------------------------------------------------
# ID prefixes
# ---------------------------------------------------------------------------

TYPE_PREFIXES: dict[str, str] = {
    "BUG": "bug",
    "FEATURE": "feat",
    "ENHANCEMENT": "enh",
    "SPIKE": "spike",
    "CHORE": "chore",
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BugAnalysis:
    pattern_tag: str
    severity: str  # CRITICAL or WARNING
    similar_bugs: list[str]
    suggested_fix: str | None
    is_known_pattern: bool


@dataclass
class PromotionRecommendation:
    should_promote: bool
    reason: str
    suggested_rule_id: str | None
    suggested_rule_description: str | None


# ---------------------------------------------------------------------------
# JSON helpers — atomic read/write
# ---------------------------------------------------------------------------


def read_work_log() -> dict[str, Any]:
    if not WORK_LOG_PATH.exists():
        return {"items": []}
    return json.loads(WORK_LOG_PATH.read_text())


def write_work_log(data: dict[str, Any]) -> None:
    WORK_LOG_PATH.write_text(json.dumps(data, indent=2))


def read_pattern_index() -> dict[str, Any]:
    if not PATTERN_INDEX_PATH.exists():
        return {"patterns": {}}
    return json.loads(PATTERN_INDEX_PATH.read_text())


def write_pattern_index(data: dict[str, Any]) -> None:
    PATTERN_INDEX_PATH.write_text(json.dumps(data, indent=2))


def read_promoted_rules() -> dict[str, Any]:
    if not PROMOTED_RULES_PATH.exists():
        return {"rules": []}
    data = json.loads(PROMOTED_RULES_PATH.read_text())
    # Migrate legacy key from Phase 2 scaffold
    if "promoted_rules" in data and "rules" not in data:
        data = {"rules": data["promoted_rules"]}
    return data


def write_promoted_rules(data: dict[str, Any]) -> None:
    PROMOTED_RULES_PATH.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Work item CRUD helpers
# ---------------------------------------------------------------------------


def next_item_id(item_type: str) -> str:
    """Generate next sequential ID for the given type, e.g. 'bug-0003'."""
    prefix = TYPE_PREFIXES.get(item_type.upper(), "item")
    log = read_work_log()
    existing_nums = [
        int(item["id"].split("-")[1])
        for item in log["items"]
        if item["id"].startswith(f"{prefix}-")
    ]
    next_num = max(existing_nums, default=0) + 1
    return f"{prefix}-{next_num:04d}"


def append_work_item(item: dict[str, Any]) -> None:
    log = read_work_log()
    log["items"].append(item)
    write_work_log(log)


def update_work_item(item_id: str, updated: dict[str, Any]) -> bool:
    log = read_work_log()
    for i, item in enumerate(log["items"]):
        if item["id"] == item_id:
            log["items"][i] = updated
            write_work_log(log)
            return True
    return False


def get_work_item(item_id: str) -> dict[str, Any] | None:
    log = read_work_log()
    for item in log["items"]:
        if item["id"] == item_id:
            return item
    return None


# ---------------------------------------------------------------------------
# Pattern index helpers
# ---------------------------------------------------------------------------


def upsert_pattern(tag: str, description: str, item_id: str, app: str) -> None:
    """Insert or update a pattern entry in pattern_index.json."""
    index = read_pattern_index()
    patterns = index["patterns"]
    if tag not in patterns:
        patterns[tag] = {
            "tag": tag,
            "description": description,
            "occurrences": 0,
            "apps_affected": [],
            "item_ids": [],
            "promoted_to_guard": False,
            "guard_rule_id": None,
        }
    entry = patterns[tag]
    entry["occurrences"] = entry.get("occurrences", 0) + 1
    if item_id not in entry["item_ids"]:
        entry["item_ids"].append(item_id)
    if app not in entry["apps_affected"]:
        entry["apps_affected"].append(app)
    write_pattern_index(index)


def mark_pattern_promoted(tag: str, rule_id: str) -> None:
    index = read_pattern_index()
    if tag in index["patterns"]:
        index["patterns"][tag]["promoted_to_guard"] = True
        index["patterns"][tag]["guard_rule_id"] = rule_id
    write_pattern_index(index)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# WorkIntelligence — Anthropic-powered reasoning
# ---------------------------------------------------------------------------


class WorkIntelligence:
    """AI-powered reasoning layer for work item tracking.

    All Anthropic API calls are isolated here so tests can mock them cleanly.
    """

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_new_bug(
        self, description: str, app: str, layer: str
    ) -> BugAnalysis:
        """Analyse a new bug description against the known pattern index."""
        index = read_pattern_index()
        patterns_summary = json.dumps(index["patterns"], indent=2)

        system = (
            "You are a bug pattern analyzer for a full-stack development team.\n"
            "You maintain a pattern index of known bug types across 4 applications.\n"
            "Given a new bug description, you must:\n"
            "1. Identify if this matches a known pattern\n"
            "2. Assign a snake_case pattern tag\n"
            "3. Assess severity (CRITICAL if it's a security/data issue, WARNING otherwise)\n"
            "4. Suggest a fix if this pattern has been seen before\n"
            "Return ONLY valid JSON matching the BugAnalysis schema. No preamble."
        )

        user = (
            f"Bug description: {description}\n"
            f"App: {app}\n"
            f"Layer: {layer}\n\n"
            f"Known patterns:\n{patterns_summary}\n\n"
            "Return JSON with exactly these fields:\n"
            '{\n'
            '  "pattern_tag": "snake_case_tag",\n'
            '  "severity": "CRITICAL or WARNING",\n'
            '  "similar_bugs": ["bug-0001"],\n'
            '  "suggested_fix": "fix description or null",\n'
            '  "is_known_pattern": true\n'
            '}'
        )

        response = self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

        data = json.loads(_strip_fences(response.content[0].text))
        return BugAnalysis(
            pattern_tag=data["pattern_tag"],
            severity=data["severity"],
            similar_bugs=data.get("similar_bugs", []),
            suggested_fix=data.get("suggested_fix"),
            is_known_pattern=data.get("is_known_pattern", False),
        )

    def check_prior_history(
        self, description: str, app: str
    ) -> list[dict[str, Any]]:
        """Return prior work items that are similar to the given description."""
        log = read_work_log()
        if not log["items"]:
            return []

        candidates_summary = json.dumps(
            [
                {
                    "id": i["id"],
                    "description": i["description"],
                    "app": i.get("app"),
                    "pattern_tag": i.get("pattern_tag"),
                    "status": i.get("status"),
                }
                for i in log["items"]
            ],
            indent=2,
        )

        response = self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f'Find work items similar to: "{description}" for app "{app}".\n\n'
                        f"Existing items:\n{candidates_summary}\n\n"
                        "Return ONLY a JSON array of IDs that are semantically similar "
                        "(empty array [] if none match):\n"
                        '["bug-0001", ...]'
                    ),
                }
            ],
        )

        similar_ids: list[str] = json.loads(
            _strip_fences(response.content[0].text)
        )
        matching = [i for i in log["items"] if i["id"] in similar_ids]
        matching.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
        return matching

    def should_promote_to_guard(self, bug_id: str) -> PromotionRecommendation:
        """Determine if a bug should be promoted to a Convention Guard rule."""
        item = get_work_item(bug_id)
        if not item or item.get("type") != "BUG":
            return PromotionRecommendation(
                should_promote=False,
                reason="Item not found or not a bug",
                suggested_rule_id=None,
                suggested_rule_description=None,
            )

        if item.get("promoted_to_guard"):
            return PromotionRecommendation(
                should_promote=False,
                reason="Already promoted to guard",
                suggested_rule_id=None,
                suggested_rule_description=None,
            )

        if item.get("promotion_declined"):
            return PromotionRecommendation(
                should_promote=False,
                reason="Promotion previously declined",
                suggested_rule_id=None,
                suggested_rule_description=None,
            )

        failed_attempts = [
            a for a in item.get("attempts", []) if not a.get("resolved", False)
        ]

        pattern_tag = item.get("pattern_tag", "")
        index = read_pattern_index()
        pattern_count = 0
        if pattern_tag and pattern_tag in index["patterns"]:
            pattern_count = len(index["patterns"][pattern_tag]["item_ids"])

        trigger_by_attempts = len(failed_attempts) >= 2
        trigger_by_pattern = pattern_count >= 3

        if not (trigger_by_attempts or trigger_by_pattern):
            return PromotionRecommendation(
                should_promote=False,
                reason=(
                    f"Only {len(failed_attempts)} failed attempt(s) and "
                    f"pattern seen {pattern_count} time(s) — threshold not reached"
                ),
                suggested_rule_id=None,
                suggested_rule_description=None,
            )

        if trigger_by_attempts:
            reason = f"Bug '{bug_id}' has {len(failed_attempts)} failed fix attempts"
        else:
            apps = index["patterns"][pattern_tag]["apps_affected"]
            reason = (
                f"Pattern '{pattern_tag}' appears in {pattern_count} separate bugs "
                f"across {apps}"
            )

        rule_id = re.sub(r"[^a-z0-9_]", "_", pattern_tag.replace("-", "_")) if pattern_tag else bug_id.replace("-", "_")
        rule_description = (
            f"Files must not exhibit the '{pattern_tag}' pattern"
            if pattern_tag
            else f"Prevent recurrence of {bug_id}"
        )

        return PromotionRecommendation(
            should_promote=True,
            reason=reason,
            suggested_rule_id=rule_id,
            suggested_rule_description=rule_description,
        )

    def generate_pattern_tag(self, description: str) -> str:
        """Generate a short, consistent snake_case pattern tag from a description."""
        response = self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=50,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f'Generate a short snake_case bug pattern tag for: "{description}"\n'
                        "Return ONLY the tag (e.g. rbac_cte_missing), nothing else."
                    ),
                }
            ],
        )
        raw = response.content[0].text.strip().lower()
        tag = re.sub(r"[^a-z0-9_]", "_", raw.replace("-", "_"))
        tag = re.sub(r"_+", "_", tag).strip("_")
        return tag
