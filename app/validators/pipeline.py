"""Run validation stages and return sectioned reports for GUI / CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.models import ValidationReport
from app.validators.lua_auditor import LuaAuditor
from app.validators.moddesc_validator import ModDescValidator
from app.validators.vehicle_validator import VehicleValidator

SECTION_MODDESC = "modDesc.xml"
SECTION_VEHICLES = "Vehicle Validation"
SECTION_LUA = "Lua Audit"


@dataclass(slots=True)
class ValidationSuiteResult:
    """Ordered sections produced by a full Validate click."""

    mod_root: Path
    sections: list[tuple[str, ValidationReport]]

    @property
    def passed(self) -> bool:
        return all(section.passed for _, section in self.sections)

    @property
    def error_count(self) -> int:
        return sum(section.error_count for _, section in self.sections)

    @property
    def warning_count(self) -> int:
        return sum(section.warning_count for _, section in self.sections)

    def section(self, title: str) -> ValidationReport | None:
        """Report of the section called ``title`` (None if it was not run)."""
        return next((report for name, report in self.sections if name == title), None)

    def summary_line(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        return (
            f"{status} - {self.mod_root.name}: "
            f"{self.error_count} error(s), {self.warning_count} warning(s) "
            f"across {len(self.sections)} section(s)"
        )

    def format_text(self) -> str:
        lines: list[str] = [
            f"Target folder: {self.mod_root}",
            self.summary_line(),
            "=" * 72,
        ]
        for title, report in self.sections:
            lines.append(f"[{title}]")
            lines.append(report.summary_line())
            lines.append("-" * 72)
            for issue in report.issues:
                lines.append(issue.format_line())
            lines.append("")
        lines.append("=" * 72)
        lines.append("Done.")
        return "\n".join(lines) + "\n"


def run_xml_validation_suite(mod_root: Path, *, include_lua: bool = True) -> ValidationSuiteResult:
    """Execute modDesc validation, vehicle validation, then the Lua audit.

    The Lua audit reads the files registered in modDesc.xml (extraSourceFiles,
    custom specializations ...) and the files they load with source(); pass
    ``include_lua=False`` to run the XML stages only.
    """
    root = mod_root.resolve()
    print(f"[Pipeline] Starting validation suite for: {root}")

    sections: list[tuple[str, ValidationReport]] = [
        (SECTION_MODDESC, ModDescValidator(root).validate()),
        (SECTION_VEHICLES, VehicleValidator(root).validate()),
    ]
    if include_lua:
        sections.append((SECTION_LUA, LuaAuditor(root).audit()))

    result = ValidationSuiteResult(mod_root=root, sections=sections)
    print(f"[Pipeline] {result.summary_line()}")
    return result
