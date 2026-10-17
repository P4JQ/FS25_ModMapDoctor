"""TerraFarm Generator tab: visual wizard for TerraFarm machine XML."""

from __future__ import annotations

from dataclasses import dataclass
from tkinter import TclError

import customtkinter as ctk

from app.generators.terrafarm_generator import (
    INPUT_MODES,
    MACHINE_TYPE_DESCRIPTIONS,
    MACHINE_TYPE_OPTIONS,
    GeneratedFiles,
    MachineConfigInput,
    TerraFarmGenerator,
)
from app.gui.widgets import (
    LabeledEntry,
    OutputDocument,
    SectionCard,
    UnavailableDocument,
    Vector3Field,
    XmlOutputPanel,
)

_MUTED = ("gray40", "gray60")
_ERROR_COLOR = "#E74C3C"

TAB_MACHINE = "Machine File"
TAB_REGISTRATION = "machineConfigurations.xml"

# Shown in the output tabs before anything has been generated.
_EMPTY_MESSAGES = {
    TAB_MACHINE: 'Click "Generate TerraFarm XML" to build the machine file here.\n',
    TAB_REGISTRATION: "The machineConfigurations.xml registration appears here after generating.\n",
}

# Shown in the registration tab when the "Also generate ..." option is off.
_REGISTRATION_OFF = UnavailableDocument(
    box_text=(
        "Registration is turned off.\n"
        'Enable "Also generate machineConfigurations.xml" to generate it.\n'
    ),
    status="Registration file was not generated (the option is turned off).",
)


@dataclass(frozen=True, slots=True)
class FieldRule:
    """How one input field behaves for a given machine type."""

    enabled: bool = True
    required: bool = False
    placeholder: str = ""


def _rule(placeholder: str, *, enabled: bool = True, required: bool = False) -> FieldRule:
    return FieldRule(enabled=enabled, required=required, placeholder=placeholder)


# Which fields apply to which machine type, based on the MACHINE_*.md tables.
# Placeholders show the documented default (or a typical value when required).
_FIELD_KEYS = (
    "fill_unit",
    "shovel_node",
    "leveler_node",
    "discharge_node",
    "raycast",
    "reference_node",
    "width",
    "density",
)

_PROFILES: dict[str, dict[str, FieldRule]] = {
    "shovel": {
        "fill_unit": _rule("auto"),
        "shovel_node": _rule("1"),
        "leveler_node": _rule("1"),
        "discharge_node": _rule("auto"),
        "raycast": _rule("0.4"),
        "reference_node": _rule("auto"),
        "width": _rule("auto"),
        "density": _rule("0.75"),
    },
    "excavatorShovel": {
        "fill_unit": _rule("auto"),
        "shovel_node": _rule("1"),
        "leveler_node": _rule("1"),
        "discharge_node": _rule("auto"),
        "raycast": _rule("0.4"),
        "reference_node": _rule("auto"),
        "width": _rule("auto"),
        "density": _rule("0.75"),
    },
    "leveler": {
        "fill_unit": _rule("auto"),
        "shovel_node": _rule("", enabled=False),
        "leveler_node": _rule("1"),
        "discharge_node": _rule("", enabled=False),
        "raycast": _rule("", enabled=False),
        "reference_node": _rule("auto"),
        "width": _rule("auto"),
        "density": _rule("0.75"),
    },
    "trencher": {
        "fill_unit": _rule("e.g. 2", required=True),
        "shovel_node": _rule("", enabled=False),
        "leveler_node": _rule("", enabled=False),
        "discharge_node": _rule("", enabled=False),
        "raycast": _rule("", enabled=False),
        "reference_node": _rule("e.g. posNodeRef", required=True),
        "width": _rule("e.g. 3.5", required=True),
        "density": _rule("0.75"),
    },
    "compactor": {
        "fill_unit": _rule("", enabled=False),
        "shovel_node": _rule("", enabled=False),
        "leveler_node": _rule("", enabled=False),
        "discharge_node": _rule("", enabled=False),
        "raycast": _rule("", enabled=False),
        "reference_node": _rule("e.g. posNodeRef", required=True),
        "width": _rule("e.g. 3", required=True),
        "density": _rule("0.75"),
    },
}

# Machine types that expose an outputOffset in their <workArea> table.
_OUTPUT_OFFSET_TYPES = frozenset({"shovel", "excavatorShovel"})

# Fields that live inside <workArea> and are disabled when it is excluded.
_WORK_AREA_KEYS = frozenset({"reference_node", "width", "density"})


class TerraFarmTab(ctk.CTkFrame):
    """Wizard: choose machine type, modes and indices, then generate TerraFarm XML."""

    def __init__(self, master: ctk.CTkBaseClass, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._generator = TerraFarmGenerator()
        self._type_label_to_id = dict(MACHINE_TYPE_OPTIONS)
        self._mode_vars: dict[str, ctk.BooleanVar] = {}
        self._fields: dict[str, LabeledEntry] = {}
        self._generated: GeneratedFiles | None = None
        self._build()
        self._on_type_changed(self.type_var.get())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=15, uniform="panes")
        self.grid_columnconfigure(1, weight=8, uniform="panes")
        self.grid_rowconfigure(1, weight=1)

        # Header: title on the left, hint on the right, in separate grid cells.
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 8))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="TerraFarm Generator",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="* required for the selected type  |  empty optional fields use the game default",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(16, 0))

        self._build_form_panel().grid(row=1, column=0, sticky="nsew", padx=(16, 6))
        self.output_panel = XmlOutputPanel(
            self,
            tab_names=(TAB_MACHINE, TAB_REGISTRATION),
            empty_messages=_EMPTY_MESSAGES,
            on_status=self._set_status,
            save_dialog_title="Save TerraFarm XML",
            log_prefix="TerraFarm",
        )
        self.output_panel.grid(row=1, column=1, sticky="nsew", padx=(6, 16))
        self._build_action_bar().grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 12)
        )

    def _build_form_panel(self) -> ctk.CTkScrollableFrame:
        """Two balanced columns of cards.

        Left:  Machine & Modes, Node Indices
        Right: File Paths, Work Area
        """
        panel = ctk.CTkScrollableFrame(self, fg_color="transparent")
        panel.grid_columnconfigure(0, weight=1, uniform="cards")
        panel.grid_columnconfigure(1, weight=1, uniform="cards")
        self.form_panel = panel

        # Each column is its own container so card heights never share grid rows
        # (shared rows would stretch every row to the taller card of the pair).
        left = ctk.CTkFrame(panel, fg_color="transparent")
        left.grid(row=0, column=0, sticky="new", padx=(0, 6))
        right = ctk.CTkFrame(panel, fg_color="transparent")
        right.grid(row=0, column=1, sticky="new", padx=(6, 0))
        for column in (left, right):
            column.grid_columnconfigure(0, weight=1)

        self._build_machine_card(left).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_nodes_card(left).grid(row=1, column=0, sticky="ew")
        self._build_paths_card(right).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_work_area_card(right).grid(row=1, column=0, sticky="ew")
        return panel

    # -- Card: Machine & Modes ------------------------------------------

    def _build_machine_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "Machine & Modes")
        body = card.body
        body.grid_columnconfigure(0, weight=1, uniform="modes")
        body.grid_columnconfigure(1, weight=1, uniform="modes")

        ctk.CTkLabel(
            body, text="Machine Type", anchor="w", height=18, font=ctk.CTkFont(size=12)
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        self.type_var = ctk.StringVar(value=MACHINE_TYPE_OPTIONS[0][0])
        ctk.CTkOptionMenu(
            body,
            values=[label for label, _ in MACHINE_TYPE_OPTIONS],
            variable=self.type_var,
            command=self._on_type_changed,
            height=30,
            dynamic_resizing=False,
        ).grid(row=1, column=0, columnspan=2, sticky="ew")

        self.type_description = ctk.CTkLabel(
            body,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED,
            anchor="nw",
            justify="left",
            wraplength=290,
            height=34,
        )
        self.type_description.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 8))

        ctk.CTkLabel(
            body, text="Input Modes", anchor="w", height=18, font=ctk.CTkFont(size=12)
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        for index, mode in enumerate(INPUT_MODES):
            var = ctk.BooleanVar(value=True)
            self._mode_vars[mode] = var
            row, column = divmod(index, 2)
            ctk.CTkCheckBox(body, text=mode, variable=var).grid(
                row=4 + row, column=column, sticky="w", pady=(0, 6)
            )

        ctk.CTkLabel(
            body, text="Activation Requirements", anchor="w", height=18, font=ctk.CTkFont(size=12)
        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        self.require_turned_on_var = ctk.BooleanVar(value=True)
        self.require_powered_on_var = ctk.BooleanVar(value=True)
        flags = ctk.CTkFrame(body, fg_color="transparent")
        flags.grid(row=7, column=0, columnspan=2, sticky="w")
        for column, (text, var) in enumerate(
            (
                ("requireTurnedOn", self.require_turned_on_var),
                ("requirePoweredOn", self.require_powered_on_var),
            )
        ):
            ctk.CTkCheckBox(
                flags,
                text=text,
                variable=var,
                checkbox_width=20,
                checkbox_height=20,
                font=ctk.CTkFont(size=12),
            ).grid(row=0, column=column, padx=(0, 14), sticky="w")
        return card

    # -- Card: File Paths -----------------------------------------------

    def _build_paths_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "File Paths")
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.vehicle_path = LabeledEntry(
            body, "Vehicle Path", "FS25_MyMod/vehicles/myMachine.xml"
        )
        self.vehicle_path.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.machine_file_path = LabeledEntry(
            body, "Machine File Path", "xml/machines/myMachine.xml"
        )
        self.machine_file_path.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self.include_registration_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            body,
            text="Also generate machineConfigurations.xml",
            variable=self.include_registration_var,
            checkbox_width=20,
            checkbox_height=20,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, sticky="w")
        return card

    # -- Card: Node Indices ---------------------------------------------

    def _build_nodes_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "Node Indices")
        body = card.body
        body.grid_columnconfigure(0, weight=1, uniform="nodes")
        body.grid_columnconfigure(1, weight=1, uniform="nodes")

        specs: list[tuple[str, str, str]] = [
            ("fill_unit", "fillUnitIndex", "int"),
            ("shovel_node", "shovelNodeIndex", "int"),
            ("leveler_node", "levelerNodeIndex", "int"),
            ("discharge_node", "dischargeNodeIndex", "int"),
            ("raycast", "raycastDistance", "float"),
        ]
        for position, (key, label, kind) in enumerate(specs):
            field = LabeledEntry(body, label, kind=kind)  # type: ignore[arg-type]
            row, column = divmod(position, 2)
            field.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0, 6) if column == 0 else (6, 0),
                pady=(0, 8 if row < 2 else 0),
            )
            self._fields[key] = field
        return card

    # -- Card: Work Area ------------------------------------------------

    def _build_work_area_card(self, parent: ctk.CTkBaseClass) -> SectionCard:
        card = SectionCard(parent, "Work Area")

        # The include toggle lives on the title row to save vertical space.
        self.include_work_area_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            card.header,
            text="Include <workArea>",
            variable=self.include_work_area_var,
            command=self._refresh_field_states,
            checkbox_width=20,
            checkbox_height=20,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=1, sticky="e")

        body = card.body
        body.grid_columnconfigure(0, weight=1, uniform="area")
        body.grid_columnconfigure(1, weight=1, uniform="area")

        self._fields["reference_node"] = LabeledEntry(body, "referenceNode")
        self._fields["reference_node"].grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        self._fields["width"] = LabeledEntry(body, "width", kind="float")
        self._fields["width"].grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(0, 10))

        self._fields["density"] = LabeledEntry(body, "density", kind="float")
        self._fields["density"].grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(0, 10))

        # Vectors share one X / Y / Z header so each row stays compact.
        Vector3Field.build_header(body).grid(row=2, column=0, columnspan=2, sticky="ew")

        self.offset_field = Vector3Field(body, "offset")
        self.offset_field.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.rotation_field = Vector3Field(body, "rotation (\u00b0)")
        self.rotation_field.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.output_offset_field = Vector3Field(body, "outputOffset")
        self.output_offset_field.grid(row=5, column=0, columnspan=2, sticky="ew")
        return card

    # -- Bottom action bar ----------------------------------------------

    def _build_action_bar(self) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid_columnconfigure(2, weight=1)

        ctk.CTkButton(
            bar,
            text="Generate TerraFarm XML",
            width=220,
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._generate,
        ).grid(row=0, column=0, sticky="w")

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

    def _current_machine_type(self) -> str:
        return self._type_label_to_id.get(self.type_var.get(), "shovel")

    def _on_type_changed(self, _selected: str) -> None:
        machine_type = self._current_machine_type()
        defaults = set(self._generator.default_modes_for(machine_type))
        for mode, var in self._mode_vars.items():
            var.set(mode in defaults)

        self.type_description.configure(text=MACHINE_TYPE_DESCRIPTIONS.get(machine_type, ""))
        self._refresh_field_states()
        self._set_status(f"Machine type: {machine_type}. Fill in the fields, then generate.")
        print(f"[TerraFarm] Machine type selected: {machine_type}")

    def _refresh_field_states(self) -> None:
        """Enable, require and re-placeholder fields for the current type."""
        machine_type = self._current_machine_type()
        profile = _PROFILES[machine_type]
        work_area_on = self.include_work_area_var.get()

        for key in _FIELD_KEYS:
            rule = profile[key]
            in_work_area = key in _WORK_AREA_KEYS
            enabled = rule.enabled and (work_area_on or not in_work_area)
            self._fields[key].configure_field(
                enabled=enabled,
                required=rule.required and enabled,
                placeholder=rule.placeholder,
            )

        self.offset_field.configure_field(enabled=work_area_on)
        self.rotation_field.configure_field(enabled=work_area_on)
        self.output_offset_field.configure_field(
            enabled=work_area_on and machine_type in _OUTPUT_OFFSET_TYPES
        )

    def _collect_config(self) -> MachineConfigInput:
        """Read and validate every field. Raises ValueError with a clear message."""
        for field in self._fields.values():
            field.clear_invalid()
        for vector in (self.offset_field, self.rotation_field, self.output_offset_field):
            vector.clear_invalid()

        modes = [mode for mode, var in self._mode_vars.items() if var.get()]
        include_registration = self.include_registration_var.get()
        vehicle_path = self.vehicle_path.value()
        machine_file = self.machine_file_path.value()
        if include_registration:
            if not vehicle_path:
                self.vehicle_path.mark_invalid()
                raise ValueError("Vehicle Path is required for machineConfigurations.xml.")
            if not machine_file:
                self.machine_file_path.mark_invalid()
                raise ValueError("Machine File Path is required for machineConfigurations.xml.")

        fields = self._fields
        return MachineConfigInput(
            machine_type=self._current_machine_type(),
            modes=modes,
            vehicle_path=vehicle_path,
            machine_file_path=machine_file or "machine.xml",
            require_turned_on=self.require_turned_on_var.get(),
            require_powered_on=self.require_powered_on_var.get(),
            fill_unit_index=fields["fill_unit"].value(),
            shovel_node_index=fields["shovel_node"].value(),
            leveler_node_index=fields["leveler_node"].value(),
            discharge_node_index=fields["discharge_node"].value(),
            raycast_distance=fields["raycast"].value(),
            reference_node=fields["reference_node"].value(),
            work_width=fields["width"].value(),
            work_density=fields["density"].value(),
            offset=self.offset_field.value(),
            rotation=self.rotation_field.value(),
            output_offset=self.output_offset_field.value(),
            include_work_area=self.include_work_area_var.get(),
            include_registration=include_registration,
        )

    def _generate(self) -> None:
        try:
            config = self._collect_config()
            files = self._generator.generate_files(config)
        except ValueError as exc:
            self._generated = None
            self.output_panel.clear()
            self._set_status(f"Error: {exc}", error=True)
            print(f"[TerraFarm] Generate failed: {exc}")
            return

        self._generated = files
        registration: OutputDocument | UnavailableDocument = (
            OutputDocument(files.registration_xml, files.registration_filename)
            if files.registration_xml is not None
            else _REGISTRATION_OFF
        )
        self.output_panel.show(
            {
                TAB_MACHINE: OutputDocument(files.machine_xml, files.machine_filename),
                TAB_REGISTRATION: registration,
            }
        )
        self.output_panel.select(TAB_MACHINE)
        self._set_status(
            f"Generated {config.machine_type} config with modes: {' '.join(config.modes)}."
        )
        print(f"[TerraFarm] Generated XML for type={config.machine_type} modes={config.modes}")

    def _reset_form(self) -> None:
        for field in self._fields.values():
            field.clear()
        for vector in (self.offset_field, self.rotation_field, self.output_offset_field):
            vector.clear()
        self.vehicle_path.clear()
        self.machine_file_path.clear()
        self.require_turned_on_var.set(True)
        self.require_powered_on_var.set(True)
        self.include_registration_var.set(True)
        self.include_work_area_var.set(True)
        self._generated = None
        self._on_type_changed(self.type_var.get())
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
