"""Tests for Java Spring Boot convention guard rules.

Each rule has a passing case (no violations) and a failing case (violations found).
Rules are pure functions — no file system or I/O needed.
"""
import pytest
from guards.rules.java_rules import (
    check_liquibase_migration_has_rollback,
    check_method_too_long,
    check_missing_mapstruct_mapper,
    check_no_block_in_webflux,
    check_security_annotation_on_controller,
    check_todo_fixme,
)


# ---------------------------------------------------------------------------
# check_no_block_in_webflux
# ---------------------------------------------------------------------------


def test_no_block_passes_clean_reactive_code():
    content = """\
public Mono<User> getUser(String id) {
    return userRepository.findById(id)
        .map(UserMapper::toDto);
}
"""
    result = check_no_block_in_webflux("src/UserService.java", content)
    assert result == []


def test_no_block_fails_block_call():
    content = """\
public User getUser(String id) {
    return userRepository.findById(id).block();
}
"""
    result = check_no_block_in_webflux("src/UserService.java", content)
    assert len(result) == 1
    assert result[0].rule_id == "no-block-in-webflux"
    assert result[0].severity == "CRITICAL"
    assert result[0].line_number == 2


def test_no_block_fails_multiple_block_calls():
    content = """\
public void process() {
    User u = userRepo.findById("1").block();
    Order o = orderRepo.findById("2").block();
}
"""
    result = check_no_block_in_webflux("src/Processor.java", content)
    assert len(result) == 2


def test_no_block_ignores_non_java_files():
    content = "return repo.findById(id).block();"
    result = check_no_block_in_webflux("src/service.py", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_security_annotation_on_controller
# ---------------------------------------------------------------------------


def test_security_annotation_passes_with_preauthorize():
    content = """\
@PreAuthorize("hasRole('USER')")
@RestController
@RequestMapping("/api/users")
public class UserController {
}
"""
    result = check_security_annotation_on_controller("src/UserController.java", content)
    assert result == []


def test_security_annotation_passes_with_secured():
    content = """\
@Secured("ROLE_ADMIN")
@RestController
public class AdminController {
}
"""
    result = check_security_annotation_on_controller("src/AdminController.java", content)
    assert result == []


def test_security_annotation_fails_missing():
    content = """\
@RestController
@RequestMapping("/api/users")
public class UserController {
    public ResponseEntity<List<User>> getUsers() {
        return ResponseEntity.ok(users);
    }
}
"""
    result = check_security_annotation_on_controller("src/UserController.java", content)
    assert len(result) == 1
    assert result[0].rule_id == "security-annotation-on-controller"
    assert result[0].severity == "CRITICAL"


def test_security_annotation_ignores_non_controller_files():
    content = """\
@Service
public class UserService {
}
"""
    result = check_security_annotation_on_controller("src/UserService.java", content)
    assert result == []


def test_security_annotation_ignores_non_java_files():
    content = "@RestController\npublic class Foo {}"
    result = check_security_annotation_on_controller("src/Foo.py", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_liquibase_migration_has_rollback
# ---------------------------------------------------------------------------


def test_liquibase_passes_with_rollback():
    content = """\
databaseChangeLog:
  - changeSet:
      id: 1
      author: dev
      changes:
        - createTable:
            tableName: users
      rollback:
        - dropTable:
            tableName: users
"""
    result = check_liquibase_migration_has_rollback("db/changelog/001_create_users.yaml", content)
    assert result == []


def test_liquibase_fails_missing_rollback():
    content = """\
databaseChangeLog:
  - changeSet:
      id: 1
      author: dev
      changes:
        - createTable:
            tableName: users
"""
    result = check_liquibase_migration_has_rollback("db/changelog/001_create_users.yaml", content)
    assert len(result) == 1
    assert result[0].rule_id == "liquibase-migration-has-rollback"
    assert result[0].severity == "CRITICAL"


def test_liquibase_ignores_non_yaml_files():
    content = "databaseChangeLog:\n  - changeSet:"
    result = check_liquibase_migration_has_rollback("db/migration.sql", content)
    assert result == []


def test_liquibase_ignores_non_migration_yaml():
    content = """\
server:
  port: 8080
spring:
  datasource:
    url: jdbc:postgresql://localhost/mydb
"""
    result = check_liquibase_migration_has_rollback("config/application.yaml", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_todo_fixme
# ---------------------------------------------------------------------------


def test_todo_fixme_passes_clean():
    content = """\
public class UserService {
    public User getUser(String id) {
        return repo.findById(id);
    }
}
"""
    result = check_todo_fixme("src/UserService.java", content)
    assert result == []


def test_todo_fixme_fails_todo():
    content = """\
public class UserService {
    // TODO: add caching here
    public User getUser(String id) {
        return repo.findById(id);
    }
}
"""
    result = check_todo_fixme("src/UserService.java", content)
    assert len(result) == 1
    assert result[0].rule_id == "todo-fixme-in-new-code"
    assert result[0].severity == "WARNING"
    assert result[0].line_number == 2


def test_todo_fixme_fails_fixme():
    content = """\
public void process() {
    // FIXME: this is broken
    doSomething();
}
"""
    result = check_todo_fixme("src/Processor.java", content)
    assert len(result) == 1


def test_todo_fixme_ignores_non_java_files():
    content = "// TODO: fix this"
    result = check_todo_fixme("src/notes.txt", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_method_too_long
# ---------------------------------------------------------------------------


def test_method_too_long_passes_short_method():
    content = """\
public class Foo {
    public String greet(String name) {
        return "Hello " + name;
    }
}
"""
    result = check_method_too_long("src/Foo.java", content)
    assert result == []


def test_method_too_long_fails_long_method():
    body = "\n".join(["        System.out.println(\"line\");"] * 52)
    content = f"""\
public class Foo {{
    public void longMethod() {{
{body}
    }}
}}
"""
    result = check_method_too_long("src/Foo.java", content)
    assert len(result) == 1
    assert result[0].rule_id == "method-too-long"
    assert result[0].severity == "WARNING"


def test_method_too_long_ignores_non_java_files():
    content = "public void longMethod() {\n" + "    pass;\n" * 60 + "}"
    result = check_method_too_long("src/Foo.py", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_missing_mapstruct_mapper
# ---------------------------------------------------------------------------


def test_missing_mapper_passes_with_mapper_import():
    content = """\
import org.mapstruct.Mapper;

@Mapper(componentModel = "spring")
public interface UserDtoMapper {
    UserDto toDto(User user);
}
"""
    result = check_missing_mapstruct_mapper("src/UserDto.java", content)
    assert result == []


def test_missing_mapper_fails_dto_without_mapper():
    content = """\
import lombok.Data;

@Data
public class UserDto {
    private String id;
    private String name;
}
"""
    result = check_missing_mapstruct_mapper("src/UserDto.java", content)
    assert len(result) == 1
    assert result[0].rule_id == "missing-mapstruct-mapper"
    assert result[0].severity == "WARNING"


def test_missing_mapper_ignores_non_dto_classes():
    content = """\
public class UserService {
    public User getUser() { return null; }
}
"""
    result = check_missing_mapstruct_mapper("src/UserService.java", content)
    assert result == []


def test_missing_mapper_ignores_non_java_files():
    content = "class UserDto:\n    pass"
    result = check_missing_mapstruct_mapper("src/user_dto.py", content)
    assert result == []
