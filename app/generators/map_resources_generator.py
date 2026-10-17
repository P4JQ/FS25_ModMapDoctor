"""Generate map ground-resource XML for TerraFarm.

Source of truth: Documentation/docs/MAP_RESOURCES.md plus its two example files
(``mapGroundResources.xml`` and ``mapResources.i3d.xml``).

Two standalone, well-formed XML documents are produced, one per destination:

* ``mapGroundResources.xml`` - lives next to the map xml file. It maps every
  InfoLayer option value to a fillType, a paintLayer and an optional yield.
* An ``<InfoLayer>`` snippet - belongs in the map **.i3d** (not in map.xml). It
  declares the density-map channels that map makers paint in Giants Editor.

Notes on the documentation:

* The attribute table in MAP_RESOURCES.md spells the optional attribute
  ``paintLayerDisharge``, but both example files (and the page's own XML
  sample) use ``paintLayerDischarge``. The example spelling is used here.
* The page says the maximum number of layers is ``numChannels ^ 2``. An
  N-channel layer stores N bits, so the real capacity is ``2 ^ N`` values
  (0 .. 2^N - 1); that is what this module enforces.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from xml.sax.saxutils import quoteattr

DEFAULT_INFO_LAYER_NAME = "mapGroundResources"
DEFAULT_GROUP_NAME = "Ground resource"

GROUND_RESOURCES_FILENAME = "mapGroundResources.xml"
INFO_LAYER_FILENAME = "mapResources.i3d.xml"

# Fill types that appear in the documentation's examples. Any other fillType
# name is allowed (it only has to exist in the game / your map, case-sensitive).
DOCUMENTED_FILL_TYPES: tuple[str, ...] = ("STONE", "DIRT")

_XML_DECLARATION = '<?xml version="1.0" encoding="utf-8" standalone="no" ?>'
_INDENT = "    "


@dataclass(frozen=True, slots=True)
class GroundLayer:
    """One ``<layer>`` entry plus the matching InfoLayer ``<Option>``."""

    value: int
    fill_type: str
    paint_layer: str
    paint_layer_discharge: str = ""  # "" -> omit, the game uses paintLayer
    yield_value: float | None = None  # None -> omit, the game uses 1.0
    option_name: str = ""  # Giants Editor label; "" -> sensible default


@dataclass(slots=True)
class InfoLayerSettings:
    """Density-map channel settings for the InfoLayer."""

    name: str = DEFAULT_INFO_LAYER_NAME
    group_name: str = DEFAULT_GROUP_NAME
    file_id: str = ""  # "" -> keep the '...' template placeholder
    num_channels: int | None = None  # total channels; None -> smallest that fits
    first_channel: int = 0


@dataclass(frozen=True, slots=True)
class GeneratedMapResources:
    """Result of one generation run."""

    ground_resources_xml: str
    info_layer_xml: str
    ground_resources_filename: str = GROUND_RESOURCES_FILENAME
    info_layer_filename: str = INFO_LAYER_FILENAME
    total_channels: int = 1
    group_channels: int = 1
    warnings: tuple[str, ...] = field(default_factory=tuple)


# The example layers documented in MAP_RESOURCES.md / mapGroundResources.xml,
# with the option names from mapResources.i3d.xml.
EXAMPLE_LAYERS: tuple[GroundLayer, ...] = (
    GroundLayer(0, "STONE", "GRAVEL", yield_value=1.0, option_name="None"),
    GroundLayer(1, "DIRT", "dirt", paint_layer_discharge="dirtDark", option_name="Soil"),
    GroundLayer(2, "STONE", "rock", yield_value=0.8, option_name="Stone"),
    GroundLayer(3, "STONE", "cobblestone", option_name="Gravel"),
)


def channels_needed(max_value: int) -> int:
    """Smallest channel count that can store ``max_value`` (at least 1)."""
    return max(1, int(max_value).bit_length())


def value_capacity(channels: int) -> int:
    """How many distinct values ``channels`` bits can hold (2 ** channels)."""
    return 2 ** max(channels, 0)


def format_yield(value: float) -> str:
    """Yield text for XML: always has a decimal point (1.0, 0.8, 1.25)."""
    if float(value).is_integer():
        return f"{value:.1f}"
    return f"{value:.6f}".rstrip("0").rstrip(".")


class MapResourcesGenerator:
    """Build formatted map-resource XML documents from wizard input."""

    def generate(
        self,
        layers: Sequence[GroundLayer],
        settings: InfoLayerSettings | None = None,
    ) -> GeneratedMapResources:
        """Validate the layers and settings, then build both documents.

        Raises:
            ValueError: with a user-facing message when input is invalid.
        """
        settings = settings or InfoLayerSettings()
        ordered = self._validate_layers(layers)
        info_name = self._require_text(settings.name or DEFAULT_INFO_LAYER_NAME, "InfoLayer name")
        group_name = self._require_text(
            settings.group_name or DEFAULT_GROUP_NAME, "Group name"
        )
        total, group_channels = self._resolve_channels(ordered, settings)

        warnings = self._collect_warnings(ordered)
        return GeneratedMapResources(
            ground_resources_xml=self._build_ground_resources(info_name, ordered),
            info_layer_xml=self._build_info_layer(
                info_name=info_name,
                group_name=group_name,
                file_id=settings.file_id.strip(),
                total_channels=total,
                first_channel=settings.first_channel,
                group_channels=group_channels,
                layers=ordered,
            ),
            total_channels=total,
            group_channels=group_channels,
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _require_text(text: str, label: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError(f"{label} must not be empty.")
        if any(ord(ch) < 32 for ch in cleaned):
            raise ValueError(f"{label} must not contain control characters or line breaks.")
        return cleaned

    def _validate_layers(self, layers: Sequence[GroundLayer]) -> list[GroundLayer]:
        if not layers:
            raise ValueError("Add at least one layer. Layer value 0 is required.")

        seen: set[int] = set()
        for layer in layers:
            if layer.value < 0:
                raise ValueError(f"Layer value {layer.value}: must be 0 or greater.")
            if layer.value in seen:
                raise ValueError(f"Layer value {layer.value} is used more than once.")
            seen.add(layer.value)

            self._require_text(layer.fill_type, f"Layer {layer.value} fillType")
            self._require_text(layer.paint_layer, f"Layer {layer.value} paintLayer")
            if layer.yield_value is not None and (
                math.isnan(layer.yield_value)
                or math.isinf(layer.yield_value)
                or layer.yield_value < 0
            ):
                raise ValueError(f"Layer {layer.value} yield must be a number of 0 or more.")

        if 0 not in seen:
            raise ValueError(
                "Layer value 0 is required: it is the fallback for areas that are not painted."
            )
        return sorted(layers, key=lambda item: item.value)

    @staticmethod
    def _resolve_channels(
        layers: Sequence[GroundLayer], settings: InfoLayerSettings
    ) -> tuple[int, int]:
        """Return (InfoLayer numChannels, Group numChannels)."""
        first = settings.first_channel
        if first < 0:
            raise ValueError("firstChannel must be 0 or greater.")

        highest = layers[-1].value
        needed = channels_needed(highest)

        if settings.num_channels is None:
            return first + needed, needed

        total = settings.num_channels
        if total < 1:
            raise ValueError("numChannels must be 1 or greater.")
        group = total - first
        if group < 1:
            raise ValueError(
                f"numChannels ({total}) must be greater than firstChannel ({first})."
            )
        if group < needed:
            raise ValueError(
                f"Layer value {highest} needs {needed} channel(s), but only {group} "
                f"are available (numChannels {total} minus firstChannel {first}). "
                f"Increase numChannels to at least {first + needed}."
            )
        return total, group

    @staticmethod
    def _collect_warnings(layers: Sequence[GroundLayer]) -> list[str]:
        warnings: list[str] = []
        for layer in layers:
            fill = layer.fill_type.strip()
            if fill != fill.upper():
                warnings.append(
                    f"Layer {layer.value}: fillType '{fill}' is not upper-case. "
                    "Names are case-sensitive; fill types are normally upper-case (e.g. STONE)."
                )
        names: dict[str, int] = {}
        for layer in layers:
            name = MapResourcesGenerator._option_name(layer)
            if name in names:
                warnings.append(
                    f"Layers {names[name]} and {layer.value} share the Option name '{name}'."
                )
            else:
                names[name] = layer.value
        return warnings

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    @staticmethod
    def _option_name(layer: GroundLayer) -> str:
        explicit = layer.option_name.strip()
        if explicit:
            return explicit
        return "None" if layer.value == 0 else layer.paint_layer.strip()

    @staticmethod
    def _layer_line(layer: GroundLayer) -> str:
        parts = [
            f"value={quoteattr(str(layer.value))}",
            f"fillType={quoteattr(layer.fill_type.strip())}",
            f"paintLayer={quoteattr(layer.paint_layer.strip())}",
        ]
        discharge = layer.paint_layer_discharge.strip()
        if discharge and discharge != layer.paint_layer.strip():
            parts.append(f"paintLayerDischarge={quoteattr(discharge)}")
        if layer.yield_value is not None:
            parts.append(f"yield={quoteattr(format_yield(layer.yield_value))}")
        return f"<layer {' '.join(parts)} />"

    def _build_ground_resources(self, info_name: str, layers: Sequence[GroundLayer]) -> str:
        lines = [
            _XML_DECLARATION,
            "<!--",
            f"{_INDENT}{GROUND_RESOURCES_FILENAME} - generated by FS25 Mod & Map Doctor",
            f"{_INDENT}Place this file in the same folder as your map xml file.",
            "",
            f"{_INDENT}Each layer maps one InfoLayer option value (see the .i3d snippet) to:",
            f"{_INDENT}- fillType: material produced when terraforming (case-sensitive)",
            f"{_INDENT}- paintLayer: terrain layer painted when terraforming (case-sensitive)",
            f"{_INDENT}- paintLayerDischarge: layer painted when discharging to the ground [optional]",
            f"{_INDENT}- yield: terraforming yield multiplier [optional, default 1.0]",
            "-->",
            f"<groundResources infoLayer={quoteattr(info_name)}>",
            f"{_INDENT}<layers>",
        ]
        for layer in layers:
            if layer.value == 0:
                lines.append(
                    f"{_INDENT * 2}<!-- Value 0 is the required fallback for unpainted areas -->"
                )
            lines.append(f"{_INDENT * 2}{self._layer_line(layer)}")
        lines += [f"{_INDENT}</layers>", "</groundResources>", ""]
        return "\n".join(lines)

    def _build_info_layer(
        self,
        *,
        info_name: str,
        group_name: str,
        file_id: str,
        total_channels: int,
        first_channel: int,
        group_channels: int,
        layers: Sequence[GroundLayer],
    ) -> str:
        file_id_text = file_id or "..."
        lines = [
            "<!--",
            f"{_INDENT}InfoLayer for your map .i3d (not map.xml) - generated by FS25 Mod & Map Doctor",
            f"{_INDENT}Add this inside your map.i3d. runtime=\"true\" is required so the game can read it.",
            (
                f"{_INDENT}Replace fileId=\"...\" with the id Giants Editor assigns to your layer file."
                if not file_id
                else f"{_INDENT}fileId must match the layer file entry in your map.i3d."
            ),
            f"{_INDENT}Do not let painted areas of different values overlap in Giants Editor.",
            f"{_INDENT}Capacity: {total_channels} channel(s) in total, "
            f"{group_channels} in this group = {value_capacity(group_channels)} values "
            f"(0 to {value_capacity(group_channels) - 1}).",
            "-->",
            (
                f"<InfoLayer name={quoteattr(info_name)} fileId={quoteattr(file_id_text)} "
                f'numChannels={quoteattr(str(total_channels))} runtime="true">'
            ),
            (
                f"{_INDENT}<Group name={quoteattr(group_name)} "
                f"firstChannel={quoteattr(str(first_channel))} "
                f"numChannels={quoteattr(str(group_channels))}>"
            ),
        ]
        for layer in layers:
            if layer.value == 0:
                lines.append(
                    f"{_INDENT * 2}<!-- value=\"0\" is required; unpainted areas use it -->"
                )
            lines.append(
                f"{_INDENT * 2}<Option value={quoteattr(str(layer.value))} "
                f"name={quoteattr(self._option_name(layer))} />"
            )
        lines += [f"{_INDENT}</Group>", "</InfoLayer>", ""]
        return "\n".join(lines)
