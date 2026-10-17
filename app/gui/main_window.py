"""Application main window with tabbed workspace."""

from __future__ import annotations

import customtkinter as ctk

from app import __app_name__, __version__
from app.gui.tabs.lua_generator_tab import LuaGeneratorTab
from app.gui.tabs.map_helper_tab import MapHelperTab
from app.gui.tabs.terrafarm_tab import TerraFarmTab
from app.gui.tabs.xml_validator_tab import XmlValidatorTab


TAB_VALIDATOR = "Mod & Lua Auditor"
TAB_TERRAFARM = "TerraFarm Generator"
TAB_MAP_HELPER = "Map Helper"
TAB_LUA_GENERATOR = "Lua Generator"

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800
MIN_WIDTH = 1000
MIN_HEIGHT = 700


class MainWindow(ctk.CTk):
    """Root window for FS25 Mod & Map Doctor."""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"{__app_name__} v{__version__}")
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._apply_centered_geometry(DEFAULT_WIDTH, DEFAULT_HEIGHT)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Title on the left, tagline on the right, in one compact row.
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(12, 6))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text=__app_name__,
            font=ctk.CTkFont(size=22, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Audit mods & Lua  |  Generate TerraFarm configs  |  Help build maps  |  Lua templates",
            anchor="e",
            text_color=("gray30", "gray70"),
        ).grid(row=0, column=1, sticky="e", padx=(16, 0))

        tabs = ctk.CTkTabview(self)
        tabs.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        tabs.add(TAB_VALIDATOR)
        tabs.add(TAB_TERRAFARM)
        tabs.add(TAB_MAP_HELPER)
        tabs.add(TAB_LUA_GENERATOR)

        XmlValidatorTab(tabs.tab(TAB_VALIDATOR)).pack(fill="both", expand=True)
        TerraFarmTab(tabs.tab(TAB_TERRAFARM)).pack(fill="both", expand=True)
        MapHelperTab(tabs.tab(TAB_MAP_HELPER)).pack(fill="both", expand=True)
        LuaGeneratorTab(tabs.tab(TAB_LUA_GENERATOR)).pack(fill="both", expand=True)

        print(f"[{__app_name__}] UI ready (v{__version__})")

    def _apply_centered_geometry(self, width: int, height: int) -> None:
        """Size the window and center it, clamped to the visible screen."""
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(width, screen_w - 40)
        height = min(height, screen_h - 80)
        pos_x = max((screen_w - width) // 2, 0)
        pos_y = max((screen_h - height) // 2 - 20, 0)
        self.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
