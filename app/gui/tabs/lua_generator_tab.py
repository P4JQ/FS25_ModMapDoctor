"""Lua Generator tab: pick a script type, target and name, then generate a complete template."""

from __future__ import annotations

from tkinter import TclError

import customtkinter as ctk

from app.generators.store_item_generator import (
    STORE_BRAND_DEFAULT,
    STORE_CATEGORY_DEFAULT,
    STORE_PRICE_DEFAULT,
    StoreItemGenerator,
    StoreItemRequest,
)
from app.generators.lua_generator import (
    SCRIPT_TYPE_OPTIONS,
    TARGET_OBJECT_OPTIONS,
    GeneratedLuaScript,
    LuaGenerator,
    LuaScriptRequest,
)
from app.gui.widgets import LabeledCombo, LabeledEntry, OutputDocument, SectionCard, XmlOutputPanel

_MUTED = ("gray40", "gray60")
_ERROR_COLOR = "#E74C3C"
_OK_COLOR = "#2E9E5B"

TAB_LUA = "Lua Script"
TAB_XML = "XML Snippets"
TAB_STORE = "Store XML"
FORM_LUA = "Lua Script"
FORM_STORE = "Store Item"

# Shown in the output tabs before anything has been generated.
_EMPTY_MESSAGES = {
    TAB_LUA: (
        'Click "Generate Lua Script" to build the script here.\n'
        "\n"
        "Save it as a .lua file inside your mod, for example in a scripts folder.\n"
    ),
    TAB_XML: (
        "The modDesc.xml and vehicle / placeable XML snippets appear here after generating.\n"
        "\n"
        "They register the script so the game loads it.\n"
    ),
    TAB_STORE: (
        'Click "Generate Store XML" to build a <storeData> block here.\n'
        "\n"
        "Paste it inside the vehicle or placeable XML.\n"
    ),
}


class LuaGeneratorTab(ctk.CTkFrame):
    """Choose a script type, a target object and a name, then generate a Lua template."""

    def __init__(self, master: ctk.CTkBaseClass, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._generated: GeneratedLuaScript | None = None
        self._build()
        self._on_selection_changed()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        # Same 15 : 8 split as the TerraFarm and Map Helper tabs.
        self.grid_columnconfigure(0, weight=15, uniform="panes")
        self.grid_columnconfigure(1, weight=8, uniform="panes")
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 8))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="Lua Generator",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="* required  |  templates follow the vanilla FS25 script structures",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(16, 0))

        self._build_form_panel().grid(row=1, column=0, sticky="nsew", padx=(16, 6))

        self.output_panel = XmlOutputPanel(
            self,
            tab_names=(TAB_LUA, TAB_XML, TAB_STORE),
            empty_messages=_EMPTY_MESSAGES,
            on_status=self._set_status,
            title="Generated Lua",
            save_dialog_title="Save Lua Generator output",
            log_prefix="LuaGenerator",
        )
        self.output_panel.grid(row=1, column=1, sticky="nsew", padx=(6, 16))

        self._build_action_bar().grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 12)
        )

    def _build_form_panel(self) -> ctk.CTkScrollableFrame:
        panel = ctk.CTkScrollableFrame(self, fg_color="transparent")
        panel.grid_columnconfigure(0, weight=1)
        self.form_panel = panel

        self.form_tabs = ctk.CTkTabview(panel, height=640, command=self._on_form_tab)
        self.form_tabs.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.form_tabs.add(FORM_LUA)
        self.form_tabs.add(FORM_STORE)
        lua_page = self.form_tabs.tab(FORM_LUA)
        store_page = self.form_tabs.tab(FORM_STORE)
        lua_page.grid_columnconfigure(0, weight=1)
        store_page.grid_columnconfigure(0, weight=1)

        self._build_setup_card(lua_page).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_plan_card(lua_page).grid(row=1, column=0, sticky="ew")
        self._build_store_card(store_page).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_store_features_card(store_page).grid(row=1, column=0, sticky="ew")
        return panel

    def _build_store_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "Store Item")
        body = card.body
        body.grid_columnconfigure(0, weight=1, uniform="store")
        body.grid_columnconfigure(1, weight=1, uniform="store")

        self.title_field = LabeledEntry(body, "Item Title", placeholder="Sample Trailer")
        self.title_field.configure_field(enabled=True, required=True)
        self.title_field.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.brand_field = LabeledEntry(body, "Brand Name", placeholder=STORE_BRAND_DEFAULT)
        self.brand_field.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))

        self.price_field = LabeledEntry(
            body, "Retail Price", placeholder=STORE_PRICE_DEFAULT, kind="float"
        )
        self.price_field.grid(row=1, column=1, sticky="ew", pady=(0, 8))

        self.category_field = LabeledCombo(
            body,
            "Vehicle Category",
            (STORE_CATEGORY_DEFAULT,),
            default=STORE_CATEGORY_DEFAULT,
        )
        self.category_field.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.image_field = LabeledEntry(body, "Store Image", placeholder="store_icon.dds")
        self.image_field.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        ctk.CTkLabel(
            body,
            text=(
                "Category starts at misc, the default registered for storeData.category. "
                "storeCategories.xml is not in the local documentation, so type another "
                "category name if you already use one. Leave Brand, Price and Store Image "
                "empty to omit them."
            ),
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            anchor="w",
            justify="left",
            wraplength=460,
        ).grid(row=4, column=0, columnspan=2, sticky="ew")
        return card

    def _build_store_features_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "Functional Features")
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.washable_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="Washable",
            variable=self.washable_var,
            checkbox_width=20,
            checkbox_height=20,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.configuration_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="Component configurations",
            variable=self.configuration_var,
            command=self._on_configuration_toggled,
            checkbox_width=20,
            checkbox_height=20,
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        self.config_name_field = LabeledEntry(body, "Configuration Name", placeholder="design")
        self.config_name_field.configure_field(enabled=False, required=False, placeholder="design")
        self.config_name_field.grid(row=2, column=0, sticky="ew", pady=(0, 4))

        ctk.CTkLabel(
            body,
            text=(
                "Washable writes <washable /> beside storeData (vehicle.washable). "
                "Component configurations write storeData.bundleElements with the name you enter. "
                "allowChange stays at its schema default, false, so the attribute is omitted."
            ),
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            anchor="w",
            justify="left",
            wraplength=460,
        ).grid(row=3, column=0, sticky="ew")
        return card

    def _on_configuration_toggled(self) -> None:
        enabled = bool(self.configuration_var.get())
        self.config_name_field.configure_field(enabled=enabled, required=enabled, placeholder="design")

    def _on_form_tab(self) -> None:
        button = getattr(self, "generate_button", None)
        if button is None:
            return
        if self.form_tabs.get() == FORM_STORE:
            button.configure(text="Generate Store XML")
        else:
            button.configure(text="Generate Lua Script")

    # -- Card: Script Setup ---------------------------------------------

    def _build_setup_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "Script Setup")
        body = card.body
        body.grid_columnconfigure(0, weight=1, uniform="setup")
        body.grid_columnconfigure(1, weight=1, uniform="setup")

        self.script_type_var = ctk.StringVar(value=SCRIPT_TYPE_OPTIONS[0])
        self.target_var = ctk.StringVar(value=TARGET_OBJECT_OPTIONS[0])

        self._dropdown(
            body, "Script Type", self.script_type_var, SCRIPT_TYPE_OPTIONS, column=0
        )
        self._dropdown(
            body, "Target Object", self.target_var, TARGET_OBJECT_OPTIONS, column=1
        )

        self.name_field = LabeledEntry(body, "Script Name")
        self.name_field.configure_field(enabled=True, required=True, placeholder="e.g. MyVehicleSpec")
        self.name_field.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self.compat_label = ctk.CTkLabel(
            body,
            text="",
            font=ctk.CTkFont(size=12),
            anchor="nw",
            justify="left",
            wraplength=480,
            height=18,
        )
        self.compat_label.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        return card

    def _dropdown(
        self,
        body: ctk.CTkFrame,
        label: str,
        variable: ctk.StringVar,
        values: tuple[str, ...],
        *,
        column: int,
    ) -> ctk.CTkOptionMenu:
        padx = (0, 6) if column == 0 else (6, 0)
        ctk.CTkLabel(
            body, text=label, anchor="w", height=18, font=ctk.CTkFont(size=12)
        ).grid(row=0, column=column, sticky="ew", padx=padx, pady=(0, 2))
        menu = ctk.CTkOptionMenu(
            body,
            values=list(values),
            variable=variable,
            command=lambda _selected: self._on_selection_changed(),
            height=30,
            dynamic_resizing=False,
        )
        menu.grid(row=1, column=column, sticky="ew", padx=padx)
        return menu

    # -- Card: Planned Output -------------------------------------------

    def _build_plan_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "What Will Be Generated")
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.summary_label = self._plan_label(body, row=0)
        self.files_label = self._plan_label(body, row=1, top=8)
        self.reference_label = self._plan_label(body, row=2, top=8, muted=True)
        return card

    @staticmethod
    def _plan_label(
        body: ctk.CTkFrame, *, row: int, top: int = 0, muted: bool = False
    ) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            body,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED if muted else None,
            anchor="nw",
            justify="left",
            wraplength=480,
        )
        label.grid(row=row, column=0, sticky="ew", pady=(top, 0))
        return label

    # -- Bottom action bar ----------------------------------------------

    def _build_action_bar(self) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid_columnconfigure(2, weight=1)

        self.generate_button = ctk.CTkButton(
            bar,
            text="Generate Lua Script",
            width=220,
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_generate_clicked,
        )
        self.generate_button.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            bar,
            text="Reset Form",
            width=110,
            height=38,
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80"),
            command=self._reset_form,
        ).grid(row=0, column=1, padx=(10, 0), sticky="w")

        self.status_label = ctk.CTkLabel(
            bar,
            text="Ready.",
            anchor="w",
            justify="left",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            wraplength=640,
        )
        self.status_label.grid(row=0, column=2, sticky="ew", padx=(16, 0))
        return bar

    # ------------------------------------------------------------------
    # Behaviour
    # ------------------------------------------------------------------

    def current_request(self) -> LuaScriptRequest:
        """The current form content. Raises ValueError for unknown dropdown labels."""
        return LuaScriptRequest(
            script_type=LuaGenerator.parse_script_type(self.script_type_var.get()),
            target=LuaGenerator.parse_target(self.target_var.get()),
            name=self.name_field.raw(),
        )

    def _on_selection_changed(self) -> None:
        """Refresh the compatibility hint, the plan card and the name placeholder."""
        try:
            request = self.current_request()
        except ValueError as exc:
            self._set_status(f"Error: {exc}", error=True)
            return

        info = LuaGenerator.info(request.script_type)
        problem = LuaGenerator.compatibility_error(request.script_type, request.target)

        if problem is None:
            self.compat_label.configure(
                text=f"{request.script_type.value} for {request.target.value}: supported.",
                text_color=_OK_COLOR,
            )
        else:
            self.compat_label.configure(text=problem, text_color=_ERROR_COLOR)

        self.name_field.configure_field(enabled=True, required=True, placeholder=info.name_hint)
        self.summary_label.configure(text=info.summary)
        self.files_label.configure(text="Files: " + ", ".join(info.planned_files))
        self.reference_label.configure(text=f"Based on: {info.reference}.")
        print(f"[LuaGenerator] Selected {request.script_type.value} / {request.target.value}")

    def _on_generate_clicked(self) -> None:
        if self.form_tabs.get() == FORM_STORE:
            self._generate_store()
        else:
            self._generate()

    def _generate_store(self) -> None:
        self.title_field.clear_invalid()
        self.price_field.clear_invalid()
        self.config_name_field.clear_invalid()
        try:
            price = self.price_field.value()
            config_name = ""
            if self.configuration_var.get():
                self.config_name_field.configure_field(enabled=True, required=True, placeholder="design")
                config_name = self.config_name_field.value()
            result = StoreItemGenerator.generate(
                StoreItemRequest(
                    title=self.title_field.value(),
                    brand=self.brand_field.raw(),
                    price=price,
                    category=self.category_field.value(),
                    image=self.image_field.raw(),
                    washable=bool(self.washable_var.get()),
                    configuration_name=config_name,
                )
            )
        except ValueError as exc:
            self.output_panel.show({TAB_STORE: None})
            self._set_status(f"Error: {exc}", error=True)
            print(f"[StoreItem] Generate failed: {exc}")
            return

        self.output_panel.show({TAB_STORE: OutputDocument(result.xml_text, result.filename)})
        self.output_panel.select(TAB_STORE)
        self._set_status(f"Generated {result.filename}. Copy or save the Store XML tab.")
        print(f"[StoreItem] Generated {result.filename}")

    def _generate(self) -> None:
        self.name_field.clear_invalid()
        try:
            request = self.current_request()
            LuaGenerator.validate(request)
            result = LuaGenerator.generate(request)
        except ValueError as exc:
            self._generated = None
            self.output_panel.clear()
            if "Script Name" in str(exc):
                self.name_field.mark_invalid()
            self._set_status(f"Error: {exc}", error=True)
            print(f"[LuaGenerator] Generate failed: {exc}")
            return

        self._generated = result
        self.output_panel.show(
            {
                TAB_LUA: OutputDocument(result.lua_code, result.lua_filename),
                TAB_XML: OutputDocument(result.xml_snippet, result.xml_filename),
            }
        )
        self.output_panel.select(TAB_LUA)

        lines = result.lua_code.count("\n")
        self._set_status(
            f"Generated {result.lua_filename} ({lines} lines). Save it in your mod, then register "
            f"it with the XML Snippets tab."
        )
        print(f"[LuaGenerator] Generated {result.lua_filename} ({lines} lines)")

    def _reset_form(self) -> None:
        self.name_field.clear()
        self.script_type_var.set(SCRIPT_TYPE_OPTIONS[0])
        self.target_var.set(TARGET_OBJECT_OPTIONS[0])
        self.title_field.clear()
        self.brand_field.clear()
        self.price_field.clear()
        self.image_field.clear()
        self.category_field.reset()
        self.washable_var.set(False)
        self.configuration_var.set(False)
        self._on_configuration_toggled()
        self.config_name_field.clear()
        if self.form_tabs.get() != FORM_LUA:
            self.form_tabs.set(FORM_LUA)
        self._on_form_tab()
        self._generated = None
        self.output_panel.clear()
        self._on_selection_changed()
        self._set_status("Form reset.")

    def _set_status(self, message: str, *, error: bool = False) -> None:
        try:
            self.status_label.configure(
                text=message,
                text_color=_ERROR_COLOR if error else _MUTED,
            )
        except TclError:
            # The widget is being destroyed; nothing to update.
            pass
