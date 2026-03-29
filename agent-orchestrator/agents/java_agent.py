"""Java Spring Boot Agent — generates a full Spring Boot layer chain for a feature.

Uses claude-opus-4-5 with the spring-boot context as system prompt.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import anthropic

from agents.fastapi_agent import BackendGenerationResult, _parse_contract


_FILE_TYPES = [
    "controller",
    "service",
    "repository",
    "migration",
    "request_dto",
    "response_dto",
    "mapper",
]

_HEADER_MAP = [
    ("controller", r"controller"),
    ("service", r"service"),
    ("repository", r"repositor|repo"),
    ("migration", r"migration|liquibase"),
    ("request_dto", r"request.?dto|request"),
    ("response_dto", r"response.?dto|response"),
    ("mapper", r"mapper"),
]


def _parse_java_files(text: str) -> dict[str, str]:
    """Parse generated Java files from the response using ## section headers."""
    text = re.sub(r"<contract>.*?</contract>", "", text, flags=re.DOTALL)

    files: dict[str, str] = {}
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue
        first_line = section.split("\n", 1)[0]
        for file_type, pattern in _HEADER_MAP:
            if file_type in files:
                continue
            if re.search(pattern, first_line, re.IGNORECASE):
                code_match = re.search(r"```(?:\w+)?\n(.*?)```", section, re.DOTALL)
                if code_match:
                    files[file_type] = code_match.group(1).strip()
                break

    for file_type in _FILE_TYPES:
        if file_type not in files:
            files[file_type] = f"// {file_type} — not generated\n"

    return files


class JavaAgent:
    """Calls claude-opus-4-5 to generate a Spring Boot layer chain."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        system_prompt: str = "",
    ) -> None:
        self._client = client or anthropic.Anthropic()
        self._system_prompt = system_prompt or "You are a Java Spring Boot code generation expert."

    def generate(self, description: str, app_name: str) -> BackendGenerationResult:
        user_prompt = (
            f"Feature: {description}\n"
            f"App: {app_name}\n\n"
            "Generate the complete Spring Boot layer chain for this feature.\n"
            "Follow ALL conventions in your system prompt exactly.\n"
            "Controllers must have @PreAuthorize annotations.\n"
            "Services must use Mono.fromCallable + Schedulers.boundedElastic().\n"
            "Never use .block() in reactive code.\n\n"
            "Structure your response with these sections in order:\n"
            "## controller\n"
            "## service\n"
            "## repository\n"
            "## migration\n"
            "## request_dto\n"
            "## response_dto\n"
            "## mapper\n\n"
            "Each section must contain a fenced code block.\n"
            "After all files, output the API contract as a JSON block "
            "tagged with <contract>...</contract> so it can be parsed."
        )

        response = self._client.messages.create(
            model="claude-opus-4-5",
            max_tokens=8000,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw = response.content[0].text
        contract = _parse_contract(raw)
        files = _parse_java_files(raw)

        return BackendGenerationResult(contract=contract, files=files)
