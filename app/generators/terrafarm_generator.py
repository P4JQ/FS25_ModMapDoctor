"""Generate TerraFarm machine XML from documented MACHINE_* schemas.

Source of truth: Documentation/docs/MACHINE_*.md and INDEX.md
(machineConfigurations.xml + vehicle.machine blocks).

Output is returned as two standalone, well-formed XML documents so each can
be saved to disk as-is:
    * the machine file (``<vehicle><machine .../></vehicle>``)
    * the ``machineConfigurations.xml`` registration file
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from xml.sax.saxutils import quoteattr

# Display label -> TerraFarm machine type attribute value
MACHINE_TYPE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Shovel (wheel loader / bucket)", "shovel"),
    ("Leveler (bulldozer blade / grader)", "leveler"),
    ("Trencher", "trencher"),
    ("Excavator", "excavatorShovel"),
    ("Compactor (roller)", "compactor"),
)

# Short descriptions taken from INDEX.md / MACHINE_*.md
MACHINE_TYPE_DESCRIPTIONS: dict[str, str] = {
    "shovel": "Wheel loaders, generic shovels and attachable buckets.",
    "leveler": "Bulldozers, bulldozer blades, graders and similar levelers.",
    "trencher": "Trenchers and similar equipment with a fillUnit to store material.",
    "excavatorShovel": "Excavators and excavator shovels (stationary, no driving direction).",
    "compactor": "Ground compactors and generic equipment without material handling.",
}

INPUT_MODES: tuple[str, ...] = ("FLATTEN", "SMOOTH", "LOWER", "PAINT")

REGISTRATION_FILENAME = "machineConfigurations.xml"

# Default mode order from docs examples (per type)
_DEFAULT_MODES: dict[str, tuple[str, ...]] = {
    "shovel": ("FLATTEN", "SMOOTH", "LOWER", "PAINT"),
    "leveler": ("FLATTEN", "SMOOTH", "PAINT"),
    "trencher": ("LOWER", "FLATTEN", "SMOOTH", "PAINT"),
    "excavatorShovel": ("FLATTEN", "SMOOTH", "LOWER", "PAINT"),
    "compactor": ("FLATTEN", "SMOOTH", "PAINT"),
}

_PREREQUISITES: dict[str, str] = {
    "shovel": "fillUnit (required), shovel (required), dischargeable / leveler (optional)",
    "leveler": "leveler (required), fillUnit (required)",
    "trencher": "fillUnit (required), dischargeable (optional)",
    "excavatorShovel": "fillUnit (required), shovel (required), dischargeable / leveler (optional)",
    "compactor": "none",
}

_XML_DECLARATION = '<?xml version="1.0" encoding="utf-8" standalone="no" ?>'


@dataclass(slots=True)
class MachineConfigInput:
    """User-facing wizard values for one TerraFarm machine config."""

    machine_type: str
    modes: list[str] = field(default_factory=list)

    # Paths for machineConfigurations.xml registration
    vehicle_path: str = "FS25_MyMod/vehicles/myMachine/myMachine.xml"
    machine_file_path: str = "xml/machines/myMachine.xml"

    require_turned_on: bool = True
    require_powered_on: bool = True

    # Node / unit indices (empty string = omit attribute, game default applies)
    fill_unit_index: str = ""
    shovel_node_index: str = ""
    leveler_node_index: str = ""
    discharge_node_index: str = ""
    raycast_distance: str = ""

    # Work area (empty string = omit attribute, game default applies)
    reference_node: str = ""
    work_width: str = ""
    work_density: str = ""
    offset: str = ""
    rotation: str = ""
    output_offset: str = ""

    include_work_area: bool = True
    include_registration: bool = True


@dataclass(slots=True, frozen=True)
class GeneratedFiles:
    """Result of one generation run: two standalone XML documents."""

    machine_xml: str
    machine_filename: str
    registration_xml: str | None
    registration_filename: str = REGISTRATION_FILENAME

    def combined_text(self) -> str:
        """Human-readable preview with both documents (not a valid single XML file)."""
        parts = [f"<!-- ===== {self.machine_filename} ===== -->", self.machine_xml]
        if self.registration_xml is not None:
            parts += ["", f"<!-- ===== {self.registration_filename} ===== -->", self.registration_xml]
        return "\n".join(parts)


class TerraFarmGenerator:
    """Build formatted TerraFarm XML documents from wizard input."""

    def generate_files(self, config: MachineConfigInput) -> GeneratedFiles:
        """Validate input and build the machine file and registration file."""
        machine_type = config.machine_type.strip()
        if machine_type not in {t for _, t in MACHINE_TYPE_OPTIONS}:
            raise ValueError(f"Unsupported machine type: {machine_type}")

        modes = self._normalize_modes(config.modes, machine_type)
        if not modes:
            raise ValueError("Select at least one input mode (FLATTEN / SMOOTH / LOWER / PAINT).")

        self._validate_required(config, machine_type)

        machine_xml = self._build_machine_file(config, machine_type, modes)
        registration_xml = (
            self._build_registration_file(config) if config.include_registration else None
        )
        machine_name = PurePosixPath(config.machine_file_path.replace("\\", "/")).name
        return GeneratedFiles(
            machine_xml=machine_xml,
            machine_filename=machine_name or "machine.xml",
            registration_xml=registration_xml,
        )

    def generate(self, config: MachineConfigInput) -> str:
        """Return a combined preview string (kept for CLI / backwards compatibility)."""
        return self.generate_files(config).combined_text()

    def default_modes_for(self, machine_type: str) -> list[str]:
        return list(_DEFAULT_MODES.get(machine_type, INPUT_MODES))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _normalize_modes(self, modes: list[str], machine_type: str) -> list[str]:
        selected = {m.strip().upper() for m in modes if m.strip()}
        unknown = selected - set(INPUT_MODES)
        if unknown:
            raise ValueError(f"Unknown input mode(s): {', '.join(sorted(unknown))}")

        # Preserve documented order for the machine type, then any extras.
        ordered = [m for m in _DEFAULT_MODES.get(machine_type, INPUT_MODES) if m in selected]
        for mode in INPUT_MODES:
            if mode in selected and mode not in ordered:
                ordered.append(mode)
        return ordered

    def _validate_required(self, config: MachineConfigInput, machine_type: str) -> None:
        if machine_type == "trencher" and not config.fill_unit_index.strip():
            raise ValueError("Trencher requires fillUnitIndex (see MACHINE_TRENCHER.md).")

        if machine_type in {"trencher", "compactor"} and config.include_work_area:
            label = "Trencher" if machine_type == "trencher" else "Compactor"
            if not config.reference_node.strip():
                raise ValueError(f"{label} workArea requires referenceNode.")
            if not config.work_width.strip():
                raise ValueError(f"{label} workArea requires width.")

        if config.include_registration:
            if not config.vehicle_path.strip():
                raise ValueError("Vehicle path is required for machineConfigurations.xml.")
            if not config.machine_file_path.strip():
                raise ValueError("Machine file path is required for machineConfigurations.xml.")

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _build_registration_file(self, config: MachineConfigInput) -> str:
        vehicle = quoteattr(config.vehicle_path.strip().replace("\\", "/"))
        file_path = quoteattr(config.machine_file_path.strip().replace("\\", "/"))
        return "\n".join(
            [
                _XML_DECLARATION,
                "<!-- Save as machineConfigurations.xml in the mod root or in xml/ (case-sensitive). -->",
                "<!-- Add one <configuration> entry per vehicle. -->",
                "<configurations>",
                "    <configuration",
                f"        vehicle={vehicle}",
                f"        file={file_path} />",
                "</configurations>",
                "",
            ]
        )

    def _build_machine_file(
        self,
        config: MachineConfigInput,
        machine_type: str,
        modes: list[str],
    ) -> str:
        indent = "    "
        attrs = self._machine_attributes(config, machine_type)
        lines = [
            _XML_DECLARATION,
            "<!-- TerraFarm machine config generated by FS25 Mod & Map Doctor. -->",
            f"<!-- Machine type: {machine_type} -->",
            f"<!-- Prerequisites: {_PREREQUISITES[machine_type]} -->",
            "<!-- When used as a vehicle type, add FS25_0_TerraFarm.machine as the LAST specialization. -->",
            "<vehicle>",
            f"{indent}<machine {self._format_attributes([('type', machine_type), *attrs])}>",
            f"{indent * 2}<input modes={quoteattr(' '.join(modes))} />",
        ]

        if config.include_work_area:
            work_attrs = self._work_area_attributes(config, machine_type)
            if work_attrs:
                lines.append(f"{indent * 2}<workArea {self._format_attributes(work_attrs)} />")

        lines.append(f"{indent}</machine>")
        lines.append("</vehicle>")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_attributes(attrs: list[tuple[str, str]]) -> str:
        return " ".join(f"{key}={quoteattr(value)}" for key, value in attrs)

    def _machine_attributes(
        self,
        config: MachineConfigInput,
        machine_type: str,
    ) -> list[tuple[str, str]]:
        attrs: list[tuple[str, str]] = [
            ("requireTurnedOn", "true" if config.require_turned_on else "false"),
            ("requirePoweredOn", "true" if config.require_powered_on else "false"),
        ]

        if config.fill_unit_index.strip() and machine_type != "compactor":
            attrs.append(("fillUnitIndex", config.fill_unit_index.strip()))

        if machine_type in {"shovel", "excavatorShovel"}:
            if config.shovel_node_index.strip():
                attrs.append(("shovelNodeIndex", config.shovel_node_index.strip()))
            if config.leveler_node_index.strip():
                attrs.append(("levelerNodeIndex", config.leveler_node_index.strip()))
            if config.discharge_node_index.strip():
                attrs.append(("dischargeNodeIndex", config.discharge_node_index.strip()))
            # Docs: shovel has raycastDistance on <machine>, excavator on <workArea>.
            if machine_type == "shovel" and config.raycast_distance.strip():
                attrs.append(("raycastDistance", config.raycast_distance.strip()))

        if machine_type == "leveler" and config.leveler_node_index.strip():
            attrs.append(("levelerNodeIndex", config.leveler_node_index.strip()))

        return attrs

    def _work_area_attributes(
        self,
        config: MachineConfigInput,
        machine_type: str,
    ) -> list[tuple[str, str]]:
        attrs: list[tuple[str, str]] = []

        if config.reference_node.strip():
            attrs.append(("referenceNode", config.reference_node.strip()))
        if config.work_width.strip():
            attrs.append(("width", config.work_width.strip()))
        if config.work_density.strip():
            attrs.append(("density", config.work_density.strip()))
        if config.offset.strip():
            attrs.append(("offset", config.offset.strip()))
        if config.rotation.strip():
            attrs.append(("rotation", config.rotation.strip()))

        if machine_type in {"shovel", "excavatorShovel"} and config.output_offset.strip():
            attrs.append(("outputOffset", config.output_offset.strip()))

        if machine_type == "excavatorShovel" and config.raycast_distance.strip():
            attrs.append(("raycastDistance", config.raycast_distance.strip()))

        return attrs
