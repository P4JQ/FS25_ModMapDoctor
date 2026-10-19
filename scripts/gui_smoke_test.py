"""Headless-ish GUI smoke test for the TerraFarm tab (opens a real window briefly)."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import customtkinter as ctk  # noqa: E402

from app.gui.main_window import MainWindow  # noqa: E402
from app.gui.tabs.terrafarm_tab import TAB_MACHINE, TAB_REGISTRATION  # noqa: E402

SHOT_DIR = ROOT / "scripts" / "_shots"
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


def find_tab(window: MainWindow):
    from app.gui.tabs.terrafarm_tab import TerraFarmTab

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, TerraFarmTab):
                return child
            found = walk(child)
            if found is not None:
                return found
        return None

    return walk(window)


_PS_CAPTURE = r"""
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System.Runtime.InteropServices;
public class Dpi {{ [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }}
'@
[Dpi]::SetProcessDPIAware() | Out-Null
$bmp = New-Object System.Drawing.Bitmap({w}, {h})
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen({x}, {y}, 0, 0, $bmp.Size)
$bmp.Save('{path}', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"""


def screenshot(window: MainWindow, name: str) -> None:
    """Best-effort window screenshot using Windows' built-in .NET (no Pillow needed)."""
    import subprocess

    try:
        window.lift()
        window.attributes("-topmost", True)
        pump(window, 8)
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOT_DIR / f"{name}.png"
        script = _PS_CAPTURE.format(
            x=window.winfo_rootx(),
            y=window.winfo_rooty(),
            w=window.winfo_width(),
            h=window.winfo_height(),
            path=str(path),
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=True,
            capture_output=True,
            timeout=30,
        )
        window.attributes("-topmost", False)
        print(f"[shot] {path}")
    except Exception as exc:  # noqa: BLE001 - screenshot is best effort
        print(f"[shot] skipped: {exc}")


def pump(window: MainWindow, times: int = 5) -> None:
    for _ in range(times):
        window.update_idletasks()
        window.update()


def install_settling_select() -> None:
    """Make XmlOutputPanel tab switches behave like human clicks.

    CTkTabview.set() hides the other tabs through a 100 ms timer; calling it
    several times back-to-back in a script lets an old timer hide the new tab.
    Shared by every GUI smoke test that switches output tabs.
    """
    import time

    from app.gui.widgets import XmlOutputPanel

    original = XmlOutputPanel.select

    def settled(self: XmlOutputPanel, tab_name: str) -> None:
        original(self, tab_name)
        time.sleep(0.25)
        pump(self.winfo_toplevel(), 10)

    XmlOutputPanel.select = settled  # type: ignore[method-assign]


def run() -> int:
    install_settling_select()
    window = MainWindow()
    window.deiconify()
    pump(window, 10)

    print(f"window size: {window.winfo_width()}x{window.winfo_height()}")
    check(window.winfo_width() >= 1000, "window is at least 1000 px wide")

    # Switch to the TerraFarm tab
    for child in window.winfo_children():
        if isinstance(child, ctk.CTkTabview):
            child.set("TerraFarm Generator")
    pump(window, 10)

    tab = find_tab(window)
    check(tab is not None, "TerraFarm tab found")
    if tab is None:
        window.destroy()
        return 1

    # Placeholders must survive set()/clear(), including on Reset Form.
    width = tab._fields["width"]
    width.set("9")
    width.clear()
    check(width._entry._placeholder_text_active, "placeholder returns after clear()")
    tab.offset_field._entries[0].insert(0, "7")
    tab.offset_field.clear()
    check(
        all(e._placeholder_text_active for e in tab.offset_field._entries),
        "X/Y/Z placeholders return after clear()",
    )

    # Layout: how much form content is there vs. how much is visible?
    needed = tab.form_panel.winfo_reqheight()
    visible = tab.form_panel._parent_canvas.winfo_height()
    print(f"form content height={needed}px, visible={visible}px")
    check(needed <= visible + 4, "whole form fits without scrolling at the default window size")

    # Placeholders: empty entries return '' (placeholder is not real text)
    check(tab._fields["raycast"].raw() == "", "placeholder is not read as a value")
    screenshot(window, "01_shovel_default")

    # Shovel happy path with XYZ vectors
    tab.vehicle_path.set("FS25_Demo/vehicles/bucket/bucket.xml")
    tab.machine_file_path.set("xml/machines/bucket.xml")
    tab._fields["width"].set("2.8")
    for entry, text in zip(tab.offset_field._entries, ("0", "-0.15", "0.75")):
        entry.insert(0, text)
    tab._generate()
    pump(window)
    files = tab._generated
    check(files is not None, "shovel generation succeeded")
    if files is not None:
        machine_root = ET.fromstring(files.machine_xml)
        reg_root = ET.fromstring(files.registration_xml or "<x/>")
        check(machine_root.tag == "vehicle", "machine file is well-formed <vehicle>")
        check(reg_root.tag == "configurations", "registration file is well-formed <configurations>")
        work_area = machine_root.find("machine/workArea")
        check(
            work_area is not None and work_area.get("offset") == "0 -0.15 0.75",
            "X/Y/Z fields combine into 'offset=\"0 -0.15 0.75\"'",
        )
        check(machine_root.find("machine").get("type") == "shovel", "machine type is shovel")
        check(files.machine_filename == "bucket.xml", "default save name comes from machine path")
    screenshot(window, "02_shovel_generated")

    # Partly filled vector: empty axes become 0
    tab.offset_field.clear()
    tab.offset_field._entries[2].insert(0, "1.5")
    check(tab.offset_field.value() == "0 0 1.5", "partly filled vector pads empty axes with 0")

    # Invalid number is rejected and flagged
    tab.offset_field._entries[0].insert(0, "abc")
    try:
        tab.offset_field.value()
        check(False, "invalid vector number raises ValueError")
    except ValueError as exc:
        check("not a valid number" in str(exc), f"invalid vector number rejected ({exc})")
    tab.offset_field.clear()

    # Trencher: required fields enforced
    tab.type_var.set("Trencher")
    tab._on_type_changed("Trencher")
    pump(window)
    check(not tab._fields["shovel_node"]._enabled, "trencher disables shovelNodeIndex")
    check(tab._fields["fill_unit"]._required, "trencher marks fillUnitIndex as required")
    tab._fields["width"].clear()
    tab._generate()
    check(tab._generated is None, "trencher without required fields fails")
    print("status:", tab.status_label.cget("text"))
    screenshot(window, "03_trencher_error")

    tab._fields["fill_unit"].set("2")
    tab._fields["reference_node"].set("posNodeRef")
    tab._fields["width"].set("3.5")
    tab._generate()
    check(tab._generated is not None, "trencher generation succeeded")
    if tab._generated is not None:
        root = ET.fromstring(tab._generated.machine_xml)
        machine = root.find("machine")
        check(machine.get("fillUnitIndex") == "2", "trencher fillUnitIndex=2 in XML")
        check(machine.get("shovelNodeIndex") is None, "disabled fields are omitted from XML")

    # Work area off -> its fields disabled
    tab.include_work_area_var.set(False)
    tab._refresh_field_states()
    check(not tab._fields["width"]._enabled, "unchecking <workArea> disables width")
    tab.include_work_area_var.set(True)
    tab._refresh_field_states()

    # Registration tab selection controls what Copy/Save would export
    panel = tab.output_panel
    panel.select(TAB_REGISTRATION)
    doc = panel.active_document()
    check(doc is not None and doc.filename == "machineConfigurations.xml", "registration tab exports machineConfigurations.xml")
    panel.select(TAB_MACHINE)
    doc = panel.active_document()
    check(doc is not None and doc.filename == "bucket.xml", "machine tab exports the machine file")

    # Registration switched off: the tab explains it and Copy / Save are refused.
    tab.include_registration_var.set(False)
    tab._generate()
    check(tab._generated is not None and tab._generated.registration_xml is None, "registration off: no registration file")
    check("turned off" in panel.boxes[TAB_REGISTRATION].get("1.0", "end").lower(), "registration tab explains it is turned off")
    panel.select(TAB_REGISTRATION)
    check(panel.active_document() is None, "registration off: nothing to export")
    check("turned off" in tab.status_label.cget("text"), "registration off: status says the option is turned off")
    panel.select(TAB_MACHINE)
    tab.include_registration_var.set(True)

    # A failed generation clears the panel so stale XML can never be exported.
    tab._generate()
    check(panel.document(TAB_MACHINE) is not None, "valid generation fills the panel")
    tab.include_registration_var.set(True)
    saved_vehicle = tab.vehicle_path.value()
    tab.vehicle_path.clear()
    tab._generate()
    check(panel.document(TAB_MACHINE) is None, "failed generation clears the panel")
    tab.vehicle_path.set(saved_vehicle)

    # Save as XML file: fake the dialog, then re-parse what was written to disk.
    import tempfile

    from app.gui.widgets import output_panel as panel_module

    # Generate a fresh trencher result so both documents exist.
    tab._generate()
    with tempfile.TemporaryDirectory() as tmp:
        machine_path = Path(tmp) / "machine_out.xml"
        reg_path = Path(tmp) / "reg_out.xml"
        original = panel_module.filedialog.asksaveasfilename

        panel.select(TAB_MACHINE)
        panel_module.filedialog.asksaveasfilename = lambda **_kw: str(machine_path)
        panel.save_active()
        panel.select(TAB_REGISTRATION)
        panel_module.filedialog.asksaveasfilename = lambda **_kw: str(reg_path)
        panel.save_active()

        panel_module.filedialog.asksaveasfilename = lambda **_kw: ""
        panel.save_active()
        check("cancelled" in tab.status_label.cget("text").lower(), "cancelling the save dialog is handled")
        panel_module.filedialog.asksaveasfilename = original

        check(machine_path.is_file(), "machine XML was written to disk")
        check(reg_path.is_file(), "registration XML was written to disk")
        if machine_path.is_file():
            check(ET.parse(machine_path).getroot().tag == "vehicle", "saved machine file re-parses as <vehicle>")
        if reg_path.is_file():
            check(ET.parse(reg_path).getroot().tag == "configurations", "saved registration file re-parses")
    panel.select(TAB_MACHINE)

    # Reset Form restores placeholders and defaults
    tab.vehicle_path.set("something")
    tab._reset_form()
    check(tab.vehicle_path._entry._placeholder_text_active, "Reset Form restores the Vehicle Path placeholder")
    check(tab._generated is None, "Reset Form clears the generated result")
    check(panel.document(TAB_MACHINE) is None and panel.document(TAB_REGISTRATION) is None, "Reset Form empties the output panel")
    tab.type_var.set("Excavator")
    tab._on_type_changed("Excavator")

    # Registration needs paths: after a reset, generating without them must fail clearly.
    tab._generate()
    check(tab._generated is None, "generating with registration but no Vehicle Path fails")
    tab.vehicle_path.set("FS25_Demo/vehicles/excavator/excavator.xml")
    tab.machine_file_path.set("xml/machines/excavator.xml")

    # Clipboard
    tab._generate()
    check(tab._generated is not None, "excavator generation after reset succeeded")
    panel.copy_active()
    check("<vehicle>" in window.clipboard_get(), "Copy to Clipboard puts XML on the clipboard")

    # Compactor + excavator quick pass
    for label, expected in (
        ("Compactor (roller)", "compactor"),
        ("Excavator", "excavatorShovel"),
        ("Ripper", "ripper"),
        ("Excavator ripper", "excavatorRipper"),
    ):
        tab.type_var.set(label)
        tab._on_type_changed(label)
        tab._fields["reference_node"].set("posNodeRef")
        tab._fields["width"].set("3")
        tab._generate()
        check(tab._generated is not None, f"{expected} generation succeeded")
        if tab._generated is not None:
            machine = ET.fromstring(tab._generated.machine_xml).find("machine")
            check(machine is not None and machine.get("type") == expected, f"{expected} type attribute")

    tab.type_var.set("Discharger (trailer / truck)")
    tab._on_type_changed("Discharger (trailer / truck)")
    check(tab._mode_boxes["LOWER"].cget("state") == "disabled", "discharger disables input modes")
    tab._fields["reference_node"].clear()
    tab._fields["width"].clear()
    tab._generate()
    check(tab._generated is not None, "discharger generation succeeded")
    if tab._generated is not None:
        machine = ET.fromstring(tab._generated.machine_xml).find("machine")
        check(machine is not None and machine.get("type") == "discharger", "discharger type attribute")
        check(machine is not None and machine.find("input") is None, "discharger XML has no input block")

    screenshot(window, "04_excavator")
    window.destroy()

    print("-" * 60)
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
