"""Read-only checks for i3D files referenced by a mod.

The element and attribute names come from the Giants i3D 1.6 schema
(``i3D``, ``Files/File@fileId``, ``Files/File@filename``, ``Scene`` nodeId on
``TransformGroup`` and the types that extend it). Paths are checked with the
same case-sensitive walk used for modDesc, because Linux dedicated servers
do not ignore letter case.

This module never rewrites an i3D file.
"""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.models import Severity, ValidationReport
from app.core.path_utils import (
    is_engine_dollar_path,
    normalize_mod_relative,
    path_exists_case_sensitive,
)

# Scene nodes that inherit TransformGroupType.nodeId in i3d-1.6.xsd.
_TRANSFORM_TAGS = frozenset(
    {
        "TransformGroup",
        "ReferenceNode",
        "Shape",
        "Camera",
        "Light",
        "Dynamic",
        "AudioSource",
        "TerrainTransformGroup",
        "NavigationMesh",
        "Note",
    }
)

# fileId is the Files/File key. fileIds is the AudioSource integer list.
# iesProfileFileId is the Light attribute the schema uses for an IES profile file.
_FILE_ID_ATTRIBUTES = frozenset({"fileId", "fileIds", "iesProfileFileId"})


class I3DAuditor:
    """Check i3D files named by vehicle.base.filename and placeable.base.filename."""

    def __init__(self, mod_root: Path) -> None:
        self.mod_root = mod_root.resolve()

    def audit(self) -> ValidationReport:
        report = ValidationReport(target=self.mod_root)
        if not self.mod_root.is_dir():
            report.add(Severity.ERROR, f"I3D-000: Mod folder does not exist: {self.mod_root}")
            print(f"[I3DAuditor] {report.summary_line()}")
            return report

        references = _referenced_i3d_files(self.mod_root)
        if not references:
            report.add(
                Severity.INFO,
                "I3D-000: No vehicle.base.filename or placeable.base.filename points at an .i3d file.",
                location=self.mod_root.name,
            )
            print(f"[I3DAuditor] {report.summary_line()}")
            return report

        seen: set[Path] = set()
        for xml_location, relative in references:
            if is_engine_dollar_path(relative):
                continue
            exists, detail = path_exists_case_sensitive(self.mod_root, relative)
            if not exists:
                report.add(
                    Severity.WARNING,
                    f"I3D-002: {xml_location} '{relative}' does not match a file on disk. {detail}",
                    location=xml_location,
                )
                continue
            path = (self.mod_root / normalize_mod_relative(relative)).resolve()
            if path in seen:
                continue
            seen.add(path)
            _audit_i3d_file(self.mod_root, path, report)

        print(f"[I3DAuditor] {report.summary_line()}")
        return report


def _referenced_i3d_files(mod_root: Path) -> list[tuple[str, str]]:
    """Return (xml location, relative i3d path) for verified base.filename entries."""
    found: list[tuple[str, str]] = []
    for path in sorted(mod_root.rglob("*.xml")):
        if _under_junk(mod_root, path):
            continue
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        location = _relative(mod_root, path)
        xml_dir = _relative(mod_root, path.parent)
        for tag in ("vehicle", "placeable"):
            for owner in root.iter(tag):
                base = owner.find("base")
                if base is None:
                    continue
                filename = base.find("filename")
                text = (filename.text or "").strip() if filename is not None else ""
                if not text.lower().endswith(".i3d"):
                    continue
                # vehicle.base.filename is loaded from the XML file's directory.
                relative = text.replace("\\", "/")
                if not is_engine_dollar_path(relative):
                    joined = _join_i3d_relative(xml_dir, relative)
                    if joined is not None:
                        relative = joined
                found.append((f"{location} {tag}.base.filename", relative))
    return found


def _audit_i3d_file(mod_root: Path, path: Path, report: ValidationReport) -> None:
    location = _relative(mod_root, path)
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        report.add(Severity.ERROR, f"I3D-005: Cannot read i3D XML: {exc}", location=location)
        return
    if root.tag != "i3D":
        report.add(
            Severity.ERROR,
            f"I3D-005: Root element must be <i3D>, found <{root.tag}>.",
            location=location,
        )
        return

    declared = _declared_files(root, report, location)
    _check_filenames(mod_root, path, declared, report, location)
    _check_file_references(root, declared, report, location)
    _check_duplicate_node_ids(root, report, location)


def _declared_files(root: ET.Element, report: ValidationReport, location: str) -> dict[str, str]:
    """Map fileId text to the filename from Files/File."""
    declared: dict[str, str] = {}
    files = root.find("Files")
    if files is None:
        return declared
    for index, file_node in enumerate(files.findall("File"), start=1):
        file_id = (file_node.get("fileId") or "").strip()
        filename = (file_node.get("filename") or "").strip()
        where = f"{location} Files/File[{index}]"
        if not file_id:
            report.add(Severity.WARNING, "I3D-004: <File> has no fileId.", location=where)
            continue
        if file_id in declared:
            report.add(
                Severity.WARNING,
                f"I3D-004: fileId {file_id} is declared more than once in <Files>.",
                location=where,
            )
        else:
            declared[file_id] = filename
        if not filename:
            report.add(
                Severity.WARNING,
                f"I3D-002: fileId {file_id} has no filename.",
                location=where,
            )
    return declared


def _check_filenames(
    mod_root: Path,
    i3d_path: Path,
    declared: dict[str, str],
    report: ValidationReport,
    location: str,
) -> None:
    i3d_dir = _relative(mod_root, i3d_path.parent)
    for file_id, filename in declared.items():
        if not filename or is_engine_dollar_path(filename):
            continue
        combined = _join_i3d_relative(i3d_dir, filename)
        if combined is None:
            report.add(
                Severity.WARNING,
                f"I3D-002: fileId {file_id} filename '{filename}' points outside the mod folder.",
                location=location,
            )
            continue
        exists, detail = path_exists_case_sensitive(mod_root, combined)
        if not exists:
            report.add(
                Severity.WARNING,
                f"I3D-002: fileId {file_id} filename '{filename}' does not match a file on disk. {detail}",
                location=location,
            )


def _check_file_references(
    root: ET.Element,
    declared: dict[str, str],
    report: ValidationReport,
    location: str,
) -> None:
    for element in root.iter():
        for attr, raw in element.attrib.items():
            if attr not in _FILE_ID_ATTRIBUTES:
                continue
            for token in raw.split():
                token = token.strip()
                if not token or token in declared:
                    continue
                report.add(
                    Severity.WARNING,
                    f"I3D-001: {element.tag} @{attr} '{token}' is not a fileId in <Files>.",
                    location=f"{location} {element.tag}",
                )


def _check_duplicate_node_ids(root: ET.Element, report: ValidationReport, location: str) -> None:
    scene = root.find("Scene")
    if scene is None:
        return
    seen: dict[str, str] = {}
    for element in scene.iter():
        if element.tag not in _TRANSFORM_TAGS:
            continue
        node_id = (element.get("nodeId") or "").strip()
        if not node_id:
            continue
        name = element.get("name") or element.tag
        label = f"{element.tag} '{name}'"
        previous = seen.get(node_id)
        if previous is None:
            seen[node_id] = label
            continue
        report.add(
            Severity.WARNING,
            f"I3D-003: nodeId {node_id} is repeated in <Scene> ({previous} and {label}). "
            "i3d-1.6.xsd stores one nodeId on each TransformGroup.",
            location=location,
        )


def _join_i3d_relative(i3d_dir: str, filename: str) -> str | None:
    """Join a Files filename onto the i3D directory. None when it leaves the mod."""
    declared = normalize_mod_relative(filename.replace("\\", "/"))
    base = i3d_dir.strip("/")
    combined = posixpath.normpath(f"{base}/{declared}" if base else declared)
    if combined.startswith("../") or combined == "..":
        return None
    return combined


def _under_junk(root: Path, path: Path) -> bool:
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    return any(part.lower() in {".git", ".github"} for part in parts)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name
