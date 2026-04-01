"""RooClient — drop-in replacement for anthropic.Anthropic() via roo CLI subprocess.

Mimics the anthropic.Anthropic().messages.create() interface so it can be
passed as the ``client`` argument to FastAPIAgent, JavaAgent, ReactAgent,
WorkIntelligence, and HealthMonitor without changing any calling code.

The system prompt and user messages are combined into a single prompt and
forwarded to ``roo --task <prompt>``.  stdout is returned as the response text.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class _Content:
    text: str


@dataclass
class _Response:
    content: list[_Content]


class _Messages:
    def create(
        self,
        model: str = "",
        max_tokens: int = 4096,
        system: str = "",
        messages: list[dict] | None = None,
    ) -> _Response:
        parts: list[str] = []

        if system:
            parts.append(f"<system>\n{system}\n</system>")

        for msg in messages or []:
            if msg.get("role") == "user":
                content = msg["content"]
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                parts.append(str(content))

        full_prompt = "\n\n".join(parts)

        result = subprocess.run(
            ["roo", "--task", full_prompt],
            capture_output=True,
            text=True,
        )
        return _Response(content=[_Content(text=result.stdout.strip())])


class RooClient:
    """Drop-in replacement for anthropic.Anthropic() that delegates to roo CLI."""

    def __init__(self) -> None:
        self.messages = _Messages()
