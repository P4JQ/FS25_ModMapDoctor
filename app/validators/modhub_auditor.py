"""ModHub pre-flight: junk files, localization keys, and DDS header compliance.

Nothing in this module writes, converts, or flips a texture. DDS files are
opened read-only and only the header bytes are unpacked.

Texture expectations follow ``Documentation/All compression types.pdf`` for the
suffixes this suite checks. Localization file names follow
``fs25-claude-skill`` ``references/basics/localization.md``: a ``filenamePrefix``
loads ``<prefix>_<lang>.xml``, and each ``<text name="...">`` is one key.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.models import Severity, ValidationReport
from app.core.path_utils import normalize_mod_relative, path_exists_case_sensitive
from app.validators.dds_header import DdsHeader, DdsHeaderError, read_dds_header

# Language codes listed in references/basics/localization.md.
_LANG_CODES: tuple[str, ...] = (
    "en",
    "de",
    "fr",
    "es",
    "it",
    "pl",
    "ru",
    "pt",
    "cs",
    "nl",
    "hu",
    "ro",
    "tr",
    "jp",
    "kr",
    "cn",
    "ct",
)

_JUNK_DIRECTORIES = frozenset({".git", ".github"})
_JUNK_FILE_NAMES = frozenset({"thumbs.db", "desktop.ini"})
_JUNK_SUFFIXES = frozenset({".blend", ".blend1"})

_STORE_TEXT_TAGS = frozenset({"name", "description", "function"})
_L10N_KEY = re.compile(r"\$l10n_([A-Za-z0-9_]+)")
_HEADER_READ = 148


class ModHubAuditor:
    """Static ModHub compliance scan for one mod folder."""

    def __init__(self, mod_root: Path) -> None:
        self.mod_root = mod_root.resolve()

    def audit(self) -> ValidationReport:
        report = ValidationReport(target=self.mod_root)
        if not self.mod_root.is_dir():
            report.add(Severity.ERROR, f"HUB-000: Mod folder does not exist: {self.mod_root}")
            return report

        self._scan_junk(report)
        self._scan_textures(report)
        self._scan_l10n(report)
        print(f"[ModHubAuditor] {report.summary_line()}")
        return report

    def _scan_junk(self, report: ValidationReport) -> None:
        for dirpath, dirnames, filenames in os.walk(self.mod_root):
            folder = Path(dirpath)
            kept: list[str] = []
            for name in dirnames:
                if name.lower() in _JUNK_DIRECTORIES:
                    report.add(
                        Severity.ERROR,
                        f"HUB-001: Developer folder '{name}' must not be shipped in a ModHub zip.",
                        location=_relative(self.mod_root, folder / name),
                    )
                else:
                    kept.append(name)
            dirnames[:] = kept

            for name in filenames:
                suffix = Path(name).suffix.lower()
                if name.lower() in _JUNK_FILE_NAMES or suffix in _JUNK_SUFFIXES:
                    report.add(
                        Severity.ERROR,
                        f"HUB-001: Developer leftover '{name}' must not be shipped in a ModHub zip.",
                        location=_relative(self.mod_root, folder / name),
                    )

    def _scan_textures(self, report: ValidationReport) -> None:
        dds_files = sorted(
            (
                path
                for path in self.mod_root.rglob("*")
                if path.is_file()
                and path.suffix.lower() == ".dds"
                and not _under_junk(self.mod_root, path)
            ),
            key=lambda path: path.as_posix().lower(),
        )
        if not dds_files:
            report.add(
                Severity.INFO,
                "DDS-000: No .dds files in this mod. Texture rules were not applied.",
                location=self.mod_root.name,
            )
            return

        for path in dds_files:
            location = _relative(self.mod_root, path)
            try:
                with path.open("rb") as handle:
                    data = handle.read(_HEADER_READ)
            except OSError as exc:
                report.add(Severity.ERROR, f"DDS-001: Cannot read DDS header: {exc}", location=location)
                continue
            try:
                header = read_dds_header(data)
            except DdsHeaderError as exc:
                report.add(Severity.ERROR, f"DDS-001: {exc}", location=location)
                continue
            _report_texture(report, path, location, header)

    def _scan_l10n(self, report: ValidationReport) -> None:
        mod_desc = self.mod_root / "modDesc.xml"
        if not mod_desc.is_file():
            report.add(
                Severity.INFO,
                "L10N-000: modDesc.xml is missing, so title and store keys were not checked.",
                location="modDesc.xml",
            )
            return

        try:
            root = ET.parse(mod_desc).getroot()
        except (ET.ParseError, OSError) as exc:
            report.add(
                Severity.INFO,
                f"L10N-000: modDesc.xml could not be parsed ({exc}). Localization was not checked.",
                location="modDesc.xml",
            )
            return

        dictionary = _load_dictionary(self.mod_root, root, report)
        for key, location in _declared_keys(self.mod_root, root):
            if key not in dictionary:
                report.add(
                    Severity.WARNING,
                    f"L10N-001: '$l10n_{key}' is used but no localization file defines it.",
                    location=location,
                )
        _compare_language_files(self.mod_root, report)


def _report_texture(report: ValidationReport, path: Path, location: str, header: DdsHeader) -> None:
    role = _texture_role(path.stem)
    summary = (
        f"{header.format_name} ({header.fourcc or 'raw'}), "
        f"{header.width}x{header.height}, mipmapCount={header.mipmap_count}, "
        f"alpha={'yes' if header.has_alpha else 'no'}"
    )
    if not header.power_of_two:
        report.add(
            Severity.WARNING,
            "DDS-004: "
            f"{header.width}x{header.height} is not a power-of-two size. "
            "Non-power-of-two textures cost extra at runtime.",
            location=location,
        )

    if role is None:
        report.add(
            Severity.INFO,
            f"DDS-000: No suffix rule for this file. Header: {summary}.",
            location=location,
        )
        return

    expected_format, mipmaps_required = _expected(role, header.has_alpha)
    format_ok = header.format_name == expected_format
    mips_ok = header.mipmaps_present == mipmaps_required
    if not format_ok:
        report.add(
            Severity.WARNING,
            f"DDS-002: {role} expects {expected_format}. Header reports {summary}.",
            location=location,
        )
    if mipmaps_required and not header.mipmaps_present:
        report.add(
            Severity.WARNING,
            f"DDS-003: {role} expects mipmaps (mipmapCount > 1). "
            f"Header has mipmapCount={header.mipmap_count}.",
            location=location,
        )
    if not mipmaps_required and header.mipmaps_present:
        report.add(
            Severity.WARNING,
            f"DDS-003: {role} expects no mipmaps. Header has mipmapCount={header.mipmap_count}.",
            location=location,
        )
    if format_ok and mips_ok:
        mip_label = "mipmaps" if mipmaps_required else "no mipmaps"
        report.add(
            Severity.INFO,
            f"DDS-000: {role} matches the texture matrix "
            f"({expected_format}, {mip_label}, {header.width}x{header.height}).",
            location=location,
        )


def _texture_role(stem: str) -> str | None:
    """Map a file stem onto one row of the texture matrix."""
    name = stem.lower()
    if "store_icon" in name:
        return "store_icon"
    if "mod_icon" in name:
        return "mod_icon"
    if name == "diffuse" or name.endswith("_diffuse"):
        return "diffuse"
    if name == "height" or name.endswith("_height"):
        return "height"
    if name == "specular" or name.endswith("_specular"):
        return "specular"
    if name == "normal" or name.endswith("_normal") or name.endswith("_n"):
        return "normal"
    return None


def _expected(role: str, has_alpha: bool) -> tuple[str, bool]:
    """Return (block compression, mipmaps required) for a recognized role.

    Diffuse follows the PDF rows: transparency uses BC7, an opaque diffuse uses BC1.
    ``has_alpha`` comes from the header flags. Pixel blocks are not decoded.
    """
    if role == "diffuse":
        return ("BC7" if has_alpha else "BC1", True)
    if role == "normal":
        return ("BC1", True)
    if role == "height":
        return ("BC4", True)
    if role == "specular":
        return ("BC1", True)
    if role == "mod_icon":
        return ("BC1", False)
    if role == "store_icon":
        return ("BC7", False)
    raise ValueError(role)


def _load_dictionary(mod_root: Path, root: ET.Element, report: ValidationReport) -> set[str]:
    keys: set[str] = set()
    seen: set[Path] = set()
    for l10n in root.iter("l10n"):
        _collect_text_names(l10n, keys)
        prefix = (l10n.get("filenamePrefix") or "").strip()
        if not prefix:
            continue
        english = f"{prefix}_en.xml"
        exists, detail = path_exists_case_sensitive(mod_root, english)
        if not exists:
            report.add(
                Severity.WARNING,
                f"L10N-002: filenamePrefix '{prefix}' has no English file '{english}'. {detail}",
                location="l10n",
            )
        for lang in _LANG_CODES:
            relative = f"{prefix}_{lang}.xml"
            found, _reason = path_exists_case_sensitive(mod_root, relative)
            if not found:
                continue
            path = (mod_root / normalize_mod_relative(relative)).resolve()
            seen.add(path)
            _read_l10n_file(path, keys, report)

    for path in sorted(mod_root.rglob("*.xml")):
        if _under_junk(mod_root, path):
            continue
        stem = path.stem.lower()
        if not (stem.startswith("l10n_") or stem.startswith("translation_")):
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        _read_l10n_file(resolved, keys, report)
    return keys


def _compare_language_files(mod_root: Path, report: ValidationReport) -> None:
    """Report keys present in the English file and absent from a sibling language file."""
    families: dict[str, dict[str, Path]] = {}
    for path in sorted(mod_root.rglob("*.xml")):
        if _under_junk(mod_root, path):
            continue
        split = _split_language(path)
        if split is None:
            continue
        family, lang = split
        families.setdefault(family, {})[lang] = path

    for languages in families.values():
        english = languages.get("en")
        if english is None or len(languages) < 2:
            continue
        english_keys = _keys_in_file(english)
        if not english_keys:
            continue
        for lang, path in sorted(languages.items()):
            if lang == "en":
                continue
            other = _keys_in_file(path)
            if other is None:
                continue
            for key in sorted(english_keys - other):
                report.add(
                    Severity.INFO,
                    f"L10N-003: '{key}' is defined in {english.name} and missing from {path.name}.",
                    location=_relative(mod_root, path),
                )


def _split_language(path: Path) -> tuple[str, str] | None:
    stem = path.stem
    for lang in _LANG_CODES:
        suffix = f"_{lang}"
        if stem.lower().endswith(suffix) and len(stem) > len(suffix):
            family = f"{path.parent.as_posix()}/{stem[: -len(suffix)].lower()}"
            return family, lang
    return None


def _keys_in_file(path: Path) -> set[str] | None:
    try:
        file_root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    keys: set[str] = set()
    _collect_text_names(file_root, keys)
    return keys


def _read_l10n_file(path: Path, keys: set[str], report: ValidationReport) -> None:
    try:
        file_root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        report.add(
            Severity.WARNING,
            f"L10N-002: Cannot read localization file: {exc}",
            location=path.name,
        )
        return
    _collect_text_names(file_root, keys)


def _collect_text_names(node: ET.Element, keys: set[str]) -> None:
    for text in node.iter("text"):
        name = (text.get("name") or "").strip()
        if name.startswith("$l10n_"):
            name = name[6:]
        if name:
            keys.add(name)


def _declared_keys(mod_root: Path, root: ET.Element) -> list[tuple[str, str]]:
    """Title, description, and store name/description/function keys."""
    found: list[tuple[str, str]] = []
    for tag in ("title", "description"):
        for element in root.findall(tag):
            found.extend(_keys_under(element, tag, store_only=False))

    for item in root.iter("storeItem"):
        relative = (item.get("xmlFilename") or "").strip()
        if not relative:
            continue
        exists, _reason = path_exists_case_sensitive(mod_root, relative)
        if not exists:
            continue
        path = mod_root / normalize_mod_relative(relative)
        try:
            store_root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        found.extend(_keys_under(store_root, relative.replace("\\", "/"), store_only=True))
    return found


def _keys_under(element: ET.Element, location: str, *, store_only: bool) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []

    def walk(node: ET.Element, path: str) -> None:
        interesting = (not store_only) or node.tag in _STORE_TEXT_TAGS
        if interesting:
            for attr, value in node.attrib.items():
                for key in _L10N_KEY.findall(value or ""):
                    found.append((key, f"{path}#{attr}"))
            for key in _L10N_KEY.findall(node.text or ""):
                found.append((key, path))
        for child in list(node):
            walk(child, f"{path}/{child.tag}")

    walk(element, location)
    return found


def _under_junk(root: Path, path: Path) -> bool:
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    return any(part.lower() in _JUNK_DIRECTORIES for part in parts)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name
