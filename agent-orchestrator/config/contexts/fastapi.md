# FastAPI Conventions

<!-- TODO: Copy full conventions from .roo/fastapi.md -->

## Auth
- Every endpoint must declare `Depends(get_current_user)` or an explicit override.
- Never bypass auth for non-public routes.

## SQL / RBAC
- All SQL files must include the RBAC CTE pattern at the top.
- Never use raw string interpolation in queries — always parameterize.

## Structure
- Routers live in `routers/`, services in `services/`, repositories in `repositories/`.
- Each layer has a single responsibility; routers must not contain business logic.

## Testing
- Every new module requires a corresponding test file.
- Use `pytest-asyncio` for async route tests.
