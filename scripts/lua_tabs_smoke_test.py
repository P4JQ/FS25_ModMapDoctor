"""Smoke test for the "Mod & Lua Auditor" and "Lua Generator" tabs (opens a real window).

Reuses the helpers of ``gui_smoke_test.py`` (check, pump, screenshot).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import customtkinter as ctk  # noqa: E402
import gui_smoke_test as base  # noqa: E402

from app.generators import (  # noqa: E402
    SCRIPT_TYPE_OPTIONS,
    TARGET_OBJECT_OPTIONS,
    LuaGenerator,
    LuaScriptRequest,
    ScriptType,
    TargetObject,
)
from app.gui.main_window import (  # noqa: E402
    TAB_LUA_GENERATOR,
    TAB_VALIDATOR,
    MainWindow,
)
from app.gui.tabs.lua_generator_tab import (  # noqa: E402
    FORM_STORE,
    TAB_LUA,
    TAB_STORE,
    TAB_XML,
    LuaGeneratorTab,
)
from app.gui.tabs.xml_validator_tab import XmlValidatorTab  # noqa: E402
from app.gui.widgets import output_panel as panel_module  # noqa: E402

check = base.check
pump = base.pump


def find(widget, cls):
    for child in widget.winfo_children():
        if isinstance(child, cls):
            return child
        found = find(child, cls)
        if found is not None:
            return found
    return None


def test_generator_model() -> None:
    print("-- LuaGenerator model")
    check(
        SCRIPT_TYPE_OPTIONS
        == ("Custom Specialization Mod", "Network Event Script", "Placeable Extension"),
        "script type options match the requested labels",
    )
    check(
        TARGET_OBJECT_OPTIONS == ("Vehicle", "Placeable", "Game Environment"),
        "target object options match the requested labels",
    )
    check(
        LuaGenerator.parse_script_type("Network Event Script") is ScriptType.NETWORK_EVENT,
        "script type label parses",
    )
    try:
        LuaGenerator.parse_target("Boat")
    except ValueError:
        check(True, "unknown target label raises ValueError")
    else:
        check(False, "unknown target label raises ValueError")
    result = LuaGenerator.generate(
        LuaScriptRequest(ScriptType.NETWORK_EVENT, TargetObject.VEHICLE, "Probe")
    )
    check(result.class_name == "ProbeEvent" and "ProbeEvent" in result.lua_code, "generate() returns a script")


def run() -> int:
    base.install_settling_select()
    test_generator_model()

    window = MainWindow()
    window.deiconify()
    pump(window, 10)

    tabview = find(window, ctk.CTkTabview)
    check(tabview is not None, "main tabview exists")
    if tabview is None:
        window.destroy()
        return 1

    names = list(tabview._tab_dict)
    check(
        names == [TAB_VALIDATOR, "TerraFarm Generator", "Map Helper", TAB_LUA_GENERATOR],
        f"four tabs in order ({names})",
    )

    # ---- Mod & Lua Auditor -------------------------------------------------
    tabview.set(TAB_VALIDATOR)
    pump(window, 10)
    validator = find(window, XmlValidatorTab)
    check(validator is not None, "auditor tab found")
    if validator is not None:
        validator._mod_root = ROOT / "samples" / "sample_broken_mod"
        validator._run_validation()
        pump(window, 10)
        text = validator.results.get("1.0", "end")
        check("[Lua Audit]" in text, "results contain the [Lua Audit] section")
        check("[Fill Types & Foliage]" in text, "results contain the fill-type section")
        check("[ModHub Compliance]" in text, "results contain the ModHub section")
        check("[I3D Scenegraph]" in text, "results contain the I3D section")
        check("[Husbandry]" in text, "results contain the Husbandry section")
        check("[Store Items]" in text, "results contain the Store Items section")
        check("FILL-004" in text and "FRUIT-008" in text, "broken sample reports fill and foliage findings")
        check("LUA-EVT-004" in text, "broken sample reports LUA-EVT-004")
        check("LUA-OLD-001" in text, "broken sample reports LUA-OLD-001")
        check("FAILED" in validator.status_var.get(), "status line says FAILED")
        base.screenshot(window, "20_auditor_broken")

        validator._mod_root = ROOT / "samples" / "sample_ok_mod"
        validator._run_validation()
        pump(window, 10)
        text = validator.results.get("1.0", "end")
        check("[Lua Audit]" in text and "LUA-" not in text, "ok sample: Lua audit without findings")
        check("[Fill Types & Foliage]" in text and "FILL-" not in text and "FRUIT-" not in text, "ok sample: fill and foliage section is clean")
        check("[ModHub Compliance]" in text and "HUB-001" not in text and "DDS-002" not in text, "ok sample: ModHub section has no junk or format errors")
        check("[Husbandry]" in text and "HUS-001" not in text, "ok sample: Husbandry section has no load errors")
        check("[Store Items]" in text and "STORE-001" not in text, "ok sample: store image is present")
        check("PASSED" in validator.status_var.get(), "ok sample: status line says PASSED")
        base.screenshot(window, "21_auditor_ok")

    # ---- Lua Generator -----------------------------------------------------
    tabview.set(TAB_LUA_GENERATOR)
    pump(window, 10)
    tab = find(window, LuaGeneratorTab)
    check(tab is not None, "Lua Generator tab found")
    if tab is None:
        window.destroy()
        return 1
    panel = tab.output_panel

    check(tab.script_type_var.get() == "Custom Specialization Mod", "script type default is the first option")
    check(tab.target_var.get() == "Vehicle", "target default is the first option")
    check("supported" in tab.compat_label.cget("text"), "default combination is supported")
    check(tab.name_field._required, "Script Name is marked as required")
    check(tab.name_field._entry._placeholder_text_active, "Script Name shows a grey placeholder")
    check(panel.save_label() == "Save as XML file", "save button starts with the generic label")
    base.screenshot(window, "22_lua_generator_default")

    # Nothing generated yet: Copy / Save are refused with a message.
    panel.copy_active()
    check("Nothing to export" in tab.status_label.cget("text"), "copy before generating is refused")

    # Missing name
    tab._generate()
    check("Script Name is required" in tab.status_label.cget("text"), "empty name is reported")
    check(panel.document(TAB_LUA) is None, "failed generation leaves the panel empty")

    # Invalid name
    tab.name_field.set("my spec")
    tab._generate()
    check("letters, digits" in tab.status_label.cget("text"), "invalid name is reported")

    # Incompatible combination
    tab.script_type_var.set("Placeable Extension")
    tab._on_selection_changed()
    check("can only target" in tab.compat_label.cget("text"), "Placeable Extension + Vehicle shows a hint")
    check("placeable" in tab.name_field._placeholder.lower() or "Placeable" in tab.name_field._placeholder, "name placeholder follows the script type")
    tab.name_field.set("MyExt")
    tab._generate()
    check("can only target" in tab.status_label.cget("text"), "Generate on an invalid combination reports the reason")
    check(panel.document(TAB_LUA) is None, "invalid combination generates nothing")
    base.screenshot(window, "23_lua_generator_invalid")

    # ---- the three templates ----------------------------------------------
    cases = [
        ("Custom Specialization Mod", "Vehicle", "MyVehicleSpec", "MyVehicleSpec.lua", "function MyVehicleSpec.initSpecialization()"),
        ("Network Event Script", "Game Environment", "GlobalPing", "GlobalPingEvent.lua", "InitEventClass(GlobalPingEvent"),
        ("Network Event Script", "Vehicle", "SetFuelLevel", "SetFuelLevelEvent.lua", "function SetFuelLevelEvent:run(connection)"),
        ("Placeable Extension", "Placeable", "MyPlaceableExtension", "MyPlaceableExtension.lua", "function MyPlaceableExtension:saveToXMLFile("),
    ]
    for script_type, target, name, filename, marker in cases:
        tab.script_type_var.set(script_type)
        tab.target_var.set(target)
        tab._on_selection_changed()
        tab.name_field.set(name)
        tab._generate()
        pump(window, 10)
        lua_doc = panel.document(TAB_LUA)
        xml_doc = panel.document(TAB_XML)
        check(lua_doc is not None and lua_doc.filename == filename, f"{script_type} / {target}: Lua document {filename}")
        check(xml_doc is not None and xml_doc.filename.endswith("_snippets.xml"), f"{script_type} / {target}: XML snippet document")
        shown = panel.boxes[TAB_LUA].get("1.0", "end")
        check(marker in shown, f"{script_type} / {target}: text box shows the generated script")
        check(panel.active_tab() == TAB_LUA, f"{script_type} / {target}: Lua tab is selected")
        check(panel.save_label() == "Save as Lua file", f"{script_type} / {target}: button says Save as Lua file")
        check("Generated" in tab.status_label.cget("text"), f"{script_type} / {target}: status reports success")

    base.screenshot(window, "24_lua_generator_generated")

    # ---- Copy / Save (last case: Placeable Extension) ------------------------
    panel.select(TAB_LUA)
    panel.copy_active()
    clip = window.clipboard_get()
    check("MyPlaceableExtension.registerXMLPaths" in clip, "Copy to Clipboard copies the Lua script")

    panel.select(TAB_XML)
    check(panel.save_label() == "Save as XML file", "button switches to Save as XML file on the snippet tab")
    base.screenshot(window, "25_lua_generator_xml_tab")
    panel.select(TAB_LUA)
    check(panel.save_label() == "Save as Lua file", "button switches back to Save as Lua file")

    with tempfile.TemporaryDirectory() as tmp:
        captured: dict = {}
        lua_path = Path(tmp) / "MyPlaceableExtension.lua"
        xml_path = Path(tmp) / "snippets.xml"

        def fake_dialog(**kwargs):
            captured.update(kwargs)
            return str(captured["_answer"])

        original = panel_module.filedialog.asksaveasfilename
        panel_module.filedialog.asksaveasfilename = lambda **kw: fake_dialog(_answer=lua_path, **kw)
        panel.save_active()
        check(captured.get("defaultextension") == ".lua", "Lua save dialog uses the .lua extension")
        check(captured.get("filetypes", [("", "")])[0][0] == "Lua files", "Lua save dialog offers Lua files")
        check(captured.get("initialfile") == "MyPlaceableExtension.lua", "Lua save dialog suggests the file name")

        panel.select(TAB_XML)
        panel_module.filedialog.asksaveasfilename = lambda **kw: fake_dialog(_answer=xml_path, **kw)
        panel.save_active()
        check(captured.get("defaultextension") == ".xml", "XML save dialog uses the .xml extension")

        panel_module.filedialog.asksaveasfilename = lambda **_kw: ""
        panel.save_active()
        check("cancelled" in tab.status_label.cget("text").lower(), "cancelling the save dialog is handled")
        panel_module.filedialog.asksaveasfilename = original

        check(lua_path.is_file(), "the Lua file was written to disk")
        if lua_path.is_file():
            written = lua_path.read_text(encoding="utf-8")
            check(written == panel.document(TAB_LUA).text, "the saved Lua file equals the generated script")
            check("\r" not in written, "the saved Lua file uses LF line endings")
        check(xml_path.is_file(), "the XML snippet file was written to disk")
    panel.select(TAB_LUA)

    # ---- Reset ----------------------------------------------------------------
    tab._reset_form()
    pump(window, 10)
    check(panel.document(TAB_LUA) is None and panel.document(TAB_XML) is None, "Reset Form empties the output panel")
    check(tab.name_field.raw() == "" and tab.name_field._entry._placeholder_text_active, "Reset Form restores the name placeholder")
    check(tab.script_type_var.get() == SCRIPT_TYPE_OPTIONS[0] and tab.target_var.get() == TARGET_OBJECT_OPTIONS[0], "Reset Form restores the dropdowns")
    check(panel.save_label() == "Save as XML file", "Reset Form restores the generic save label")
    base.screenshot(window, "26_lua_generator_reset")

    # ---- Store Item --------------------------------------------------------
    tab.form_tabs.set(FORM_STORE)
    tab._on_form_tab()
    pump(window, 8)
    check(tab.generate_button.cget("text") == "Generate Store XML", "Store Item tab renames the generate button")
    tab._generate_store()
    check("Item Title is required" in tab.status_label.cget("text"), "store title is required")
    tab.title_field.set("Sample Trailer")
    tab.price_field.set("12500")
    tab.brand_field.set("LIZARD")
    tab.washable_var.set(True)
    tab._generate_store()
    pump(window, 8)
    store_doc = panel.document(TAB_STORE)
    check(store_doc is not None and "<storeData>" in store_doc.text, "store generation fills the Store XML tab")
    check(store_doc is not None and "<name>Sample Trailer</name>" in store_doc.text, "store XML contains the title")
    check(store_doc is not None and "<category>misc</category>" in store_doc.text, "store XML uses the schema default category")
    check(store_doc is not None and "<price>12500</price>" in store_doc.text, "store XML contains the price")
    check(store_doc is not None and "<washable />" in store_doc.text, "washable is written beside storeData")
    check(panel.active_tab() == TAB_STORE, "Store XML tab is selected")
    check(panel.save_label() == "Save as XML file", "store output saves as XML")
    panel.copy_active()
    check("Copied" in tab.status_label.cget("text"), "Copy to Clipboard works for store XML")
    base.screenshot(window, "27_store_item_generated")

    window.destroy()
    print("-" * 60)
    print("ALL CHECKS PASSED" if not base.failures else f"{len(base.failures)} CHECK(S) FAILED: {base.failures}")
    return 1 if base.failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
