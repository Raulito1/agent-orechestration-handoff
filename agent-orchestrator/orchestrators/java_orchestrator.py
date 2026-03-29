"""Java Orchestrator — sequences Java Spring Boot agent → React agent for feature generation."""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agents.java_agent import JavaAgent
from agents.fastapi_agent import BackendGenerationResult
from agents.react_agent import ReactAgent, ReactGenerationResult
from orchestrators.base_orchestrator import BaseOrchestrator
from orchestrators.fastapi_orchestrator import (
    FeatureOutput,
    _component_name,
    _feature_slug,
    _write_output,
)

_BACKEND_FILENAMES = {
    "controller": "Controller.java",
    "service": "Service.java",
    "repository": "Repository.java",
    "migration": "migration.yaml",
    "request_dto": "RequestDTO.java",
    "response_dto": "ResponseDTO.java",
    "mapper": "Mapper.java",
}

_REACT_FILENAMES = {
    "rtk_endpoint": "apiSlice.ts",
    "ts_types": "types.ts",
    "component": "{component}.tsx",
}


class JavaOrchestrator(BaseOrchestrator):
    """Orchestrates Java Spring Boot + React feature generation."""

    def run(
        self,
        description: str,
        app_id: str,
        progress_callback=None,
    ) -> FeatureOutput:
        app_config = self.get_app(app_id)
        app_name = app_config.get("name", app_id)

        # Load context files
        java_context = self._load_context_safe(app_config.get("contexts", {}).get("api", ""))
        react_context = self._load_context_safe(app_config.get("contexts", {}).get("web", ""))

        # Step 1: Java agent
        if progress_callback:
            progress_callback("java_start")

        java_agent = JavaAgent(
            client=self.get_anthropic_client(),
            system_prompt=java_context,
        )
        backend_result: BackendGenerationResult = java_agent.generate(description, app_name)

        if progress_callback:
            progress_callback("java_done", backend_result.files)

        # Step 2: Extract contract
        if progress_callback:
            progress_callback("contract_done", backend_result.contract)

        # Step 3: React agent
        if progress_callback:
            progress_callback("react_start")

        react_agent = ReactAgent(
            client=self.get_anthropic_client(),
            system_prompt=react_context,
        )
        react_result: ReactGenerationResult = react_agent.generate(backend_result.contract)

        if progress_callback:
            progress_callback("react_done", react_result.files)

        # Step 4: Write output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _feature_slug(description)
        out_dir = Path("output") / app_id / f"{timestamp}_{slug}"
        out_dir.mkdir(parents=True, exist_ok=True)

        _write_java_output(out_dir, backend_result, react_result, description, slug)

        return FeatureOutput(
            app_id=app_id,
            feature_description=description,
            timestamp=timestamp,
            contract=backend_result.contract,
            backend_files=backend_result.files,
            react_files=react_result.files,
            output_directory=str(out_dir),
        )

    def _load_context_safe(self, context_path: str) -> str:
        if not context_path:
            warnings.warn("Context path is empty — using default prompt.")
            return ""
        try:
            return self.load_context(context_path)
        except (FileNotFoundError, OSError) as exc:
            warnings.warn(f"Context file not found ({context_path}): {exc} — using default prompt.")
            return ""


def _write_java_output(
    out_dir: Path,
    backend: BackendGenerationResult,
    react: ReactGenerationResult,
    description: str,
    slug: str,
) -> None:
    # contract.json
    (out_dir / "contract.json").write_text(
        json.dumps(backend.contract, indent=2), encoding="utf-8"
    )

    # backend/
    backend_dir = out_dir / "backend"
    backend_dir.mkdir(exist_ok=True)
    for file_type, code in backend.files.items():
        filename = _BACKEND_FILENAMES.get(file_type, f"{file_type}.java")
        (backend_dir / filename).write_text(code, encoding="utf-8")

    # react/
    react_dir = out_dir / "react"
    react_dir.mkdir(exist_ok=True)
    component_name = _component_name(description)
    for file_type, code in react.files.items():
        filename = _REACT_FILENAMES.get(file_type, f"{file_type}.ts")
        filename = filename.replace("{component}", component_name)
        (react_dir / filename).write_text(code, encoding="utf-8")
