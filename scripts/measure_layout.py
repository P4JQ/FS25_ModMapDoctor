"""Print requested heights of the TerraFarm form cards (layout tuning helper)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import customtkinter as ctk  # noqa: E402

from app.gui.main_window import MainWindow  # noqa: E402
from app.gui.tabs.terrafarm_tab import TerraFarmTab  # noqa: E402
from app.gui.widgets import SectionCard  # noqa: E402


def find(widget, cls):
    for child in widget.winfo_children():
        if isinstance(child, cls):
            return child
        found = find(child, cls)
        if found is not None:
            return found
    return None


window = MainWindow()
for child in window.winfo_children():
    if isinstance(child, ctk.CTkTabview):
        child.set("TerraFarm Generator")
for _ in range(10):
    window.update_idletasks()
    window.update()

tab = find(window, TerraFarmTab)
print(f"window {window.winfo_width()}x{window.winfo_height()}")
print(f"form visible height: {tab.form_panel._parent_canvas.winfo_height()}")
print(f"form visible width : {tab.form_panel._parent_canvas.winfo_width()}")
for child in tab.form_panel.winfo_children():
    if isinstance(child, SectionCard):
        print(f"card {child.header.winfo_children()[0].cget('text'):<14} "
              f"req={child.winfo_reqheight():>4}px  width={child.winfo_width()}px")
print(f"tab header+action chrome: tab height={tab.winfo_height()}")
window.destroy()
