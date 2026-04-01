# SKILL: FastAPI Conventions

Apply every rule in this file to all FastAPI code generation and review tasks.
No exceptions unless the task brief explicitly overrides a specific rule and states a reason.

---

## Layer structure

Every feature spans exactly these files. One responsibility per layer — never mix them.

| File | Location | Responsibility |
|------|----------|----------------|
| `router.py` | `routers/` | HTTP routing, request validation, response shaping only |
| `service.py` | `services/` | Business logic, orchestration, no DB calls |
| `repository.py` | `repositories/` | All database I/O via named SQL files, no logic |
| `<feature>.sql` | `sql/` | Raw SQL loaded from disk, never inlined |
| `request_model.py` | `models/request/` | Pydantic `BaseModel` for request bodies |
| `response_model.py` | `models/response/` | Pydantic `BaseModel` for response bodies |

Routers must contain **no business logic**. If a router does more than call a single service method and return a response, it is wrong.

---

## Authentication and authorisation — mandatory Depends() chain

Every non-public endpoint must declare the full dependency chain in its signature:

```python
@router.get("/items")
async def list_items(
    current_user: UserContext = Depends(get_current_user),
    rbac: RBACService    = Depends(get_rbac_service),
    db: AsyncSession     = Depends(get_db),
) -> list[ItemResponse]:
    ...
```

### RBAC pipeline

The pipeline is **always** JWT → UnifiedSecurityService → RBACService → repository.
Never short-circuit any step.

1. **JWT verification** — `get_current_user` decodes and validates the token, raises `401` on failure.
2. **UnifiedSecurityService** — resolves the user's roles and tenant context from the decoded claims.
3. **RBACService** — checks whether the resolved roles permit the requested action on the target resource. Raises `403` on denial.
4. **Repository** — receives the verified `UserContext`; passes it into every SQL query as the `current_user_id` and `tenant_id` parameters so the RBAC CTE can filter at the database level.

`Depends(get_current_user)` is not optional on any route in the application except routes explicitly marked public with `allow_unauthenticated=True`.

---

## SQL conventions

### SQL-on-disk via Loader

All SQL lives in `.sql` files under `sql/`. Never inline SQL strings in Python.

```python
# repository.py
from utils.sql_loader import Loader

_SQL = Loader(__file__)  # resolves sql/ relative to the repository file

class ItemRepository:
    async def list_items(self, user_ctx: UserContext, db: AsyncSession) -> list[Row]:
        query = _SQL("list_items")          # loads sql/list_items.sql
        result = await db.execute(query, {"current_user_id": user_ctx.user_id,
                                           "tenant_id":       user_ctx.tenant_id})
        return result.fetchall()
```

### RBAC CTE pattern — mandatory in every SQL file

Every `.sql` file must open with the RBAC CTE block. No exceptions.

```sql
-- ─── RBAC CTE ─────────────────────────────────────────────────────────────
WITH rbac AS (
    SELECT
        ur.user_id,
        ur.role_id,
        r.permissions
    FROM   user_roles    ur
    JOIN   roles         r  ON r.id = ur.role_id
    WHERE  ur.user_id   = %(current_user_id)s
      AND  ur.tenant_id = %(tenant_id)s
      AND  ur.is_active = TRUE
)
-- ─── feature query ────────────────────────────────────────────────────────
SELECT
    i.id,
    i.name,
    i.created_at
FROM   items i
JOIN   rbac  ON rbac.user_id = i.owner_id   -- enforce row-level access
WHERE  i.tenant_id = %(tenant_id)s
  AND  i.is_deleted = FALSE
ORDER  BY i.created_at DESC;
```

### Parameter placeholders

Always use `%(name)s` for named parameters (psycopg2 / asyncpg style).
Never use `%s` positional placeholders or f-string / `.format()` interpolation.

```python
# correct
await db.execute(query, {"item_id": item_id, "current_user_id": user_ctx.user_id})

# wrong — positional
await db.execute(query, (item_id,))

# wrong — interpolation (SQL injection risk)
query = f"SELECT * FROM items WHERE id = {item_id}"
```

---

## Request / response models

- All request bodies extend `pydantic.BaseModel`.
- All response bodies extend `pydantic.BaseModel` and declare `model_config = ConfigDict(from_attributes=True)`.
- Never return raw `dict` or `Row` objects from a router. Always map through a response model.
- Use `Optional[X]` only when a field is genuinely nullable. Do not make fields optional to avoid validation.

---

## Error handling

| Condition | Exception |
|-----------|-----------|
| Resource not found | `HTTPException(status_code=404)` |
| Unauthorised (bad/missing token) | `HTTPException(status_code=401)` |
| Forbidden (valid token, wrong role) | `HTTPException(status_code=403)` |
| Validation failure | Raised automatically by Pydantic; do not catch |
| Unexpected server error | Let it propagate to the global exception handler |

Never catch broad `Exception` and return a 500 manually — the global handler does this.

---

## Testing

- Every new router, service, and repository requires a corresponding test file.
- Router tests use `httpx.AsyncClient` with the FastAPI app and a mocked `get_current_user` dependency.
- Repository tests run against a real test database (no mocking of SQL).
- Use `pytest-asyncio` with `asyncio_mode = "auto"`.
- Every test that exercises RBAC must test both the allowed and denied cases.
