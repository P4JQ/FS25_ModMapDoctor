"""Static Lua audit for FS25 mods: multiplayer synchronisation + outdated API.

Which Lua files are audited
---------------------------
Every ``filename="....lua"`` in modDesc.xml (``<extraSourceFiles>``, custom
``<specializations>``, ``<vehicleTypes>`` ...) plus every file those scripts
load themselves with a literal ``source("....lua")`` call.

What is checked
---------------
The checks are modelled on the vanilla FS25 scripts (see
``app/knowledge/lua_rules.py`` for the evidence behind each outdated-API rule):

* Network events (``Class(X, Event)``): the emptyNew / readStream / writeStream
  / run template, read/write symmetry of the stream data, server/client
  awareness in ``run()``, and a ``sendEvent`` that reaches both directions.
* Specializations: ``prerequisitesPresent`` / ``registerEventListeners``,
  registered handlers that do not exist, join/update stream handlers that exist
  on one side only, mismatching stream data, and update streams without dirty
  flags.
* Outdated API: only things the vanilla code marks deprecated or never uses
  while using a documented replacement.

The analysis is text based (comments and strings are ignored) and never
executes Lua, so it reports likely problems with a rule id, not certainties.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from app.core.lua_scanner import LuaFunction, LuaSource
from app.core.models import Severity, ValidationReport
from app.core.path_utils import (
    find_path_ignoring_case,
    is_engine_dollar_path,
    path_exists_case_sensitive,
    resolve_mod_relative_path,
)
from app.knowledge.lua_rules import (
    LEGACY_API_RULES,
    NETWORK_SIDE_MARKERS,
    STREAM_HANDLER_PAIRS,
    deprecated_xml_paths,
)

# Findings per rule and file are capped so one bad pattern cannot flood the report.
_MAX_FINDINGS_PER_RULE = 5

_EVENT_CLASS = re.compile(r"\bClass\s*\(\s*([A-Za-z_]\w*)\s*,\s*Event\s*\)")
_REGISTER_LISTENER = re.compile(
    r"SpecializationUtil\s*\.\s*registerEventListener\s*\(\s*[\w.]+\s*,"
    r"\s*[\"'](\w+)[\"']\s*,\s*([A-Za-z_][\w.]*)\s*\)"
)
_STREAM_CALL = re.compile(
    r"\bstream(?P<d1>Write|Read)(?P<t1>[A-Za-z0-9_]+)\s*\("
    r"|\bNetworkUtil\s*\.\s*(?P<d2>write|read)(?P<t2>[A-Za-z0-9_]+)\s*\("
    r"|[:.]\s*(?P<d3>write|read)(?P<t3>(?:Update)?Stream)\s*\("
)
_SOURCE_CALL = re.compile(r"(?<![\w.:])source\s*\(")
_DIRTY_FLAG_USE = re.compile(r"\b(?:raiseDirtyFlags|getNextDirtyFlag)\s*\(")
_NETWORK_FEATURE = re.compile(r"\b(?:g_server|g_client)\b|\bbroadcastEvent\b")


# ----------------------------------------------------------------------
# Pure analysis of one Lua text (also used by tests and calibration)
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule hit inside a single Lua file."""

    rule_id: str
    severity: Severity
    message: str
    line: int


@dataclass(slots=True)
class LuaAnalysis:
    """Everything the auditor learned about one Lua file."""

    findings: list[Finding] = field(default_factory=list)
    event_classes: dict[str, int] = field(default_factory=dict)  # name -> line
    spec_classes: list[str] = field(default_factory=list)
    uses_network_api: bool = False
    source: LuaSource | None = None


def analyze_lua(text: str) -> LuaAnalysis:
    """Run all single-file checks on Lua source text."""
    source = LuaSource.from_text(text)
    analysis = LuaAnalysis(source=source)

    for match in _EVENT_CLASS.finditer(source.masked):
        analysis.event_classes.setdefault(match.group(1), source.line_of(match.start()))

    analysis.spec_classes = _find_spec_classes(source, set(analysis.event_classes))
    analysis.uses_network_api = bool(
        analysis.event_classes
        or _NETWORK_FEATURE.search(source.masked)
        or any(
            source.find_function(spec, name) is not None
            for spec in analysis.spec_classes
            for pair in STREAM_HANDLER_PAIRS
            for name in pair
        )
    )

    for name, line in analysis.event_classes.items():
        _audit_event(source, name, line, analysis)
    for spec in analysis.spec_classes:
        _audit_specialization(source, spec, analysis)

    _audit_legacy_api(source, analysis)
    _audit_deprecated_xml_paths(source, analysis)
    return analysis


def _add(
    analysis: LuaAnalysis,
    rule_id: str,
    severity: Severity,
    line: int,
    message: str,
) -> None:
    analysis.findings.append(Finding(rule_id, severity, message, line))


# -- stream helpers ----------------------------------------------------


def stream_tokens(body: str, direction: str) -> list[str]:
    """Ordered stream primitives (``Int8``, ``NodeObject`` ...) of one direction.

    ``direction`` is ``"write"`` or ``"read"``; the same primitive name is
    returned for the writing and the reading call so the two lists compare.

    ``NodeObject`` and ``NodeObjectId`` are treated as the same wire format:
    vanilla code writes with ``writeNodeObject`` and reads with
    ``readNodeObjectId`` (InlineWrapper, PlaceableTrainSystem).
    """
    tokens: list[str] = []
    for match in _STREAM_CALL.finditer(body):
        if match.group("d1"):
            found_direction, name = match.group("d1").lower(), match.group("t1")
        elif match.group("d2"):
            found_direction, name = match.group("d2"), match.group("t2")
        else:
            found_direction, name = match.group("d3"), match.group("t3")
        if found_direction == direction:
            tokens.append("NodeObject" if name == "NodeObjectId" else name)
    return tokens


@dataclass(frozen=True, slots=True)
class StreamSignature:
    """Stream primitives of one read/write function.

    ``tokens`` only covers the straight-line part: everything before the first
    loop or ``else`` branch. Beyond that point write and read code can be shaped
    differently and still put identical bytes on the wire (vanilla does this in
    FillUnitUnloadedEvent, BaleWrapper and PlaceableRiceField), so a plain
    sequence comparison would raise false alarms.
    """

    tokens: list[str]
    complete: bool  # True when the function has no loop / else branch at all


_STRUCTURE = re.compile(r"\b(?:for|while|repeat|else|elseif)\b")


def stream_signature(body: str, direction: str) -> StreamSignature:
    structural = _STRUCTURE.search(body)
    cut = structural.start() if structural else len(body)
    return StreamSignature(stream_tokens(body[:cut], direction), complete=structural is None)


def describe_stream_mismatch(written: StreamSignature, read: StreamSignature) -> str | None:
    """Return a human-readable difference, or None when both sides match."""

    def fmt(tokens: list[str]) -> str:
        return ", ".join(tokens) if tokens else "(nothing)"

    summary = f"[write: {fmt(written.tokens)} | read: {fmt(read.tokens)}]"
    for index, (w, r) in enumerate(zip(written.tokens, read.tokens, strict=False), start=1):
        if w != r:
            return f"item {index} is written as {w} but read as {r} {summary}"

    # A different *count* only proves a mismatch when neither side branches or loops.
    if written.complete and read.complete and len(written.tokens) != len(read.tokens):
        return f"{len(written.tokens)} value(s) written but {len(read.tokens)} read {summary}"
    return None


def _usable(func: LuaFunction | None) -> LuaFunction | None:
    return func if func is not None and func.closed else None


# -- events ------------------------------------------------------------


def _audit_event(source: LuaSource, name: str, line: int, analysis: LuaAnalysis) -> None:
    empty_new = _usable(source.find_function(name, "emptyNew"))
    read_stream = _usable(source.find_function(name, "readStream"))
    write_stream = _usable(source.find_function(name, "writeStream"))
    run = _usable(source.find_function(name, "run"))
    send_event = _usable(source.find_function(name, "sendEvent"))

    # The receiving side builds the event with X.emptyNew() before readStream.
    if empty_new is None:
        _add(
            analysis, "LUA-EVT-001", Severity.ERROR, line,
            f"Event '{name}' has no {name}.emptyNew(): the engine creates events "
            "on the receiving side with emptyNew() and cannot instantiate this one.",
        )
    else:
        _check_event_constructor(source, name, empty_new, analysis)

    if (read_stream is None) != (write_stream is None):
        missing = "readStream" if read_stream is None else "writeStream"
        present = "writeStream" if read_stream is None else "readStream"
        _add(
            analysis, "LUA-EVT-002", Severity.ERROR, line,
            f"Event '{name}' implements {present}() but not {missing}(): data sent "
            "over the network cannot be read back (multiplayer desync or crash).",
        )
    elif read_stream is None and write_stream is None:
        _add(
            analysis, "LUA-EVT-002", Severity.WARNING, line,
            f"Event '{name}' has neither readStream() nor writeStream(): it carries no "
            "data, so the receiving side cannot know what happened.",
        )
    elif read_stream is not None and write_stream is not None:
        problem = describe_stream_mismatch(
            stream_signature(write_stream.body, "write"),
            stream_signature(read_stream.body, "read"),
        )
        if problem:
            _add(
                analysis, "LUA-EVT-004", Severity.ERROR, write_stream.line,
                f"Event '{name}': writeStream() and readStream() do not match - {problem}. "
                "Both sides must write and read the same values in the same order.",
            )

    if run is None:
        _add(
            analysis, "LUA-EVT-003", Severity.INFO, line,
            f"Event '{name}' has no run(): all handling must happen inside readStream().",
        )

    if send_event is not None:
        _check_send_event(name, send_event, analysis)
        # A client->server event must be forwarded by the server, otherwise the
        # other clients never see the change. (30% of vanilla events have no
        # side checks at all, so this only fires when sendEvent() proves the
        # event travels from a client to the server.)
        if (
            "getServerConnection" in send_event.body
            and run is not None
            and not any(marker in run.body for marker in NETWORK_SIDE_MARKERS)
        ):
            _add(
                analysis, "LUA-EVT-005", Severity.WARNING, run.line,
                f"{name}:run() receives a client request (sendEvent() uses "
                "getServerConnection()) but never relays it: add "
                "'if not connection:getIsServer() then g_server:broadcastEvent(...) end' "
                "so the other clients stay in sync (a few vanilla events skip this on "
                "purpose, so verify).",
            )


def _check_event_constructor(
    source: LuaSource, name: str, empty_new: LuaFunction, analysis: LuaAnalysis
) -> None:
    metatables = {
        match.group(1)
        for match in re.finditer(
            rf"([A-Za-z_]\w*)\s*=\s*Class\s*\(\s*{re.escape(name)}\b", source.masked
        )
    }
    call = re.search(r"\bEvent\s*\.\s*new\s*\(\s*([A-Za-z_]\w*)", empty_new.body)
    if call is None:
        _add(
            analysis, "LUA-EVT-008", Severity.ERROR, empty_new.line,
            f"{name}.emptyNew() never calls Event.new(<metatable>): the instance would "
            "not be a network event.",
        )
    elif metatables and call.group(1) not in metatables:
        _add(
            analysis, "LUA-EVT-008", Severity.ERROR, empty_new.line,
            f"{name}.emptyNew() uses Event.new({call.group(1)}) but the class metatable "
            f"is '{sorted(metatables)[0]}' (copy-paste mistake?).",
        )


def _check_send_event(name: str, send_event: LuaFunction, analysis: LuaAnalysis) -> None:
    body = send_event.body
    to_clients = "g_server" in body
    to_server = "g_client" in body or "getServerConnection" in body
    if to_clients and not to_server:
        _add(
            analysis, "LUA-EVT-006", Severity.WARNING, send_event.line,
            f"{name}.sendEvent() only broadcasts with g_server: when called on a client "
            "(multiplayer) nothing is sent to the server. Vanilla code falls back to "
            "g_client:getServerConnection():sendEvent(...).",
        )
    elif to_server and not to_clients:
        _add(
            analysis, "LUA-EVT-006", Severity.WARNING, send_event.line,
            f"{name}.sendEvent() only sends to the server: on the server/host the other "
            "clients are never notified. Vanilla code uses g_server:broadcastEvent(...) there.",
        )


# -- specializations -----------------------------------------------------


def _find_spec_classes(source: LuaSource, event_names: set[str]) -> list[str]:
    owners: list[str] = []
    for func in source.functions:
        if (
            func.method in ("prerequisitesPresent", "registerEventListeners")
            and func.owner
            and "." not in func.owner
            and func.owner not in event_names
            and func.owner not in owners
        ):
            owners.append(func.owner)
    return owners


def _audit_specialization(source: LuaSource, spec: str, analysis: LuaAnalysis) -> None:
    anchor = (
        source.find_function(spec, "prerequisitesPresent")
        or source.find_function(spec, "registerEventListeners")
    )
    anchor_line = anchor.line if anchor else 1

    if source.find_function(spec, "prerequisitesPresent") is None:
        _add(
            analysis, "LUA-SPEC-001", Severity.ERROR, anchor_line,
            f"Specialization '{spec}' has no {spec}.prerequisitesPresent(specializations): "
            "the vehicle type loader calls it for every specialization.",
        )
    handlers = [
        func.method
        for func in source.functions_of(spec)
        if re.fullmatch(r"on[A-Z]\w*", func.method)
    ]
    if source.find_function(spec, "registerEventListeners") is None and handlers:
        _add(
            analysis, "LUA-SPEC-001", Severity.WARNING, anchor_line,
            f"Specialization '{spec}' defines {', '.join(f'{h}()' for h in handlers[:3])}"
            f"{' ...' if len(handlers) > 3 else ''} but has no {spec}.registerEventListeners"
            "(vehicleType): the engine will never call these handlers.",
        )

    registered: dict[str, int] = {}
    for match in _REGISTER_LISTENER.finditer(source.code):
        if match.group(2) == spec:
            registered.setdefault(match.group(1), source.line_of(match.start()))

    # Registered handler that is not defined in this file.
    for event_name, line in registered.items():
        if source.find_function(spec, event_name) is None:
            _add(
                analysis, "LUA-SPEC-002", Severity.ERROR, line,
                f"'{event_name}' is registered for {spec} but {spec}:{event_name}() is not "
                "defined in this file; the engine would call a nil function.",
            )

    for write_name, read_name in STREAM_HANDLER_PAIRS:
        _audit_stream_pair(source, spec, write_name, read_name, registered, analysis)


def _audit_stream_pair(
    source: LuaSource,
    spec: str,
    write_name: str,
    read_name: str,
    registered: dict[str, int],
    analysis: LuaAnalysis,
) -> None:
    write_fn = _usable(source.find_function(spec, write_name))
    read_fn = _usable(source.find_function(spec, read_name))
    anchor = write_fn or read_fn
    if anchor is None:
        return

    if (write_fn is None) != (read_fn is None):
        missing = read_name if read_fn is None else write_name
        present = write_name if read_fn is None else read_name
        _add(
            analysis, "LUA-SPEC-003", Severity.ERROR, anchor.line,
            f"{spec}:{present}() has no matching {spec}:{missing}(): data written by one "
            "side is never read by the other (multiplayer desync).",
        )
        return

    assert write_fn is not None and read_fn is not None
    for handler in (write_name, read_name):
        if handler not in registered:
            _add(
                analysis, "LUA-SPEC-003", Severity.ERROR, anchor.line,
                f"{spec}:{handler}() is defined but never registered with "
                f"SpecializationUtil.registerEventListener(vehicleType, \"{handler}\", {spec}); "
                "the engine will not call it.",
            )

    problem = describe_stream_mismatch(
        stream_signature(write_fn.body, "write"), stream_signature(read_fn.body, "read")
    )
    if problem:
        _add(
            analysis, "LUA-SPEC-004", Severity.ERROR, write_fn.line,
            f"{spec}: {write_name}() and {read_name}() do not match - {problem}.",
        )

    if write_name == "onWriteUpdateStream" and not _DIRTY_FLAG_USE.search(source.masked):
        _add(
            analysis, "LUA-SPEC-005", Severity.WARNING, write_fn.line,
            f"{spec} writes an update stream but never calls raiseDirtyFlags() / "
            "getNextDirtyFlag(): the server will not send updates to clients.",
        )


# -- outdated API ----------------------------------------------------------


def _audit_legacy_api(source: LuaSource, analysis: LuaAnalysis) -> None:
    is_specialization = bool(analysis.spec_classes)
    for rule in LEGACY_API_RULES:
        if rule.specializations_only and not is_specialization:
            continue
        matches = [
            match
            for match in rule.pattern.finditer(source.masked)
            if not _is_function_definition(source.masked, match.start())
        ]
        for match in matches[:_MAX_FINDINGS_PER_RULE]:
            _add(
                analysis, rule.rule_id, rule.severity, source.line_of(match.start()),
                f"{rule.summary}. Use {rule.replacement}. (Evidence: {rule.evidence}.)",
            )
        if len(matches) > _MAX_FINDINGS_PER_RULE:
            _add(
                analysis, rule.rule_id, rule.severity,
                source.line_of(matches[_MAX_FINDINGS_PER_RULE].start()),
                f"{len(matches) - _MAX_FINDINGS_PER_RULE} more occurrence(s) of the same problem.",
            )


def _is_function_definition(masked: str, offset: int) -> bool:
    """True when the match is the name in ``function Owner:name(`` (a definition, not a call)."""
    line_start = masked.rfind("\n", 0, offset) + 1
    return re.search(r"\bfunction\s+[\w.:]*$", masked[line_start:offset]) is not None


def _audit_deprecated_xml_paths(source: LuaSource, analysis: LuaAnalysis) -> None:
    table = deprecated_xml_paths()
    if not table:
        return
    reported = 0
    for literal in source.strings:
        entry = table.get(literal.value)
        if entry is None:
            continue
        # The vanilla pattern that *declares* a deprecation is not a use of it.
        if "checkDeprecatedXMLElements" in source.code[max(0, literal.offset - 240) : literal.offset]:
            continue
        if reported >= _MAX_FINDINGS_PER_RULE:
            break
        reported += 1
        era = f" ({entry.era})" if entry.era else ""
        replacement = f"use '{entry.new}'" if entry.new else "the element was removed"
        _add(
            analysis, "LUA-OLD-009", Severity.WARNING, literal.line,
            f"Vehicle XML path '{entry.old}' is deprecated{era}: {replacement}. "
            "(Evidence: vanilla XMLUtil.checkDeprecatedXMLElements.)",
        )


# ----------------------------------------------------------------------
# Mod-level audit: discovery + cross-file checks
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LuaTarget:
    """A Lua file queued for auditing."""

    path: Path
    rel: str  # posix path relative to the mod root, as found on disk
    origin: str  # where it was registered (for messages)
    from_moddesc: bool


@dataclass(slots=True)
class _AuditedFile:
    target: LuaTarget
    analysis: LuaAnalysis


class LuaAuditor:
    """Audit every Lua file a mod registers or loads."""

    def __init__(self, mod_root: Path) -> None:
        self.mod_root = mod_root.resolve()

    # -- public ------------------------------------------------------------

    def audit(self) -> ValidationReport:
        report = ValidationReport(target=self.mod_root / "(lua scripts)")
        if not self.mod_root.is_dir():
            report.add(Severity.ERROR, f"Mod folder does not exist: {self.mod_root}")
            return report

        multiplayer_supported = False
        queue: list[LuaTarget] = []
        mod_desc = self.mod_root / "modDesc.xml"
        if mod_desc.is_file():
            root = self._parse_mod_desc(mod_desc, report)
            if root is not None:
                multiplayer_supported = self._multiplayer_supported(root)
                queue.extend(self._targets_from_mod_desc(root, report))
        else:
            report.add(
                Severity.INFO,
                "No modDesc.xml found, so no Lua files are registered.",
                location="modDesc.xml",
            )

        audited = self._audit_queue(queue, report)

        if not audited:
            report.add(
                Severity.INFO,
                "No Lua files to audit (nothing registered in <extraSourceFiles> or "
                "custom specializations).",
            )
            return report

        self._report_files(audited, report)
        self._cross_file_checks(audited, report, multiplayer_supported)

        print(f"[LuaAuditor] {report.summary_line()}")
        return report

    # -- discovery ---------------------------------------------------------

    @staticmethod
    def _parse_mod_desc(path: Path, report: ValidationReport) -> ET.Element | None:
        try:
            return ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            report.add(
                Severity.WARNING,
                f"modDesc.xml could not be read, Lua files were not discovered: {exc}",
                location="modDesc.xml",
            )
            return None

    @staticmethod
    def _multiplayer_supported(root: ET.Element) -> bool:
        element = root.find("multiplayer")
        return element is not None and (element.get("supported") or "").lower() == "true"

    def _targets_from_mod_desc(
        self, root: ET.Element, report: ValidationReport
    ) -> list[LuaTarget]:
        """Every element with filename="*.lua" (sourceFile, specialization, type ...)."""
        targets: list[LuaTarget] = []

        def walk(element: ET.Element, trail: str) -> None:
            for child in element:
                child_trail = f"{trail}/{child.tag}" if trail else child.tag
                filename = (child.get("filename") or "").strip()
                if filename.lower().endswith(".lua"):
                    target = self._resolve_target(
                        filename,
                        origin=f"modDesc <{child_trail}>",
                        from_moddesc=True,
                        report=report,
                        base_dir=None,
                        location=None,
                    )
                    if target is not None:
                        targets.append(target)
                walk(child, child_trail)

        walk(root, "")
        return targets

    def _resolve_target(
        self,
        relative: str,
        *,
        origin: str,
        from_moddesc: bool,
        report: ValidationReport,
        base_dir: Path | None,
        location: str | None,
    ) -> LuaTarget | None:
        """Find the file on disk. modDesc problems are reported by ModDescValidator."""
        if is_engine_dollar_path(relative):
            return None  # game files, not part of the mod

        ok, detail = path_exists_case_sensitive(self.mod_root, relative)
        if ok:
            resolved = resolve_mod_relative_path(self.mod_root, relative)
            if resolved is not None and resolved.is_file():
                return LuaTarget(resolved, self._rel(resolved), origin, from_moddesc)

        # Wrong casing: still audit the content; report the path problem once.
        wrong_case = find_path_ignoring_case(self.mod_root, relative)
        if wrong_case is not None and wrong_case.is_file():
            if not from_moddesc:
                report.add(
                    Severity.ERROR,
                    f"source() path '{relative}' differs in letter case from the file on "
                    f"disk ({self._rel(wrong_case)}); this fails on Linux/dedicated servers.",
                    location=location,
                )
            return LuaTarget(wrong_case, self._rel(wrong_case), origin, from_moddesc)

        # Relative to the script that calls source()?
        if base_dir is not None:
            sibling = (base_dir / relative).resolve()
            if sibling.is_file():
                return LuaTarget(sibling, self._rel(sibling), origin, from_moddesc)

        if from_moddesc:
            report.add(
                Severity.INFO,
                f"Skipped '{relative}': file not found (reported in the [modDesc.xml] section).",
                location=origin,
            )
        else:
            report.add(
                Severity.ERROR,
                f"source() loads '{relative}' but that file does not exist in the mod.",
                location=location,
            )
        return None

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.mod_root).as_posix()
        except ValueError:
            return path.as_posix()

    # -- analysis ----------------------------------------------------------

    def _audit_queue(
        self, queue: list[LuaTarget], report: ValidationReport
    ) -> list[_AuditedFile]:
        audited: list[_AuditedFile] = []
        seen: set[Path] = set()
        pending = list(queue)

        while pending:
            target = pending.pop(0)
            key = target.path.resolve()
            if key in seen:
                continue
            seen.add(key)

            text = self._read(target, report)
            if text is None:
                continue
            analysis = analyze_lua(text)
            audited.append(_AuditedFile(target, analysis))

            # Follow literal source("....lua") calls so event files loaded by a
            # main script are audited as well.
            assert analysis.source is not None
            for relative, line in _source_references(analysis.source):
                follow = self._resolve_target(
                    relative,
                    origin=f"source() in {target.rel}:{line}",
                    from_moddesc=False,
                    report=report,
                    base_dir=target.path.parent,
                    location=f"{target.rel}:{line}",
                )
                if follow is not None:
                    pending.append(follow)

        return audited

    @staticmethod
    def _read(target: LuaTarget, report: ValidationReport) -> str | None:
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                return target.path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                report.add(Severity.ERROR, f"Cannot read Lua file: {exc}", location=target.rel)
                return None
        return None

    # -- reporting -----------------------------------------------------------

    def _report_files(self, audited: list[_AuditedFile], report: ValidationReport) -> None:
        from_moddesc = sum(1 for item in audited if item.target.from_moddesc)
        report.add(
            Severity.INFO,
            f"Audited {len(audited)} Lua file(s): {from_moddesc} registered in modDesc.xml, "
            f"{len(audited) - from_moddesc} loaded through source().",
        )

        for item in audited:
            analysis = item.analysis
            rel = item.target.rel
            kinds: list[str] = []
            if analysis.event_classes:
                kinds.append(f"{len(analysis.event_classes)} network event(s)")
            if analysis.spec_classes:
                kinds.append(f"{len(analysis.spec_classes)} specialization(s)")
            detail = ", ".join(kinds) if kinds else "plain script"
            report.add(Severity.INFO, f"{rel} - {detail} ({item.target.origin})", location=rel)

            findings = sorted(analysis.findings, key=lambda f: (f.line, f.rule_id))
            for finding in findings:
                report.add(
                    finding.severity,
                    f"{finding.rule_id}: {finding.message}",
                    location=f"{rel}:{finding.line}",
                )
            if not any(f.severity in (Severity.ERROR, Severity.WARNING) for f in findings):
                report.add(Severity.OK, f"No problems found in {rel}.", location=rel)

    def _cross_file_checks(
        self,
        audited: list[_AuditedFile],
        report: ValidationReport,
        multiplayer_supported: bool,
    ) -> None:
        # Events that nothing ever creates.
        for item in audited:
            for name, line in item.analysis.event_classes.items():
                if not _event_is_used(name, audited):
                    report.add(
                        Severity.INFO,
                        f"LUA-EVT-007: Event '{name}' is never created with {name}.new() or "
                        f"{name}.sendEvent() in the audited files, so it is never sent "
                        "(or it is created from a file that is not registered).",
                        location=f"{item.target.rel}:{line}",
                    )

        # Network code in a mod that does not declare multiplayer support.
        network_files = [item for item in audited if item.analysis.uses_network_api]
        if network_files and not multiplayer_supported:
            names = ", ".join(item.target.rel for item in network_files[:3])
            report.add(
                Severity.WARNING,
                "LUA-MP-001: network code was found (" + names + ") but modDesc.xml does not "
                'declare <multiplayer supported="true" />, so the mod cannot be used in '
                "multiplayer sessions.",
                location="modDesc.xml",
            )


def _event_is_used(name: str, audited: list[_AuditedFile]) -> bool:
    """True when code outside the event class creates it or calls its sendEvent().

    Calls inside the event's own methods (e.g. the relay in run() or the
    ``X.new`` inside ``X.sendEvent``) do not count: they only exist because
    something else sent the event in the first place.
    """
    use = re.compile(rf"\b{re.escape(name)}\s*\.\s*(?:new|sendEvent)\s*\(")
    for item in audited:
        source = item.analysis.source
        if source is None:
            continue
        own_spans = [
            (func.body_offset, func.body_offset + len(func.body))
            for func in source.functions_of(name)
        ]
        for match in use.finditer(source.masked):
            if _is_function_definition(source.masked, match.start()):
                continue
            if any(start <= match.start() < end for start, end in own_spans):
                continue
            return True
    return False


def _source_references(source: LuaSource) -> list[tuple[str, int]]:
    """Literal ``.lua`` paths inside ``source(...)`` calls: (path, line)."""
    masked = source.masked
    references: list[tuple[str, int]] = []
    for call in _SOURCE_CALL.finditer(masked):
        open_index = call.end() - 1
        depth = 0
        close_index = -1
        for index in range(open_index, len(masked)):
            char = masked[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close_index = index
                    break
        if close_index == -1:
            continue
        for literal in source.strings:
            if open_index < literal.offset < close_index and literal.value.lower().endswith(".lua"):
                references.append((literal.value, literal.line))
    return references
