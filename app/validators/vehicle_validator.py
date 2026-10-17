"""Validate FS25 vehicle XML files against vehicleTypes and specializations."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from app.core.models import Severity, ValidationReport
from app.knowledge.fs25_catalog import Fs25Catalog, get_catalog

# Folders / names that are never vehicle definitions.
_SKIP_DIR_NAMES = {
    "languages",
    "l10n",
    "maps",
    "map",
    "sounds",
    "shaders",
    "textures",
    ".git",
    "__pycache__",
}
_SKIP_FILE_NAMES = {
    "moddesc.xml",
    "machineconfigurations.xml",
    "map.xml",
    "mapgroundresources.xml",
}


@dataclass(slots=True)
class VehicleTypeDef:
    """A <type> entry from modDesc <vehicleTypes>."""

    name: str
    parent: str | None
    specializations: list[str] = field(default_factory=list)
    filename: str | None = None


@dataclass(slots=True)
class ResolvedType:
    """Resolved specialization set for a vehicle type attribute."""

    name: str
    specializations: set[str]
    source: str  # "custom" | "vanilla" | "custom+vanilla_parent" | "unknown"
    vanilla_ancestor: str | None = None


class VehicleValidator:
    """Scan mod vehicle XMLs and check type / specialization consistency."""

    def __init__(self, mod_root: Path, catalog: Fs25Catalog | None = None) -> None:
        self.mod_root = mod_root.resolve()
        self.catalog = catalog or get_catalog()
        self._custom_types: dict[str, VehicleTypeDef] = {}

    def validate(self) -> ValidationReport:
        report = ValidationReport(target=self.mod_root / "(vehicles)")
        self._custom_types = self._parse_vehicle_types(report)

        vehicle_files = self._discover_vehicle_files(report)
        if not vehicle_files:
            report.add(
                Severity.INFO,
                "No <vehicle> XML files found in this mod.",
            )
            print(f"[VehicleValidator] {report.summary_line()}")
            return report

        report.add(
            Severity.INFO,
            f"Found {len(vehicle_files)} vehicle XML file(s).",
        )

        for path in vehicle_files:
            self._validate_vehicle_file(path, report)

        if report.passed:
            report.add(
                Severity.OK,
                "Vehicle XML scan finished without errors.",
            )

        print(f"[VehicleValidator] {report.summary_line()}")
        return report

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_vehicle_files(self, report: ValidationReport) -> list[Path]:
        found: list[Path] = []
        for path in sorted(self.mod_root.rglob("*.xml")):
            rel = path.relative_to(self.mod_root)
            if any(part.lower() in _SKIP_DIR_NAMES for part in rel.parts[:-1]):
                continue
            if path.name.lower() in _SKIP_FILE_NAMES:
                continue
            if not self._looks_like_vehicle_xml(path):
                continue
            found.append(path)
        return found

    def _looks_like_vehicle_xml(self, path: Path) -> bool:
        try:
            # Fast path: peek root tag without full parse of huge files when possible.
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for _ in range(40):
                    line = handle.readline()
                    if not line:
                        break
                    stripped = line.strip()
                    if not stripped or stripped.startswith("<?") or stripped.startswith("<!--"):
                        continue
                    return stripped.startswith("<vehicle")
        except OSError:
            return False
        return False

    # ------------------------------------------------------------------
    # modDesc vehicleTypes
    # ------------------------------------------------------------------

    def _parse_vehicle_types(self, report: ValidationReport) -> dict[str, VehicleTypeDef]:
        mod_desc = self.mod_root / "modDesc.xml"
        types: dict[str, VehicleTypeDef] = {}
        if not mod_desc.is_file():
            report.add(
                Severity.WARNING,
                "modDesc.xml missing — cannot resolve custom vehicleTypes.",
                location="vehicleTypes",
            )
            return types

        try:
            root = ET.parse(mod_desc).getroot()
        except ET.ParseError as exc:
            report.add(
                Severity.WARNING,
                f"Could not parse modDesc for vehicleTypes: {exc}",
                location="vehicleTypes",
            )
            return types

        container = root.find("vehicleTypes")
        if container is None:
            report.add(
                Severity.INFO,
                "No custom <vehicleTypes> in modDesc (vanilla types only).",
                location="vehicleTypes",
            )
            return types

        for type_el in container.findall("type"):
            name = (type_el.get("name") or "").strip()
            if not name:
                report.add(
                    Severity.ERROR,
                    "A <type> entry is missing name attribute.",
                    location="vehicleTypes",
                )
                continue
            parent = (type_el.get("parent") or "").strip() or None
            specs = [
                (spec.get("name") or "").strip()
                for spec in type_el.findall("specialization")
                if (spec.get("name") or "").strip()
            ]
            types[name] = VehicleTypeDef(
                name=name,
                parent=parent,
                specializations=specs,
                filename=(type_el.get("filename") or None),
            )
            report.add(
                Severity.INFO,
                (
                    f"Custom vehicleType '{name}'"
                    + (f" parent='{parent}'" if parent else "")
                    + f" (+{len(specs)} specialization(s))"
                ),
                location="vehicleTypes",
            )

        return types

    def _resolve_type(self, type_name: str) -> ResolvedType:
        catalog = self.catalog
        if type_name in self._custom_types:
            specs: set[str] = set()
            vanilla_ancestor: str | None = None
            current: str | None = type_name
            seen: set[str] = set()

            while current:
                if current in seen:
                    break
                seen.add(current)

                if current in self._custom_types:
                    typedef = self._custom_types[current]
                    for spec in typedef.specializations:
                        specs.add(catalog.normalize_specialization(spec))
                    current = typedef.parent
                    continue

                # Hit vanilla / external parent
                vanilla_ancestor = current
                break

            source = "custom+vanilla_parent" if vanilla_ancestor else "custom"
            return ResolvedType(
                name=type_name,
                specializations=specs,
                source=source,
                vanilla_ancestor=vanilla_ancestor,
            )

        if catalog.is_known_vanilla_type(type_name):
            return ResolvedType(
                name=type_name,
                specializations=set(),
                source="vanilla",
                vanilla_ancestor=type_name,
            )

        return ResolvedType(
            name=type_name,
            specializations=set(),
            source="unknown",
        )

    def _type_has_specialization(self, resolved: ResolvedType, spec_name: str) -> bool:
        canonical = self.catalog.normalize_specialization(spec_name)
        for owned in resolved.specializations:
            if owned.lower() == canonical.lower():
                return True
        return False

    # ------------------------------------------------------------------
    # Per-file validation
    # ------------------------------------------------------------------

    def _validate_vehicle_file(self, path: Path, report: ValidationReport) -> None:
        rel = path.relative_to(self.mod_root).as_posix()
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            report.add(
                Severity.ERROR,
                f"XML is not well-formed: {exc}",
                location=rel,
            )
            return

        if root.tag != "vehicle":
            report.add(
                Severity.ERROR,
                f"Root element must be <vehicle>, found <{root.tag}>.",
                location=rel,
            )
            return

        report.add(Severity.OK, "Root tag <vehicle> OK.", location=rel)

        type_name = (root.get("type") or "").strip()
        if not type_name:
            report.add(
                Severity.ERROR,
                "Missing required attribute type=\"...\".",
                location=rel,
            )
            return

        resolved = self._resolve_type(type_name)
        self._report_type_resolution(rel, type_name, resolved, report)
        if resolved.source == "unknown":
            return

        self._check_specialization_blocks(rel, root, resolved, report)

    def _report_type_resolution(
        self,
        rel: str,
        type_name: str,
        resolved: ResolvedType,
        report: ValidationReport,
    ) -> None:
        if resolved.source == "custom":
            report.add(
                Severity.OK,
                (
                    f"type=\"{type_name}\" matches custom vehicleType "
                    f"({len(resolved.specializations)} specialization(s) resolved)."
                ),
                location=rel,
            )
        elif resolved.source == "custom+vanilla_parent":
            report.add(
                Severity.OK,
                (
                    f"type=\"{type_name}\" is custom; inherits vanilla parent "
                    f"'{resolved.vanilla_ancestor}' "
                    f"(+{len(resolved.specializations)} explicit specialization(s))."
                ),
                location=rel,
            )
            report.add(
                Severity.INFO,
                (
                    "Only specializations listed in this mod's <vehicleTypes> chain "
                    "are treated as registered. Blocks that need extra specs must be "
                    "added explicitly (errors if missing)."
                ),
                location=rel,
            )
        elif resolved.source == "vanilla":
            report.add(
                Severity.OK,
                f"type=\"{type_name}\" is a recognized FS25 base vehicle type.",
                location=rel,
            )
            report.add(
                Severity.INFO,
                (
                    "Vanilla type specialization lists are not fully embedded; "
                    "XML block vs specialization mismatches are warnings only."
                ),
                location=rel,
            )
        else:
            known_custom = ", ".join(sorted(self._custom_types)) or "(none)"
            report.add(
                Severity.ERROR,
                (
                    f"Unknown vehicle type \"{type_name}\". "
                    f"Not found in modDesc <vehicleTypes> [{known_custom}] "
                    "and not in the known FS25 base type list. "
                    "Check spelling or register a custom <type>."
                ),
                location=rel,
            )

    def _check_specialization_blocks(
        self,
        rel: str,
        root: ET.Element,
        resolved: ResolvedType,
        report: ValidationReport,
    ) -> None:
        catalog = self.catalog
        checked_specs: set[str] = set()

        for child in list(root):
            tag = child.tag
            if not isinstance(tag, str):
                continue
            if tag in catalog.force_skip_tags:
                continue

            ambiguous = catalog.ambiguous_specs_for_block(tag)
            if ambiguous:
                self._check_ambiguous_block(rel, tag, ambiguous, resolved, report)
                continue

            required = catalog.specialization_for_block(tag)
            if required is None:
                # Unknown child — ignore (could be mod-specific / TerraFarm machine, etc.)
                if tag == "machine":
                    report.add(
                        Severity.INFO,
                        (
                            "Found <machine> block (TerraFarm). Ensure specialization "
                            "'FS25_0_TerraFarm.machine' is last on the vehicle type."
                        ),
                        location=rel,
                    )
                continue

            if required.lower() in checked_specs:
                continue
            checked_specs.add(required.lower())

            self._assert_spec_present(rel, tag, required, resolved, report)

    def _check_ambiguous_block(
        self,
        rel: str,
        tag: str,
        candidates: tuple[str, ...],
        resolved: ResolvedType,
        report: ValidationReport,
    ) -> None:
        if any(self._type_has_specialization(resolved, c) for c in candidates):
            report.add(
                Severity.OK,
                (
                    f"<{tag}> OK - at least one of related specializations present "
                    f"({', '.join(candidates)})."
                ),
                location=rel,
            )
            return

        joined = ", ".join(candidates)
        if resolved.source == "vanilla":
            report.add(
                Severity.WARNING,
                (
                    f"XML has <{tag}> (needs one of [{joined}]). "
                    f"Cannot fully verify against vanilla type \"{resolved.name}\"."
                ),
                location=rel,
            )
            return

        # Custom type (with or without vanilla parent): modder owns the registration.
        report.add(
            Severity.ERROR,
            (
                f"XML has <{tag}> which requires one of [{joined}], "
                f"but vehicle type \"{resolved.name}\" does not register any of them."
            ),
            location=rel,
        )

    def _assert_spec_present(
        self,
        rel: str,
        tag: str,
        required_spec: str,
        resolved: ResolvedType,
        report: ValidationReport,
    ) -> None:
        if self._type_has_specialization(resolved, required_spec):
            report.add(
                Severity.OK,
                f"<{tag}> OK - specialization '{required_spec}' is on type \"{resolved.name}\".",
                location=rel,
            )
            return

        if resolved.source == "vanilla":
            report.add(
                Severity.WARNING,
                (
                    f"XML has <{tag}> requiring '{required_spec}'. "
                    f"Cannot fully verify against vanilla type \"{resolved.name}\". "
                    "If you need this block, use a custom vehicleType that registers "
                    f"'{required_spec}'."
                ),
                location=rel,
            )
            return

        # custom or custom+vanilla_parent — missing explicit registration is an error
        parent_note = ""
        if resolved.vanilla_ancestor:
            parent_note = (
                f" Parent '{resolved.vanilla_ancestor}' is vanilla and was not assumed "
                f"to provide '{required_spec}'."
            )

        report.add(
            Severity.ERROR,
            (
                f"XML has <{tag}> which requires specialization '{required_spec}', "
                f"but custom vehicle type \"{resolved.name}\" does not register it. "
                f"Add <specialization name=\"{required_spec}\" /> to the type "
                f"(or a parent type in modDesc).{parent_note}"
            ),
            location=rel,
        )
