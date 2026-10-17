"""Validate FS25 modDesc.xml structure, required tags, and referenced files."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.models import Severity, ValidationReport
from app.core.path_utils import is_engine_dollar_path, path_exists_case_sensitive

# Tags that every shippable FS25 modDesc should contain (text content).
REQUIRED_TEXT_TAGS: tuple[str, ...] = (
    "author",
    "version",
    "iconFilename",
)


class ModDescValidator:
    """Phase-1 validator focused on modDesc.xml integrity."""

    def __init__(self, mod_root: Path) -> None:
        self.mod_root = mod_root.resolve()
        self.mod_desc_path = self.mod_root / "modDesc.xml"

    def validate(self) -> ValidationReport:
        report = ValidationReport(target=self.mod_desc_path)

        if not self.mod_root.is_dir():
            report.add(
                Severity.ERROR,
                f"Mod folder does not exist: {self.mod_root}",
            )
            return report

        # Case-sensitive check for modDesc.xml itself (common Linux fail).
        ok, detail = path_exists_case_sensitive(self.mod_root, "modDesc.xml")
        if not ok:
            # Also try discovering wrong case of the filename.
            ci = self._find_moddesc_case_mismatch()
            if ci:
                report.add(
                    Severity.ERROR,
                    (
                        f"modDesc.xml casing is wrong. Disk has '{ci.name}'. "
                        "Dedicated servers require exact 'modDesc.xml'."
                    ),
                    location=ci.name,
                )
            else:
                report.add(Severity.ERROR, detail, location="modDesc.xml")
            return report

        raw = self._read_text(report)
        if raw is None:
            return report

        root = self._parse_xml(raw, report)
        if root is None:
            return report

        self._check_root_element(root, report)
        self._check_required_tags(root, report)
        self._check_icon_filename(root, report)
        self._check_extra_source_files(root, report)

        if report.passed and report.error_count == 0:
            report.add(
                Severity.OK,
                "modDesc.xml is well-formed; required tags and referenced files OK.",
            )

        print(f"[ModDescValidator] {report.summary_line()}")
        return report

    def _find_moddesc_case_mismatch(self) -> Path | None:
        try:
            for entry in self.mod_root.iterdir():
                if entry.is_file() and entry.name.lower() == "moddesc.xml":
                    if entry.name != "modDesc.xml":
                        return entry
        except OSError:
            return None
        return None

    def _read_text(self, report: ValidationReport) -> str | None:
        try:
            # Giants files are typically UTF-8; fall back for older packs.
            return self.mod_desc_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return self.mod_desc_path.read_text(encoding="utf-8-sig")
            except OSError as exc:
                report.add(Severity.ERROR, f"Cannot read modDesc.xml: {exc}")
                return None
        except OSError as exc:
            report.add(Severity.ERROR, f"Cannot read modDesc.xml: {exc}")
            return None

    def _parse_xml(self, raw: str, report: ValidationReport) -> ET.Element | None:
        try:
            return ET.fromstring(raw)
        except ET.ParseError as exc:
            report.add(
                Severity.ERROR,
                f"XML is not well-formed: {exc}",
                location="modDesc.xml",
            )
            return None

    def _check_root_element(self, root: ET.Element, report: ValidationReport) -> None:
        if root.tag != "modDesc":
            report.add(
                Severity.ERROR,
                f"Root element must be <modDesc>, found <{root.tag}>.",
                location="modDesc.xml",
            )
            return

        desc_version = root.get("descVersion")
        if not desc_version:
            report.add(
                Severity.WARNING,
                "Missing descVersion attribute on <modDesc> (recommended for FS25).",
                location="modDesc",
            )
        else:
            report.add(
                Severity.INFO,
                f"descVersion = {desc_version}",
                location="modDesc",
            )

    def _check_required_tags(self, root: ET.Element, report: ValidationReport) -> None:
        for tag in REQUIRED_TEXT_TAGS:
            element = root.find(tag)
            if element is None:
                report.add(
                    Severity.ERROR,
                    f"Missing required tag <{tag}>.",
                    location=tag,
                )
                continue

            text = (element.text or "").strip()
            if not text:
                report.add(
                    Severity.ERROR,
                    f"Required tag <{tag}> is empty.",
                    location=tag,
                )
            else:
                report.add(
                    Severity.INFO,
                    f"<{tag}> = {text}",
                    location=tag,
                )

    def _check_icon_filename(self, root: ET.Element, report: ValidationReport) -> None:
        element = root.find("iconFilename")
        if element is None:
            return  # already reported as missing required tag

        relative = (element.text or "").strip()
        if not relative:
            return

        if is_engine_dollar_path(relative):
            report.add(
                Severity.WARNING,
                f"iconFilename uses engine path (not verified on disk): {relative}",
                location="iconFilename",
            )
            return

        ok, detail = path_exists_case_sensitive(self.mod_root, relative)
        if ok:
            report.add(
                Severity.OK,
                f"iconFilename exists: {detail}",
                location="iconFilename",
            )
        else:
            report.add(
                Severity.ERROR,
                f"iconFilename: {detail}",
                location="iconFilename",
            )

    def _check_extra_source_files(
        self,
        root: ET.Element,
        report: ValidationReport,
    ) -> None:
        container = root.find("extraSourceFiles")
        if container is None:
            report.add(
                Severity.INFO,
                "No <extraSourceFiles> block (OK for vehicle-only mods).",
                location="extraSourceFiles",
            )
            return

        source_files = list(container.findall("sourceFile"))
        if not source_files:
            report.add(
                Severity.WARNING,
                "<extraSourceFiles> is present but has no <sourceFile> entries.",
                location="extraSourceFiles",
            )
            return

        for index, source in enumerate(source_files, start=1):
            filename = (source.get("filename") or "").strip()
            loc = f"extraSourceFiles/sourceFile[{index}]"

            if not filename:
                report.add(
                    Severity.ERROR,
                    "Missing filename attribute on <sourceFile>.",
                    location=loc,
                )
                continue

            if is_engine_dollar_path(filename):
                report.add(
                    Severity.WARNING,
                    f"Engine path skipped: {filename}",
                    location=loc,
                )
                continue

            ok, detail = path_exists_case_sensitive(self.mod_root, filename)
            if ok:
                report.add(
                    Severity.OK,
                    f"Source file exists: {detail}",
                    location=loc,
                )
            else:
                report.add(
                    Severity.ERROR,
                    f"sourceFile '{filename}': {detail}",
                    location=loc,
                )
