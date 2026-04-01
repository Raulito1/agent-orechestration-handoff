# tasks/

This directory holds task briefs and RPI phase outputs for each repo.

## File layout

```
tasks/
  README.md                  ← this file
  status.json                ← auto-written by `rpi` commands; tracks phase state per repo
  <repo-name>.md             ← task brief you write; read by `rpi research` and `rpi plan`
  <repo-name>-RESEARCH.md    ← written by `rpi research`
  <repo-name>-PLAN.md        ← written by `rpi plan`; required before `rpi implement`
```

## Task brief format  (<repo-name>.md)

The brief is free-form markdown. Write whatever context helps the agent understand
what to build. A useful structure:

```markdown
# <Short feature title>

## What to build
One paragraph describing the feature from the user's perspective.

## Scope for this repo
What this specific repo (API, web, etc.) needs to do.
Mention specific files, endpoints, or components if you know them.

## Acceptance criteria
- [ ] Criterion one
- [ ] Criterion two

## Out of scope
What should NOT be changed in this pass.

## Notes / context
Anything else the agent should know: related tickets, prior art, constraints.
```

Leaving a file empty (or absent) causes `rpi research` and `rpi plan` to skip that
repo with a warning. You can still run `rpi implement --repo <name>` on a single repo
after writing its brief.

## Workflow

```bash
# 1. Fill in the .md brief for each repo you want to work on.
#    The empty stubs below are placeholders — replace with real content.

# 2. Research phase — reads briefs, writes *-RESEARCH.md in parallel.
python cli.py rpi research --project peekr

# 3. Plan phase — reads briefs + research, writes *-PLAN.md in parallel.
python cli.py rpi plan --project peekr

# 4. Review the generated PLAN.md files and edit as needed.

# 5. Implement — gate checks PLAN.md exists for every repo, then runs in parallel.
#    Auto-expands coupled repos (e.g. peekr-api pulls in peekr-web).
python cli.py rpi implement --repo peekr-api

# 6. Check phase state across all repos.
python cli.py rpi status
```
