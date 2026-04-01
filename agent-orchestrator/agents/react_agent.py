"""React Agent — consumes a backend API contract and generates the React layer.

Uses claude-sonnet-4-6 with the react context as system prompt.
Receives contract JSON as input — never reads backend files directly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from utils.roo_client import RooClient


@dataclass
class ReactGenerationResult:
    files: dict[str, str]
    # file_type values: rtk_endpoint, ts_types, component


_FILE_TYPES = ["rtk_endpoint", "ts_types", "component"]

_HEADER_MAP = [
    ("rtk_endpoint", r"rtk|api.?slice|endpoint|apiSlice"),
    ("ts_types", r"ts.?type|type|types\.ts"),
    ("component", r"component|\.tsx"),
]


def _parse_react_files(text: str) -> dict[str, str]:
    """Parse generated React files from the response using ## section headers."""
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


class ReactAgent:
    """Calls claude-sonnet-4-6 to generate a React layer from an API contract."""

    def __init__(
        self,
        client: RooClient | None = None,
        system_prompt: str = "",
    ) -> None:
        self._client = client or RooClient()
        self._system_prompt = system_prompt or "You are a React code generation expert."

    def generate(self, contract: dict) -> ReactGenerationResult:
        contract_json = json.dumps(contract, indent=2)

        user_prompt = (
            f"API Contract:\n{contract_json}\n\n"
            "Generate the React layer for this feature.\n"
            "Follow ALL conventions in your system prompt exactly.\n"
            "Use UIX primitives — never raw Tailwind on non-primitive elements.\n"
            "Wrap data-fetching components in <AsyncBoundary>.\n"
            "Wire the RTK Query hook to the component.\n\n"
            "Structure your response with these sections in order:\n"
            "## rtk_endpoint (apiSlice.ts)\n"
            "## ts_types (types.ts)\n"
            "## component (.tsx)\n\n"
            "Each section must contain a fenced code block."
        )

        response = self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw = response.content[0].text
        files = _parse_react_files(raw)

        return ReactGenerationResult(files=files)
