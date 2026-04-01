"""Health Monitor — nightly digest across all 4 apps.

Runs in sequence (not parallel) to produce one coherent digest:
  1. Convention Guard read-only scan across all apps
  2. Work log analysis (open bugs, weekly activity, persisting bugs)
  3. Pattern index top patterns
  4. Anthropic synthesis call (claude-sonnet-4-6)
  5. Slack post (optional, skipped if SLACK_WEBHOOK_URL not set)
  6. Local output file ./output/health/{date}.md

Health monitor is read-only — it never modifies work_log.json or guard rules.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from utils.roo_client import RooClient

from orchestrators.base_orchestrator import BaseOrchestrator

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = _PROJECT_ROOT / "output" / "health"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AppGuardSummary:
    app_id: str
    app_name: str
    critical_count: int
    warning_count: int
    scan_error: str | None = None

    @property
    def status_icon(self) -> str:
        if self.scan_error:
            return "⚠"
        if self.critical_count > 0:
            return "🔴"
        if self.warning_count > 0:
            return "⚠"
        return "✅"

    @property
    def status_label(self) -> str:
        if self.scan_error:
            return f"scan error: {self.scan_error}"
        if self.critical_count > 0:
            return f"{self.critical_count} critical"
        if self.warning_count > 0:
            return f"{self.warning_count} warning(s)"
        return "Clean"


@dataclass
class BugActivitySummary:
    opened_this_week: int
    resolved_this_week: int
    open_by_app: dict[str, int]
    persisting_bugs: list[dict[str, Any]]


@dataclass
class PatternSummary:
    tag: str
    occurrences: int
    promoted: bool
    guard_rule_id: str | None


@dataclass
class HealthDigest:
    run_date: str
    guard_summaries: list[AppGuardSummary]
    bug_activity: BugActivitySummary
    top_patterns: list[PatternSummary]
    insight: str

    def to_slack_text(self) -> str:
        lines: list[str] = []
        lines.append(f"🏥 Daily Health Digest — {self.run_date}")
        lines.append("━" * 38)
        lines.append("")

        # Guard summary
        lines.append("📊 Guard Summary (all apps)")
        for gs in self.guard_summaries:
            name_padded = gs.app_name.ljust(24)
            lines.append(f"  {name_padded} {gs.status_icon} {gs.status_label}")
        lines.append("")

        # Bug activity
        ba = self.bug_activity
        persisting_count = len(ba.persisting_bugs)
        lines.append("🐛 Bug Activity (this week)")
        lines.append(
            f"  Opened: {ba.opened_this_week}  |  "
            f"Resolved: {ba.resolved_this_week}  |  "
            f"Persisting: {persisting_count}"
        )
        if ba.persisting_bugs:
            lines.append("")
            for bug in ba.persisting_bugs:
                attempts = len(bug.get("attempts", []))
                tag = bug.get("pattern_tag", "unknown-pattern")
                lines.append(
                    f"  Persisting: {bug['id']} — {bug.get('app', '?')} — "
                    f"{tag} ({attempts} fix attempt(s))"
                )
        lines.append("")

        # Top patterns
        lines.append("📈 Top Patterns")
        if self.top_patterns:
            for p in self.top_patterns:
                promoted_label = "  (promoted to guard ✅)" if p.promoted else ""
                lines.append(
                    f"  {p.tag:<28} {p.occurrences} occurrence(s){promoted_label}"
                )
        else:
            lines.append("  No patterns recorded yet.")
        lines.append("")

        # Weekly insight
        lines.append("🧠 Weekly Insight")
        lines.append(f"  {self.insight}")
        lines.append("")
        lines.append("━" * 38)
        lines.append("Run manually: python cli.py health")

        return "\n".join(lines)

    def to_markdown(self) -> str:
        return self.to_slack_text()


# ---------------------------------------------------------------------------
# Guard scan
# ---------------------------------------------------------------------------


async def _scan_app_guard(
    app_config: dict, connector: Any
) -> AppGuardSummary:
    """Run convention guard read-only on one app. Never posts PR comments."""
    from guards.convention_guard import run_guard

    app_id = app_config["id"]
    app_name = app_config.get("name", app_id)

    try:
        result = await run_guard(app_config, connector, pr_id=None)
        return AppGuardSummary(
            app_id=app_id,
            app_name=app_name,
            critical_count=len(result.critical_violations),
            warning_count=len(result.warning_violations),
        )
    except Exception as exc:
        logger.warning("Guard scan failed for %s: %s", app_id, exc)
        return AppGuardSummary(
            app_id=app_id,
            app_name=app_name,
            critical_count=0,
            warning_count=0,
            scan_error=str(exc)[:60],
        )


# ---------------------------------------------------------------------------
# Work log analysis
# ---------------------------------------------------------------------------


def _analyse_work_log() -> BugActivitySummary:
    from intelligence.work_intelligence import read_work_log

    log = read_work_log()
    items = log.get("items", [])

    week_ago = (date.today() - timedelta(days=7)).isoformat()
    today_str = date.today().isoformat()

    opened_this_week = 0
    resolved_this_week = 0
    open_by_app: dict[str, int] = {}
    persisting_bugs: list[dict[str, Any]] = []

    for item in items:
        if item.get("type") != "BUG":
            continue

        app = item.get("app", "unknown")
        status = item.get("status", "OPEN")

        # Opened this week
        first_seen = item.get("first_seen", "")
        if week_ago <= first_seen <= today_str:
            opened_this_week += 1

        # Resolved this week
        if status == "RESOLVED":
            for attempt in item.get("attempts", []):
                if attempt.get("resolved") and week_ago <= attempt.get("resolved_date", "") <= today_str:
                    resolved_this_week += 1
                    break

        # Open bugs by app
        if status in ("OPEN", "IN_PROGRESS", "PERSISTING"):
            open_by_app[app] = open_by_app.get(app, 0) + 1

        # Persisting bugs (2+ failed attempts)
        failed_attempts = [a for a in item.get("attempts", []) if not a.get("resolved", False)]
        if len(failed_attempts) >= 2 or status == "PERSISTING":
            persisting_bugs.append(item)

    return BugActivitySummary(
        opened_this_week=opened_this_week,
        resolved_this_week=resolved_this_week,
        open_by_app=open_by_app,
        persisting_bugs=persisting_bugs,
    )


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------


def _get_top_patterns(n: int = 3) -> list[PatternSummary]:
    from intelligence.work_intelligence import read_pattern_index

    index = read_pattern_index()
    patterns = index.get("patterns", {})

    sorted_patterns = sorted(
        patterns.values(),
        key=lambda p: p.get("occurrences", 0),
        reverse=True,
    )

    return [
        PatternSummary(
            tag=p["tag"],
            occurrences=p.get("occurrences", 0),
            promoted=p.get("promoted_to_guard", False),
            guard_rule_id=p.get("guard_rule_id"),
        )
        for p in sorted_patterns[:n]
    ]


# ---------------------------------------------------------------------------
# Anthropic synthesis
# ---------------------------------------------------------------------------


def _synthesize_insight(
    guard_summaries: list[AppGuardSummary],
    bug_activity: BugActivitySummary,
    top_patterns: list[PatternSummary],
    client: RooClient,
) -> str:
    data = {
        "guard_summary": [
            {
                "app": gs.app_name,
                "critical": gs.critical_count,
                "warnings": gs.warning_count,
                "status": gs.status_label,
            }
            for gs in guard_summaries
        ],
        "bug_activity": {
            "opened_this_week": bug_activity.opened_this_week,
            "resolved_this_week": bug_activity.resolved_this_week,
            "persisting_count": len(bug_activity.persisting_bugs),
            "open_by_app": bug_activity.open_by_app,
            "persisting_bugs": [
                {
                    "id": b["id"],
                    "app": b.get("app"),
                    "pattern": b.get("pattern_tag"),
                    "attempts": len(b.get("attempts", [])),
                }
                for b in bug_activity.persisting_bugs
            ],
        },
        "top_patterns": [
            {
                "tag": p.tag,
                "occurrences": p.occurrences,
                "promoted": p.promoted,
            }
            for p in top_patterns
        ],
    }

    system = (
        "You are a development health analyst for a team managing 4 full-stack applications.\n"
        "You receive structured data about code quality violations, bug trends, and recurring\n"
        "patterns. Produce a concise 2-3 sentence plain English insight that:\n"
        "1. Names the biggest risk or trend this week\n"
        "2. Calls out any app that needs attention\n"
        "3. Suggests one concrete focus area\n\n"
        "Be specific, not generic. Reference actual pattern names and app names.\n"
        "Return only the insight paragraph — no preamble, no markdown."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system,
        messages=[
            {
                "role": "user",
                "content": f"Health data for today:\n{json.dumps(data, indent=2)}",
            }
        ],
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Slack posting
# ---------------------------------------------------------------------------


def post_to_slack(text: str, webhook_url: str) -> bool:
    """POST digest text to Slack webhook. Returns True on success."""
    try:
        response = httpx.post(
            webhook_url,
            json={"text": text},
            timeout=10.0,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("Slack post failed with HTTP %s: %s", exc.response.status_code, exc)
        return False
    except Exception as exc:
        logger.error("Slack post failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


def write_output_file(digest: HealthDigest) -> Path:
    """Write digest markdown to ./output/health/{date}.md and return the path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{digest.run_date}.md"
    out_path.write_text(digest.to_markdown(), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_health_monitor(
    app_ids: list[str] | None = None,
    no_slack: bool = False,
    client: RooClient | None = None,
) -> HealthDigest:
    """Run the full health monitor and return the digest.

    Args:
        app_ids: If provided, only scan these app IDs. None means all 4 apps.
        no_slack: If True, skip the Slack post even if webhook URL is set.
        client: Anthropic client (injectable for testing).

    Returns:
        HealthDigest with all sections populated.
    """
    base = BaseOrchestrator()
    all_apps = base._apps

    if app_ids:
        target_apps = [a for a in all_apps if a["id"] in app_ids]
    else:
        target_apps = all_apps

    anthropic_client = client or RooClient()
    run_date = date.today().isoformat()

    # 1. Guard scan (read-only, no PR comments)
    guard_summaries: list[AppGuardSummary] = []
    for app_config in target_apps:
        summary = asyncio.run(_scan_app_guard(app_config, base.connector))
        guard_summaries.append(summary)

    # 2. Work log analysis
    bug_activity = _analyse_work_log()

    # 3. Top patterns
    top_patterns = _get_top_patterns(n=3)

    # 4. Anthropic synthesis (last — after all data collected)
    try:
        insight = _synthesize_insight(guard_summaries, bug_activity, top_patterns, anthropic_client)
    except Exception as exc:
        logger.error("Anthropic synthesis failed: %s", exc)
        insight = f"Insight unavailable (synthesis error: {exc})"

    digest = HealthDigest(
        run_date=run_date,
        guard_summaries=guard_summaries,
        bug_activity=bug_activity,
        top_patterns=top_patterns,
        insight=insight,
    )

    # 5. Write local output file
    out_path = write_output_file(digest)
    logger.info("Health digest written to %s", out_path)

    # 6. Slack post (optional)
    if not no_slack:
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if webhook_url:
            success = post_to_slack(digest.to_slack_text(), webhook_url)
            if success:
                logger.info("Health digest posted to Slack.")
            else:
                logger.warning("Slack post failed — digest still written to disk.")
        else:
            logger.warning("SLACK_WEBHOOK_URL not set — skipping Slack post.")

    return digest
