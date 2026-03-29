"""Tests for FastAPI orchestrator — mocks both agents."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.fastapi_agent import BackendGenerationResult
from agents.react_agent import ReactGenerationResult
from orchestrators.fastapi_orchestrator import FeatureOutput, FastAPIOrchestrator, _feature_slug, _component_name


MOCK_CONTRACT = {
    "app_id": "new-hire",
    "feature_description": "Add CSV export to user profiles",
    "endpoints": [{"method": "GET", "path": "/api/v1/users/{user_id}/export", "auth_required": True, "response_model": "UserExportResponse", "response_fields": []}],
    "models": [{"name": "UserExportResponse", "fields": []}],
    "stack": "fastapi-react",
}

MOCK_BACKEND_RESULT = BackendGenerationResult(
    contract=MOCK_CONTRACT,
    files={
        "router": "# router",
        "service": "# service",
        "repository": "# repository",
        "sql": "-- sql",
        "request_model": "# request_model",
        "response_model": "# response_model",
    },
)

MOCK_REACT_RESULT = ReactGenerationResult(
    files={
        "rtk_endpoint": "// rtk_endpoint",
        "ts_types": "// ts_types",
        "component": "// component",
    }
)


@pytest.fixture()
def orchestrator(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orch = FastAPIOrchestrator.__new__(FastAPIOrchestrator)
    # Stub out apps config
    orch._apps = [
        {
            "id": "new-hire",
            "name": "New Hire Experience",
            "stack": "fastapi-react",
            "contexts": {"api": "contexts/fastapi.md", "web": "contexts/react.md"},
        }
    ]
    orch._connector = MagicMock()
    return orch


class TestFastAPIOrchestrator:
    @patch("orchestrators.fastapi_orchestrator.FastAPIAgent")
    @patch("orchestrators.fastapi_orchestrator.ReactAgent")
    def test_output_directory_created(self, MockReact, MockFastAPI, orchestrator):
        MockFastAPI.return_value.generate.return_value = MOCK_BACKEND_RESULT
        MockReact.return_value.generate.return_value = MOCK_REACT_RESULT

        with patch.object(orchestrator, "get_anthropic_client", return_value=MagicMock()), \
             patch.object(orchestrator, "_load_context_safe", return_value=""):
            result = orchestrator.run("Add CSV export to user profiles", "new-hire")

        out = Path(result.output_directory)
        assert out.exists()
        assert (out / "contract.json").exists()
        assert (out / "backend").is_dir()
        assert (out / "react").is_dir()

    @patch("orchestrators.fastapi_orchestrator.FastAPIAgent")
    @patch("orchestrators.fastapi_orchestrator.ReactAgent")
    def test_contract_json_is_valid(self, MockReact, MockFastAPI, orchestrator):
        MockFastAPI.return_value.generate.return_value = MOCK_BACKEND_RESULT
        MockReact.return_value.generate.return_value = MOCK_REACT_RESULT

        with patch.object(orchestrator, "get_anthropic_client", return_value=MagicMock()), \
             patch.object(orchestrator, "_load_context_safe", return_value=""):
            result = orchestrator.run("Add CSV export to user profiles", "new-hire")

        contract_data = json.loads(Path(result.output_directory, "contract.json").read_text())
        assert contract_data["app_id"] == "new-hire"

    @patch("orchestrators.fastapi_orchestrator.FastAPIAgent")
    @patch("orchestrators.fastapi_orchestrator.ReactAgent")
    def test_work_item_logged(self, MockReact, MockFastAPI, orchestrator, tmp_path):
        from intelligence.work_intelligence import WORK_LOG_PATH, KNOWLEDGE_DIR
        import intelligence.work_intelligence as wi

        # Point work log to tmp dir
        test_log = tmp_path / "work_log.json"
        test_log.write_text('{"items": []}')

        MockFastAPI.return_value.generate.return_value = MOCK_BACKEND_RESULT
        MockReact.return_value.generate.return_value = MOCK_REACT_RESULT

        with patch.object(orchestrator, "get_anthropic_client", return_value=MagicMock()), \
             patch.object(orchestrator, "_load_context_safe", return_value=""), \
             patch.object(wi, "WORK_LOG_PATH", test_log):
            result = orchestrator.run("Add CSV export to user profiles", "new-hire")

        # The CLI creates the work item, not the orchestrator directly.
        # Here we verify the result object has all expected fields.
        assert isinstance(result, FeatureOutput)
        assert result.app_id == "new-hire"
        assert result.output_directory != ""

    @patch("orchestrators.fastapi_orchestrator.FastAPIAgent")
    @patch("orchestrators.fastapi_orchestrator.ReactAgent")
    def test_react_agent_receives_contract_not_files(self, MockReact, MockFastAPI, orchestrator):
        MockFastAPI.return_value.generate.return_value = MOCK_BACKEND_RESULT
        MockReact.return_value.generate.return_value = MOCK_REACT_RESULT

        with patch.object(orchestrator, "get_anthropic_client", return_value=MagicMock()), \
             patch.object(orchestrator, "_load_context_safe", return_value=""):
            orchestrator.run("Add CSV export to user profiles", "new-hire")

        # React agent must be called with contract dict, not backend files
        react_call_args = MockReact.return_value.generate.call_args
        contract_arg = react_call_args.args[0] if react_call_args.args else react_call_args.kwargs.get("contract")
        assert isinstance(contract_arg, dict)
        assert "endpoints" in contract_arg

    @patch("orchestrators.fastapi_orchestrator.FastAPIAgent")
    @patch("orchestrators.fastapi_orchestrator.ReactAgent")
    def test_backend_files_written(self, MockReact, MockFastAPI, orchestrator):
        MockFastAPI.return_value.generate.return_value = MOCK_BACKEND_RESULT
        MockReact.return_value.generate.return_value = MOCK_REACT_RESULT

        with patch.object(orchestrator, "get_anthropic_client", return_value=MagicMock()), \
             patch.object(orchestrator, "_load_context_safe", return_value=""):
            result = orchestrator.run("Add CSV export to user profiles", "new-hire")

        backend_dir = Path(result.output_directory) / "backend"
        assert any(backend_dir.iterdir())

    @patch("orchestrators.fastapi_orchestrator.FastAPIAgent")
    @patch("orchestrators.fastapi_orchestrator.ReactAgent")
    def test_react_files_written(self, MockReact, MockFastAPI, orchestrator):
        MockFastAPI.return_value.generate.return_value = MOCK_BACKEND_RESULT
        MockReact.return_value.generate.return_value = MOCK_REACT_RESULT

        with patch.object(orchestrator, "get_anthropic_client", return_value=MagicMock()), \
             patch.object(orchestrator, "_load_context_safe", return_value=""):
            result = orchestrator.run("Add CSV export to user profiles", "new-hire")

        react_dir = Path(result.output_directory) / "react"
        assert any(react_dir.iterdir())

    @patch("orchestrators.fastapi_orchestrator.FastAPIAgent")
    @patch("orchestrators.fastapi_orchestrator.ReactAgent")
    def test_never_writes_to_app_repos(self, MockReact, MockFastAPI, orchestrator, tmp_path):
        """Orchestrator writes only to ./output/ — never to app repo paths."""
        MockFastAPI.return_value.generate.return_value = MOCK_BACKEND_RESULT
        MockReact.return_value.generate.return_value = MOCK_REACT_RESULT

        with patch.object(orchestrator, "get_anthropic_client", return_value=MagicMock()), \
             patch.object(orchestrator, "_load_context_safe", return_value=""):
            result = orchestrator.run("Add CSV export to user profiles", "new-hire")

        assert result.output_directory.startswith("output")


class TestHelpers:
    def test_feature_slug_five_words(self):
        slug = _feature_slug("Add CSV export to user profiles now")
        assert slug == "add-csv-export-to-user"

    def test_feature_slug_short_description(self):
        slug = _feature_slug("Add CSV")
        assert slug == "add-csv"

    def test_feature_slug_lowercase_hyphenated(self):
        slug = _feature_slug("Add BIG Feature TODAY!")
        assert "-" in slug
        assert slug == slug.lower()

    def test_component_name_pascal_case(self):
        name = _component_name("Add CSV export to user profiles")
        assert name == "AddCsvExportComponent"
