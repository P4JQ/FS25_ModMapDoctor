#!/usr/bin/env python3
"""Entry point for FS25 Mod & Map Doctor.

Run from the project root:

    python main.py
    python main.py --validate samples/sample_ok_mod
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_project_on_path() -> None:
    """Allow `import app` when launching via `python main.py`."""
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def run_cli_validate(mod_root: Path) -> int:
    """Headless validation (modDesc, vehicles, Lua) without opening the GUI."""
    from app.validators.pipeline import run_xml_validation_suite

    suite = run_xml_validation_suite(mod_root)
    print(suite.format_text())
    return 0 if suite.passed else 1


def run_gui() -> int:
    from app.gui.main_window import MainWindow

    app = MainWindow()
    app.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    _ensure_project_on_path()

    parser = argparse.ArgumentParser(
        description="FS25 Mod & Map Doctor — validate and generate FS25 mod assets.",
    )
    parser.add_argument(
        "--validate",
        metavar="MOD_FOLDER",
        type=Path,
        help="Validate modDesc.xml, vehicles and Lua scripts in MOD_FOLDER without opening the GUI.",
    )
    args = parser.parse_args(argv)

    if args.validate is not None:
        return run_cli_validate(args.validate.resolve())

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
