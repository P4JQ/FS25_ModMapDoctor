"""XML / asset generators for FS25 Mod & Map Doctor."""

from app.generators.lua_generator import (
    SCRIPT_TYPE_INFO,
    SCRIPT_TYPE_OPTIONS,
    TARGET_OBJECT_OPTIONS,
    EVENT_REGISTRATION_BLOCK,
    GeneratedLuaScript,
    LuaGenerator,
    LuaScriptRequest,
    ScriptType,
    TargetObject,
    name_error,
)
from app.generators.map_resources_generator import (
    DOCUMENTED_FILL_TYPES,
    EXAMPLE_LAYERS,
    GeneratedMapResources,
    GroundLayer,
    InfoLayerSettings,
    MapResourcesGenerator,
)
from app.generators.terrafarm_generator import (
    INPUT_MODES,
    MACHINE_TYPE_DESCRIPTIONS,
    MACHINE_TYPE_OPTIONS,
    GeneratedFiles,
    MachineConfigInput,
    TerraFarmGenerator,
)

__all__ = [
    "DOCUMENTED_FILL_TYPES",
    "EVENT_REGISTRATION_BLOCK",
    "EXAMPLE_LAYERS",
    "INPUT_MODES",
    "MACHINE_TYPE_DESCRIPTIONS",
    "MACHINE_TYPE_OPTIONS",
    "SCRIPT_TYPE_INFO",
    "SCRIPT_TYPE_OPTIONS",
    "TARGET_OBJECT_OPTIONS",
    "GeneratedFiles",
    "GeneratedLuaScript",
    "GeneratedMapResources",
    "GroundLayer",
    "InfoLayerSettings",
    "LuaGenerator",
    "LuaScriptRequest",
    "MachineConfigInput",
    "MapResourcesGenerator",
    "ScriptType",
    "TargetObject",
    "TerraFarmGenerator",
    "name_error",
]
