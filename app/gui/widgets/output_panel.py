"""Right-hand "Generated XML" panel: output tabs plus Copy / Save buttons.

The panel knows nothing about what is generated. A tab passes it one
``OutputDocument`` per output tab; Copy and Save always act on the tab that is
currently visible. Status messages go back through the ``on_status`` callback
so the owning tab can show them in its own status bar.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk


@dataclass(frozen=True, slots=True)
class OutputDocument:
    """Text of one generated file and the file name suggested when saving it."""

    text: str
    filename: str


@dataclass(frozen=True, slots=True)
class UnavailableDocument:
    """A tab whose file was deliberately not generated (e.g. an option is turned off).

    ``box_text`` is shown inside the tab; ``status`` is reported (as an error)
    when the user presses Copy or Save on it.
    """

    box_text: str
    status: str


# File kinds the panel can save: suffix -> (name used in the button, label in the file dialog).
_FILE_KINDS: dict[str, tuple[str, str]] = {
    ".xml": ("XML", "XML files"),
    ".lua": ("Lua", "Lua files"),
}

# What ``XmlOutputPanel.show`` accepts for one tab.
PanelContent = OutputDocument | UnavailableDocument | None

# Called as on_status(message) or on_status(message, error=True).
StatusCallback = Callable[..., None]


class XmlOutputPanel(ctk.CTkFrame):
    """Tabbed text preview with "Copy to Clipboard" and "Save as <kind> file" buttons.

    Despite the name the panel also handles Lua: the save button label and the file
    dialog follow the suffix of the visible document (``.xml`` -> "Save as XML file",
    ``.lua`` -> "Save as Lua file").
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        tab_names: Sequence[str],
        empty_messages: Mapping[str, str],
        on_status: StatusCallback,
        *,
        title: str = "Generated XML",
        save_dialog_title: str = "Save XML file",
        log_prefix: str = "Output",
        **kwargs,
    ) -> None:
        super().__init__(master, corner_radius=10, **kwargs)
        self._tab_names = tuple(tab_names)
        self._empty_messages = dict(empty_messages)
        self._on_status = on_status
        self._save_dialog_title = save_dialog_title
        self._log_prefix = log_prefix
        self._documents: dict[str, PanelContent] = {name: None for name in tab_names}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))

        # The command runs after the user clicks a tab, so the save label can follow it.
        self.tabs = ctk.CTkTabview(self, height=200, command=self._refresh_save_label)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.boxes: dict[str, ctk.CTkTextbox] = {}
        for name in self._tab_names:
            self.tabs.add(name)
            box = ctk.CTkTextbox(
                self.tabs.tab(name),
                font=ctk.CTkFont(family="Consolas", size=12),
                wrap="none",
            )
            box.pack(fill="both", expand=True)
            self.boxes[name] = box

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
        buttons.grid_columnconfigure((0, 1), weight=1, uniform="outbtn")

        ctk.CTkButton(
            buttons, text="Copy to Clipboard", height=34, command=self.copy_active
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._save_button = ctk.CTkButton(
            buttons,
            text=self._DEFAULT_SAVE_LABEL,
            height=34,
            fg_color=("gray55", "gray30"),
            hover_color=("gray45", "gray40"),
            command=self.save_active,
        )
        self._save_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.clear()

    _DEFAULT_SAVE_LABEL = "Save as XML file"

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def show(self, documents: Mapping[str, PanelContent]) -> None:
        """Replace the content of every tab named in ``documents``.

        ``None`` restores the tab's empty message; an ``UnavailableDocument``
        shows its explanation and blocks Copy / Save for that tab.
        """
        for name, document in documents.items():
            if name not in self.boxes:
                raise KeyError(f"Unknown output tab: {name}")
            self._documents[name] = document
            if isinstance(document, OutputDocument):
                text = document.text
            elif isinstance(document, UnavailableDocument):
                text = document.box_text
            else:
                text = self._empty_messages.get(name, "")
            self._set_box(name, text)
        self._refresh_save_label()

    def clear(self) -> None:
        """Back to the initial 'nothing generated yet' state."""
        for name in self._tab_names:
            self._documents[name] = None
            self._set_box(name, self._empty_messages.get(name, ""))
        self._refresh_save_label()

    def select(self, tab_name: str) -> None:
        """Show ``tab_name``.

        CTkTabview.set() schedules a delayed clean-up that hides every tab
        except the one it was called with. Skipping the call when the tab is
        already visible avoids stacking those timers.
        """
        if self.tabs.get() != tab_name:
            self.tabs.set(tab_name)
        self._refresh_save_label()

    def save_label(self) -> str:
        """Current text of the save button."""
        return self._save_button.cget("text")

    def _refresh_save_label(self) -> None:
        """Make the save button say "Save as Lua file" / "Save as XML file" for the visible tab."""
        document = self._documents.get(self.tabs.get())
        kind = "XML"
        if isinstance(document, OutputDocument):
            kind = _FILE_KINDS.get(Path(document.filename).suffix.lower(), ("", ""))[0] or "XML"
        self._save_button.configure(text=f"Save as {kind} file")

    def active_tab(self) -> str:
        return self.tabs.get()

    def document(self, tab_name: str) -> OutputDocument | None:
        """The exportable document of ``tab_name`` (None if empty or unavailable)."""
        document = self._documents.get(tab_name)
        return document if isinstance(document, OutputDocument) else None

    def active_document(self) -> OutputDocument | None:
        """Exportable document of the visible tab, or None (with a status message)."""
        content = self._documents.get(self.active_tab())
        if isinstance(content, OutputDocument):
            return content
        if isinstance(content, UnavailableDocument):
            self._on_status(content.status, error=True)
        else:
            self._on_status(
                f'Nothing to export in "{self.active_tab()}" yet. Generate first.', error=True
            )
        return None

    def _set_box(self, tab_name: str, text: str) -> None:
        box = self.boxes[tab_name]
        box.delete("1.0", "end")
        box.insert("1.0", text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def copy_active(self) -> None:
        document = self.active_document()
        if document is None:
            return
        self.clipboard_clear()
        self.clipboard_append(document.text)
        self.update_idletasks()
        self._on_status(f"Copied {document.filename} to the clipboard.")
        print(f"[{self._log_prefix}] Copied {document.filename} to clipboard")

    def save_active(self) -> None:
        document = self.active_document()
        if document is None:
            return

        suffix = Path(document.filename).suffix.lower()
        if suffix not in _FILE_KINDS:
            suffix = ".xml"
        chosen = filedialog.asksaveasfilename(
            title=self._save_dialog_title,
            defaultextension=suffix,
            initialfile=document.filename,
            filetypes=[(_FILE_KINDS[suffix][1], f"*{suffix}"), ("All files", "*.*")],
        )
        if not chosen:
            self._on_status("Save cancelled.")
            return

        path = Path(chosen)
        try:
            path.write_text(document.text, encoding="utf-8", newline="\n")
        except OSError as exc:
            self._on_status(f"Could not save file: {exc}", error=True)
            print(f"[{self._log_prefix}] Save failed: {exc}")
            return

        self._on_status(f"Saved {path.name} to {path.parent}.")
        print(f"[{self._log_prefix}] Saved {document.filename} to {path}")
