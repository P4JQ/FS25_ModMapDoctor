"""Static checks for the ModHub compliance section (DDS headers, junk, l10n)."""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Severity  # noqa: E402
from app.validators.dds_header import read_dds_header  # noqa: E402
from app.validators.modhub_auditor import ModHubAuditor  # noqa: E402
from app.validators.pipeline import SECTION_MODHUB, run_xml_validation_suite  # noqa: E402

failures: list[str] = []
passed = 0


def check(condition: bool, label: str) -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}")


def pack_dds(
    *,
    fourcc: bytes = b"DXT1",
    width: int = 64,
    height: int = 64,
    mipmaps: int = 1,
    alpha: bool = False,
    dxgi: int | None = None,
) -> bytes:
    """Build a header-only DDS blob. No pixel blocks are written."""
    flags = 0x1 | 0x2 | 0x4 | 0x1000
    if mipmaps > 0:
        flags |= 0x20000
    pf_flags = 0x4
    if alpha:
        pf_flags |= 0x1
    fourcc_bytes = b"DX10" if dxgi is not None else fourcc
    pixel = struct.pack("<II4sIIIII", 32, pf_flags, fourcc_bytes, 0, 0, 0, 0, 0)
    caps = 0x1000
    if mipmaps > 1:
        caps |= 0x400008
    header = struct.pack("<IIIIIII", 124, flags, height, width, 0, 0, mipmaps)
    header += b"\x00" * 44
    header += pixel
    header += struct.pack("<IIIII", caps, 0, 0, 0, 0)
    blob = b"DDS " + header
    if dxgi is not None:
        blob += struct.pack("<IIIII", dxgi, 3, 0, 1, 0)
    return blob


def _ids(report) -> list[str]:
    found: list[str] = []
    for issue in report.issues:
        token = issue.message.split(":", 1)[0]
        if token[:3].isalpha() or token.startswith("DDS") or token.startswith("HUB") or token.startswith("L10N"):
            found.append(token)
    return found


def _write(mod: Path, relative: str, data: bytes | str) -> None:
    path = mod / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def _mod_desc(title: str = "<en>Sample</en>", extra: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="no" ?>\n'
        '<modDesc descVersion="104">\n'
        "    <author>a</author>\n"
        "    <version>1.0.0.0</version>\n"
        f"    <title>{title}</title>\n"
        "    <description><en>Text</en></description>\n"
        "    <iconFilename>icon.png</iconFilename>\n"
        f"{extra}\n"
        "</modDesc>\n"
    )


def test_header_reader() -> None:
    print("DDS header reader")
    opaque = read_dds_header(pack_dds(fourcc=b"DXT1", width=128, height=64, mipmaps=5))
    check(opaque.format_name == "BC1" and not opaque.has_alpha, "DXT1 reads as BC1 without alpha")
    check(opaque.mipmaps_present and opaque.power_of_two, "mipmapCount 5 is a chain and 128x64 is power-of-two")

    alpha = read_dds_header(pack_dds(fourcc=b"DXT1", alpha=True, mipmaps=2))
    check(alpha.has_alpha and alpha.format_name == "BC1", "DXT1 with the alpha flag is BC1 with alpha")

    bc7 = read_dds_header(pack_dds(dxgi=98, width=256, height=256, mipmaps=8))
    check(bc7.format_name == "BC7" and bc7.has_alpha and bc7.fourcc == "DX10", "DXGI 98 reads as BC7")

    bc4 = read_dds_header(pack_dds(fourcc=b"BC4U", mipmaps=4))
    check(bc4.format_name == "BC4" and not bc4.has_alpha, "BC4U reads as BC4")

    odd = read_dds_header(pack_dds(width=100, height=64, mipmaps=1))
    check(not odd.power_of_two and not odd.mipmaps_present, "100px width is not power-of-two and count 1 is no chain")

    try:
        read_dds_header(b"NOT_A_DDS_FILE!!")
    except Exception as exc:  # noqa: BLE001
        check("DDS" in str(exc), "a non-DDS magic is rejected")
    else:
        check(False, "a non-DDS magic is rejected")


def test_texture_matrix() -> None:
    print("Texture matrix")
    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        _write(mod, "modDesc.xml", _mod_desc())
        _write(mod, "icon.png", b"x")
        files = {
            "textures/body_n.dds": pack_dds(fourcc=b"DXT1", mipmaps=6),
            "textures/body_diffuse.dds": pack_dds(fourcc=b"DXT1", mipmaps=6),
            "textures/glass_diffuse.dds": pack_dds(dxgi=98, mipmaps=6),
            "textures/body_height.dds": pack_dds(fourcc=b"BC4U", mipmaps=6),
            "textures/body_specular.dds": pack_dds(fourcc=b"DXT1", mipmaps=6),
            "mod_icon.dds": pack_dds(fourcc=b"DXT1", width=256, height=256, mipmaps=1),
            "store_icon.dds": pack_dds(dxgi=98, width=512, height=256, mipmaps=1),
        }
        for name, blob in files.items():
            _write(mod, name, blob)
        report = ModHubAuditor(mod).audit()
        codes = _ids(report)
        check("DDS-002" not in codes and "DDS-003" not in codes and "DDS-004" not in codes, "compliant matrix has no texture warnings")
        check(all(issue.severity != Severity.ERROR for issue in report.issues), "compliant matrix has no errors")
        check(sum(1 for issue in report.issues if issue.message.startswith("DDS-000")) == 7, "each compliant file reports metadata")


def test_texture_violations() -> None:
    print("Texture violations")
    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        _write(mod, "modDesc.xml", _mod_desc())
        _write(mod, "icon.png", b"x")
        _write(mod, "textures/body_n.dds", pack_dds(dxgi=98, width=100, height=60, mipmaps=1))
        _write(mod, "textures/paint_diffuse.dds", pack_dds(fourcc=b"DXT1", alpha=True, mipmaps=4))
        _write(mod, "mod_icon.dds", pack_dds(fourcc=b"DXT1", mipmaps=4))
        _write(mod, "store_icon.dds", pack_dds(fourcc=b"DXT1", mipmaps=1))
        _write(mod, "textures/notes.dds", b"PNG_NOT_DDS" + b"\x00" * 32)
        report = ModHubAuditor(mod).audit()
        by_file: dict[str, set[str]] = {}
        for issue in report.issues:
            by_file.setdefault(issue.location or "", set()).add(issue.message.split(":", 1)[0])
        check(by_file.get("textures/body_n.dds") == {"DDS-002", "DDS-003", "DDS-004"}, "normal map flags format, mips and size")
        check("DDS-002" in by_file.get("textures/paint_diffuse.dds", set()), "alpha diffuse stored as BC1 expects BC7")
        check("DDS-003" in by_file.get("mod_icon.dds", set()), "mod_icon with a mip chain is flagged")
        check("DDS-002" in by_file.get("store_icon.dds", set()), "store_icon stored as BC1 expects BC7")
        check("DDS-001" in by_file.get("textures/notes.dds", set()), "a .dds file with a bad magic is an error")
        check(any(issue.severity == Severity.ERROR for issue in report.issues), "bad magic fails the section")


def test_junk_and_l10n() -> None:
    print("Junk and localization")
    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        _write(
            mod,
            "modDesc.xml",
            _mod_desc(
                title="<en>$l10n_mod_title</en>",
                extra=(
                    '<l10n filenamePrefix="translations/translation"/>\n'
                    '<storeItems><storeItem xmlFilename="shop.xml"/></storeItems>'
                ),
            ),
        )
        _write(mod, "icon.png", b"x")
        _write(mod, "shop.xml", "<vehicle><storeData><name>$l10n_shop_item</name></storeData></vehicle>")
        _write(mod, "translations/translation_en.xml", '<l10n><texts><text name="mod_title" text="Title"/></texts></l10n>')
        _write(mod, "Thumbs.db", b"junk")
        _write(mod, "desktop.ini", "junk")
        _write(mod, "source/mesh.blend", b"junk")
        (mod / ".git").mkdir()
        (mod / ".git" / "config").write_text("git", encoding="utf-8")
        (mod / ".github").mkdir()
        report = ModHubAuditor(mod).audit()
        messages = [issue.message for issue in report.issues]
        locations = [issue.location or "" for issue in report.issues if "HUB-001" in issue.message]
        check(any(issue.severity == Severity.ERROR and "HUB-001" in issue.message for issue in report.issues), "junk is an error")
        check(any(".git" == Path(loc).name for loc in locations), ".git directory is flagged once")
        check(any(".github" == Path(loc).name for loc in locations), ".github directory is flagged")
        check(any("Thumbs.db" in loc for loc in locations), "Thumbs.db is flagged")
        check(any("desktop.ini" in loc for loc in locations), "desktop.ini is flagged")
        check(any(loc.endswith("mesh.blend") for loc in locations), ".blend file is flagged")
        check(not any("config" == Path(loc).name for loc in locations), "files inside .git are not listed one by one")
        check(any("L10N-001" in message and "shop_item" in message for message in messages), "missing store key is a warning")
        check(not any("L10N-001" in message and "mod_title" in message for message in messages), "a key defined in translation_en.xml is resolved")

    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        _write(mod, "modDesc.xml", _mod_desc(title="<en>$l10n_from_file</en>"))
        _write(mod, "l10n_en.xml", '<l10n><texts><text name="from_file" text="Hello"/></texts></l10n>')
        report = ModHubAuditor(mod).audit()
        check(
            not any("L10N-001" in issue.message for issue in report.issues),
            "l10n_en.xml resolves a title key without a filenamePrefix",
        )

    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        _write(
            mod,
            "modDesc.xml",
            _mod_desc(
                extra='<l10n><text name="inline_title"><en>Hello</en></text></l10n>',
                title="<en>$l10n_inline_title</en>",
            ),
        )
        report = ModHubAuditor(mod).audit()
        check(
            not any("L10N-001" in issue.message for issue in report.issues),
            "an inline modDesc text entry resolves the title key",
        )

    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        _write(mod, "modDesc.xml", _mod_desc())
        _write(
            mod,
            "l10n_en.xml",
            '<l10n><texts><text name="shared" text="Yes"/><text name="english_only" text="Only"/></texts></l10n>',
        )
        _write(mod, "l10n_de.xml", '<l10n><texts><text name="shared" text="Ja"/></texts></l10n>')
        _write(mod, "l10n_fr.xml", '<l10n><texts><text name="shared" text="Oui"/><text name="english_only" text="Oui"/></texts></l10n>')
        report = ModHubAuditor(mod).audit()
        missing = [issue for issue in report.issues if "L10N-003" in issue.message]
        check(len(missing) == 1 and "english_only" in missing[0].message and "l10n_de.xml" in missing[0].message, "a key missing from another language file is info")
        check(all(issue.severity == Severity.INFO for issue in missing), "cross-language gaps are info, not warnings")
        check(not any("l10n_fr.xml" in issue.message and "L10N-003" in issue.message for issue in report.issues), "a language file that has the key is not flagged")


def test_samples() -> None:
    print("Samples")
    ok = run_xml_validation_suite(ROOT / "samples" / "sample_ok_mod")
    section = ok.section(SECTION_MODHUB)
    check(section is not None and section.passed, "sample_ok_mod ModHub section passes")
    check(
        section is not None and not any(issue.severity == Severity.WARNING for issue in section.issues),
        "sample_ok_mod ModHub section has no warnings",
    )
    check(ok.passed, "sample_ok_mod suite still passes")
    check(len(ok.sections) == 8, "suite has eight sections")

    broken = run_xml_validation_suite(ROOT / "samples" / "sample_broken_mod")
    broken_section = broken.section(SECTION_MODHUB)
    found = set(_ids(broken_section)) if broken_section else set()
    check({"HUB-001", "L10N-001", "DDS-002", "DDS-003", "DDS-004"} <= found, f"sample_broken_mod reports ModHub rules (found {sorted(found)})")
    check(not broken.passed, "sample_broken_mod suite still fails")


def main() -> int:
    test_header_reader()
    test_texture_matrix()
    test_texture_violations()
    test_junk_and_l10n()
    test_samples()
    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED, {passed} passed:")
        for label in failures:
            print(f"  - {label}")
        return 1
    print(f"ALL {passed} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
