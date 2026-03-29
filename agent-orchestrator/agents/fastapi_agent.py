"""FastAPI Agent — generates a full FastAPI layer chain for a feature.

Uses claude-opus-4-5 with the fastapi context as system prompt.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import anthropic


@dataclass
class BackendGenerationResult:
    contract: dict
    files: dict[str, str]
    # file_type values: router, service, repository, sql, request_model, response_model


_FILE_TYPES = ["router", "service", "repository", "sql", "request_model", "response_model"]

_HEADER_MAP = [
    ("router", r"router"),
    ("service", r"service"),
    ("repository", r"repositor|repo"),
    ("sql", r"\.sql|^sql"),
    ("request_model", r"request.?model|request"),
    ("response_model", r"response.?model|response"),
]


def _parse_contract(text: str) -> dict:
    """Extract and parse the <contract>...</contract> block."""
    match = re.search(r"<contract>(.*?)</contract>", text, re.DOTALL)
    if not match:
        return {}
    raw = match.group(1).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {}


def _parse_files(text: str) -> dict[str, str]:
    """Parse generated files from the response using ## section headers."""
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
            files[file_type] = f"# {file_type} — not generated\n"

    return files


class FastAPIAgent:
    """Calls claude-opus-4-5 to generate a FastAPI layer chain."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        system_prompt: str = "",
    ) -> None:
        self._client = client or anthropic.Anthropic()
        self._system_prompt = system_prompt or "You are a FastAPI code generation expert."

    def generate(self, description: str, app_name: str) -> BackendGenerationResult:
        user_prompt = (
            f"Feature: {description}\n"
            f"App: {app_name}\n\n"
            "Generate the complete FastAPI layer chain for this feature.\n"
            "Follow ALL conventions in your system prompt exactly.\n"
            "The RBAC CTE pattern is mandatory in every SQL file.\n\n"
            "Structure your response with these sections in order:\n"
            "## router.py\n"
            "## service.py\n"
            "## repository.py\n"
            "## sql\n"
            "## request_model.py\n"
            "## response_model.py\n\n"
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
        files = _parse_files(raw)

        return BackendGenerationResult(contract=contract, files=files)
