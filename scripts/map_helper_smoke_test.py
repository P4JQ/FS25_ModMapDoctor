"""Smoke test for the Map Helper tab (opens a real window briefly).

Reuses the helpers (check/pump/screenshot) of ``gui_smoke_test.py``.
"""

from __future__ import annotations

import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import customtkinter as ctk  # noqa: E402
import gui_smoke_test as base  # noqa: E402

from app.generators import (  # noqa: E402
    EXAMPLE_LAYERS,
    GroundLayer,
    InfoLayerSettings,
    MapResourcesGenerator,
)
from app.gui.main_window import MainWindow  # noqa: E402
from app.gui.tabs import map_helper_tab as tab_module  # noqa: E402
from app.gui.tabs.map_helper_tab import (  # noqa: E402
    TAB_GROUND_RESOURCES,
    TAB_INFO_LAYER,
    MapHelperTab,
)
from app.gui.widgets import output_panel as panel_module  # noqa: E402

check = base.check
pump = base.pump


def find_tab(widget) -> MapHelperTab | None:
    for child in widget.winfo_children():
        if isinstance(child, MapHelperTab):
            return child
        found = find_tab(child)
        if found is not None:
            return found
    return None


def expect_error(callable_, needle: str, label: str) -> None:
    try:
        callable_()
    except ValueError as exc:
        check(needle.lower() in str(exc).lower(), f"{label} ({exc})")
    else:
        check(False, f"{label}: expected ValueError")


def test_generator() -> None:
    """Pure-logic checks, no window."""
    gen = MapResourcesGenerator()
    result = gen.generate(list(EXAMPLE_LAYERS))
    root = ET.fromstring(result.ground_resources_xml)
    layers = root.findall("layers/layer")
    check(root.tag == "groundResources" and root.get("infoLayer") == "mapGroundResources", "ground xml root + infoLayer")
    check([l.get("value") for l in layers] == ["0", "1", "2", "3"], "layers are sorted by value")
    check(layers[1].get("paintLayerDischarge") == "dirtDark", "paintLayerDischarge written (documented spelling)")
    check(layers[2].get("yield") == "0.8", "yield 0.8 written")
    check(layers[0].get("yield") == "1.0", "yield 1 formatted as 1.0")
    check(layers[3].get("yield") is None, "empty yield omitted")
    check(layers[0].get("paintLayerDischarge") is None, "empty discharge omitted")

    info = ET.fromstring(result.info_layer_xml)
    group = info.find("Group")
    check(info.tag == "InfoLayer" and info.get("runtime") == "true", "InfoLayer root with runtime=true")
    check(info.get("numChannels") == "2" and group.get("numChannels") == "2", "values 0-3 need 2 channels")
    check(info.get("fileId") == "...", "fileId keeps the template placeholder when empty")
    check(len(group.findall("Option")) == 4, "one Option per layer")
    check(group.findall("Option")[0].get("name") == "None", "value 0 option defaults to 'None'")

    # Same discharge as paintLayer is redundant -> omitted
    same = gen.generate([GroundLayer(0, "STONE", "rock", paint_layer_discharge="rock")])
    check(ET.fromstring(same.ground_resources_xml).find("layers/layer").get("paintLayerDischarge") is None,
          "discharge equal to paintLayer is omitted")

    # Channels with firstChannel
    big = gen.generate(
        [GroundLayer(0, "STONE", "a"), GroundLayer(5, "DIRT", "b")],
        InfoLayerSettings(first_channel=1, file_id="12"),
    )
    info = ET.fromstring(big.info_layer_xml)
    check(info.get("numChannels") == "4" and info.find("Group").get("firstChannel") == "1", "firstChannel 1 + 3 bits = 4 channels")
    check(info.get("fileId") == "12", "explicit fileId is used")

    expect_error(lambda: gen.generate([]), "at least one layer", "no layers rejected")
    expect_error(lambda: gen.generate([GroundLayer(1, "STONE", "a")]), "value 0 is required", "missing value 0 rejected")
    expect_error(lambda: gen.generate([GroundLayer(0, "STONE", "a"), GroundLayer(0, "DIRT", "b")]), "more than once", "duplicate value rejected")
    expect_error(lambda: gen.generate([GroundLayer(0, "", "a")]), "fillType", "empty fillType rejected")
    expect_error(lambda: gen.generate([GroundLayer(0, "STONE", "a", yield_value=-1.0)]), "yield", "negative yield rejected")
    expect_error(
        lambda: gen.generate([GroundLayer(0, "STONE", "a"), GroundLayer(4, "DIRT", "b")], InfoLayerSettings(num_channels=2)),
        "needs 3 channel", "too few channels rejected",
    )
    expect_error(
        lambda: gen.generate([GroundLayer(0, "STONE", "a")], InfoLayerSettings(num_channels=1, first_channel=1)),
        "must be greater than firstChannel", "numChannels <= firstChannel rejected",
    )

    # Special characters are escaped, output stays well-formed
    tricky = gen.generate([GroundLayer(0, "STONE", 'a"b&c<d')], InfoLayerSettings(name="my&layer"))
    check(ET.fromstring(tricky.ground_resources_xml).find("layers/layer").get("paintLayer") == 'a"b&c<d',
          "special characters are escaped and round-trip")

    lower = gen.generate([GroundLayer(0, "stone", "a")])
    check(any("upper-case" in w for w in lower.warnings), "lower-case fillType triggers a warning")


def run() -> int:
    test_generator()
    base.install_settling_select()

    window = MainWindow()
    window.deiconify()
    pump(window, 10)
    for child in window.winfo_children():
        if isinstance(child, ctk.CTkTabview):
            child.set("Map Helper")
    pump(window, 10)

    tab = find_tab(window)
    check(tab is not None, "Map Helper tab found")
    if tab is None:
        window.destroy()
        return 1

    # Layout and placeholders
    needed = tab.form_panel.winfo_reqheight()
    visible = tab.form_panel._parent_canvas.winfo_height()
    print(f"form content height={needed}px, visible={visible}px")
    check(needed <= visible + 4, "whole form fits without scrolling at the default window size")
    check(tab.layer_value._entry._placeholder_text_active, "Layer ID shows a placeholder")
    check(tab.yield_entry.raw() == "", "placeholder is not read as a value")
    check(tab.fill_type.value() == "STONE", "fillType starts on STONE")
    base.screenshot(window, "10_map_default")

    # Nothing configured
    tab._generate()
    check("add at least one layer" in tab.status_label.cget("text").lower(), "generate without layers fails clearly")

    # paintLayer is required when adding
    tab._add_layer()
    check(not tab._layers, "adding without paintLayer is rejected")
    check(tab.paint_layer._entry.cget("border_color") == "#E74C3C", "paintLayer is flagged with a red border")
    base.screenshot(window, "11_map_error")

    # Manual add: blank ID -> next free value (0)
    tab.paint_layer._entry.insert(0, "gravel")
    tab._add_layer()
    check(0 in tab._layers and tab._layers[0].paint_layer == "gravel", "blank Layer ID uses next free value 0")
    check(tab.layer_value._entry._placeholder_text_active, "Layer ID placeholder returns after add")
    check(tab.layer_value._placeholder == "1", "placeholder suggests the next free ID (1)")
    check(tab.paint_layer._entry._placeholder_text_active, "paintLayer is cleared after add")

    # Add with explicit values, then update the same ID
    tab.layer_value._entry.insert(0, "1")
    tab.fill_type.set("DIRT")
    tab.paint_layer._entry.insert(0, "dirt")
    tab.paint_layer_discharge._entry.insert(0, "dirtDark")
    tab.yield_entry._entry.insert(0, "0,8")
    tab._add_layer()
    check(tab._layers[1].yield_value == 0.8, "comma decimal is accepted for yield")
    check(tab._layers[1].paint_layer_discharge == "dirtDark", "discharge stored")

    tab.layer_value._entry.insert(0, "1")
    tab.paint_layer._entry.insert(0, "soil")
    tab._add_layer()
    check(len(tab._layers) == 2 and tab._layers[1].paint_layer == "soil", "same ID updates instead of duplicating")
    check("updated layer 1" in tab.status_label.cget("text").lower(), "status says the layer was updated")

    # Click a row -> loaded into editor
    tab._load_layer(1)
    check(tab.paint_layer.raw() == "soil" and tab.layer_value.raw() == "1", "clicking a layer loads it into the editor")
    tab.layer_value.clear()
    tab.paint_layer.clear()
    tab.paint_layer_discharge.clear()
    tab.option_name.clear()

    # Invalid number input
    tab.layer_value._entry.insert(0, "-3")
    tab._add_layer()
    check("must be 0 or greater" in tab.status_label.cget("text") or "not a whole number" in tab.status_label.cget("text"),
          "negative Layer ID rejected")
    tab.layer_value.clear()

    # Generate -> both tabs
    tab._generate()
    pump(window)
    ground = tab.output_panel.document(TAB_GROUND_RESOURCES)
    info = tab.output_panel.document(TAB_INFO_LAYER)
    check(ground is not None and info is not None, "generate fills both output tabs")
    if ground and info:
        ET.fromstring(ground.text)
        ET.fromstring(info.text)
        check(ground.filename == "mapGroundResources.xml", "ground file name")
        check(info.filename == "mapResources.i3d.xml", "InfoLayer file name")
    base.screenshot(window, "12_map_generated")

    # Too few channels
    tab.num_channels._entry.insert(0, "1")
    tab.layer_value._entry.insert(0, "5")
    tab.paint_layer._entry.insert(0, "rock")
    tab._add_layer()
    tab._generate()
    check("needs 3 channel" in tab.status_label.cget("text"), "numChannels too small is reported")
    check(tab.output_panel.document(TAB_GROUND_RESOURCES) is None, "failed generate clears stale output")
    tab.num_channels.clear()
    tab._update_capacity()
    check("IDs 0-7" in tab.capacity_label.cget("text"), f"capacity label follows layers ({tab.capacity_label.cget('text')})")

    # Remove layer 0 -> value 0 required
    tab._remove_layer(0)
    tab._generate()
    check("value 0 is required" in tab.status_label.cget("text").lower(), "removing layer 0 blocks generation")

    # Example + copy + save
    tab._load_example()
    check(len(tab._layers) == 4, "Load Example adds the 4 documented layers")
    tab._generate()
    check(tab.output_panel.document(TAB_GROUND_RESOURCES) is not None, "example generates")

    tab.output_panel.select(TAB_INFO_LAYER)
    tab.output_panel.copy_active()
    check("<InfoLayer" in window.clipboard_get(), "Copy to Clipboard copies the InfoLayer tab")
    tab.output_panel.select(TAB_GROUND_RESOURCES)
    tab.output_panel.copy_active()
    check("<groundResources" in window.clipboard_get(), "Copy to Clipboard copies the active tab only")

    original = panel_module.filedialog.asksaveasfilename
    with tempfile.TemporaryDirectory() as tmp:
        ground_path = Path(tmp) / "g.xml"
        info_path = Path(tmp) / "i.xml"
        tab.output_panel.select(TAB_GROUND_RESOURCES)
        panel_module.filedialog.asksaveasfilename = lambda **_kw: str(ground_path)
        tab.output_panel.save_active()
        tab.output_panel.select(TAB_INFO_LAYER)
        panel_module.filedialog.asksaveasfilename = lambda **_kw: str(info_path)
        tab.output_panel.save_active()
        panel_module.filedialog.asksaveasfilename = lambda **_kw: ""
        tab.output_panel.save_active()
        check("cancelled" in tab.status_label.cget("text").lower(), "cancelling the save dialog is handled")
        panel_module.filedialog.asksaveasfilename = original
        check(ground_path.is_file() and info_path.is_file(), "both files were written")
        if ground_path.is_file():
            check(ET.parse(ground_path).getroot().tag == "groundResources", "saved ground file re-parses")
        if info_path.is_file():
            check(ET.parse(info_path).getroot().tag == "InfoLayer", "saved InfoLayer file re-parses")

    # Save with nothing generated
    tab._reset_form()
    tab.output_panel.save_active()
    check("nothing to export" in tab.status_label.cget("text").lower(), "save before generating is handled")

    # Reset restores everything
    check(not tab._layers, "Reset Form clears layers")
    check(tab.fill_type.value() == "STONE", "Reset Form restores fillType default")
    check(tab.layer_value._entry._placeholder_text_active, "Reset Form restores placeholders")
    check(tab.paint_layer._entry._placeholder_text_active, "Reset Form restores paintLayer placeholder")
    check(tab.output_panel.document(TAB_INFO_LAYER) is None, "Reset Form clears the output")

    # Final look
    tab._load_example()
    tab._generate()
    # Give Tk time to repaint the freshly shown tab before taking screenshots.
    tab.output_panel.select(TAB_INFO_LAYER)
    pump(window, 25)
    check(len(tab.output_panel.boxes[TAB_INFO_LAYER].get("1.0", "end").strip()) > 100, "InfoLayer tab shows the snippet text")
    base.screenshot(window, "13_map_infolayer")
    tab.output_panel.select(TAB_GROUND_RESOURCES)
    pump(window, 25)
    base.screenshot(window, "14_map_example")
    check(tab_module.MapHelperTab is MapHelperTab, "module sanity")
    window.destroy()

    print("-" * 60)
    failures = base.failures
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
