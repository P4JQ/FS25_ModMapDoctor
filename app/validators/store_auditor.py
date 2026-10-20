"""Store-item checks copied from ``StoreManager:loadItem``.

Evidence: ``Documentation/docs/script/Shop/StoreManager.md``, the ``loadItem``
body. Every ``Logging.xmlWarning`` / ``Logging.xmlError`` in that function:

* ``xmlError`` "No storeData found..." — STORE-003. Logged as an error, but
  the function returns nil for that item only, so the mod still loads.
  Reported as a warning, same as the other dropped-item checks.
* ``xmlWarning`` "Name missing..." — STORE-002.
* ``xmlWarning`` "Image icon is missing..." — STORE-001.
* ``xmlWarning`` "Invalid category..." — STORE-006. Names are the ``name``
  attributes in ``reference/storeCategories.xml``, compared with
  ``string.upper``, plus ``storeCategory`` names from this mod's ``modDesc``.
* ``xmlWarning`` "No categories defined..." — STORE-007, only when the file
  is listed in ``storeItems`` and ``showInStore`` is not false. A normal item
  defaults to shown. Bundle items default to hidden via ``isBundleItem``,
  which is not an XML attribute, so an unlisted file is not reported.
* ``xmlWarning`` "Price has to be greater than 0..." — STORE-004. The
  comparison in code is ``price < 0``. Zero and a missing element use the
  default ``0`` and do not log.
* ``xmlWarning`` "Lifetime has to be greater than 0..." — STORE-005. The
  comparison is ``lifetime <= 0``. A missing element uses ``600`` and does not log.
* ``xmlError`` "Unknown brush type..." and the three brush-tab / brush-category
  warnings — deferred. They read live construction-brush tables.
* ``xmlDevWarning`` for a filename that starts with a digit or a brand, and the
  shop-translation warning inside ``--#debug``, are not player-facing load
  failures and are not reported.

The image path is not resolved. ``Utils.getFilename`` runs after the empty
check, and its base directory is not in the local sources.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.etree.ElementTree import Element

from app.core.models import Severity, ValidationReport
from app.core.path_utils import is_engine_dollar_path, normalize_mod_relative, path_exists_case_sensitive
from app.knowledge.store_categories import STORE_CATEGORY_NAMES

_JUNK_DIRS = frozenset({".git", ".github"})
# A plain decimal only. XMLValueType.FLOAT's parser is not in the local sources,
# so "1e-2", "10,5" and other unproven spellings are left alone.
_PLAIN_DECIMAL = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$")


class StoreAuditor:
    """Read storeData blocks and report items the shop loader discards."""

    def __init__(self, mod_root: Path) -> None:
        self.mod_root = mod_root.resolve()

    def audit(self) -> ValidationReport:
        report = ValidationReport(target=self.mod_root)
        if not self.mod_root.is_dir():
            report.add(Severity.ERROR, f"STORE-000: Mod folder does not exist: {self.mod_root}")
            print(f"[StoreAuditor] {report.summary_line()}")
            return report

        found = False
        for path in _iter_xml(self.mod_root):
            location = _relative(self.mod_root, path)
            try:
                root = ET.parse(path).getroot()
            except (ET.ParseError, OSError):
                continue
            for index, store in enumerate(_elements_named(root, "storeData"), start=1):
                found = True
                where = f"{location} storeData[{index}]"
                _check_store_data(store, report, where)

        _check_registered_store_items(self.mod_root, report)

        if not found:
            report.add(
                Severity.INFO,
                "STORE-000: No storeData block in this folder.",
                location=self.mod_root.name,
            )
        print(f"[StoreAuditor] {report.summary_line()}")
        return report


def _check_store_data(store: Element, report: ValidationReport, location: str) -> None:
    if _is_blank(_child_text(store, "name")):
        report.add(
            Severity.WARNING,
            "STORE-002: storeData name is empty. "
            "StoreManager logs 'Name missing for storeitem. Ignoring store item!' "
            "and drops the item.",
            location=location,
        )
    if _is_blank(_child_text(store, "image")) and _show_in_store(store):
        report.add(
            Severity.WARNING,
            "STORE-001: storeData image is empty while showInStore is enabled. "
            "StoreManager logs 'Image icon is missing for storeitem. Ignoring store item!' "
            "and drops the item.",
            location=location,
        )
    price = _plain_float(_child_text(store, "price"))
    if price is not None and price < 0:
        report.add(
            Severity.WARNING,
            "STORE-004: storeData price is below 0. "
            "StoreManager logs 'Price has to be greater than 0. Using default 10.000 instead!' "
            "and replaces the price. Zero and a missing price do not log.",
            location=location,
        )
    lifetime = _plain_float(_child_text(store, "lifetime"))
    if lifetime is not None and lifetime <= 0:
        report.add(
            Severity.WARNING,
            "STORE-005: storeData lifetime is 0 or below. "
            "StoreManager logs 'Lifetime has to be greater than 0. Using default 600 instead!' "
            "and replaces the lifetime. A missing lifetime does not log.",
            location=location,
        )


def _check_registered_store_items(mod_root: Path, report: ValidationReport) -> None:
    """Warn when a modDesc storeItem file has no root storeData child.

    ``loadItem`` builds the key as ``getXMLRootName .. ".storeData"`` and logs
    when that property is absent. A file that is not listed in ``storeItems``
    is never passed to ``loadItem``. A missing file returns before this log,
    because ``loadXMLFile`` fails first.
    """
    mod_desc = mod_root / "modDesc.xml"
    if not mod_desc.is_file():
        return
    try:
        root = ET.parse(mod_desc).getroot()
    except (ET.ParseError, OSError):
        return

    seen: set[str] = set()
    for item in root.iter():
        if _local(item.tag) != "storeItem":
            continue
        relative = normalize_mod_relative(item.get("xmlFilename") or "")
        if not relative or is_engine_dollar_path(relative):
            continue
        key = relative.lower()
        if key in seen:
            continue
        seen.add(key)
        exists, _reason = path_exists_case_sensitive(mod_root, relative)
        if not exists:
            continue
        path = mod_root / relative
        try:
            item_root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        if _direct_child(item_root, "storeData") is None:
            report.add(
                Severity.WARNING,
                "STORE-003: store item XML has no storeData element. "
                "StoreManager logs xmlError 'No storeData found. StoreItem will be ignored!' "
                "and drops the item. The mod still loads.",
                location=relative.replace("\\", "/"),
            )
            continue
        known = {name.upper() for name in STORE_CATEGORY_NAMES}
        known.update(_mod_category_names(root))
        where = relative.replace("\\", "/")
        for index, store in enumerate(_direct_children(item_root, "storeData"), start=1):
            _check_categories(store, report, f"{where} storeData[{index}]", known)


def _check_categories(
    store: Element, report: ValidationReport, location: str, known: set[str]
) -> None:
    """Match the category loop in ``loadItem``.

    The schema types ``.category`` as a space-separated string list. Each
    token is looked up with ``string.upper``. An unknown token is skipped.
    When nothing remains and the item is shown, the loader substitutes ``MISC``.
    """
    text = _child_text(store, "category")
    tokens = [] if text is None else text.split()
    accepted = 0
    for token in tokens:
        if token.upper() in known:
            accepted += 1
            continue
        report.add(
            Severity.WARNING,
            "STORE-006: storeData category "
            f"'{token}' is not a shop category. "
            "StoreManager logs 'Invalid category' and skips that name. "
            "Names in storeCategories.xml and this mod's storeCategory entries are accepted.",
            location=location,
        )
    if accepted == 0 and _show_in_store(store):
        report.add(
            Severity.WARNING,
            "STORE-007: storeData has no shop category while showInStore is enabled. "
            "StoreManager logs \"No categories defined in store data! Using 'misc' instead!\" "
            "and uses MISC.",
            location=location,
        )


def _mod_category_names(mod_desc_root: Element) -> set[str]:
    names: set[str] = set()
    for element in mod_desc_root.iter():
        if _local(element.tag) != "storeCategory":
            continue
        name = (element.get("name") or "").strip()
        if name:
            names.add(name.upper())
    return names


def _direct_children(parent: Element, tag: str) -> list[Element]:
    return [child for child in list(parent) if _local(child.tag) == tag]


def _show_in_store(store: Element) -> bool:
    """Match the image check's ``getValue(..., true)`` default.

    The BOOL parser body is not in the local sources. Missing or empty text
    uses that default (true). The literals ``true`` and ``false`` follow the
    schema type. Any other text is left alone so an unproven value cannot
    raise a warning.
    """
    text = _child_text(store, "showInStore")
    if text is None or text.strip() == "":
        return True
    token = text.strip().lower()
    if token == "false":
        return False
    if token == "true":
        return True
    return False


def _plain_float(text: str | None) -> float | None:
    """Parse a price or lifetime the load comparison can see.

    ``None`` means the element is absent, empty, or not a plain decimal.
    Those cases follow the loader default and do not warn.
    """
    if text is None:
        return None
    token = text.strip()
    if token == "" or _PLAIN_DECIMAL.fullmatch(token) is None:
        return None
    return float(token)


def _direct_child(parent: Element, tag: str) -> Element | None:
    for child in list(parent):
        if _local(child.tag) == tag:
            return child
    return None


def _is_blank(text: str | None) -> bool:
    return text is None or text == ""


def _child_text(parent: Element, tag: str) -> str | None:
    """Text of the first direct child, or None when that child is absent.

    An empty element returns ``""``. Whitespace is kept: the loader compares
    the image string to ``""`` before it treats the value as missing.
    """
    for child in list(parent):
        if _local(child.tag) == tag:
            return "" if child.text is None else child.text
    return None


def _elements_named(root: Element, tag: str) -> list[Element]:
    return [element for element in root.iter() if _local(element.tag) == tag]


def _iter_xml(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name.lower() not in _JUNK_DIRS]
        for name in filenames:
            if name.lower().endswith(".xml"):
                yield Path(dirpath) / name


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name
