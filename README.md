<div align="center">

# FS25 Mod & Map Doctor

**v0.1.0 &nbsp;|&nbsp; An all-in-one local development suite for Farming Simulator 25 modders, scripters and map makers.**

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![GUI](https://img.shields.io/badge/GUI-CustomTkinter-1f6aa5)
![License](https://img.shields.io/badge/license-MIT-green)
![Tested on](https://img.shields.io/badge/tested%20on-Windows%2011-lightgrey)
![Game](https://img.shields.io/badge/target-Farming%20Simulator%2025-4c9a2a)

*Catch the problems that crash dedicated servers and desync multiplayer sessions **before** you upload your mod,
and generate correct boilerplate instead of writing it from memory.*

</div>

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
   - [Mod & Lua Auditor](#1-mod--lua-auditor)
   - [TerraFarm Configuration Generator](#2-terrafarm-configuration-generator)
   - [Map Helper](#3-map-helper)
   - [Lua Script Generator](#4-lua-script-generator)
3. [Configuration & How It Works](#configuration--how-it-works)
4. [Installation & Usage](#installation--usage)
5. [Using the Tool: Tips & Parameters](#using-the-tool-tips--parameters)
6. [Project Structure](#project-structure)
7. [Running the Test Suite](#running-the-test-suite)
8. [Known Limitations](#known-limitations)

---

## Overview

Building an FS25 mod usually means a long loop of *edit, zip, start the game, read `log.txt`, repeat*. Many mistakes
never show up on your own Windows machine at all: a wrongly capitalised file name works on NTFS and then kills a Linux
dedicated server, and a `writeStream` that does not match its `readStream` only breaks when a second player joins.

**FS25 Mod & Map Doctor** moves that feedback loop onto your desktop. It is a local, offline toolkit with four tabs:

| Tab | What it is for |
| --- | --- |
| **Mod & Lua Auditor** | Validate `modDesc.xml`, vehicle XML files and Lua scripts. |
| **TerraFarm Generator** | Build TerraFarm machine XML (shovel, leveler, trencher, excavator, compactor) with a visual form. |
| **Map Helper** | Build `mapGroundResources.xml` and the matching `InfoLayer` snippet for a map. |
| **Lua Generator** | Generate multiplayer-aware Lua templates plus the XML needed to register them. |

Nothing is uploaded and no Lua is ever executed. Everything runs on your machine.

<div align="center">

![Mod & Lua Auditor](docs/images/auditor.png)

</div>

---

## Key Features

### 1. Mod & Lua Auditor

One click runs three checks in sequence and prints a single sectioned report (`modDesc.xml`, `Vehicle Validation`,
`Lua Audit`). Every finding has a severity (error, warning or info) and, for Lua, a stable rule ID.

**modDesc.xml and file references**

- Checks the structure of `modDesc.xml`: root element, `descVersion`, the required `author`, `version` and
  `iconFilename` tags, and the files referenced from `extraSourceFiles` and the other file entries.
- **Linux-safe, case-sensitive path checking.** Windows will happily open `Scripts/MySpec.lua` when the file is
  really called `scripts/myspec.lua`. A Linux dedicated server will not, and the mod fails to load there. The
  validator walks every path component against the real directory listing and reports wrong casing, including the
  casing of `modDesc.xml` itself. This is how you prevent that class of **Dedicated Server crash** on a PC that
  would never show it.

**Vehicle XML and specializations**

- Cross-references the blocks inside a vehicle XML against the specializations its `vehicleType` actually provides,
  using a bundled table of **261 vehicle XML block to specialization mappings**. If your XML contains a block such
  as `<machine>` or `<wearable>` but the vehicle type does not include the specialization that reads it, the block is
  silently ignored by the engine. The auditor tells you which specialization is missing.
- Resolves custom `<vehicleTypes>` declared in your `modDesc.xml` and flags unknown types.
- For vanilla vehicle types the full specialization list is not embedded, so those mismatches are reported as
  **warnings** rather than errors. The tool does not claim certainty it does not have.

**Static Lua scanner (multiplayer safety)**

The Lua audit is a **heuristic, text-based scanner**. Comments and string contents are blanked out first, so a
`streamWriteBool` inside a comment never counts. Lua files are discovered from `modDesc.xml` plus any literal
`source("...")` calls.

| Rule | What it catches |
| --- | --- |
| `LUA-EVT-001` / `LUA-EVT-008` | Event classes without a working `emptyNew()` (the engine creates events on the receiving side with it). |
| `LUA-EVT-002` | An event with `writeStream()` but no `readStream()` (or the reverse). |
| `LUA-EVT-004` | **Stream asymmetry:** `writeStream()` and `readStream()` do not read and write the same types in the same order. |
| `LUA-EVT-005` / `LUA-EVT-006` | Client requests that are never relayed, and `sendEvent()` that only reaches one direction. |
| `LUA-SPEC-001` / `002` / `003` | Missing `prerequisitesPresent`, `registerEventListeners`, or registered handlers that do not exist. |
| `LUA-SPEC-003` / `004` | Specialization `onWriteStream`/`onReadStream` (and update-stream) pairs that are missing or do not match. |
| `LUA-SPEC-005` | An update stream that never raises dirty flags, so clients never receive it. |
| `LUA-OLD-009` and legacy API rules | **321 deprecated vehicle XML paths** inherited from FS19/FS21/FS22, plus 8 legacy Lua API patterns. Each hit names the replacement. |

> **Why it matters:** read/write asymmetry is the classic multiplayer bug. It works in single player, works for the
> host, and then corrupts the stream or disconnects clients as soon as someone joins.

The auditor only flags an API as outdated when the vanilla scripts themselves mark it deprecated or never use it
while using a documented replacement. API that vanilla code still uses is deliberately **not** flagged, to avoid
false alarms.

---

### 2. TerraFarm Configuration Generator

A visual wizard for TerraFarm machine configuration. It produces two standalone,
well-formed documents: the machine file (`<vehicle><machine/></vehicle>`) and `machineConfigurations.xml`.

![TerraFarm Generator](docs/images/terrafarm.png)

- **Machine types:** shovel (wheel loader / bucket), leveler (blade / grader), trencher, excavator and compactor.
- **Safe Vector3 inputs.** Offset, rotation and output offset are entered in horizontal **X / Y / Z** grids instead of
  one free-text string like `0 0.5 1.2`. That removes the usual typos: missing components, commas instead of spaces,
  and swapped axes.
- **Automatic `n/a` field masking.** Fields that do not apply to the selected machine type are greyed out and marked
  `n/a`. A leveler or trencher has no shovel node, and a compactor has no fill unit or node settings, so you cannot
  fill in settings that the machine would ignore. Fields that a type *requires* (for example the trencher's fill unit,
  reference node and width) are marked with `*`.
- **Two output tabs** (machine XML and registration XML) so each file stays a valid, standalone XML document.
- Shows a short description of the selected machine type, and writes a `Prerequisites` comment into the generated
  XML listing which specializations the vehicle needs (for example `fillUnit` and `shovel`).

---

### 3. Map Helper

A visual builder for the ground resources that TerraFarm reads from your map, based on `MAP_RESOURCES.md`. It
produces `mapGroundResources.xml` and the `InfoLayer` snippet that belongs in your map `.i3d`.

![Map Helper](docs/images/map-helper.png)

- **Ground & Paint Layers card:** the InfoLayer name and group, `numChannels`, `firstChannel`, optional `fileId`,
  and the list of layer IDs with their `paintLayer` and optional `paintLayerDischarge`.
- **Fruit & Yield Configurations card:** a `fillType` dropdown (or any custom fill type name) and a **yield
  multiplier** for each layer.
- **Binary channel capacity logic.** An InfoLayer stores its value in density-map *bits*, so the number of layers you
  can paint is `2^N`, not `N` squared:

  | Channels (bits) | Layer IDs you can use |
  | :---: | :---: |
  | 1 | 0-1 |
  | 2 | 0-3 |
  | 3 | 0-7 |
  | 4 | 0-15 |

  The form shows the live capacity next to the channel field. If you leave `numChannels` empty it picks the smallest
  channel count that fits your highest ID. If you set one that is too small, it tells you instead of generating a
  layer that cannot be painted.
- **Well-formed output.** Two documents are generated: `mapGroundResources.xml`, and an `InfoLayer` snippet (saved
  as `mapResources.i3d.xml`) for you to paste into your map `.i3d`. The `InfoLayer` is **not** a standalone `.i3d`
  file and does not go into `map.xml`.
- Copy to Clipboard and Save as XML file are available for both outputs.

> The documentation page spells one attribute `paintLayerDisharge` while its own examples use
> `paintLayerDischarge`. The tool follows the examples.

---

### 4. Lua Script Generator

Generates complete, ready-to-edit FS25 Lua templates and the precise XML snippets you need in `modDesc.xml`.

![Lua Generator](docs/images/lua-generator.png)

| Script Type | Target | What you get |
| --- | --- | --- |
| **Custom Specialization Mod** | Vehicle | `prerequisitesPresent`, `initSpecialization`, `registerFunctions`, `registerEventListeners`, `onLoad`, `onUpdate`, `onDelete`, savegame `saveToXMLFile`, plus `onWriteStream`/`onReadStream` and `onWriteUpdateStream`/`onReadUpdateStream` with dirty flags. |
| **Network Event Script** | Vehicle, Placeable or Game Environment | An `Event` subclass with `emptyNew()`, `new()`, `readStream()`, `writeStream()`, `run()` and `sendEvent()`. Comments mark exactly where **server-side safety checks** belong (sync check, range check, permissions and ownership). |
| **Placeable Extension** | Placeable | `registerXMLPaths`, savegame paths, `onLoad`, `loadFromXMLFile`, `saveToXMLFile`, stream and update-stream handlers. |

- **Multiplayer-ready by default.** Server and client roles are handled in the template, state changes go through the
  server, and clients get updates through dirty flags.
- **Companion XML.** The second output tab contains the `modDesc.xml` entries (`<multiplayer supported="true" />`,
  `<specializations>`, `<extraSourceFiles>`, `<vehicleTypes>` or `<placeableTypes>`) and a sample vehicle or
  placeable XML fragment.
- **Validated names.** The script name must be a valid Lua identifier, is checked against Lua keywords and engine
  globals, and is converted to the correct case (`MyThing` for the class, `myThing` for the XML name).
- Generated code is checked against the project's own Lua auditor and must produce **zero findings**.
- The save button follows the visible tab: *Save as Lua file* or *Save as XML file*.

---

## Configuration & How It Works

The rules in this tool are not guesses. They are derived from two documentation sets that sit next to the project:

| Source folder | Used for |
| --- | --- |
| `Documentation/docs/` | The XML documentation: `MACHINE_*.md`, `MAP_RESOURCES.md`, `INDEX.md`, and the script reference. |
| `Documentation/FS25-lua-scripting-main/` | The vanilla Lua sources: how events, specializations and placeables are really structured. |

**How the knowledge gets into the app**

1. Extraction scripts in `scripts/` (`_extract_spec_map.py`, `_extract_deprecated_xml.py`, `_analyze_lua_source.py`)
   read those folders and produce compact data files in `app/knowledge/`:
   - `xml_block_to_specialization.json`: 261 XML block mappings
   - `lua_deprecated_xml_paths.json`: 321 deprecated XML paths
   - `lua_rules.py`: the legacy API and network rules, each carrying its **evidence** from the vanilla code
2. At runtime the app loads those bundled files. **It does not need the `Documentation/` folders to run**, and it does
   not read them while you work.
3. `scripts/calibrate_lua_auditor.py` and the test suite re-check the rules against the vanilla scripts. Rules that
   flagged things vanilla code still does were removed.

**Safe by design.** The Lua auditor only reads your scripts as text. A small scanner blanks comments and strings and
finds function bodies by counting block keywords. **It never runs, loads or `require`s any Lua file**, so a mod you
download from anywhere can be audited without risk.

> Because the checks are heuristic, a finding is a *likely problem with a rule ID*, not a proof. Each message says what
> was found and what the vanilla scripts do instead.

---

## Installation & Usage

### Requirements

- **Python 3.10 or newer** (developed and tested on Python 3.14)
- **CustomTkinter** (`>=5.2.0,<7`; tested with 6.0.0)
- A desktop with Tk available. Developed and tested on **Windows 11**; the code is plain cross-platform Python, but
  other platforms have not been tested.

### Install

```bash
pip install customtkinter
```

or, from the project folder:

```bash
pip install -r requirements.txt
```

### Launch the GUI

```bash
python main.py
```

### Command-line validation (smoke testing and CI)

Run the full audit without opening a window:

```bash
python main.py --validate <mod_folder>
```

It prints the same sectioned report as the GUI and sets the exit code, so it works in scripts and CI:

| Exit code | Meaning |
| :---: | --- |
| `0` | Passed (no errors). |
| `1` | At least one error was found. |

Try it on the bundled samples:

```bash
python main.py --validate samples/sample_ok_mod       # passes
python main.py --validate samples/sample_broken_mod   # reports errors, exits with 1
```

---

## Using the Tool: Tips & Parameters

- **`*` means mandatory.** Fields marked with an asterisk must be filled in. If one is empty, the tool shows an
  error in the status bar next to the Generate button, highlights the field, and generates nothing.
- **Empty optional fields use the game default.** Leave an optional field blank and the attribute is simply **left out**
  of the generated XML, so the game engine applies its own default. For example, an empty `yield` means the game uses
  `1.0`, and an empty `paintLayerDischarge` means it uses `paintLayer`. You never have to guess default values.
- **Grey text is a placeholder, not a value.** It shows an example of the expected format and is never written to
  the output.
- **Try "Load Example" first.** In the **Map Helper**, the **Load Example** button fills the form with the example
  layers from `MAP_RESOURCES.md`. Click it, then **Generate Map Resources**, to see a complete working output
  straight away.
- **Reset Form** clears a tab and restores its defaults. It is available on the TerraFarm, Map Helper and Lua
  Generator tabs.
- **Copy to Clipboard** and **Save as ... file** act on the output tab you are looking at. Each tab saves its own
  document, so the XML stays well-formed.
- **Read the status line.** The bar at the bottom of each tab reports what was generated or why generation failed.

---

## Project Structure

```text
FS25_ModMapDoctor/
|-- main.py                     # GUI launcher and --validate CLI
|-- requirements.txt
|-- README.md
|-- app/
|   |-- core/                   # models, case-sensitive path helpers, Lua scanner
|   |-- validators/             # modDesc, vehicle and Lua auditors + pipeline
|   |-- generators/             # TerraFarm, map resources and Lua generators
|   |-- knowledge/              # bundled rule data derived from the documentation
|   `-- gui/                    # main window, tabs and reusable widgets
|-- samples/                    # sample_ok_mod and sample_broken_mod
|-- scripts/                    # tests and knowledge-extraction tools
`-- docs/images/                # README screenshots
```

---

## Running the Test Suite

Each script is standalone and exits non-zero on failure. The GUI tests open a real window briefly.

```bash
python scripts/lua_auditor_test.py        # Lua auditor rules
python scripts/lua_generator_test.py      # generated templates
python scripts/gui_smoke_test.py          # TerraFarm tab
python scripts/map_helper_smoke_test.py   # Map Helper tab
python scripts/lua_tabs_smoke_test.py     # Auditor and Lua Generator tabs
```

`lua_generator_test.py` can also run the generated Lua inside a real Lua VM with a mock engine to verify that stream
reads and writes match. That layer needs the optional, **development-only** package `lupa`
(`pip install lupa`) and is skipped automatically when it is not installed.

---

## Known Limitations

Being honest about what the tool can and cannot promise:

- **Heuristic Lua analysis.** The scanner is not a full Lua parser. Expect the occasional false positive or missed
  case, and treat results as strong hints.
- **Generated Lua is not verified by the game itself.** Templates are checked by the project's auditor, by a mock
  engine and for XML well-formedness, but not by a running copy of FS25. Test them in-game before release.
- **Event registration.** The event templates end with a guarded `InitEventClass(...)` call. The `registerEventId`
  style call is not used because it does not appear in the reference sources. If your game version needs a different
  registration call, change the single block in `lua_generator.py` (`EVENT_REGISTRATION_BLOCK`).
- **Unconfirmed engine names.** Details such as `g_currentModName` and the exact specialization table key are taken
  from vanilla usage but could not be fully confirmed from the stripped reference sources.
- **Vanilla vehicle types** are only partly embedded, so some specialization checks on them are warnings.
- **Vehicle XML only.** The validator checks vehicle files. Placeable XML files are not validated, although the Lua
  auditor checks placeable specialization scripts.
- **Static knowledge.** Rules reflect the documentation snapshot they were built from. Future game updates may need
  new extraction runs.

---

## License

Released under the [MIT License](LICENSE).

---

<div align="center">

Made for the FS25 modding community.

</div>
