from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Violation:
    rule_id: str
    severity: Literal["CRITICAL", "WARNING"]
    file_path: str
    line_number: int | None
    message: str
    suggestion: str


@dataclass
class GuardResult:
    app_id: str
    critical_violations: list[Violation] = field(default_factory=list)
    warning_violations: list[Violation] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def passed(self) -> bool:
        return len(self.critical_violations) == 0
