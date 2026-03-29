"""Tests for Java Spring Boot agent — mocks Anthropic calls."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.fastapi_agent import BackendGenerationResult
from agents.java_agent import JavaAgent, _parse_java_files


MOCK_RESPONSE = """\
## controller
```java
@RestController
@RequestMapping("/api/v1/users")
@PreAuthorize("hasRole('USER')")
public class UserExportController {
    @GetMapping("/{userId}/export")
    public Mono<ResponseEntity<UserExportResponseDTO>> export(@PathVariable String userId) {
        return service.export(userId).map(ResponseEntity::ok);
    }
}
```

## service
```java
@Service
public class UserExportService {
    public Mono<UserExportResponseDTO> export(String userId) {
        return Mono.fromCallable(() -> repository.getExport(userId))
            .subscribeOn(Schedulers.boundedElastic())
            .map(mapper::toDTO);
    }
}
```

## repository
```java
public interface UserExportRepository extends JpaRepository<User, String> {
    Optional<User> findByUserId(String userId);
}
```

## migration
```yaml
databaseChangeLog:
  - changeSet:
      id: add-user-export
      author: developer
      changes: []
      rollback: []
```

## request_dto
```java
@Data
@Builder
public class UserExportRequestDTO {
    private String userId;
}
```

## response_dto
```java
@Data
@Builder
public class UserExportResponseDTO {
    private String csvData;
    private String filename;
}
```

## mapper
```java
@Mapper(componentModel = "spring")
public interface UserExportMapper {
    UserExportResponseDTO toDTO(UserExport entity);
}
```

<contract>
{
  "app_id": "agm",
  "feature_description": "Add CSV export to user profiles",
  "generated_at": "2026-03-28T10:00:00Z",
  "endpoints": [
    {
      "method": "GET",
      "path": "/api/v1/users/{userId}/export",
      "auth_required": true,
      "rbac_required": true,
      "request_params": [{"name": "userId", "type": "String", "location": "path"}],
      "request_body": null,
      "response_model": "UserExportResponseDTO",
      "response_fields": [
        {"name": "csvData", "type": "String"},
        {"name": "filename", "type": "String"}
      ]
    }
  ],
  "models": [
    {
      "name": "UserExportResponseDTO",
      "fields": [
        {"name": "csvData", "type": "String", "description": "CSV file content"},
        {"name": "filename", "type": "String", "description": "Suggested filename"}
      ]
    }
  ],
  "stack": "java-react"
}
</contract>
"""


def _make_mock_client(text: str) -> MagicMock:
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=text)]
    mock_client.messages.create.return_value = mock_message
    return mock_client


class TestJavaAgent:
    def test_generate_returns_backend_generation_result(self):
        agent = JavaAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "AGM")
        assert isinstance(result, BackendGenerationResult)

    def test_contract_is_parsed(self):
        agent = JavaAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "AGM")
        assert result.contract["app_id"] == "agm"
        assert len(result.contract["endpoints"]) == 1

    def test_files_keys_present(self):
        agent = JavaAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "AGM")
        for key in ["controller", "service", "repository", "migration", "request_dto", "response_dto", "mapper"]:
            assert key in result.files

    def test_controller_has_preuathorize(self):
        agent = JavaAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "AGM")
        assert "@PreAuthorize" in result.files["controller"]

    def test_service_uses_mono(self):
        agent = JavaAgent(client=_make_mock_client(MOCK_RESPONSE))
        result = agent.generate("Add CSV export to user profiles", "AGM")
        assert "Mono" in result.files["service"]

    def test_calls_correct_model(self):
        mock_client = _make_mock_client(MOCK_RESPONSE)
        agent = JavaAgent(client=mock_client)
        agent.generate("test", "TestApp")
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-opus-4-5"

    def test_empty_contract_on_missing_tags(self):
        agent = JavaAgent(client=_make_mock_client("No contract here"))
        result = agent.generate("test", "TestApp")
        assert result.contract == {}


class TestParseJavaFiles:
    def test_all_file_types_present(self):
        files = _parse_java_files(MOCK_RESPONSE)
        for key in ["controller", "service", "repository", "migration", "request_dto", "response_dto", "mapper"]:
            assert key in files

    def test_controller_content_extracted(self):
        files = _parse_java_files(MOCK_RESPONSE)
        assert "@PreAuthorize" in files["controller"]

    def test_missing_sections_get_placeholder(self):
        files = _parse_java_files("## controller\n```java\npublic class C {}\n```")
        assert "service" in files
        assert "not generated" in files["service"]
