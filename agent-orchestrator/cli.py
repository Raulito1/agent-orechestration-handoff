from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()  # Must be called before any module that reads env vars.

import asyncio
from typing import Optional

import typer

app = typer.Typer(help="Agent Orchestrator — AI-powered multi-app CLI.")

# ---------------------------------------------------------------------------
# Sub-app groups
# ---------------------------------------------------------------------------

log_app = typer.Typer(help="Log work items (bug, feature, spike, enhancement, chore).")
work_app = typer.Typer(help="Query work items and patterns.")
rpi_app = typer.Typer(help="RPI workflow: Research → Plan → Implement across repos in parallel.")

app.add_typer(log_app, name="log")
app.add_typer(work_app, name="work")
app.add_typer(rpi_app, name="rpi")


# ---------------------------------------------------------------------------
# Phase 4 — feature generation
# ---------------------------------------------------------------------------


@app.command()
def feature(
    description: str = typer.Argument(..., help="Feature description."),
    app_id: str = typer.Option(..., "--app", help="Target app id."),
) -> None:
    """Generate a full-stack feature across backend and frontend."""
    from intelligence.work_intelligence import append_work_item, next_item_id, today
    from orchestrators.base_orchestrator import BaseOrchestrator

    base = BaseOrchestrator()
    app_config = base.get_app(app_id)
    app_name = app_config.get("name", app_id)
    stack = app_config.get("stack", "")

    typer.echo(f"Feature: {description}")
    typer.echo(f"App: {app_name} ({stack})")
    typer.echo("")

    # Choose orchestrator based on stack
    is_java = stack.startswith("java") or stack.startswith("spring")

    if is_java:
        from orchestrators.java_orchestrator import JavaOrchestrator
        orchestrator = JavaOrchestrator()
        backend_label = "Java Spring Boot"
        backend_files_order = ["controller", "service", "repository", "migration", "request_dto", "response_dto", "mapper"]
        backend_filenames = {
            "controller": "Controller.java",
            "service": "Service.java",
            "repository": "Repository.java",
            "migration": "migration.yaml",
            "request_dto": "RequestDTO.java",
            "response_dto": "ResponseDTO.java",
            "mapper": "Mapper.java",
        }
    else:
        from orchestrators.fastapi_orchestrator import FastAPIOrchestrator
        orchestrator = FastAPIOrchestrator()
        backend_label = "FastAPI"
        backend_files_order = ["router", "service", "repository", "sql", "request_model", "response_model"]
        backend_filenames = {
            "router": "router.py",
            "service": "service.py",
            "repository": "repository.py",
            "sql": "sql",
            "request_model": "request_model.py",
            "response_model": "response_model.py",
        }

    step = [0]

    def progress(event: str, data=None) -> None:
        if event in ("fastapi_start", "java_start"):
            step[0] += 1
            typer.echo(f"[1/3] Running {backend_label} sub agent...")
        elif event in ("fastapi_done", "java_done"):
            if data:
                for ft in backend_files_order:
                    fname = backend_filenames.get(ft, ft)
                    typer.echo(f"  \u2713 {fname}")
        elif event == "contract_done":
            step[0] += 1
            endpoints = len(data.get("endpoints", [])) if data else 0
            models = len(data.get("models", [])) if data else 0
            typer.echo(f"\n[2/3] Extracting API contract...")
            typer.echo(f"  \u2713 {endpoints} endpoint(s), {models} model(s)")
        elif event == "react_start":
            step[0] += 1
            typer.echo(f"\n[3/3] Running React sub agent...")
        elif event == "react_done":
            if data:
                react_names = {"rtk_endpoint": "apiSlice.ts", "ts_types": "types.ts", "component": "Component.tsx"}
                for ft in ["rtk_endpoint", "ts_types", "component"]:
                    typer.echo(f"  \u2713 {react_names[ft]}")

    result = orchestrator.run(description, app_id, progress_callback=progress)

    # Auto-create FEATURE work item
    item_id = next_item_id("FEATURE")
    work_item = {
        "id": item_id,
        "type": "FEATURE",
        "status": "IN_PROGRESS",
        "app": app_id,
        "description": description,
        "first_seen": today(),
        "last_updated": today(),
        "output_directory": result.output_directory,
        "related_item_ids": [],
    }
    append_work_item(work_item)

    typer.echo("")
    typer.echo("\u2500" * 38)
    typer.echo(f"Output: ./{result.output_directory}")
    typer.echo(f"Work item created: {item_id}")
    typer.echo("")
    typer.echo("Review the generated files before copying to your repos.")
    typer.echo(f"Run guard after integrating: python cli.py guard --app {app_id}")


# ---------------------------------------------------------------------------
# Phase 2 — convention guard
# ---------------------------------------------------------------------------


@app.command()
def guard(
    app_id: str = typer.Option(..., "--app", help="Target app id, or 'all'."),
    pr_id: str | None = typer.Option(None, "--pr-id", help="PR id for Bitbucket comment (Jenkins use)."),
) -> None:
    """Run convention guard checks against an app. Exits 1 on critical violations."""
    from guards.convention_guard import format_terminal_output, run_guard
    from orchestrators.base_orchestrator import BaseOrchestrator

    orchestrator = BaseOrchestrator()
    all_apps = orchestrator._apps

    target_apps = all_apps if app_id == "all" else [orchestrator.get_app(app_id)]

    any_failed = False
    for app_config in target_apps:
        result = asyncio.run(
            run_guard(app_config, orchestrator.connector, pr_id=pr_id)
        )
        output = format_terminal_output(app_config.get("name", app_config["id"]), result)
        typer.echo(output)
        if not result.passed:
            any_failed = True

    if any_failed:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Phase 3 — work item logging
# ---------------------------------------------------------------------------


@log_app.command("bug")
def log_bug(
    app_id: str = typer.Option(..., "--app", help="Target app id."),
    layer: str = typer.Option(..., "--layer", help="Affected layer (e.g. fastapi, react)."),
    description: str = typer.Argument(..., help="Bug description."),
) -> None:
    """Log a bug work item with self-healing history lookup."""
    from intelligence.work_intelligence import (
        BugAnalysis,
        append_work_item,
        get_work_item,
        mark_pattern_promoted,
        next_item_id,
        read_promoted_rules,
        today,
        update_work_item,
        upsert_pattern,
        write_promoted_rules,
        WorkIntelligence,
    )

    intel = WorkIntelligence()

    typer.echo("Analysing bug against known patterns…")
    analysis: BugAnalysis = intel.analyze_new_bug(description, app_id, layer)

    related_ids: list[str] = []

    if analysis.is_known_pattern and analysis.similar_bugs:
        # Surface the most recent similar bug
        prior_id = analysis.similar_bugs[0]
        prior = get_work_item(prior_id)
        if prior:
            typer.echo("")
            typer.echo(f"⚠ Similar issue found:")
            typer.echo("")
            resolved_label = ""
            if prior.get("status") == "RESOLVED":
                attempts = prior.get("attempts", [])
                resolved_attempt = next((a for a in reversed(attempts) if a.get("resolved")), None)
                if resolved_attempt:
                    resolved_label = f", resolved {resolved_attempt.get('resolved_date', '')}"
            typer.echo(f"  {prior['id']} ({prior.get('app', '?')}{resolved_label})")
            typer.echo(f"  \"{prior['description']}\"")
            if analysis.suggested_fix:
                typer.echo(f"  Fix applied: {analysis.suggested_fix}")
            typer.echo("")
            choice = typer.prompt("Is this the same issue? [y/n/new]").strip().lower()

            if choice == "y":
                # Link to existing — log as new occurrence on the existing bug
                prior["occurrences_across_apps"] = list(
                    set(prior.get("occurrences_across_apps", [prior.get("app", app_id)]) + [app_id])
                )
                prior["last_updated"] = today()
                update_work_item(prior_id, prior)
                typer.echo(f"Linked to existing bug {prior_id}.")
                _check_and_prompt_promotion(prior_id, intel)
                return
            elif choice == "new":
                related_ids = [prior_id]
            # "n" → fall through and log as completely new

    # Create the new bug item
    item_id = next_item_id("BUG")
    item = {
        "id": item_id,
        "type": "BUG",
        "status": "OPEN",
        "severity": analysis.severity,
        "app": app_id,
        "layer": layer,
        "pattern_tag": analysis.pattern_tag,
        "description": description,
        "first_seen": today(),
        "last_updated": today(),
        "attempts": [],
        "promoted_to_guard": False,
        "promotion_declined": False,
        "guard_rule_id": None,
        "occurrences_across_apps": [app_id],
        "related_item_ids": related_ids,
    }
    append_work_item(item)
    upsert_pattern(analysis.pattern_tag, description, item_id, app_id)
    typer.echo(f"Logged {item_id} [{analysis.severity}] — {analysis.pattern_tag}")

    _check_and_prompt_promotion(item_id, intel)


def _check_and_prompt_promotion(bug_id: str, intel: "WorkIntelligence") -> None:
    """Check if a bug warrants guard promotion and prompt the user."""
    from intelligence.work_intelligence import (
        get_work_item,
        mark_pattern_promoted,
        read_promoted_rules,
        read_pattern_index,
        today,
        update_work_item,
        write_promoted_rules,
    )

    rec = intel.should_promote_to_guard(bug_id)
    if not rec.should_promote:
        return

    item = get_work_item(bug_id)
    if not item:
        return

    pattern_tag = item.get("pattern_tag", "")
    index = read_pattern_index()
    affected_apps: list[str] = []
    if pattern_tag and pattern_tag in index["patterns"]:
        affected_apps = index["patterns"][pattern_tag]["apps_affected"]

    typer.echo("")
    typer.echo("💡 Promotion recommended:")
    typer.echo("")
    typer.echo(f"  {rec.reason}")
    typer.echo(f"  Suggested guard rule: {rec.suggested_rule_id}")
    typer.echo("")

    promote = typer.confirm("Promote to Convention Guard?")
    if promote:
        rules_data = read_promoted_rules()
        rules_data["rules"].append(
            {
                "rule_id": rec.suggested_rule_id,
                "promoted_from_bug": bug_id,
                "pattern_tag": pattern_tag,
                "description": rec.suggested_rule_description,
                "promoted_date": today(),
                "apps_affected": affected_apps,
                "active": True,
            }
        )
        write_promoted_rules(rules_data)

        item["promoted_to_guard"] = True
        item["guard_rule_id"] = rec.suggested_rule_id
        item["last_updated"] = today()
        update_work_item(bug_id, item)

        mark_pattern_promoted(pattern_tag, rec.suggested_rule_id)
        typer.echo(f"Rule '{rec.suggested_rule_id}' promoted to Convention Guard.")
    else:
        item["promotion_declined"] = True
        item["last_updated"] = today()
        update_work_item(bug_id, item)
        typer.echo("Promotion declined — will not prompt again for this bug.")


@log_app.command("feature")
def log_feature(
    app_id: str = typer.Option(..., "--app", help="Target app id."),
    layer: Optional[str] = typer.Option(None, "--layer", help="Affected layer (optional)."),
    description: str = typer.Argument(..., help="Feature description."),
) -> None:
    """Log a feature work item."""
    _log_simple_item("FEATURE", app_id, description, layer)


@log_app.command("enhancement")
def log_enhancement(
    app_id: str = typer.Option(..., "--app", help="Target app id."),
    layer: Optional[str] = typer.Option(None, "--layer", help="Affected layer (optional)."),
    description: str = typer.Argument(..., help="Enhancement description."),
) -> None:
    """Log an enhancement work item."""
    _log_simple_item("ENHANCEMENT", app_id, description, layer)


@log_app.command("spike")
def log_spike(
    app_id: str = typer.Option(..., "--app", help="Target app id."),
    description: str = typer.Argument(..., help="Spike description."),
) -> None:
    """Log a spike (investigation) work item."""
    _log_simple_item("SPIKE", app_id, description, layer=None)


@log_app.command("chore")
def log_chore(
    app_id: str = typer.Option(..., "--app", help="Target app id."),
    description: str = typer.Argument(..., help="Chore description."),
) -> None:
    """Log a chore work item."""
    _log_simple_item("CHORE", app_id, description, layer=None)


def _log_simple_item(
    item_type: str, app_id: str, description: str, layer: str | None
) -> None:
    from intelligence.work_intelligence import append_work_item, next_item_id, today

    item_id = next_item_id(item_type)
    item: dict = {
        "id": item_id,
        "type": item_type,
        "status": "OPEN",
        "app": app_id,
        "description": description,
        "first_seen": today(),
        "last_updated": today(),
        "related_item_ids": [],
        "notes": "",
    }
    if layer:
        item["layer"] = layer
    append_work_item(item)
    typer.echo(f"Logged {item_id} — {description}")


# ---------------------------------------------------------------------------
# Phase 3 — work item queries
# ---------------------------------------------------------------------------


@work_app.command("patterns")
def work_patterns() -> None:
    """Show recurring patterns across logged work items."""
    from intelligence.work_intelligence import read_pattern_index

    index = read_pattern_index()
    patterns = index.get("patterns", {})

    if not patterns:
        typer.echo("No patterns recorded yet.")
        return

    sep = "─" * 50
    typer.echo(sep)
    typer.echo(f"{'TAG':<30} {'OCC':>4}  {'APPS'}")
    typer.echo(sep)
    for tag, p in sorted(patterns.items(), key=lambda x: x[1]["occurrences"], reverse=True):
        promoted = " [PROMOTED]" if p.get("promoted_to_guard") else ""
        apps = ", ".join(p.get("apps_affected", []))
        typer.echo(f"{tag:<30} {p['occurrences']:>4}  {apps}{promoted}")
    typer.echo(sep)
    typer.echo(f"Total patterns: {len(patterns)}")


@work_app.command("history")
def work_history(
    app_id: Optional[str] = typer.Option(None, "--app", help="Filter by app id."),
    item_type: Optional[str] = typer.Option(None, "--type", help="Filter by type (bug, feature, etc.)."),
) -> None:
    """Show work item history, optionally filtered by app or type."""
    from intelligence.work_intelligence import read_work_log

    log = read_work_log()
    items = log.get("items", [])

    if app_id:
        items = [i for i in items if i.get("app") == app_id]
    if item_type:
        items = [i for i in items if i.get("type", "").lower() == item_type.lower()]

    if not items:
        typer.echo("No work items found.")
        return

    sep = "─" * 60
    typer.echo(sep)
    for item in sorted(items, key=lambda x: x.get("last_updated", ""), reverse=True):
        status = item.get("status", "?")
        itype = item.get("type", "?")
        app = item.get("app", "?")
        desc = item["description"]
        if len(desc) > 55:
            desc = desc[:52] + "..."
        typer.echo(f"{item['id']}  [{itype:<12}] [{status:<11}] {app}")
        typer.echo(f"  {desc}")
    typer.echo(sep)
    typer.echo(f"Total: {len(items)}")


@work_app.command("item")
def work_item(
    item_id: str = typer.Argument(..., help="Work item id (e.g. bug-0012)."),
) -> None:
    """Show full detail for a specific work item."""
    from intelligence.work_intelligence import get_work_item

    item = get_work_item(item_id)
    if not item:
        typer.echo(f"Item '{item_id}' not found.", err=True)
        raise typer.Exit(code=1)

    sep = "─" * 50
    typer.echo(sep)
    typer.echo(f"ID:          {item['id']}")
    typer.echo(f"Type:        {item.get('type', '?')}")
    typer.echo(f"Status:      {item.get('status', '?')}")
    typer.echo(f"App:         {item.get('app', '?')}")
    if item.get("layer"):
        typer.echo(f"Layer:       {item['layer']}")
    if item.get("severity"):
        typer.echo(f"Severity:    {item['severity']}")
    if item.get("pattern_tag"):
        typer.echo(f"Pattern:     {item['pattern_tag']}")
    typer.echo(f"Description: {item['description']}")
    typer.echo(f"First seen:  {item.get('first_seen', '?')}")
    typer.echo(f"Updated:     {item.get('last_updated', '?')}")

    attempts = item.get("attempts", [])
    if attempts:
        typer.echo("")
        typer.echo(f"Fix attempts ({len(attempts)}):")
        for a in attempts:
            resolved = "✓ resolved" if a.get("resolved") else "✗ failed"
            typer.echo(f"  #{a['attempt']}  {a['date']}  [{resolved}]")
            typer.echo(f"      {a['fix_applied']}")

    if item.get("promoted_to_guard"):
        typer.echo(f"Guard rule:  {item.get('guard_rule_id')}")
    if item.get("related_item_ids"):
        typer.echo(f"Related:     {', '.join(item['related_item_ids'])}")
    if item.get("notes"):
        typer.echo(f"Notes:       {item['notes']}")
    typer.echo(sep)


# ---------------------------------------------------------------------------
# Phase 3 — bug lifecycle commands
# ---------------------------------------------------------------------------


@work_app.command("attempt")
def work_attempt(
    bug_id: str = typer.Argument(..., help="Bug id (e.g. bug-0012)."),
    fix_description: str = typer.Argument(..., help="Description of the fix applied."),
) -> None:
    """Log a fix attempt on an open or persisting bug."""
    from intelligence.work_intelligence import (
        WorkIntelligence,
        get_work_item,
        today,
        update_work_item,
    )

    item = get_work_item(bug_id)
    if not item:
        typer.echo(f"Bug '{bug_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if item.get("type") != "BUG":
        typer.echo(f"'{bug_id}' is not a bug.", err=True)
        raise typer.Exit(code=1)
    if item.get("status") == "RESOLVED":
        typer.echo(f"Bug '{bug_id}' is already resolved.", err=True)
        raise typer.Exit(code=1)

    attempts = item.get("attempts", [])
    attempt_num = len(attempts) + 1
    attempts.append(
        {
            "attempt": attempt_num,
            "date": today(),
            "fix_applied": fix_description,
            "resolved": False,
            "resolved_date": None,
        }
    )
    item["attempts"] = attempts
    item["status"] = "PERSISTING" if attempt_num > 1 else "OPEN"
    item["last_updated"] = today()
    update_work_item(bug_id, item)

    typer.echo(f"Attempt #{attempt_num} logged for {bug_id}.")

    intel = WorkIntelligence()
    _check_and_prompt_promotion(bug_id, intel)


@work_app.command("resolve")
def work_resolve(
    bug_id: str = typer.Argument(..., help="Bug id (e.g. bug-0012)."),
    resolution: str = typer.Argument(..., help="Description of the resolution."),
) -> None:
    """Mark a bug as resolved."""
    from intelligence.work_intelligence import get_work_item, today, update_work_item

    item = get_work_item(bug_id)
    if not item:
        typer.echo(f"Bug '{bug_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if item.get("type") != "BUG":
        typer.echo(f"'{bug_id}' is not a bug.", err=True)
        raise typer.Exit(code=1)

    attempts = item.get("attempts", [])
    attempt_num = len(attempts) + 1
    attempts.append(
        {
            "attempt": attempt_num,
            "date": today(),
            "fix_applied": resolution,
            "resolved": True,
            "resolved_date": today(),
        }
    )
    item["attempts"] = attempts
    item["status"] = "RESOLVED"
    item["last_updated"] = today()
    update_work_item(bug_id, item)

    typer.echo(f"Bug {bug_id} marked RESOLVED.")


@work_app.command("promoted")
def work_promoted() -> None:
    """Show all guard rules promoted from bugs."""
    from intelligence.work_intelligence import read_promoted_rules

    data = read_promoted_rules()
    rules = data.get("rules", [])

    if not rules:
        typer.echo("No guard rules promoted yet.")
        return

    sep = "─" * 60
    typer.echo(sep)
    for rule in rules:
        active = "active" if rule.get("active") else "inactive"
        typer.echo(f"{rule['rule_id']}  [{active}]")
        typer.echo(f"  Pattern:  {rule.get('pattern_tag', '?')}")
        typer.echo(f"  From bug: {rule.get('promoted_from_bug', '?')}")
        typer.echo(f"  Promoted: {rule.get('promoted_date', '?')}")
        typer.echo(f"  Desc:     {rule.get('description', '?')}")
        typer.echo(f"  Apps:     {', '.join(rule.get('apps_affected', []))}")
    typer.echo(sep)
    typer.echo(f"Total: {len(rules)}")


# ---------------------------------------------------------------------------
# Phase 3 — context Q&A
# ---------------------------------------------------------------------------


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question about the app."),
    app_id: str = typer.Option(..., "--app", help="Target app id."),
) -> None:
    """Ask a context-aware question about an app."""
    typer.echo("Phase 3 — not yet implemented")


# ---------------------------------------------------------------------------
# Phase 5 — health monitor
# ---------------------------------------------------------------------------


@app.command()
def health(
    no_slack: bool = typer.Option(False, "--no-slack", help="Skip Slack post."),
    app_id: Optional[str] = typer.Option(None, "--app", help="Single app id to scan."),
) -> None:
    """Run the nightly health monitor digest across all apps."""
    from monitors.health_monitor import run_health_monitor

    app_ids = [app_id] if app_id else None

    typer.echo("Running health monitor...")
    if app_ids:
        typer.echo(f"Scope: {', '.join(app_ids)}")
    else:
        typer.echo("Scope: all apps")
    typer.echo("")

    digest = run_health_monitor(app_ids=app_ids, no_slack=no_slack)

    typer.echo(digest.to_slack_text())
    typer.echo("")
    typer.echo(f"Output written to: output/health/{digest.run_date}.md")


# ---------------------------------------------------------------------------
# RPI — Research → Plan → Implement
# ---------------------------------------------------------------------------


def _rpi_resolve_repos(
    project: Optional[str],
    repo: Optional[str],
) -> list[dict]:
    """Return repo list from --project or --repo, raising Exit on bad input."""
    from orchestrators.rpi_orchestrator import all_repos

    if project and repo:
        typer.echo("Pass either --project or --repo, not both.", err=True)
        raise typer.Exit(code=1)
    if not project and not repo:
        typer.echo("Pass --project <name> or --repo <name>.", err=True)
        raise typer.Exit(code=1)

    if project:
        try:
            return all_repos(project=project)
        except KeyError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

    # --repo: find the single matching repo across all projects
    candidates = [r for r in all_repos() if r["name"] == repo]
    if not candidates:
        typer.echo(
            f"Repo '{repo}' not found in projects.yaml. "
            "Run `python cli.py rpi status` to list known repos.",
            err=True,
        )
        raise typer.Exit(code=1)
    return candidates


@rpi_app.command("research")
def rpi_research(
    project: Optional[str] = typer.Option(None, "--project", help="Project name from projects.yaml."),
    repo: Optional[str] = typer.Option(None, "--repo", help="Single repo name."),
) -> None:
    """Research phase — runs in parallel across selected repos.

    Reads the task brief from tasks/<repo-name>.md.
    Repos with no brief (or only the stub placeholder) are skipped with a warning.
    Output is written to tasks/<repo-name>-RESEARCH.md.
    """
    from orchestrators.rpi_orchestrator import run_phase_parallel

    repos = _rpi_resolve_repos(project, repo)
    scope = f"--project {project}" if project else f"--repo {repo}"

    typer.echo(f"[RPI] Research  ({scope})")
    typer.echo(f"  Repos: {', '.join(r['name'] for r in repos)}")
    typer.echo("")

    results: dict[str, bool] = asyncio.run(
        run_phase_parallel(repos, "research", typer.echo)
    )

    typer.echo("")
    _rpi_print_summary("research", results)


@rpi_app.command("plan")
def rpi_plan(
    project: Optional[str] = typer.Option(None, "--project", help="Project name from projects.yaml."),
    repo: Optional[str] = typer.Option(None, "--repo", help="Single repo name."),
) -> None:
    """Plan phase — runs in parallel across selected repos.

    Reads tasks/<repo-name>.md and (if present) tasks/<repo-name>-RESEARCH.md.
    Writes tasks/<repo-name>-PLAN.md for each repo.
    """
    from orchestrators.rpi_orchestrator import run_phase_parallel

    repos = _rpi_resolve_repos(project, repo)
    scope = f"--project {project}" if project else f"--repo {repo}"

    typer.echo(f"[RPI] Plan  ({scope})")
    typer.echo(f"  Repos: {', '.join(r['name'] for r in repos)}")
    typer.echo("")

    results: dict[str, bool] = asyncio.run(
        run_phase_parallel(repos, "plan", typer.echo)
    )

    typer.echo("")
    _rpi_print_summary("plan", results)
    if any(results.values()):
        typer.echo("Review the PLAN.md files in tasks/, then run `rpi implement`.")


@rpi_app.command("implement")
def rpi_implement(
    project: Optional[str] = typer.Option(None, "--project", help="Project name from projects.yaml."),
    repo: Optional[str] = typer.Option(None, "--repo", help="Single repo name; coupled repos are auto-included."),
    no_confirm: bool = typer.Option(False, "--no-confirm", help="Skip the confirmation prompt."),
) -> None:
    """Implement phase — gate-checked, coupled-aware, parallel.

    Before running:
      1. Checks that tasks/<repo-name>-PLAN.md exists for every selected repo
         (including any auto-expanded coupled repos).  Exits with an error
         listing missing plans if any are absent.
      2. Prompts "Proceed with implement for N repos? [y/N]" unless --no-confirm.

    Coupled repos are automatically added from the coupled_with field in
    projects.yaml, so passing --repo peekr-api will also implement peekr-web.
    """
    from orchestrators.rpi_orchestrator import all_repos, expand_coupled, run_phase_parallel

    base_repos = _rpi_resolve_repos(project, repo)
    all_ = all_repos()
    repos = expand_coupled(base_repos, all_)

    scope = f"--project {project}" if project else f"--repo {repo}"
    typer.echo(f"[RPI] Implement  ({scope})")

    added = [r for r in repos if r not in base_repos]
    if added:
        typer.echo(f"  Base repos:    {', '.join(r['name'] for r in base_repos)}")
        typer.echo(f"  Coupled repos: {', '.join(r['name'] for r in added)}")
    else:
        typer.echo(f"  Repos: {', '.join(r['name'] for r in repos)}")

    # --- Phase gate: every repo must have a PLAN.md ---
    tasks_dir = Path("tasks")
    missing_plans = [
        r["name"] for r in repos
        if not (tasks_dir / f"{r['name']}-PLAN.md").exists()
    ]
    if missing_plans:
        typer.echo("", err=True)
        typer.echo(
            "\u2717 Cannot implement — PLAN.md missing for the following repo(s):",
            err=True,
        )
        for name in missing_plans:
            typer.echo(f"    {name}  (run: python cli.py rpi plan --repo {name})", err=True)
        raise typer.Exit(code=1)

    # --- Confirmation ---
    typer.echo("")
    if not no_confirm:
        confirmed = typer.confirm(
            f"Proceed with implement for {len(repos)} repo(s)?",
            default=False,
        )
        if not confirmed:
            typer.echo("Aborted.")
            raise typer.Exit(code=0)
        typer.echo("")

    results: dict[str, bool] = asyncio.run(
        run_phase_parallel(repos, "implement", typer.echo)
    )

    typer.echo("")
    _rpi_print_summary("implement", results)


@rpi_app.command("status")
def rpi_status() -> None:
    """Print a phase-status table for all repos, grouped by project."""
    from orchestrators.rpi_orchestrator import load_projects, load_status

    status_data = load_status()
    repo_statuses: dict[str, dict] = status_data.get("repos", {})

    projects_data = load_projects()
    projects: dict = projects_data.get("projects", {})

    if not projects:
        typer.echo("No projects found in projects.yaml.")
        return

    phases = ("research", "plan", "implement")
    col_repo = 20
    col_phase = 11
    col_status = 10
    col_updated = 22
    sep = "\u2500" * (col_repo + col_phase + col_status + col_updated + 6)

    for proj_name, proj_data in projects.items():
        typer.echo(f"\nProject: {proj_name}")
        typer.echo(
            f"  {'REPO':<{col_repo}}  {'PHASE':<{col_phase}}  "
            f"{'STATUS':<{col_status}}  {'UPDATED':<{col_updated}}"
        )
        typer.echo(f"  {sep}")

        for repo in (proj_data or {}).get("repos", []):
            repo_name: str = repo["name"]
            repo_entry: dict = repo_statuses.get(repo_name, {})

            if not repo_entry:
                typer.echo(
                    f"  {repo_name:<{col_repo}}  {'—':<{col_phase}}  "
                    f"{'no data':<{col_status}}  {'':>{col_updated}}"
                )
                continue

            first = True
            for phase in phases:
                if phase not in repo_entry:
                    continue
                phase_data = repo_entry[phase]
                label = repo_name if first else ""
                first = False
                typer.echo(
                    f"  {label:<{col_repo}}  {phase:<{col_phase}}  "
                    f"{phase_data.get('status', '?'):<{col_status}}  "
                    f"{phase_data.get('updated', ''):<{col_updated}}"
                )

            if first:
                # repo exists in projects.yaml but has no phase entries yet
                typer.echo(
                    f"  {repo_name:<{col_repo}}  {'—':<{col_phase}}  "
                    f"{'pending':<{col_status}}  {'':>{col_updated}}"
                )

    typer.echo("")


def _rpi_print_summary(phase: str, results: dict[str, bool]) -> None:
    done = [name for name, ok in results.items() if ok]
    not_done = [name for name, ok in results.items() if not ok]

    if done:
        typer.echo(f"{phase} done: {', '.join(done)}")
    if not_done:
        typer.echo(f"{phase} skipped/failed: {', '.join(not_done)}")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
