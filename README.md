# Agent Orchestrator

An AI-powered CLI that drives code generation, convention checking, work-item tracking, and nightly health monitoring across a portfolio of full-stack applications. Built on the Anthropic API (Claude) and designed to operate locally or via Bitbucket + Jenkins in CI.

---

## Table of contents

- [Architecture](#architecture)
- [Setup](#setup)
- [Configuration](#configuration)
- [Commands](#commands)
  - [feature](#feature)
  - [guard](#guard)
  - [log](#log)
  - [work](#work)
  - [health](#health)
  - [rpi](#rpi)
- [RPI workflow](#rpi-workflow)
- [Adding a new project](#adding-a-new-project)
- [CI/CD](#cicd)
- [Project layout](#project-layout)

---

## Architecture

```
cli.py                          Entry point (Typer)
│
├── orchestrators/
│   ├── base_orchestrator.py    Loads apps.yaml + projects.yaml, picks connector
│   ├── fastapi_orchestrator.py FastAPI → React feature generation
│   ├── java_orchestrator.py    Java Spring Boot → React feature generation
│   └── rpi_orchestrator.py     Research → Plan → Implement (parallel, roo CLI)
│
├── agents/
│   ├── fastapi_agent.py        Generates FastAPI backend files via Claude
│   ├── java_agent.py           Generates Spring Boot backend files via Claude
│   └── react_agent.py          Generates React/RTK frontend files via Claude
│
├── guards/
│   ├── convention_guard.py     Runs rule checks across repos, posts PR comments
│   └── rules/                  Per-stack rule sets (fastapi, java, react)
│
├── intelligence/
│   └── work_intelligence.py    Claude-powered bug analysis and guard promotion
│
├── monitors/
│   └── health_monitor.py       Nightly digest: guard scan + work log + Slack post
│
├── connectors/
│   ├── local_connector.py      Reads files from local paths (LOCAL=true)
│   └── bitbucket_connector.py  Reads/posts via Bitbucket API
│
├── config/
│   ├── apps.yaml               App registry (id, stack, paths, Bitbucket slugs)
│   └── contexts/               Stack-specific system prompts for Claude
│
├── projects.yaml               Project registry for the RPI workflow
└── tasks/                      Per-repo task briefs and RPI phase outputs
```

Each app entry in `apps.yaml` represents one full-stack product with an API repo and a web repo. The `projects.yaml` file models the same products as a richer graph — with per-repo stack metadata and `coupled_with` links — used exclusively by the `rpi` commands.

---

## Setup

**Requirements:** Python 3.12+, `roo` CLI on PATH (for the `rpi` commands).

```bash
cd agent-orchestrator

# Create a virtual environment and install
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Copy the env template and fill in your keys
cp .env.example .env
```

### `.env` values

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `LOCAL` | Yes | `true` = read from local paths; `false` = use Bitbucket API |
| `BITBUCKET_USERNAME` | If `LOCAL=false` | Bitbucket username |
| `BITBUCKET_APP_PASSWORD` | If `LOCAL=false` | Bitbucket app password |
| `BITBUCKET_BASE_URL` | If `LOCAL=false` | Defaults to `https://api.bitbucket.org/2.0` |
| `SLACK_WEBHOOK_URL` | No | Incoming webhook for the `health` command |

---

## Configuration

### `config/apps.yaml`

Registers every app. Each entry supplies the paths and context files used by `feature`, `guard`, and `health`.

```yaml
apps:
  - id: peekr
    name: Peekr
    stack: java-react          # java-react | fastapi-react
    local:
      api_path: /path/to/peekr-api
      web_path: /path/to/peekr-web
    bitbucket:
      workspace: workspace-b
      api_repo: peekr-api-slug
      web_repo: peekr-web-slug
    contexts:
      api: contexts/spring-boot.md
      web: contexts/react.md
```

### `projects.yaml`

Used only by the `rpi` commands. Groups repos into projects with per-repo stack metadata and coupling links.

```yaml
projects:
  peekr:
    repos:
      - name: peekr-api
        app_id: peekr          # must match an id in apps.yaml
        stack: java-spring
        coupled_with:
          - peekr-web          # rpi implement auto-includes coupled repos
      - name: peekr-web
        app_id: peekr
        stack: react
        coupled_with:
          - peekr-api
```

---

## Commands

All commands are run from the `agent-orchestrator/` directory:

```bash
python cli.py <command> [options]
```

---

### `feature`

Generate a full-stack feature (backend + React frontend) for a single app.

```bash
python cli.py feature "Add CSV export to user list" --app peekr
```

Runs the appropriate orchestrator for the app's stack (`java-react` → `JavaOrchestrator`, `fastapi-react` → `FastAPIOrchestrator`). Output is written to `output/<app-id>/<timestamp>_<slug>/`. A `FEATURE` work item is created automatically in `knowledge/work_log.json`.

---

### `guard`

Run convention checks against one app or all apps. Posts a PR comment to Bitbucket when `--pr-id` is supplied (used by Jenkins).

```bash
# Single app
python cli.py guard --app peekr

# All apps
python cli.py guard --app all

# With PR comment (Jenkins use)
python cli.py guard --app peekr --pr-id 42
```

Exits with code `1` if any critical violations are found.

---

### `log`

Log work items. All items are stored in `knowledge/work_log.json`.

```bash
python cli.py log bug --app peekr --layer fastapi "Null pointer in export service"
python cli.py log feature --app agm "Add batch approval flow"
python cli.py log enhancement --app new-hire --layer react "Improve form validation UX"
python cli.py log spike --app new-client "Investigate pagination strategy"
python cli.py log chore --app peekr "Upgrade Spring Boot to 3.3"
```

Logging a bug runs an AI analysis against the known pattern index and may prompt you to promote a recurring bug to a Convention Guard rule.

---

### `work`

Query and manage work items.

```bash
# Show all recurring patterns
python cli.py work patterns

# Show history, optionally filtered
python cli.py work history
python cli.py work history --app peekr
python cli.py work history --type bug

# Show a single item in full
python cli.py work item bug-0004

# Log a fix attempt on an open bug
python cli.py work attempt bug-0004 "Added null check in ExportService.java"

# Mark a bug resolved
python cli.py work resolve bug-0004 "Root cause was missing validation — added guard"

# Show all promoted guard rules
python cli.py work promoted
```

---

### `health`

Run the nightly health digest across all apps (or a single app). Produces a markdown report in `output/health/<date>.md` and optionally posts to Slack.

```bash
python cli.py health
python cli.py health --app peekr
python cli.py health --no-slack
```

---

### `rpi`

Research → Plan → Implement workflow. Runs all phases in parallel across repos using `asyncio.gather`. See [RPI workflow](#rpi-workflow) for the full walkthrough.

```bash
python cli.py rpi research --project peekr
python cli.py rpi plan     --project peekr
python cli.py rpi implement --project peekr
python cli.py rpi status
```

---

## RPI workflow

The `rpi` commands let you drive a multi-repo feature from research to implementation in three gated phases, all running in parallel across repos.

### 1. Write task briefs

Each repo has a stub file in `tasks/`. Fill in the ones you want to target:

```
tasks/
  peekr-api.md     ← write what the API needs to do
  peekr-web.md     ← write what the frontend needs to do
```

See [tasks/README.md](agent-orchestrator/tasks/README.md) for the recommended brief format.

### 2. Research

Reads each brief, inspects the repo's file tree, and writes a research summary.

```bash
python cli.py rpi research --project peekr
# Output: tasks/peekr-api-RESEARCH.md, tasks/peekr-web-RESEARCH.md
```

### 3. Plan

Reads brief + research summary, produces a structured `PLAN.md` per repo.

```bash
python cli.py rpi plan --project peekr
# Output: tasks/peekr-api-PLAN.md, tasks/peekr-web-PLAN.md
```

Review (and edit) the PLAN.md files before proceeding.

### 4. Implement

Gate-checks that every `PLAN.md` exists, then prompts for confirmation before running.

```bash
python cli.py rpi implement --project peekr

# Target a single repo — coupled repos from projects.yaml are auto-included.
# peekr-api has coupled_with: [peekr-web], so both run.
python cli.py rpi implement --repo peekr-api

# Skip the confirmation prompt (useful in scripts)
python cli.py rpi implement --project peekr --no-confirm
```

If any `PLAN.md` is missing the command exits immediately and tells you which repos need a plan.

### 5. Check status

```bash
python cli.py rpi status
```

Prints a table grouped by project:

```
Project: peekr
  REPO                PHASE        STATUS      UPDATED
  ──────────────────────────────────────────────────────────────────
  peekr-api           research     done        2026-04-01T10:00:00
  peekr-api           plan         done        2026-04-01T10:05:00
  peekr-api           implement    running     2026-04-01T10:10:00
  peekr-web           research     done        2026-04-01T10:01:00
  peekr-web           plan         done        2026-04-01T10:06:00
  peekr-web           implement    running     2026-04-01T10:10:00
```

Phase state is persisted to `tasks/status.json`.

---

## Adding a new project

No Python changes required. Two files to edit:

**1. `config/apps.yaml`** — add an app entry with local paths, Bitbucket slugs, and context files. This enables `feature`, `guard`, and `health`.

**2. `projects.yaml`** — add a project entry with per-repo stack and coupling metadata. This enables the `rpi` commands.

Then create task brief stubs:

```bash
touch agent-orchestrator/tasks/<new-repo-api>.md
touch agent-orchestrator/tasks/<new-repo-web>.md
```

---

## CI/CD

### Convention Guard (`Jenkinsfile`)

Triggered on every Bitbucket pull request. Runs `guard` against the PR's app and posts a formatted comment with any violations. The build fails (exit code 1) on critical violations, blocking merge.

Setup: configure the Generic Webhook Trigger plugin in Jenkins to extract `APP_ID` and `PR_ID` from the Bitbucket webhook payload. Store `anthropic-api-key`, `bitbucket-username`, and `bitbucket-app-password` as Jenkins credentials.

### Health Monitor (`Jenkinsfile.monitor`)

Runs daily at 06:00. Executes `python cli.py health` across all apps, posts a digest to Slack, and archives the markdown report as a Jenkins build artifact.

---

## Project layout

```
agent-orchestrator/
├── cli.py
├── projects.yaml
├── pyproject.toml
├── .env.example
├── Jenkinsfile
├── Jenkinsfile.monitor
├── agents/
│   ├── fastapi_agent.py
│   ├── java_agent.py
│   └── react_agent.py
├── config/
│   ├── apps.yaml
│   └── contexts/
│       ├── fastapi.md
│       ├── react.md
│       └── spring-boot.md
├── connectors/
│   ├── base_connector.py
│   ├── bitbucket_connector.py
│   └── local_connector.py
├── guards/
│   ├── convention_guard.py
│   ├── promoted_rules.json
│   └── rules/
│       ├── fastapi_rules.py
│       ├── java_rules.py
│       └── react_rules.py
├── intelligence/
│   └── work_intelligence.py
├── knowledge/
│   ├── pattern_index.json
│   └── work_log.json
├── monitors/
│   └── health_monitor.py
├── orchestrators/
│   ├── base_orchestrator.py
│   ├── fastapi_orchestrator.py
│   ├── java_orchestrator.py
│   └── rpi_orchestrator.py
├── tasks/
│   ├── README.md
│   ├── status.json          (auto-generated)
│   └── <repo-name>.md       (one per repo)
├── output/                  (auto-generated, gitignored)
└── tests/
```
