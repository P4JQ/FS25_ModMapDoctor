"""Map Helper tab: wizard for TerraFarm map ground resources.

Builds the two files described in Documentation/docs/MAP_RESOURCES.md:

* ``mapGroundResources.xml`` (next to the map xml file)
* the ``<InfoLayer>`` snippet for the map .i3d
"""

from __future__ import annotations

from tkinter import TclError

import customtkinter as ctk

from app.generators.map_resources_generator import (
    DEFAULT_GROUP_NAME,
    DEFAULT_INFO_LAYER_NAME,
    DOCUMENTED_FILL_TYPES,
    EXAMPLE_LAYERS,
    GROUND_RESOURCES_FILENAME,
    INFO_LAYER_FILENAME,
    GroundLayer,
    InfoLayerSettings,
    MapResourcesGenerator,
    channels_needed,
    format_yield,
    value_capacity,
)
from app.gui.widgets import (
    LabeledCombo,
    LabeledEntry,
    OutputDocument,
    SectionCard,
    XmlOutputPanel,
)

_MUTED = ("gray40", "gray60")
_ERROR_COLOR = "#E74C3C"

TAB_GROUND_RESOURCES = "mapGroundResources.xml"
TAB_INFO_LAYER = "InfoLayer Snippet"

_EMPTY_MESSAGES = {
    TAB_GROUND_RESOURCES: (
        'Click "Generate Map Resources" to build mapGroundResources.xml here.\n'
        "\n"
        "Save it in the same folder as your map xml file.\n"
    ),
    TAB_INFO_LAYER: (
        "The <InfoLayer> snippet appears here after generating.\n"
        "\n"
        "It belongs in your map .i3d (not in map.xml).\n"
    ),
}


class MapHelperTab(ctk.CTkFrame):
    """Wizard: define ground layers and generate the map resource XML."""

    def __init__(self, master: ctk.CTkBaseClass, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._generator = MapResourcesGenerator()
        self._layers: dict[int, GroundLayer] = {}
        self._build()
        self._refresh_layer_list()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=15, uniform="panes")
        self.grid_columnconfigure(1, weight=8, uniform="panes")
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 8))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="Map Helper",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="* required  |  empty optional fields use the game default",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(16, 0))

        self._build_form_panel().grid(row=1, column=0, sticky="nsew", padx=(16, 6))

        self.output_panel = XmlOutputPanel(
            self,
            tab_names=(TAB_GROUND_RESOURCES, TAB_INFO_LAYER),
            empty_messages=_EMPTY_MESSAGES,
            on_status=self._set_status,
            save_dialog_title="Save map resources XML",
            log_prefix="MapHelper",
        )
        self.output_panel.grid(row=1, column=1, sticky="nsew", padx=(6, 16))

        self._build_action_bar().grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 12)
        )

    def _build_form_panel(self) -> ctk.CTkScrollableFrame:
        """Two columns, one card each: layers on the left, fill type & yield on the right."""
        panel = ctk.CTkScrollableFrame(self, fg_color="transparent")
        panel.grid_columnconfigure(0, weight=1, uniform="cards")
        panel.grid_columnconfigure(1, weight=1, uniform="cards")
        self.form_panel = panel

        # Separate column containers keep card heights independent.
        left = ctk.CTkFrame(panel, fg_color="transparent")
        left.grid(row=0, column=0, sticky="new", padx=(0, 6))
        right = ctk.CTkFrame(panel, fg_color="transparent")
        right.grid(row=0, column=1, sticky="new", padx=(6, 0))
        for column in (left, right):
            column.grid_columnconfigure(0, weight=1)

        self._build_ground_card(left).grid(row=0, column=0, sticky="ew")
        self._build_fruit_card(right).grid(row=0, column=0, sticky="ew")
        return panel

    @staticmethod
    def _subheading(parent: ctk.CTkBaseClass, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=_MUTED,
        )

    # -- Card 1: Ground & Paint Layers ----------------------------------

    def _build_ground_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "Ground & Paint Layers")
        body = card.body
        body.grid_columnconfigure(0, weight=1, uniform="ground")
        body.grid_columnconfigure(1, weight=1, uniform="ground")

        # -- Density map channels (the InfoLayer in the map .i3d)
        self._subheading(body, "Density Map Channels (InfoLayer)").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4)
        )

        self.info_layer_name = LabeledEntry(body, "InfoLayer Name", DEFAULT_INFO_LAYER_NAME)
        self.info_layer_name.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))

        self.group_name = LabeledEntry(body, "Group Name", DEFAULT_GROUP_NAME)
        self.group_name.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))

        self.num_channels = LabeledEntry(body, "numChannels", "auto", kind="int")
        self.num_channels.grid(row=2, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))

        self.first_channel = LabeledEntry(body, "firstChannel", "0", kind="uint")
        self.first_channel.grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))

        self.file_id = LabeledEntry(body, "fileId (optional)", "e.g. 12")
        self.file_id.grid(row=3, column=0, sticky="ew", padx=(0, 6), pady=(0, 4))

        self.capacity_label = ctk.CTkLabel(
            body,
            text="",
            anchor="sw",
            justify="left",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            wraplength=150,
        )
        self.capacity_label.grid(row=3, column=1, sticky="sw", padx=(6, 0), pady=(0, 4))
        for field in (self.num_channels, self.first_channel):
            field._entry.bind("<KeyRelease>", lambda _e: self._update_capacity(), add="+")

        # -- Paint layers and their IDs
        self._subheading(body, "Paint Layers & Layer IDs").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(10, 4)
        )

        self.layer_value = LabeledEntry(body, "Layer ID (value)", "0", kind="uint")
        self.layer_value.grid(row=5, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))

        self.option_name = LabeledEntry(body, "Option Name", "auto")
        self.option_name.grid(row=5, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))

        self.paint_layer = LabeledEntry(body, "paintLayer")
        self.paint_layer.configure_field(enabled=True, required=True, placeholder="e.g. rock")
        self.paint_layer.grid(row=6, column=0, sticky="ew", padx=(0, 6))

        self.paint_layer_discharge = LabeledEntry(
            body, "paintLayerDischarge", "same as paintLayer"
        )
        self.paint_layer_discharge.grid(row=6, column=1, sticky="ew", padx=(6, 0))
        return card

    # -- Card 2: Fruit & Yield Configurations ---------------------------

    def _build_fruit_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "Fruit & Yield Configurations")
        body = card.body
        body.grid_columnconfigure(0, weight=1, uniform="fruit")
        body.grid_columnconfigure(1, weight=1, uniform="fruit")

        self.fill_type = LabeledCombo(
            body,
            "fillType",
            values=DOCUMENTED_FILL_TYPES,
            default=DOCUMENTED_FILL_TYPES[0],
            required=True,
        )
        self.fill_type.grid(row=0, column=0, columnspan=2, sticky="ew")

        ctk.CTkLabel(
            body,
            text="Material produced when terraforming. Pick one or type any fillType "
            "name (case-sensitive).",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            anchor="nw",
            justify="left",
            wraplength=290,
            height=34,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 8))

        self.yield_entry = LabeledEntry(body, "yield (multiplier)", "1.0", kind="float")
        self.yield_entry.grid(row=2, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            body,
            text="Add / Update Layer",
            height=30,
            command=self._add_layer,
        ).grid(row=2, column=1, sticky="sew", padx=(6, 0))

        self.list_heading = self._subheading(body, "Configured Layers")
        self.list_heading.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 4))

        self.layer_list = ctk.CTkFrame(body, fg_color="transparent")
        self.layer_list.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.layer_list.grid_columnconfigure(0, weight=1)
        return card

    # -- Bottom action bar ----------------------------------------------

    def _build_action_bar(self) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid_columnconfigure(3, weight=1)

        ctk.CTkButton(
            bar,
            text="Generate Map Resources",
            width=220,
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._generate,
        ).grid(row=0, column=0, sticky="w")

        outline = {
            "height": 38,
            "fg_color": "transparent",
            "border_width": 1,
            "text_color": ("gray20", "gray80"),
        }
        ctk.CTkButton(bar, text="Reset Form", width=110, command=self._reset_form, **outline).grid(
            row=0, column=1, padx=(10, 0), sticky="w"
        )
        ctk.CTkButton(
            bar, text="Load Example", width=120, command=self._load_example, **outline
        ).grid(row=0, column=2, padx=(10, 0), sticky="w")

        self.status_label = ctk.CTkLabel(
            bar,
            text="Ready.",
            anchor="w",
            justify="left",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            wraplength=560,
        )
        self.status_label.grid(row=0, column=3, sticky="ew", padx=(16, 0))
        return bar

    # ------------------------------------------------------------------
    # Layer list
    # ------------------------------------------------------------------

    def _next_free_value(self) -> int:
        value = 0
        while value in self._layers:
            value += 1
        return value

    @staticmethod
    def _layer_summary(layer: GroundLayer) -> str:
        text = f"{layer.value}   {layer.fill_type}  |  {layer.paint_layer}"
        discharge = layer.paint_layer_discharge.strip()
        if discharge and discharge != layer.paint_layer:
            text += f" > {discharge}"
        if layer.yield_value is not None:
            text += f"  |  x{format_yield(layer.yield_value)}"
        return text

    def _refresh_layer_list(self) -> None:
        """Rebuild the list rows and everything that depends on the layer set."""
        for child in self.layer_list.winfo_children():
            child.destroy()

        count = len(self._layers)
        self.list_heading.configure(text=f"Configured Layers ({count})")

        if not self._layers:
            ctk.CTkLabel(
                self.layer_list,
                text="No layers yet. Layer 0 is required\n(fallback for unpainted areas).",
                anchor="w",
                justify="left",
                font=ctk.CTkFont(size=12),
                text_color=_MUTED,
            ).grid(row=0, column=0, sticky="w", pady=(2, 0))
        else:
            for row, value in enumerate(sorted(self._layers)):
                layer = self._layers[value]
                ctk.CTkButton(
                    self.layer_list,
                    text=self._layer_summary(layer),
                    anchor="w",
                    height=28,
                    fg_color=("gray85", "gray25"),
                    hover_color=("gray75", "gray35"),
                    text_color=("gray10", "gray90"),
                    font=ctk.CTkFont(size=12),
                    command=lambda v=value: self._load_layer(v),
                ).grid(row=row, column=0, sticky="ew", pady=(0, 4))
                ctk.CTkButton(
                    self.layer_list,
                    text="\u2715",
                    width=28,
                    height=28,
                    fg_color=("gray85", "gray25"),
                    hover_color="#C0392B",
                    text_color=("gray10", "gray90"),
                    command=lambda v=value: self._remove_layer(v),
                ).grid(row=row, column=1, sticky="e", padx=(4, 0), pady=(0, 4))

        # Suggest the next free ID as the placeholder of the Layer ID field.
        self.layer_value.configure_field(enabled=True, placeholder=str(self._next_free_value()))
        self._update_capacity()

    def _update_capacity(self) -> None:
        """Show how many layer IDs the current channel settings can hold."""
        try:
            first = int(self.first_channel.raw() or "0")
            total_text = self.num_channels.raw()
            total = int(total_text) if total_text else None
        except ValueError:
            self.capacity_label.configure(text="")
            return

        if total is None:
            if not self._layers:
                self.capacity_label.configure(text="Channels: auto")
                return
            group = channels_needed(max(self._layers))
        else:
            group = total - first
            if group < 1:
                self.capacity_label.configure(text="numChannels must exceed firstChannel")
                return
        self.capacity_label.configure(
            text=f"{group} bit(s): IDs 0-{value_capacity(group) - 1}"
        )

    def _load_layer(self, value: int) -> None:
        """Copy a configured layer back into the editor fields."""
        layer = self._layers[value]
        self._clear_invalid()
        self.layer_value.set(str(layer.value))
        self.option_name.set(layer.option_name)
        self.paint_layer.set(layer.paint_layer)
        self.paint_layer_discharge.set(layer.paint_layer_discharge)
        self.fill_type.set(layer.fill_type)
        self.yield_entry.set("" if layer.yield_value is None else format_yield(layer.yield_value))
        self._set_status(f"Editing layer {value}. Change fields and click Add / Update Layer.")

    def _remove_layer(self, value: int) -> None:
        self._layers.pop(value, None)
        self._refresh_layer_list()
        self._set_status(f"Removed layer {value}.")

    # ------------------------------------------------------------------
    # Behaviour
    # ------------------------------------------------------------------

    def _clear_invalid(self) -> None:
        for field in (
            self.info_layer_name,
            self.group_name,
            self.num_channels,
            self.first_channel,
            self.file_id,
            self.layer_value,
            self.option_name,
            self.paint_layer,
            self.paint_layer_discharge,
            self.yield_entry,
        ):
            field.clear_invalid()
        self.fill_type.clear_invalid()

    def _read_layer_editor(self) -> GroundLayer:
        """Validate the editor fields and build a layer (raises ValueError)."""
        self._clear_invalid()
        value_text = self.layer_value.value()
        value = int(value_text) if value_text else self._next_free_value()
        paint_layer = self.paint_layer.value()
        fill_type = self.fill_type.value()
        discharge = self.paint_layer_discharge.value()
        yield_text = self.yield_entry.value()
        return GroundLayer(
            value=value,
            fill_type=fill_type,
            paint_layer=paint_layer,
            paint_layer_discharge=discharge,
            yield_value=float(yield_text) if yield_text else None,
            option_name=self.option_name.value(),
        )

    def _add_layer(self) -> None:
        try:
            layer = self._read_layer_editor()
        except ValueError as exc:
            self._set_status(f"Error: {exc}", error=True)
            print(f"[MapHelper] Add layer failed: {exc}")
            return

        updated = layer.value in self._layers
        self._layers[layer.value] = layer

        # Keep fillType and yield (layers often share them); clear the rest.
        self.layer_value.clear()
        self.option_name.clear()
        self.paint_layer.clear()
        self.paint_layer_discharge.clear()
        self._refresh_layer_list()

        verb = "Updated" if updated else "Added"
        self._set_status(f"{verb} layer {layer.value} ({layer.fill_type} / {layer.paint_layer}).")
        print(f"[MapHelper] {verb} layer {layer.value}")

    def _collect_settings(self) -> InfoLayerSettings:
        num_text = self.num_channels.value()
        return InfoLayerSettings(
            name=self.info_layer_name.value() or DEFAULT_INFO_LAYER_NAME,
            group_name=self.group_name.value() or DEFAULT_GROUP_NAME,
            file_id=self.file_id.value(),
            num_channels=int(num_text) if num_text else None,
            first_channel=int(self.first_channel.value() or "0"),
        )

    def _generate(self) -> None:
        self._clear_invalid()
        try:
            settings = self._collect_settings()
            result = self._generator.generate(list(self._layers.values()), settings)
        except ValueError as exc:
            self.output_panel.clear()
            self._set_status(f"Error: {exc}", error=True)
            print(f"[MapHelper] Generate failed: {exc}")
            return

        self.output_panel.show(
            {
                TAB_GROUND_RESOURCES: OutputDocument(
                    result.ground_resources_xml, result.ground_resources_filename
                ),
                TAB_INFO_LAYER: OutputDocument(result.info_layer_xml, result.info_layer_filename),
            }
        )
        self.output_panel.select(TAB_GROUND_RESOURCES)

        message = (
            f"Generated {len(self._layers)} layer(s) using {result.total_channels} channel(s). "
            f"Save {GROUND_RESOURCES_FILENAME} next to your map xml; "
            f"put the InfoLayer in your map .i3d."
        )
        if result.warnings:
            message += f"  Warning: {result.warnings[0]}"
            if len(result.warnings) > 1:
                message += f" (+{len(result.warnings) - 1} more)"
        self._set_status(message)
        for warning in result.warnings:
            print(f"[MapHelper] Warning: {warning}")
        print(
            f"[MapHelper] Generated {len(self._layers)} layers, "
            f"{result.total_channels} channels ({INFO_LAYER_FILENAME})"
        )

    def _load_example(self) -> None:
        """Fill the layer list with the example from MAP_RESOURCES.md."""
        self._layers = {layer.value: layer for layer in EXAMPLE_LAYERS}
        self._refresh_layer_list()
        self._set_status(
            "Loaded the example layers from MAP_RESOURCES.md. Click Generate Map Resources."
        )

    def _reset_form(self) -> None:
        for field in (
            self.info_layer_name,
            self.group_name,
            self.num_channels,
            self.first_channel,
            self.file_id,
            self.layer_value,
            self.option_name,
            self.paint_layer,
            self.paint_layer_discharge,
            self.yield_entry,
        ):
            field.clear()
        self.fill_type.reset()
        self._layers.clear()
        self._refresh_layer_list()
        self.output_panel.clear()
        self._set_status("Form reset.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, message: str, *, error: bool = False) -> None:
        try:
            self.status_label.configure(
                text=message,
                text_color=_ERROR_COLOR if error else _MUTED,
            )
        except TclError:
            # The widget is being destroyed; nothing to update.
            pass
