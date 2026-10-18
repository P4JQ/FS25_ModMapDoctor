"""Fill-type and foliage fruit checks for FS25 map and crop mods.

The rules are the ones the vanilla loaders already apply. Sources:

* ``FillTypeManager:loadFillTypes`` / ``getFillTypeByName`` / ``addFillTypeCategory``
  / ``addFillTypeConverter`` (``fillTypes/FillTypeManager.lua``)
* ``FillTypeDesc:loadFromXMLFile`` (``docs/script/FillTypes/FillTypeDesc.md``)
* ``FruitTypeManager:loadFruitTypes`` / ``loadMapData`` / ``getFruitTypeByName``
  (``fruits/FruitTypeManager.lua``)
* ``FruitTypeDesc:loadFromFoliageXMLFile`` (``docs/script/Fruits/FruitTypeDesc.md``)

Limits of this documentation set, left unenforced on purpose:

* ``FillTypeManager.SEND_NUM_BITS`` and ``FruitTypeManager.SEND_NUM_BITS`` are
  read but never assigned, so the "too many types" error is not checked.
* ``ClassUtil.getIsValidIndexName`` is called but its body is not in the
  corpus. A name is reported only when it is empty or is not one Lua
  identifier (letters, digits, underscore). That is the condition every
  call site uses before it ignores the entry.
* ``FieldGroundType`` / ``FieldChopperType`` name tables are not in the
  corpus, so ``#groundType`` and ``#chopperType`` tokens are not checked
  against a list. A second state that sets ``#groundType`` is still reported,
  because the loader overwrites the first when the name does resolve.
* Base-game names are the fallback catalog in ``app/knowledge/vanilla_materials.py``.
  A name missing from the mod is accepted when that catalog has it. The catalog
  is the core crop and ground list plus every ``FillType.NAME`` / ``FruitType.NAME``
  in the documentation. It is not a full copy of ``maps_fillTypes.xml``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.models import Severity, ValidationReport
from app.core.path_utils import (
    find_path_ignoring_case,
    is_engine_dollar_path,
    normalize_mod_relative,
    path_exists_case_sensitive,
)
from app.knowledge.vanilla_materials import is_vanilla_fill_type, is_vanilla_fruit_type

# A Lua index name: the only shape that can survive getIsValidIndexName and
# then be stored with string.upper(). The function body itself is not shipped.
_INDEX_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Boolean foliage-state flags that the loader keeps only once. A second
# "true" overwrites the first and logs an xml warning.
_EXCLUSIVE_STATE_FLAGS: tuple[tuple[str, str], ...] = (
    ("isWithered", "WitheredState"),
    ("regrowthStart", "RegrowthStart"),
    ("isDestructedByWheel", "Wheel destructed state"),
    ("isDestructedByDisaster", "Disaster destructed state"),
    ("isPrepared", "Prepared state"),
    ("isWeed", "Harvested weed state"),
    ("isMulched", "Mulched state"),
    ("isRolledCut", "Rolled cut state"),
)

_SKIP_DIRS = {".git", "__pycache__"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _rel(mod_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(mod_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _index_name_problem(name: str | None) -> str | None:
    """None when the name can be an index. 'empty' or 'identifier' otherwise."""
    if name is None or not name.strip():
        return "empty"
    if _INDEX_NAME.fullmatch(name.strip()) is None:
        return "identifier"
    return None


def _is_true(value: str | None) -> bool:
    """Giants ``getBool`` truth values used by the foliage loader."""
    return (value or "").strip().lower() in {"true", "1"}


def _tokens(text: str | None) -> list[str]:
    """Space-separated names, matching ``string.split(..., " ")`` after trim."""
    if text is None:
        return []
    return [part for part in text.split() if part]


def _parse(path: Path) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None


class FillFruitAuditor:
    """Check fillTypes, fruitTypes and foliage XML against the vanilla loaders."""

    def __init__(self, mod_root: Path) -> None:
        self.mod_root = mod_root.resolve()

    def audit(self) -> ValidationReport:
        """Run the check. Warnings follow the loader; silent converter drops are warnings too."""
        report = ValidationReport(target=self.mod_root / "(fill types & foliage)")
        if not self.mod_root.is_dir():
            report.add(Severity.ERROR, f"Mod folder does not exist: {self.mod_root}")
            print(f"[FillFruitAuditor] {report.summary_line()}")
            return report

        fill_files, fruit_files, foliage_files = self._discover(report)
        if not fill_files and not fruit_files and not foliage_files:
            report.add(
                Severity.INFO,
                "No fillTypes, fruitTypes or foliage XML found in this mod.",
            )
            print(f"[FillFruitAuditor] {report.summary_line()}")
            return report

        registered = self._load_fill_types(fill_files, report)
        fruits = self._load_fruits(fruit_files, foliage_files, registered, report)
        self._check_fruit_links(fruit_files, fruits, registered, report)

        if report.passed:
            report.add(
                Severity.OK,
                f"Fill type and foliage scan finished without errors "
                f"({len(registered)} fill type(s), {len(fruits)} fruit type(s)).",
            )
        print(f"[FillFruitAuditor] {report.summary_line()}")
        return report

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover(
        self, report: ValidationReport
    ) -> tuple[list[Path], list[Path], list[Path]]:
        """Fill-type files, fruit-type files, and foliage files.

        ``XMLUtil.loadDataFromMapXML`` is called with the keys ``"fillTypes"``
        and ``"fruitTypes"``. Its body is not in this corpus. Every other
        loader here reads ``key .. "#filename"``, so a ``map.xml`` element of
        that name with a ``filename`` attribute is treated as the reference.
        A file is also picked up when it is named ``fillTypes.xml`` /
        ``fruitTypes.xml`` or its root is ``foliageType``.
        """
        fill_files: list[Path] = []
        fruit_files: list[Path] = []
        foliage_files: list[Path] = []
        seen: set[Path] = set()

        for path in sorted(self.mod_root.rglob("*.xml")):
            if any(part in _SKIP_DIRS for part in path.relative_to(self.mod_root).parts):
                continue
            root = _parse(path)
            if root is None:
                # Only complain about files we actually meant to read. A broken
                # vehicle XML belongs to the vehicle validator.
                if path.name.lower() in {"filltypes.xml", "fruittypes.xml", "map.xml"}:
                    report.add(
                        Severity.ERROR,
                        f"Cannot parse XML: {path.name}",
                        location=_rel(self.mod_root, path),
                    )
                continue

            root_name = _local(root.tag)
            if root_name == "foliageType":
                self._add_unique(foliage_files, seen, path)
                continue

            if path.name.lower() == "filltypes.xml" or self._has_definition(root, "fillTypes", "fillType"):
                self._add_unique(fill_files, seen, path)
            if path.name.lower() == "fruittypes.xml" or self._has_definition(root, "fruitTypes", "fruitType"):
                self._add_unique(fruit_files, seen, path)

            if path.name.lower() == "map.xml":
                self._follow_map_references(path, root, fill_files, fruit_files, seen, report)

        return fill_files, fruit_files, foliage_files

    @staticmethod
    def _has_definition(root: ET.Element, block: str, child: str) -> bool:
        for element in root.iter():
            if _local(element.tag) != block or element.get("filename"):
                continue
            if any(_local(kid.tag) == child for kid in list(element)):
                return True
        return False

    def _follow_map_references(
        self,
        map_path: Path,
        root: ET.Element,
        fill_files: list[Path],
        fruit_files: list[Path],
        seen: set[Path],
        report: ValidationReport,
    ) -> None:
        for element in root.iter():
            name = _local(element.tag)
            if name not in {"fillTypes", "fruitTypes"}:
                continue
            filename = element.get("filename")
            if not filename:
                continue
            target = self._resolve_reference(map_path, filename, report, report_missing=(name == "fillTypes"))
            if target is None and name == "fruitTypes":
                report.add(
                    Severity.WARNING,
                    f"FRUIT-002: fruitTypes filename '{filename}' was not found.",
                    location=_rel(self.mod_root, map_path),
                )
                continue
            if target is None:
                continue
            bucket = fill_files if name == "fillTypes" else fruit_files
            self._add_unique(bucket, seen, target)

    def _resolve_reference(
        self,
        map_path: Path,
        filename: str,
        report: ValidationReport,
        *,
        report_missing: bool = True,
    ) -> Path | None:
        """Resolve ``#filename`` next to the map XML, then from the mod root."""
        cleaned = normalize_mod_relative(filename)
        location = _rel(self.mod_root, map_path)
        if is_engine_dollar_path(cleaned):
            report.add(
                Severity.INFO,
                f"Engine path skipped: {cleaned}",
                location=location,
            )
            return None

        for base in (map_path.parent, self.mod_root):
            relative = cleaned
            if base != self.mod_root:
                try:
                    relative = (base / cleaned).resolve().relative_to(self.mod_root).as_posix()
                except ValueError:
                    continue
            ok, detail = path_exists_case_sensitive(self.mod_root, relative)
            if ok:
                return (self.mod_root / relative).resolve()
            if detail.startswith("Case mismatch"):
                report.add(
                    Severity.WARNING,
                    f"FILL-000: {detail}. The file is still checked.",
                    location=location,
                )
                found = find_path_ignoring_case(self.mod_root, relative)
                if found is not None:
                    return found
            # Try the other base before reporting missing.
        if report_missing:
            report.add(
                Severity.ERROR,
                f"FILL-000: {filename} referenced from {map_path.name} was not found "
                f"next to the map XML or in the mod root.",
                location=location,
            )
        return None

    @staticmethod
    def _add_unique(bucket: list[Path], seen: set[Path], path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        bucket.append(resolved)

    # ------------------------------------------------------------------
    # Fill types
    # ------------------------------------------------------------------

    def _load_fill_types(self, files: list[Path], report: ValidationReport) -> dict[str, str]:
        """Return UPPER name -> spelling that was registered.

        Map and mod files are loaded with ``isBaseType == false``, so a repeated
        name reloads the existing entry instead of the base-game "already exists"
        warning. That reload is still reported, because the second block wins.
        """
        registered: dict[str, str] = {}
        for path in files:
            root = _parse(path)
            if root is None:
                report.add(
                    Severity.ERROR,
                    f"Cannot parse XML: {path.name}",
                    location=_rel(self.mod_root, path),
                )
                continue
            self._read_fill_file(path, root, registered, report)
        return registered

    def _read_fill_file(
        self,
        path: Path,
        root: ET.Element,
        registered: dict[str, str],
        report: ValidationReport,
    ) -> None:
        location = _rel(self.mod_root, path)
        for block in self._blocks(root, "fillTypes"):
            for child in list(block):
                if _local(child.tag) != "fillType":
                    continue
                raw = child.get("name")
                problem = _index_name_problem(raw)
                if problem == "empty":
                    report.add(
                        Severity.WARNING,
                        "FILL-002: fillType has no #name. FillTypeDesc:loadFromXMLFile "
                        "ignores a fill type whose name fails ClassUtil.getIsValidIndexName.",
                        location=location,
                    )
                    continue
                assert raw is not None
                if problem == "identifier":
                    report.add(
                        Severity.WARNING,
                        f"FILL-002: '{raw}' is not a valid name for a fillType. "
                        "The loader ignores it (ClassUtil.getIsValidIndexName; the function "
                        "body is not in this documentation set, so a name is rejected when "
                        "it is not one identifier of letters, digits and underscore).",
                        location=location,
                    )
                    continue
                upper = raw.upper()
                if upper != raw:
                    report.add(
                        Severity.INFO,
                        f"FILL-007: fill type '{raw}' is stored as '{upper}' (string.upper). "
                        "Lookups use the upper-case form.",
                        location=location,
                    )
                if upper in registered:
                    report.add(
                        Severity.WARNING,
                        f"FILL-001: Fill type '{upper}' is defined again. For a map or mod "
                        "file isBaseType is false, so the loader reloads this entry instead "
                        "of adding a second type. The later definition wins.",
                        location=location,
                    )
                registered[upper] = raw

        for block in self._blocks(root, "fillTypeCategories"):
            for child in list(block):
                if _local(child.tag) != "fillTypeCategory":
                    continue
                self._check_category_name(child.get("name"), "fillTypeCategory", location, report)
                for token in _tokens(child.text):
                    self._note_casing(token, "fill type category entry", location, report, "FILL-007")
                    if not self._fill_known(token, registered):
                        report.add(
                            Severity.WARNING,
                            f"FILL-003: Unknown FillType '{token}' in fillTypeCategory "
                            f"'{child.get('name') or ''}'.",
                            location=location,
                        )

        for block in self._blocks(root, "fillTypeConverters"):
            for converter in list(block):
                if _local(converter.tag) != "fillTypeConverter":
                    continue
                self._check_category_name(
                    converter.get("name"), "fillTypeConverter", location, report
                )
                for rule in list(converter):
                    if _local(rule.tag) != "converter":
                        continue
                    self._check_fill_converter(rule, registered, location, report)

        for block in self._blocks(root, "fillTypeSounds"):
            for sound in list(block):
                if _local(sound.tag) != "fillTypeSound":
                    continue
                for token in _tokens(sound.get("fillTypes")):
                    if not self._fill_known(token, registered):
                        report.add(
                            Severity.WARNING,
                            f"FILL-006: Unable to load fill type '{token}' for fillTypeSound.",
                            location=location,
                        )

    def _check_fill_converter(
        self,
        rule: ET.Element,
        registered: dict[str, str],
        location: str,
        report: ValidationReport,
    ) -> None:
        """Report rules ``loadFillTypes`` drops when from, to or factor is missing.

        The loader adds the conversion only when both names resolve and
        ``#factor`` is not nil. It does not log the skip.
        """
        source = rule.get("from")
        target = rule.get("to")
        factor = rule.get("factor")
        source_ok = self._fill_known(source, registered)
        target_ok = self._fill_known(target, registered)
        factor_ok = _is_number(factor)

        if source is not None:
            self._note_casing(source, "fillTypeConverter #from", location, report, "FILL-007")
        if target is not None:
            self._note_casing(target, "fillTypeConverter #to", location, report, "FILL-007")

        if not source_ok or not target_ok or not factor_ok:
            missing: list[str] = []
            if not source_ok:
                missing.append(f"from '{source}' does not resolve")
            if not target_ok:
                missing.append(f"to '{target}' does not resolve")
            if not factor_ok:
                missing.append("#factor is missing or not a number")
            report.add(
                Severity.WARNING,
                "FILL-004: fillTypeConverter rule is silently dropped by "
                "FillTypeManager:loadFillTypes (" + "; ".join(missing) + "). "
                "The loader adds a conversion only when both names resolve and #factor is set.",
                location=location,
            )

    # ------------------------------------------------------------------
    # Fruits and foliage
    # ------------------------------------------------------------------

    def _load_fruits(
        self,
        fruit_files: list[Path],
        foliage_files: list[Path],
        registered: dict[str, str],
        report: ValidationReport,
    ) -> dict[str, str]:
        """Load foliage referenced by fruitTypes, then any other foliage XML."""
        fruits: dict[str, str] = {}
        referenced: set[Path] = set()

        for path in fruit_files:
            root = _parse(path)
            if root is None:
                report.add(
                    Severity.ERROR,
                    f"Cannot parse XML: {path.name}",
                    location=_rel(self.mod_root, path),
                )
                continue
            location = _rel(self.mod_root, path)
            for block in self._blocks(root, "fruitTypes"):
                for child in list(block):
                    if _local(child.tag) != "fruitType":
                        continue
                    filename = child.get("filename")
                    if not filename:
                        report.add(
                            Severity.WARNING,
                            "FRUIT-001: Missing fruit type filename. "
                            "FruitTypeManager:loadFruitTypes skips this entry.",
                            location=location,
                        )
                        continue
                    foliage = self._resolve_reference(path, filename, report, report_missing=False)
                    if foliage is None:
                        report.add(
                            Severity.WARNING,
                            f"FRUIT-002: fruit type filename '{filename}' was not found. "
                            "The loader cannot build this fruit.",
                            location=location,
                        )
                        continue
                    referenced.add(foliage.resolve())
                    self._read_foliage(foliage, registered, fruits, report)

        for path in foliage_files:
            if path.resolve() in referenced:
                continue
            report.add(
                Severity.INFO,
                "FRUIT-000: foliage XML is not referenced by a fruitTypes fruitType#filename. "
                "The loader only reads foliage through that attribute. The file is still checked.",
                location=_rel(self.mod_root, path),
            )
            self._read_foliage(path, registered, fruits, report)
        return fruits

    def _read_foliage(
        self,
        path: Path,
        registered: dict[str, str],
        fruits: dict[str, str],
        report: ValidationReport,
    ) -> None:
        """Apply ``FruitTypeDesc:loadFromFoliageXMLFile`` until it would return false."""
        root = _parse(path)
        location = _rel(self.mod_root, path)
        if root is None or _local(root.tag) != "foliageType":
            report.add(
                Severity.WARNING,
                "FRUIT-002: foliage file has no <foliageType> root, so loadFromFoliageXMLFile "
                "cannot read foliageType.fruitType.",
                location=location,
            )
            return

        fruit = next((el for el in list(root) if _local(el.tag) == "fruitType"), None)
        if fruit is None:
            report.add(
                Severity.WARNING,
                "FRUIT-003: Missing fruitType name. The loader ignores this foliage file.",
                location=location,
            )
            return

        raw = fruit.get("name")
        problem = _index_name_problem(raw)
        if problem == "empty":
            report.add(
                Severity.WARNING,
                "FRUIT-003: Missing fruitType name. FruitTypeDesc.loadFromFoliageXMLFile "
                "ignores this fruit.",
                location=location,
            )
            return
        assert raw is not None
        if problem == "identifier":
            report.add(
                Severity.WARNING,
                f"FRUIT-004: '{raw}' is not a valid name for a fruitType. The loader ignores it.",
                location=location,
            )
            return

        upper = raw.upper()
        if upper != raw:
            report.add(
                Severity.INFO,
                f"FRUIT-012: fruit type '{raw}' is stored as '{upper}' (string.upper).",
                location=location,
            )
        if not self._fill_known(raw, registered):
            report.add(
                Severity.WARNING,
                f"FRUIT-005: Missing fillType '{raw}' for fruitType definition. "
                "The loader ignores this fruit. Names are compared after string.upper(), "
                "then against this mod's fill types and the vanilla fill-type catalog.",
                location=location,
            )
            return

        if upper in fruits:
            report.add(
                Severity.WARNING,
                f"FRUIT-014: fruit type '{upper}' is already loaded. The later foliage file "
                "replaces the earlier one in nameToFruitType.",
                location=location,
            )
        fruits[upper] = raw
        self._check_states(root, location, report)
        self._check_windrow(fruit, registered, location, report)
        self._check_transitions(root, fruit, location, report)

    def _check_states(self, root: ET.Element, location: str, report: ValidationReport) -> None:
        layer = next((el for el in list(root) if _local(el.tag) == "foliageLayer"), None)
        if layer is None:
            return

        seen_flags: dict[str, str] = {}
        ground_owner: str | None = None
        wheel_destructible = False
        wheel_target = False
        disaster_destructible = False
        disaster_target = False

        for state in list(layer):
            if _local(state.tag) != "foliageState":
                continue
            state_name = state.get("name")
            if not state_name:
                report.add(
                    Severity.ERROR,
                    "FRUIT-013: foliageState has no #name. The loader calls string.upper on it.",
                    location=location,
                )
                continue
            for attr, label in _EXCLUSIVE_STATE_FLAGS:
                if not _is_true(state.get(attr)):
                    continue
                if attr in seen_flags:
                    report.add(
                        Severity.WARNING,
                        f"FRUIT-008: {label} already defined for foliage state '{seen_flags[attr]}'. "
                        f"Overwriting it with '{state_name}'.",
                        location=location,
                    )
                seen_flags[attr] = state_name
            if state.get("groundType"):
                if ground_owner is not None:
                    report.add(
                        Severity.WARNING,
                        f"FRUIT-008: GroundType change already defined for foliage state "
                        f"'{ground_owner}'. Overwriting it with '{state_name}'. "
                        "FieldGroundType.getByName's name list is not in this documentation set, "
                        "so the token itself is not checked.",
                        location=location,
                    )
                ground_owner = state_name
            if _is_true(state.get("isDestructibleByWheel")):
                wheel_destructible = True
            if _is_true(state.get("isDestructedByWheel")):
                wheel_target = True
            if _is_true(state.get("isDestructibleByDisaster")):
                disaster_destructible = True
            if _is_true(state.get("isDestructedByDisaster")):
                disaster_target = True

        if wheel_destructible and not wheel_target:
            report.add(
                Severity.WARNING,
                "FRUIT-009: Fruit has states where 'isDestructibleByWheel' is true but does not "
                "specify a state where 'isDestructedByWheel' is true.",
                location=location,
            )
        if disaster_destructible and not disaster_target:
            report.add(
                Severity.WARNING,
                "FRUIT-009: Fruit has states where 'isDestructibleByDisaster' is true but does not "
                "specify a state where 'isDestructedByDisaster' is true.",
                location=location,
            )

    def _check_windrow(
        self,
        fruit: ET.Element,
        registered: dict[str, str],
        location: str,
        report: ValidationReport,
    ) -> None:
        windrow = next((el for el in list(fruit) if _local(el.tag) == "windrow"), None)
        if windrow is None:
            return
        fill_name = windrow.get("fillType")
        if fill_name is not None and not self._fill_known(fill_name, registered):
            report.add(
                Severity.WARNING,
                f"FRUIT-010: FruitType windrow fillType '{fill_name}' not defined. Ignoring windrow.",
                location=location,
            )
        cut_name = windrow.get("cutFillType")
        if cut_name is not None and not self._fill_known(cut_name, registered):
            report.add(
                Severity.WARNING,
                f"FRUIT-010: FruitType windrow cut fillType '{cut_name}' not defined. Ignoring windrow.",
                location=location,
            )

    def _check_transitions(
        self, root: ET.Element, fruit: ET.Element, location: str, report: ValidationReport
    ) -> None:
        """Harvest transitions resolve state names with ``string.upper``.

        The loader stops walking transitions at the first missing state, and it
        does not look up ``#target`` when ``#src`` is already missing.
        """
        harvest = next((el for el in list(fruit) if _local(el.tag) == "harvest"), None)
        if harvest is None:
            return
        lookup = self._state_names_from_root(root)
        for transition in list(harvest):
            if _local(transition.tag) != "transition":
                continue
            src = transition.get("src")
            if src is None or src.upper() not in lookup:
                report.add(
                    Severity.WARNING,
                    f"FRUIT-011: foliage state '{src}' is not defined for harvest transition.",
                    location=location,
                )
                break
            target = transition.get("target")
            if target is None or target.upper() not in lookup:
                report.add(
                    Severity.WARNING,
                    f"FRUIT-011: foliage state '{target}' is not defined for harvest transition.",
                    location=location,
                )
                break

    def _check_fruit_links(
        self,
        fruit_files: list[Path],
        fruits: dict[str, str],
        registered: dict[str, str],
        report: ValidationReport,
    ) -> None:
        for path in fruit_files:
            root = _parse(path)
            if root is None:
                continue
            location = _rel(self.mod_root, path)
            for block in self._blocks(root, "fruitTypeCategories"):
                for child in list(block):
                    if _local(child.tag) != "fruitTypeCategory":
                        continue
                    self._check_category_name(child.get("name"), "fruitTypeCategory", location, report)
                    for token in _tokens(child.text):
                        self._note_casing(token, "fruit type category entry", location, report, "FRUIT-012")
                        if not self._fruit_known(token, fruits):
                            report.add(
                                Severity.WARNING,
                                f"FRUIT-006: FruitType '{token}' referenced in fruitTypeCategory "
                                f"'{child.get('name') or ''}' is not defined.",
                                location=location,
                            )
            for block in self._blocks(root, "fruitTypeConverters"):
                for converter in list(block):
                    if _local(converter.tag) != "fruitTypeConverter":
                        continue
                    self._check_category_name(
                        converter.get("name"), "fruitTypeConverter", location, report
                    )
                    for rule in list(converter):
                        if _local(rule.tag) != "converter":
                            continue
                        self._check_fruit_converter(rule, fruits, registered, location, report)

    def _check_fruit_converter(
        self,
        rule: ET.Element,
        fruits: dict[str, str],
        registered: dict[str, str],
        location: str,
        report: ValidationReport,
    ) -> None:
        """``loadMapData`` keeps a rule only when both names resolve.

        ``#factor`` defaults to 1 (``getFloat(..., 1)``), so a missing factor is
        not a silent drop. A missing fruit or fill type is: the loader skips
        the rule with no warning.
        """
        source = rule.get("from")
        target = rule.get("to")
        factor = rule.get("factor")
        source_ok = self._fruit_known(source, fruits)
        target_ok = self._fill_known(target, registered)
        if source is not None:
            self._note_casing(source, "fruitTypeConverter #from", location, report, "FRUIT-012")
        if target is not None:
            self._note_casing(target, "fruitTypeConverter #to", location, report, "FRUIT-012")
        if not source_ok or not target_ok:
            missing: list[str] = []
            if not source_ok:
                missing.append(f"from '{source}' is not a loaded fruit type")
            if not target_ok:
                missing.append(f"to '{target}' is not a loaded fill type")
            report.add(
                Severity.WARNING,
                "FRUIT-007: fruitTypeConverter rule is silently dropped by "
                "FruitTypeManager:loadMapData (" + "; ".join(missing) + ").",
                location=location,
            )
        elif factor is None:
            report.add(
                Severity.INFO,
                "FRUIT-015: fruitTypeConverter #factor is omitted. The loader uses 1.",
                location=location,
            )
        elif not _is_number(factor):
            report.add(
                Severity.WARNING,
                f"FRUIT-007: fruitTypeConverter #factor '{factor}' is not a number. "
                "getFloat would not use this value.",
                location=location,
            )

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _blocks(root: ET.Element, name: str) -> list[ET.Element]:
        """Definition blocks. A block that only points at ``#filename`` is a reference."""
        found: list[ET.Element] = []
        for element in root.iter():
            if _local(element.tag) != name:
                continue
            if element.get("filename") and not list(element):
                continue
            found.append(element)
        return found

    def _check_category_name(
        self, name: str | None, kind: str, location: str, report: ValidationReport
    ) -> None:
        problem = _index_name_problem(name)
        if problem is None:
            if name is not None and name != name.upper():
                self._note_casing(name, kind, location, report, "FILL-007")
            return
        shown = name if name else ""
        report.add(
            Severity.WARNING,
            f"FILL-002: '{shown}' is not a valid name for a {kind}. The loader ignores it.",
            location=location,
        )

    @staticmethod
    def _fill_known(name: str | None, registered: dict[str, str]) -> bool:
        """True when the mod defines the name, or the vanilla catalog does."""
        if _index_name_problem(name) is not None or name is None:
            return False
        return name.upper() in registered or is_vanilla_fill_type(name)

    @staticmethod
    def _fruit_known(name: str | None, fruits: dict[str, str]) -> bool:
        """True when this mod loaded the fruit, or the vanilla catalog has it."""
        if _index_name_problem(name) is not None or name is None:
            return False
        return name.upper() in fruits or is_vanilla_fruit_type(name)

    @staticmethod
    def _note_casing(name: str, what: str, location: str, report: ValidationReport, rule: str) -> None:
        if name != name.upper() and _index_name_problem(name) is None:
            report.add(
                Severity.INFO,
                f"{rule}: {what} '{name}' is compared as '{name.upper()}' (string.upper).",
                location=location,
            )

    @staticmethod
    def _state_names_from_root(root: ET.Element) -> set[str]:
        names: set[str] = set()
        for element in root.iter():
            if _local(element.tag) != "foliageLayer":
                continue
            for state in list(element):
                if _local(state.tag) == "foliageState" and state.get("name"):
                    names.add(state.get("name", "").upper())
            break
        return names


def _is_number(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True
