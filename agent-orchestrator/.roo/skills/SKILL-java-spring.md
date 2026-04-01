# SKILL: Java Spring Boot Conventions

Apply every rule in this file to all Spring Boot code generation and review tasks.
No exceptions unless the task brief explicitly overrides a specific rule and states a reason.

---

## Layer structure

Every feature spans exactly these files. One responsibility per layer.

| File | Package | Responsibility |
|------|---------|----------------|
| `*Controller.java` | `controller/` | HTTP routing, `@PreAuthorize`, request/response mapping only |
| `*Service.java` | `service/` | Business logic, orchestration, reactive chain assembly |
| `*Repository.java` | `repository/` | All database I/O via Spring Data or custom `@Query` |
| `*RequestDTO.java` | `dto/request/` | Incoming payload, Bean Validation annotations |
| `*ResponseDTO.java` | `dto/response/` | Outgoing payload, never expose entity internals |
| `*Mapper.java` | `mapper/` | MapStruct interface — entity ↔ DTO conversion only |
| `*.yaml` (migration) | `resources/db/changelog/` | Liquibase changeset for all schema changes |

---

## Reactive rules — the most common source of bugs

### Always: `Mono.fromCallable` + `Schedulers.boundedElastic()`

All blocking I/O (JDBC, file I/O, synchronous HTTP clients) **must** be wrapped:

```java
// correct
public Mono<ItemResponse> getItem(Long id) {
    return Mono.fromCallable(() -> itemRepository.findById(id)
                    .orElseThrow(() -> new ResourceNotFoundException("Item", id)))
               .subscribeOn(Schedulers.boundedElastic())
               .map(mapper::toResponse);
}
```

### Never `.block()` on the event loop

`.block()` deadlocks the Netty event loop. It is forbidden everywhere in reactive code paths.

```java
// wrong — will deadlock under load
ItemEntity item = itemRepository.findById(id).block();

// wrong — also forbidden
Mono<Item> mono = service.getItem(id);
Item item = mono.block();
```

The only permitted use of `.block()` is inside `@SpringBootTest` integration tests, never in production code.

### Error handling in reactive chains

```java
return Mono.fromCallable(() -> repository.findById(id)
               .orElseThrow(() -> new ResourceNotFoundException("Item", id)))
           .subscribeOn(Schedulers.boundedElastic())
           .onErrorMap(ResourceNotFoundException.class, ex ->
               new ResponseStatusException(HttpStatus.NOT_FOUND, ex.getMessage()));
```

Never `try/catch` inside a `Mono.fromCallable` lambda — use `.onErrorMap` or `.onErrorResume` on the chain.

---

## Security — `@PreAuthorize` on every controller method

```java
@RestController
@RequestMapping("/api/v1/items")
@RequiredArgsConstructor
public class ItemController {

    private final ItemService itemService;

    @GetMapping
    @PreAuthorize("hasRole('ROLE_USER')")
    public Mono<ResponseEntity<List<ItemResponse>>> listItems(
            @AuthenticationPrincipal UserDetails userDetails) {
        return itemService.listItems(userDetails.getUsername())
                          .collectList()
                          .map(ResponseEntity::ok);
    }
}
```

- `@PreAuthorize` is required on every public endpoint method — never on the class alone.
- Use `hasRole(...)`, `hasAuthority(...)`, or a SpEL expression — never bypass with `permitAll()` for authenticated routes.
- Never use field injection with `@Autowired`. Always use constructor injection via Lombok `@RequiredArgsConstructor`.

---

## Lombok

Use Lombok to eliminate boilerplate. Required annotations:

| Annotation | Where |
|------------|-------|
| `@Data` | DTOs (generates getters, setters, equals, hashCode, toString) |
| `@Builder` | DTOs and entities where builder construction is needed |
| `@RequiredArgsConstructor` | All Spring-managed classes (controllers, services, repositories) |
| `@Slf4j` | Any class that logs |
| `@Value` | Immutable DTOs (all fields final) |

Never write manual getters, setters, constructors, or `equals`/`hashCode` on classes that could use Lombok.

---

## MapStruct

All entity ↔ DTO conversion goes through a MapStruct mapper interface. Never convert manually in a service or controller.

```java
@Mapper(componentModel = "spring")
public interface ItemMapper {

    ItemResponse toResponse(ItemEntity entity);

    ItemEntity toEntity(ItemRequest request);

    List<ItemResponse> toResponseList(List<ItemEntity> entities);
}
```

- Annotate with `@Mapper(componentModel = "spring")` so Spring can inject it.
- Declare explicit `@Mapping` annotations when field names differ between entity and DTO.
- Never add business logic to a mapper — only field mapping.

---

## Database migrations — Liquibase YAML

All schema changes go through Liquibase changesets. Never run raw DDL against a managed schema.

```yaml
# resources/db/changelog/changes/0042_add_items_table.yaml
databaseChangeLog:
  - changeSet:
      id: 0042_add_items_table
      author: <author>
      changes:
        - createTable:
            tableName: items
            columns:
              - column:
                  name: id
                  type: BIGINT
                  autoIncrement: true
                  constraints:
                    primaryKey: true
                    nullable: false
              - column:
                  name: tenant_id
                  type: BIGINT
                  constraints:
                    nullable: false
              - column:
                  name: name
                  type: VARCHAR(255)
                  constraints:
                    nullable: false
              - column:
                  name: created_at
                  type: TIMESTAMP
                  defaultValueComputed: CURRENT_TIMESTAMP
                  constraints:
                    nullable: false
        - addForeignKeyConstraint:
            constraintName: fk_items_tenant
            baseTableName: items
            baseColumnNames: tenant_id
            referencedTableName: tenants
            referencedColumnNames: id
```

Rules:
- Changeset `id` format: `<sequential-number>_<snake_case_description>`.
- Never edit an existing changeset — add a new one.
- Always include rollback instructions for destructive changes.
- Include the changeset file in `db/changelog/db.changelog-master.yaml`.

---

## Dependency injection

- **Constructor injection only.** Use `@RequiredArgsConstructor` on the class; declare all dependencies as `private final` fields.
- Never use `@Autowired` on fields or setters.
- Never use `ApplicationContext.getBean(...)` at runtime.

---

## Testing

- Every new service class requires a `*ServiceTest.java` unit test.
- Mock repositories with `@MockBean`; never hit the database in unit tests.
- Integration tests use `@SpringBootTest` with `@AutoConfigureTestDatabase(replace = NONE)` and a real (embedded H2 or Testcontainers) datasource.
- Reactive chains are tested with `StepVerifier`:

```java
StepVerifier.create(itemService.getItem(1L))
            .expectNextMatches(r -> r.getId().equals(1L))
            .verifyComplete();
```
