"""Mod & Lua Auditor tab: modDesc.xml, vehicle / specialization and Lua checks."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from app.validators.pipeline import ValidationSuiteResult, run_xml_validation_suite


class XmlValidatorTab(ctk.CTkFrame):
    """Browse a mod folder and run the full XML + Lua validation suite."""

    def __init__(self, master: ctk.CTkBaseClass, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._mod_root: Path | None = None
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkLabel(
            self,
            text="Mod & Lua Auditor",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))

        hint = ctk.CTkLabel(
            self,
            text=(
                "Select a mod root folder. Runs [modDesc.xml] checks first, then "
                "[Vehicle Validation] (type attribute, custom vehicleTypes, and "
                "XML blocks vs registered specializations), then [Lua Audit]: every "
                ".lua file registered in modDesc.xml (extraSourceFiles, specializations, "
                "events ...) and every file it loads with source() is checked for "
                "multiplayer sync problems and outdated API calls."
            ),
            wraplength=720,
            justify="left",
            anchor="w",
            text_color=("gray30", "gray70"),
        )
        hint.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=2, column=0, sticky="ew", padx=16, pady=4)
        toolbar.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            toolbar,
            text="Browse mod folder…",
            width=160,
            command=self._browse_folder,
        ).grid(row=0, column=0, padx=(0, 8))

        self.path_var = ctk.StringVar(value="No folder selected")
        ctk.CTkLabel(
            toolbar,
            textvariable=self.path_var,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=4)

        ctk.CTkButton(
            toolbar,
            text="Validate",
            width=120,
            fg_color="#1F6AA5",
            command=self._run_validation,
        ).grid(row=0, column=2, padx=(8, 0))

        self.results = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=13),
        )
        self.results.grid(row=3, column=0, sticky="nsew", padx=16, pady=(8, 8))
        self.results.insert(
            "1.0",
            "Results will appear here.\n\n"
            "Tip: samples/sample_ok_mod and samples/sample_broken_mod cover "
            "modDesc, vehicle specialization and Lua cases.",
        )
        self.results.configure(state="disabled")

        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(
            self,
            textvariable=self.status_var,
            anchor="w",
            font=ctk.CTkFont(size=12),
        ).grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 12))

    def _browse_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Select FS25 mod root folder")
        if not chosen:
            return
        self._mod_root = Path(chosen)
        self.path_var.set(str(self._mod_root))
        self.status_var.set(f"Selected: {self._mod_root.name}")
        print(f"[XML Validator] Mod root set to: {self._mod_root}")

    def _run_validation(self) -> None:
        if self._mod_root is None:
            self.status_var.set("Select a mod folder first.")
            self._set_results("ERROR: No mod folder selected.\n")
            return

        print(f"[XML Validator] Running suite for: {self._mod_root}")
        self.status_var.set("Validating…")
        self.update_idletasks()

        suite = run_xml_validation_suite(self._mod_root)
        self._render_suite(suite)
        self.status_var.set(suite.summary_line())

    def _render_suite(self, suite: ValidationSuiteResult) -> None:
        self._set_results(suite.format_text())

    def _set_results(self, text: str) -> None:
        self.results.configure(state="normal")
        self.results.delete("1.0", "end")
        self.results.insert("1.0", text)
        self.results.configure(state="disabled")
