"""Lightweight Lua scanner used by the Lua auditor.

This is intentionally *not* a full Lua parser. It does just enough to make
regex-based static checks reliable:

* comments and string contents are blanked out (offsets and line numbers are
  preserved), so a ``streamWriteBool`` inside a comment or string never counts;
* function definitions are located with their dotted name, line and body, by
  counting ``function`` / ``if`` / ``do`` / ``repeat`` blocks against their
  ``end`` / ``until``.

Everything works on plain text and never executes any Lua.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field

_LONG_BRACKET = re.compile(r"\[(=*)\[")
_BLOCK_TOKEN = re.compile(r"\b(function|if|do|repeat|until|end)\b")
_FUNCTION_NAME = re.compile(r"\s*([A-Za-z_]\w*(?:\s*[.:]\s*[A-Za-z_]\w*)*)\s*\(")


@dataclass(frozen=True, slots=True)
class LuaString:
    """A string literal: its text and where it starts."""

    value: str
    offset: int
    line: int


@dataclass(slots=True)
class LuaFunction:
    """A named function definition (``function Owner:method(...)``)."""

    full_name: str
    owner: str  # "" for plain/local functions
    method: str
    is_method: bool  # defined with ':' (implicit self)
    line: int
    body: str = ""  # masked text between the parameter list and the closing 'end'
    body_offset: int = 0
    closed: bool = False


@dataclass(slots=True)
class LuaSource:
    """A scanned Lua file."""

    text: str
    masked: str  # comments and string contents blanked
    code: str  # only comments blanked (string literals kept, for name regexes)
    strings: list[LuaString]
    functions: list[LuaFunction]
    _newlines: list[int] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------

    @classmethod
    def from_text(cls, text: str) -> LuaSource:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        newlines = [i for i, ch in enumerate(text) if ch == "\n"]
        masked, code, raw_strings = _mask(text)
        strings = [
            LuaString(value=value, offset=offset, line=bisect_right(newlines, offset) + 1)
            for value, offset in raw_strings
        ]
        source = cls(
            text=text,
            masked=masked,
            code=code,
            strings=strings,
            functions=[],
            _newlines=newlines,
        )
        source.functions = _find_functions(source)
        return source

    def line_of(self, offset: int) -> int:
        """1-based line number of a character offset."""
        return bisect_right(self._newlines, offset) + 1

    def find_function(self, owner: str, method: str) -> LuaFunction | None:
        """First function named ``owner.method`` or ``owner:method``."""
        for func in self.functions:
            if func.owner == owner and func.method == method:
                return func
        return None

    def functions_of(self, owner: str) -> list[LuaFunction]:
        return [f for f in self.functions if f.owner == owner]


# ----------------------------------------------------------------------
# Masking
# ----------------------------------------------------------------------


def _mask(text: str) -> tuple[str, str, list[tuple[str, int]]]:
    """Return (masked, code, strings).

    ``masked`` has comments and string contents blanked; ``code`` has only the
    comments blanked. Offsets and line breaks are preserved in both.
    """
    chars = list(text)
    code_chars = list(text)
    strings: list[tuple[str, int]] = []
    length = len(text)

    def blank(start: int, end: int, *, comment: bool = False) -> None:
        for index in range(start, min(end, length)):
            if chars[index] != "\n":
                chars[index] = " "
                if comment:
                    code_chars[index] = " "

    i = 0
    while i < length:
        ch = text[i]

        if ch == "-" and text.startswith("--", i):
            long_match = _LONG_BRACKET.match(text, i + 2)
            if long_match:
                close = "]" + "=" * len(long_match.group(1)) + "]"
                found = text.find(close, long_match.end())
                end = length if found == -1 else found + len(close)
            else:
                found = text.find("\n", i)
                end = length if found == -1 else found
            blank(i, end, comment=True)
            i = end
            continue

        if ch in ('"', "'"):
            j = i + 1
            while j < length and text[j] != ch and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j, length)
            strings.append((text[i + 1 : j], i + 1))
            blank(i + 1, j)
            i = j + 1
            continue

        if ch == "[":
            long_match = _LONG_BRACKET.match(text, i)
            if long_match:
                close = "]" + "=" * len(long_match.group(1)) + "]"
                found = text.find(close, long_match.end())
                end = length if found == -1 else found + len(close)
                content_end = length if found == -1 else found
                strings.append((text[long_match.end() : content_end], long_match.end()))
                blank(i, end)
                i = end
                continue

        i += 1

    return "".join(chars), "".join(code_chars), strings


# ----------------------------------------------------------------------
# Function discovery
# ----------------------------------------------------------------------


def _find_functions(source: LuaSource) -> list[LuaFunction]:
    """Locate named functions and their bodies by pairing blocks with 'end'."""
    masked = source.masked
    functions: list[LuaFunction] = []
    # Stack entries: a LuaFunction for 'function' blocks, None for other blocks.
    stack: list[LuaFunction | None] = []

    for token in _BLOCK_TOKEN.finditer(masked):
        word = token.group(1)

        if word == "function":
            name_match = _FUNCTION_NAME.match(masked, token.end())
            if name_match is None:
                stack.append(None)  # anonymous function
                continue
            full_name = re.sub(r"\s+", "", name_match.group(1))
            parts = re.split(r"[.:]", full_name)
            method = parts[-1]
            owner = full_name[: -(len(method) + 1)] if len(parts) > 1 else ""
            close_paren = masked.find(")", name_match.end())
            func = LuaFunction(
                full_name=full_name,
                owner=owner,
                method=method,
                is_method=":" in full_name,
                line=source.line_of(token.start()),
                body_offset=(close_paren + 1) if close_paren != -1 else name_match.end(),
            )
            functions.append(func)
            stack.append(func)
        elif word in ("if", "do", "repeat"):
            stack.append(None)
        else:  # 'end' or 'until'
            if not stack:
                continue  # unbalanced; ignore rather than guess
            entry = stack.pop()
            if entry is not None:
                entry.body = masked[entry.body_offset : token.start()]
                entry.closed = True

    return functions
