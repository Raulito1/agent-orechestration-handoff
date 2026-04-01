"""RPI Orchestrator — Research → Plan → Implement via roo CLI subprocess.

Public API
----------
load_projects()              → dict
all_repos(project=None)      → list[dict]   (each dict has _project injected)
expand_coupled(selected, all_) → list[dict]
load_status()                → dict
save_status(data)            → None
build_prompt(repo, phase, task) → str
run_phase_parallel(repos, phase, echo) → dict[str, bool]   (awaitable)

Internal
--------
_run_roo(repo, phase, prompt, echo) → tuple[repo_name, success]   (awaitable)

All errors are caught per-repo.  One failure never cancels the others.
stdout from roo is written to:
  tasks/<repo-name>-RESEARCH.md  (research phase)
  tasks/<repo-name>-PLAN.md      (plan phase)
  (implement: roo writes directly into the target repo)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

# ---------------------------------------------------------------------------
# Paths — all relative to the project root (one level above this file)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_PROJECTS_FILE = _REPO_ROOT / "projects.yaml"
_TASKS_DIR = _REPO_ROOT / "tasks"
_STATUS_FILE = _TASKS_DIR / "status.json"
_SKILLS_DIR = _REPO_ROOT / ".roo" / "skills"

# Output file written for each phase (None = roo writes into the target repo)
_PHASE_OUTPUT: dict[str, str | None] = {
    "research": "{repo}-RESEARCH.md",
    "plan": "{repo}-PLAN.md",
    "implement": None,
}

# Maps projects.yaml stack values to skill file names.
# Add entries here when new stacks are introduced.
_STACK_SKILL: dict[str, str] = {
    "fastapi": "SKILL-fastapi.md",
    "java-spring": "SKILL-java-spring.md",
    "react": "SKILL-react.md",
}


# ---------------------------------------------------------------------------
# Project registry
# ---------------------------------------------------------------------------


def load_projects() -> dict[str, Any]:
    """Parse projects.yaml and return the full dict.

    Returns {"projects": {}} if the file does not exist yet.
    """
    if not _PROJECTS_FILE.exists():
        return {"projects": {}}
    with _PROJECTS_FILE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {"projects": {}}


def all_repos(project: str | None = None) -> list[dict]:
    """Return a flat list of all repo dicts, optionally filtered by project name.

    Each dict is the raw repo entry from projects.yaml with one extra key
    injected: ``_project`` (the project name it belongs to).

    Raises KeyError if *project* is given but not found.
    """
    data = load_projects()
    projects: dict[str, Any] = data.get("projects", {})

    if project is not None:
        if project not in projects:
            available = list(projects.keys())
            raise KeyError(
                f"Unknown project '{project}'. Available: {available}"
            )
        scope = {project: projects[project]}
    else:
        scope = projects

    repos: list[dict] = []
    for proj_name, proj_data in scope.items():
        for repo in (proj_data or {}).get("repos", []):
            repos.append({**repo, "_project": proj_name})
    return repos


def expand_coupled(selected: list[dict], all_: list[dict]) -> list[dict]:
    """Expand *selected* to include any coupled repos not already present.

    ``coupled_with`` lists sibling *repo names* within the same project.
    Repos already in *selected* are never duplicated.
    Repos whose name appears in ``coupled_with`` but is absent from *all_*
    are silently skipped (no KeyError).
    """
    by_name: dict[str, dict] = {r["name"]: r for r in all_}
    seen: set[str] = {r["name"] for r in selected}
    result = list(selected)

    for repo in selected:
        for coupled_name in repo.get("coupled_with", []):
            if coupled_name not in seen and coupled_name in by_name:
                result.append(by_name[coupled_name])
                seen.add(coupled_name)

    return result


# ---------------------------------------------------------------------------
# Status tracking  (tasks/status.json)
# ---------------------------------------------------------------------------


def load_status() -> dict[str, Any]:
    """Load tasks/status.json.  Returns {"repos": {}} if absent."""
    if not _STATUS_FILE.exists():
        return {"repos": {}}
    return json.loads(_STATUS_FILE.read_text(encoding="utf-8"))


def save_status(data: dict[str, Any]) -> None:
    """Write *data* to tasks/status.json, creating the directory if needed."""
    _TASKS_DIR.mkdir(exist_ok=True)
    _STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _set_phase_status(repo_name: str, phase: str, status: str) -> None:
    data = load_status()
    repo_entry = data.setdefault("repos", {}).setdefault(repo_name, {})
    repo_entry[phase] = {
        "status": status,
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    save_status(data)


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def build_prompt(repo: dict, phase: str, task: str) -> str:
    """Assemble the full prompt for *repo* in *phase* from skill files + task.

    Loads two skill files and concatenates them with the task brief:

        .roo/skills/SKILL-rpi-{phase}.md     — phase-level rules (research/plan/implement)
        .roo/skills/SKILL-{stack}.md         — stack-specific conventions

    Separated by ``---`` so roo can parse sections if needed.

    Missing skill files are silently skipped — the task brief is always
    included even if both skill files are absent.
    """
    parts: list[str] = []

    # Phase skill
    phase_skill_file = _SKILLS_DIR / f"SKILL-rpi-{phase}.md"
    if phase_skill_file.exists():
        parts.append(phase_skill_file.read_text(encoding="utf-8").strip())

    # Stack skill
    stack: str = repo.get("stack", "")
    stack_skill_name = _STACK_SKILL.get(stack)
    if stack_skill_name:
        stack_skill_file = _SKILLS_DIR / stack_skill_name
        if stack_skill_file.exists():
            parts.append(stack_skill_file.read_text(encoding="utf-8").strip())

    # Task brief is always last
    parts.append(task.strip())

    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Core subprocess helper
# ---------------------------------------------------------------------------


async def _run_roo(
    repo: dict,
    phase: str,
    prompt: str,
    echo: Callable[[str], None],
) -> tuple[str, bool]:
    """Invoke the roo CLI for *repo* in *phase* with *prompt*.

    Returns (repo_name, success).  Never raises — all errors are caught,
    echoed, and recorded in status.json so parallel siblings keep running.

    roo is invoked as:
        roo --phase <phase> --task <prompt>
    with cwd set to the repo's local_path when it exists on disk.

    stdout is captured and written to the phase-specific output file in
    tasks/ (research → *-RESEARCH.md, plan → *-PLAN.md).
    For implement, roo writes directly into the target repo; we do not
    capture or redirect stdout.
    """
    repo_name: str = repo["name"]
    local_path_str: str | None = repo.get("local_path")
    cwd: Path | None = None
    if local_path_str:
        candidate = Path(local_path_str)
        if candidate.exists():
            cwd = candidate

    cmd = ["roo", "--phase", phase, "--task", prompt]

    echo(f"  [{repo_name}] starting {phase}...")
    _set_phase_status(repo_name, phase, "running")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()

        if proc.returncode != 0:
            err = stderr_bytes.decode(errors="replace").strip()
            _set_phase_status(repo_name, phase, "failed")
            echo(f"  [{repo_name}] \u2717 {phase} failed (exit {proc.returncode}): {err[:200]}")
            return (repo_name, False)

        # Write captured stdout to the phase output file when applicable.
        output_template = _PHASE_OUTPUT.get(phase)
        if output_template is not None:
            output_text = stdout_bytes.decode(errors="replace").strip()
            if output_text:
                output_file = _TASKS_DIR / output_template.format(repo=repo_name)
                output_file.write_text(output_text, encoding="utf-8")
                echo(f"  [{repo_name}] \u2713 {phase} done \u2192 tasks/{output_file.name}")
            else:
                echo(f"  [{repo_name}] \u2713 {phase} done (no output captured)")
        else:
            echo(f"  [{repo_name}] \u2713 {phase} done")

        _set_phase_status(repo_name, phase, "done")
        return (repo_name, True)

    except FileNotFoundError:
        _set_phase_status(repo_name, phase, "failed")
        echo(
            f"  [{repo_name}] \u2717 roo not found \u2014 "
            "install roo and ensure it is on PATH"
        )
        return (repo_name, False)

    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        _set_phase_status(repo_name, phase, "failed")
        echo(f"  [{repo_name}] \u2717 unexpected error: {exc}")
        return (repo_name, False)


# ---------------------------------------------------------------------------
# Parallel phase runner
# ---------------------------------------------------------------------------


async def run_phase_parallel(
    repos: list[dict],
    phase: str,
    echo: Callable[[str], None],
) -> dict[str, bool]:
    """Run *phase* across *repos* in parallel using asyncio.gather.

    Repos whose task brief (tasks/<name>.md) is absent or empty are skipped
    with a warning — they do not count as failures.

    Returns {repo_name: success}.
    """
    if phase not in _PHASE_OUTPUT and phase != "implement":
        raise ValueError(f"Unknown phase '{phase}'. Expected: research, plan, implement.")

    coroutines = []
    skipped: dict[str, bool] = {}

    for repo in repos:
        repo_name: str = repo["name"]
        task_file = _TASKS_DIR / f"{repo_name}.md"

        if not task_file.exists():
            echo(
                f"  [{repo_name}] \u26a0 tasks/{repo_name}.md not found \u2014 skipping"
            )
            _set_phase_status(repo_name, phase, "skipped")
            skipped[repo_name] = False
            continue

        raw_task = task_file.read_text(encoding="utf-8").strip()
        # Strip HTML comment stubs so empty placeholder files are treated as absent.
        stripped = "\n".join(
            line for line in raw_task.splitlines()
            if not line.strip().startswith("<!--")
        ).strip()

        if not stripped:
            echo(
                f"  [{repo_name}] \u26a0 tasks/{repo_name}.md is empty \u2014 skipping"
            )
            _set_phase_status(repo_name, phase, "skipped")
            skipped[repo_name] = False
            continue

        full_prompt = build_prompt(repo, phase, raw_task)
        coroutines.append(_run_roo(repo, phase, full_prompt, echo))

    if not coroutines:
        return skipped

    # return_exceptions=False is intentional: _run_roo itself never raises,
    # so any exception here is a programming error and should surface.
    results: list[tuple[str, bool]] = await asyncio.gather(*coroutines)
    return {**skipped, **dict(results)}
