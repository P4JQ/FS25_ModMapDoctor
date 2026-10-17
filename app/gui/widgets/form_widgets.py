"""Form building blocks: section cards, validated entries, XYZ vector fields.

Entries intentionally do NOT use a ``textvariable``: CustomTkinter disables
placeholder text when one is attached, and placeholders are what show the
default values to the user.
"""

from __future__ import annotations

import math
from typing import Literal

import customtkinter as ctk

# "int" = whole number >= 1, "uint" = whole number >= 0, "float" = number >= 0.
EntryKind = Literal["text", "int", "uint", "float"]

_MUTED = ("gray40", "gray60")
_INVALID_BORDER = "#E74C3C"


def format_number(value: float) -> str:
    """Format a float for XML: no trailing zeros, no '-0', no exponent."""
    if value == 0:
        return "0"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _parse_float(raw: str, field_name: str) -> float:
    try:
        number = float(raw.replace(",", "."))
    except ValueError:
        raise ValueError(f"{field_name}: '{raw}' is not a valid number.") from None
    if math.isnan(number) or math.isinf(number):
        raise ValueError(f"{field_name}: '{raw}' is not a finite number.")
    return number


class SectionCard(ctk.CTkFrame):
    """Rounded card with a title row and a ``body`` frame.

    ``header`` is the title row; callers may grid extra widgets (for example a
    checkbox) into its column 1 so they sit on the same line as the title.
    """

    def __init__(self, master: ctk.CTkBaseClass, title: str, **kwargs) -> None:
        super().__init__(master, corner_radius=10, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 0))
        self.header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.header,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 12))


class LabeledEntry(ctk.CTkFrame):
    """Label above an entry with placeholder, validation, and enable/required state."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        label: str,
        placeholder: str = "",
        kind: EntryKind = "text",
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self._base_label = label
        self._kind: EntryKind = kind
        self._required = False
        self._enabled = True
        self._placeholder = placeholder

        self._label = ctk.CTkLabel(
            self, text=label, anchor="w", height=18, font=ctk.CTkFont(size=12)
        )
        self._label.grid(row=0, column=0, sticky="ew", pady=(0, 2))

        self._entry = ctk.CTkEntry(self, placeholder_text=placeholder, height=30)
        self._entry.grid(row=1, column=0, sticky="ew")

        self._default_border = self._entry.cget("border_color")
        self._default_text_color = self._entry.cget("text_color")
        self._default_label_color = self._label.cget("text_color")
        self._entry.bind("<Key>", lambda _e: self.clear_invalid(), add="+")

    # -- state -----------------------------------------------------------

    def configure_field(
        self,
        *,
        enabled: bool,
        required: bool = False,
        placeholder: str | None = None,
    ) -> None:
        """Set availability, required marker, and placeholder in one call."""
        self._enabled = enabled
        self._required = required and enabled
        if placeholder is not None:
            self._placeholder = placeholder

        # Tk ignores text changes on a disabled entry, so always re-enable first.
        self._entry.configure(state="normal")
        self._entry.configure(placeholder_text=self._placeholder if enabled else "n/a")

        suffix = " *" if self._required else ""
        self._label.configure(text=f"{self._base_label}{suffix}")

        if enabled:
            self._entry.configure(text_color=self._default_text_color)
            self._label.configure(text_color=self._default_label_color)
        else:
            self._entry.configure(text_color=_MUTED)
            self._label.configure(text_color=_MUTED)
            self.clear_invalid()
            self._entry.configure(state="disabled")

    def mark_invalid(self) -> None:
        self._entry.configure(border_color=_INVALID_BORDER)

    def clear_invalid(self) -> None:
        self._entry.configure(border_color=self._default_border)

    # -- value access ----------------------------------------------------

    def raw(self) -> str:
        return self._entry.get().strip() if self._enabled else ""

    def set(self, text: str) -> None:
        self._entry.configure(state="normal")
        self._entry.delete(0, "end")
        if text:
            self._entry.insert(0, text)
        else:
            self._restore_placeholder()
        if not self._enabled:
            self._entry.configure(state="disabled")
        self.clear_invalid()

    def _restore_placeholder(self) -> None:
        """Show the placeholder again after the entry was emptied in code.

        CustomTkinter only re-shows it on delete() when the entry is not
        focused, and a click on a button does not take focus away. Re-applying
        placeholder_text through configure() re-activates it reliably.
        """
        self._entry.configure(placeholder_text=self._placeholder if self._enabled else "n/a")

    def clear(self) -> None:
        self.set("")

    def value(self) -> str:
        """Return the validated text ('' when empty or disabled).

        Raises:
            ValueError: required value missing, or text is not a valid
                integer/float for this field's kind.
        """
        text = self.raw()
        if not text:
            if self._required:
                self.mark_invalid()
                raise ValueError(f"{self._base_label} is required.")
            return ""

        try:
            if self._kind in ("int", "uint"):
                try:
                    number = int(text)
                except ValueError:
                    raise ValueError(
                        f"{self._base_label}: '{text}' is not a whole number."
                    ) from None
                minimum = 1 if self._kind == "int" else 0
                if number < minimum:
                    raise ValueError(f"{self._base_label}: must be {minimum} or greater.")
                return str(number)

            if self._kind == "float":
                number = _parse_float(text, self._base_label)
                if number < 0:
                    raise ValueError(f"{self._base_label}: must not be negative.")
                return format_number(number)
        except ValueError:
            self.mark_invalid()
            raise

        return text


class LabeledCombo(ctk.CTkFrame):
    """Label above an editable drop-down (pick a suggestion or type any value).

    A combo box has no placeholder, so it starts on ``default`` instead, which
    also serves as the "empty" state restored by ``reset()``.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        label: str,
        values: tuple[str, ...] | list[str],
        default: str = "",
        required: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self._base_label = label
        self._default = default
        self._required = required

        self._label = ctk.CTkLabel(
            self,
            text=f"{label} *" if required else label,
            anchor="w",
            height=18,
            font=ctk.CTkFont(size=12),
        )
        self._label.grid(row=0, column=0, sticky="ew", pady=(0, 2))

        self._combo = ctk.CTkComboBox(self, values=list(values), height=30)
        self._combo.grid(row=1, column=0, sticky="ew")
        self._combo.set(default)
        self._default_border = self._combo.cget("border_color")
        # The inner entry is what receives typing; clear the red border on edit.
        inner = getattr(self._combo, "_entry", None)
        if inner is not None:
            inner.bind("<Key>", lambda _e: self.clear_invalid(), add="+")

    def mark_invalid(self) -> None:
        self._combo.configure(border_color=_INVALID_BORDER)

    def clear_invalid(self) -> None:
        self._combo.configure(border_color=self._default_border)

    def set(self, text: str) -> None:
        self._combo.set(text)
        self.clear_invalid()

    def reset(self) -> None:
        self.set(self._default)

    def value(self) -> str:
        """Return the stripped text; raises ValueError when required and empty."""
        text = self._combo.get().strip()
        if not text and self._required:
            self.mark_invalid()
            raise ValueError(f"{self._base_label} is required.")
        return text


class Vector3Field(ctk.CTkFrame):
    """One labelled row of three aligned X / Y / Z entries -> one 'x y z' string.

    Rows share a column layout with ``build_header()``, so several rows can be
    stacked under a single X / Y / Z header.
    """

    LABEL_WIDTH = 92
    _AXES = ("X", "Y", "Z")

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        label: str,
        placeholders: tuple[str, str, str] = ("0", "0", "0"),
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._base_label = label
        self._enabled = True

        self._configure_columns(self)
        self._label = ctk.CTkLabel(self, text=label, anchor="w", font=ctk.CTkFont(size=12))
        self._label.grid(row=0, column=0, sticky="w")

        self._entries: list[ctk.CTkEntry] = []
        for index in range(len(self._AXES)):
            entry = ctk.CTkEntry(self, placeholder_text=placeholders[index], height=30)
            entry.grid(row=0, column=index + 1, sticky="ew", padx=self._axis_padx(index))
            entry.bind("<Key>", lambda _e: self.clear_invalid(), add="+")
            self._entries.append(entry)

        self._default_border = self._entries[0].cget("border_color")
        self._default_text_color = self._entries[0].cget("text_color")
        self._default_label_color = self._label.cget("text_color")
        self._placeholders = placeholders

    @classmethod
    def _configure_columns(cls, frame: ctk.CTkFrame) -> None:
        """Shared column layout so a header row and value rows line up."""
        frame.grid_columnconfigure(0, minsize=cls.LABEL_WIDTH)
        for column in range(1, len(cls._AXES) + 1):
            frame.grid_columnconfigure(column, weight=1, uniform="xyz")

    @staticmethod
    def _axis_padx(index: int) -> tuple[int, int]:
        return (0 if index == 0 else 6, 0)

    @classmethod
    def build_header(cls, master: ctk.CTkBaseClass) -> ctk.CTkFrame:
        """Return an 'X  Y  Z' header row aligned with Vector3Field rows."""
        header = ctk.CTkFrame(master, fg_color="transparent")
        cls._configure_columns(header)
        for index, axis in enumerate(cls._AXES):
            ctk.CTkLabel(
                header,
                text=axis,
                height=16,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=_MUTED,
            ).grid(row=0, column=index + 1, sticky="ew", padx=cls._axis_padx(index))
        return header

    def configure_field(self, *, enabled: bool) -> None:
        self._enabled = enabled
        for index, entry in enumerate(self._entries):
            entry.configure(state="normal")
            entry.configure(placeholder_text=self._placeholders[index] if enabled else "\u2013")
            if enabled:
                entry.configure(text_color=self._default_text_color)
            else:
                entry.configure(text_color=_MUTED)
                entry.configure(state="disabled")
        color = self._default_label_color if enabled else _MUTED
        self._label.configure(text_color=color)
        if not enabled:
            self.clear_invalid()

    def mark_invalid(self) -> None:
        for entry in self._entries:
            entry.configure(border_color=_INVALID_BORDER)

    def clear_invalid(self) -> None:
        for entry in self._entries:
            entry.configure(border_color=self._default_border)

    def clear(self) -> None:
        for index, entry in enumerate(self._entries):
            entry.configure(state="normal")
            entry.delete(0, "end")
            # Re-apply the placeholder explicitly (see LabeledEntry._restore_placeholder).
            entry.configure(
                placeholder_text=self._placeholders[index] if self._enabled else "\u2013"
            )
            if not self._enabled:
                entry.configure(state="disabled")
        self.clear_invalid()

    def value(self) -> str:
        """Return 'x y z', '' if every axis is empty, or raise ValueError.

        Empty axes in a partly filled vector become 0.
        """
        if not self._enabled:
            return ""

        raw_parts = [entry.get().strip() for entry in self._entries]
        if not any(raw_parts):
            return ""

        name = self._base_label.split(" (")[0]
        numbers: list[str] = []
        for axis, text in zip(self._AXES, raw_parts, strict=True):
            if not text:
                numbers.append("0")
                continue
            try:
                numbers.append(format_number(_parse_float(text, f"{name} {axis}")))
            except ValueError:
                self.mark_invalid()
                raise
        return " ".join(numbers)
