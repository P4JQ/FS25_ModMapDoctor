"""StoreData name and image checks from StoreManager.md."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Severity  # noqa: E402
from app.validators.pipeline import SECTION_STORE, run_xml_validation_suite  # noqa: E402
from app.validators.store_auditor import StoreAuditor  # noqa: E402

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


def _ids(report) -> list[str]:
    return [issue.message.split(":", 1)[0] for issue in report.issues]


def _audit(xml: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "item.xml"
        path.write_text(xml, encoding="utf-8")
        return StoreAuditor(Path(tmp)).audit()


def test_rules() -> None:
    print("Store rules")
    missing_image = """
        <vehicle>
          <storeData>
            <name>Trailer</name>
            <price>1000</price>
          </storeData>
        </vehicle>
    """
    report = _audit(missing_image)
    check("STORE-001" in _ids(report), "missing image while shown in the shop is a warning")
    check(all(issue.severity == Severity.WARNING for issue in report.issues if "STORE-001" in issue.message), "STORE-001 is a warning")
    check("STORE-002" not in _ids(report), "a present name is not a missing-name warning")

    empty_image = """
        <vehicle>
          <storeData>
            <name>Trailer</name>
            <image></image>
          </storeData>
        </vehicle>
    """
    check("STORE-001" in _ids(_audit(empty_image)), "an empty image element is a warning")

    hidden = """
        <vehicle>
          <storeData>
            <name>Hidden</name>
            <showInStore>false</showInStore>
          </storeData>
        </vehicle>
    """
    hidden_report = _audit(hidden)
    check("STORE-001" not in _ids(hidden_report), "showInStore false does not require an image")
    check(hidden_report.warning_count == 0, "hidden item without an image has no warnings")

    filled = """
        <vehicle>
          <storeData>
            <name>Trailer</name>
            <image>store_icon.dds</image>
          </storeData>
        </vehicle>
    """
    filled_report = _audit(filled)
    check(filled_report.warning_count == 0, "a filled image is not checked on disk")

    unknown_flag = """
        <vehicle>
          <storeData>
            <name>Trailer</name>
            <showInStore>0</showInStore>
          </storeData>
        </vehicle>
    """
    check("STORE-001" not in _ids(_audit(unknown_flag)), "an unproven showInStore value is not flagged")

    missing_name = """
        <vehicle>
          <storeData>
            <image>store_icon.dds</image>
          </storeData>
        </vehicle>
    """
    name_report = _audit(missing_name)
    check("STORE-002" in _ids(name_report), "a missing name drops the store item")
    check("STORE-001" not in _ids(name_report), "a present image is enough for STORE-001")


def _audit_mod(files: dict[str, str]):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return StoreAuditor(root).audit()


def test_registered_price_lifetime() -> None:
    print("Registered items, price, lifetime")
    listed = _audit_mod(
        {
            "modDesc.xml": (
                '<modDesc descVersion="92"><author>a</author><version>1.0.0.0</version>'
                '<iconFilename>icon.png</iconFilename>'
                '<storeItems><storeItem xmlFilename="vehicles/bare.xml"/></storeItems>'
                "</modDesc>"
            ),
            "vehicles/bare.xml": "<vehicle><base><filename>x.i3d</filename></base></vehicle>",
        }
    )
    check("STORE-003" in _ids(listed), "a listed file with no storeData is a warning")
    check(
        all(issue.severity == Severity.WARNING for issue in listed.issues if "STORE-003" in issue.message),
        "STORE-003 is a warning",
    )

    unlisted = _audit_mod({"vehicles/bare.xml": "<vehicle/>"})
    check("STORE-003" not in _ids(unlisted), "a file that is not a store item is not a missing-storeData warning")

    missing = _audit_mod(
        {
            "modDesc.xml": (
                '<modDesc descVersion="92"><storeItems>'
                '<storeItem xmlFilename="vehicles/missing.xml"/>'
                "</storeItems></modDesc>"
            )
        }
    )
    check("STORE-003" not in _ids(missing), "a missing store item file is not a missing-storeData warning")

    present = """
        <vehicle>
          <storeData>
            <name>Trailer</name>
            <image>store_icon.dds</image>
            <price>{price}</price>
            {lifetime}
          </storeData>
        </vehicle>
    """
    negative = _audit(present.format(price="-1", lifetime=""))
    check("STORE-004" in _ids(negative), "a negative price is a warning")
    check("STORE-005" not in _ids(negative), "a missing lifetime is not a lifetime warning")

    zero_price = _audit(present.format(price="0", lifetime="<lifetime>600</lifetime>"))
    check("STORE-004" not in _ids(zero_price), "price 0 does not warn")
    check("STORE-005" not in _ids(zero_price), "lifetime 600 does not warn")

    omitted_price = _audit(present.format(price="", lifetime="").replace("<price></price>", ""))
    check("STORE-004" not in _ids(omitted_price), "a missing price does not warn")

    zero_life = _audit(present.format(price="1000", lifetime="<lifetime>0</lifetime>"))
    check("STORE-005" in _ids(zero_life), "lifetime 0 is a warning")
    check("STORE-004" not in _ids(zero_life), "a positive price does not warn")

    negative_life = _audit(present.format(price="1000", lifetime="<lifetime>-2.5</lifetime>"))
    check("STORE-005" in _ids(negative_life), "a negative lifetime is a warning")

    odd_price = _audit(present.format(price="10,000", lifetime="<lifetime>1e2</lifetime>"))
    check("STORE-004" not in _ids(odd_price) and "STORE-005" not in _ids(odd_price), "unproven number spellings are not flagged")


def test_categories() -> None:
    print("Shop categories")
    base = (
        '<modDesc descVersion="92"><author>a</author><version>1.0.0.0</version>'
        '<iconFilename>icon.png</iconFilename>{extra}'
        '<storeItems><storeItem xmlFilename="vehicles/item.xml"/></storeItems>'
        "</modDesc>"
    )
    item = """
        <vehicle>
          <storeData>
            <name>Trailer</name>
            <image>store_icon.dds</image>
            {category}
          </storeData>
        </vehicle>
    """

    def run(category: str, extra: str = "") -> list[str]:
        return _ids(_audit_mod({
            "modDesc.xml": base.format(extra=extra),
            "vehicles/item.xml": item.format(category=category),
        }))

    known = run("<category>trailers</category>")
    check("STORE-006" not in known and "STORE-007" not in known, "trailers is a base shop category")
    mixed = run("<category>Trailers</category>")
    check("STORE-006" not in mixed, "category lookup is case-insensitive")
    missing = run("")
    check("STORE-007" in missing and "STORE-006" not in missing, "a listed item with no category warns once")
    hidden = run('<showInStore>false</showInStore>')
    check("STORE-007" not in hidden and "STORE-006" not in hidden, "a hidden item does not need a category")
    bad = run("<category>bailing</category>")
    check("STORE-006" in bad and "STORE-007" in bad, "an unknown category is skipped and the list ends empty")
    custom = run(
        "<category>myTools</category>",
        extra='<storeCategories><storeCategory name="myTools" title="Tools" type="MISC" image="icon.png"/></storeCategories>',
    )
    check("STORE-006" not in custom and "STORE-007" not in custom, "a category declared on the mod is accepted")


def test_samples() -> None:
    print("Samples")
    ok = run_xml_validation_suite(ROOT / "samples" / "sample_ok_mod")
    section = ok.section(SECTION_STORE)
    check(section is not None and section.passed and section.warning_count == 0, "sample_ok_mod store section is clean")
    check(len(ok.sections) == 8, "suite has eight sections")
    broken = run_xml_validation_suite(ROOT / "samples" / "sample_broken_mod")
    broken_section = broken.section(SECTION_STORE)
    ids = _ids(broken_section) if broken_section is not None else []
    check(ids.count("STORE-001") == 2, "sample_broken_mod reports both store items that have no image")
    check(ids.count("STORE-006") == 1, "sample_broken_mod reports the category name bailing")
    check("STORE-007" in ids, "sample_broken_mod reports a store item with no usable category")


def main() -> int:
    test_rules()
    test_registered_price_lifetime()
    test_categories()
    test_samples()
    print(f"\n{passed} passed, {len(failures)} failed")
    if failures:
        for label in failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
