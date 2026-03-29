# Spring Boot Conventions

<!-- TODO: Copy full conventions from .roo/spring-boot.md -->

## Security
- Every controller must carry a Spring Security annotation (`@PreAuthorize`, `@Secured`, etc.).
- Never use `.block()` in reactive (Spring WebFlux) code paths.

## Structure
- Controllers in `controller/`, services in `service/`, repositories in `repository/`.
- Use constructor injection — never field injection with `@Autowired`.

## Database
- All schema changes go through Liquibase changesets.
- Never run raw DDL against a managed schema.

## Testing
- Every new service class requires a unit test.
- Integration tests use `@SpringBootTest` with a real (embedded) datasource.
