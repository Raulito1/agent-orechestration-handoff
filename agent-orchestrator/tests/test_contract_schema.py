"""Validate contract JSON against the expected schema."""
from __future__ import annotations

import json

import pytest


VALID_CONTRACT = {
    "app_id": "new-hire",
    "feature_description": "Add CSV export to user profiles",
    "generated_at": "2026-03-28T10:00:00Z",
    "endpoints": [
        {
            "method": "GET",
            "path": "/api/v1/users/{user_id}/export",
            "auth_required": True,
            "rbac_required": True,
            "request_params": [
                {"name": "user_id", "type": "str", "location": "path"}
            ],
            "request_body": None,
            "response_model": "UserExportResponse",
            "response_fields": [
                {"name": "csv_data", "type": "str"},
                {"name": "filename", "type": "str"},
            ],
        }
    ],
    "models": [
        {
            "name": "UserExportResponse",
            "fields": [
                {"name": "csv_data", "type": "str", "description": "CSV file content"},
                {"name": "filename", "type": "str", "description": "Suggested filename"},
            ],
        }
    ],
    "stack": "fastapi-react",
}


def _validate_contract(contract: dict) -> list[str]:
    """Return a list of validation errors for a contract dict."""
    errors = []
    for field in ("app_id", "feature_description", "endpoints", "models", "stack"):
        if field not in contract:
            errors.append(f"Missing top-level field: {field}")

    for i, ep in enumerate(contract.get("endpoints", [])):
        for field in ("method", "path", "auth_required", "response_model"):
            if field not in ep:
                errors.append(f"Endpoint[{i}] missing field: {field}")
        method = ep.get("method", "")
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            errors.append(f"Endpoint[{i}] invalid method: {method}")

    for i, model in enumerate(contract.get("models", [])):
        if "name" not in model:
            errors.append(f"Model[{i}] missing name")
        if "fields" not in model:
            errors.append(f"Model[{i}] missing fields")
        for j, field in enumerate(model.get("fields", [])):
            if "name" not in field:
                errors.append(f"Model[{i}].fields[{j}] missing name")
            if "type" not in field:
                errors.append(f"Model[{i}].fields[{j}] missing type")

    return errors


class TestContractSchema:
    def test_valid_contract_passes(self):
        errors = _validate_contract(VALID_CONTRACT)
        assert errors == []

    def test_missing_app_id(self):
        bad = {**VALID_CONTRACT}
        del bad["app_id"]
        errors = _validate_contract(bad)
        assert any("app_id" in e for e in errors)

    def test_missing_endpoints(self):
        bad = {**VALID_CONTRACT}
        del bad["endpoints"]
        errors = _validate_contract(bad)
        assert any("endpoints" in e for e in errors)

    def test_missing_models(self):
        bad = {**VALID_CONTRACT}
        del bad["models"]
        errors = _validate_contract(bad)
        assert any("models" in e for e in errors)

    def test_endpoint_missing_method(self):
        bad = {
            **VALID_CONTRACT,
            "endpoints": [{**VALID_CONTRACT["endpoints"][0]}],
        }
        del bad["endpoints"][0]["method"]
        errors = _validate_contract(bad)
        assert any("method" in e for e in errors)

    def test_endpoint_invalid_method(self):
        bad = {
            **VALID_CONTRACT,
            "endpoints": [{**VALID_CONTRACT["endpoints"][0], "method": "FETCH"}],
        }
        errors = _validate_contract(bad)
        assert any("invalid method" in e for e in errors)

    def test_model_missing_fields(self):
        bad = {
            **VALID_CONTRACT,
            "models": [{"name": "UserExportResponse"}],
        }
        errors = _validate_contract(bad)
        assert any("fields" in e for e in errors)

    def test_contract_is_json_serializable(self):
        serialized = json.dumps(VALID_CONTRACT)
        restored = json.loads(serialized)
        assert restored["app_id"] == VALID_CONTRACT["app_id"]

    def test_empty_contract_has_errors(self):
        errors = _validate_contract({})
        assert len(errors) > 0
