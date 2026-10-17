"""Validation result models used across Doctor modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    """Issue severity for UI coloring and summaries."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    OK = "ok"


@dataclass(slots=True)
class ValidationIssue:
    """Single check result line."""

    severity: Severity
    message: str
    location: str | None = None

    def format_line(self) -> str:
        prefix = self.severity.value.upper()
        loc = f" [{self.location}]" if self.location else ""
        return f"[{prefix}]{loc} {self.message}"


@dataclass(slots=True)
class ValidationReport:
    """Aggregated results for one validation run."""

    target: Path
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(
        self,
        severity: Severity,
        message: str,
        location: str | None = None,
    ) -> None:
        self.issues.append(ValidationIssue(severity, message, location))

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def summary_line(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        return (
            f"{status} - {self.target.name}: "
            f"{self.error_count} error(s), {self.warning_count} warning(s)"
        )
