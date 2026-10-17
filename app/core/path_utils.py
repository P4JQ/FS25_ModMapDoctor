"""Cross-platform path helpers with case-sensitive verification.

Windows NTFS is case-insensitive by default, but dedicated Linux servers
and Giants packaging treat paths as case-sensitive. These helpers walk
each path component against the real directory listing so wrong casing
is caught on Windows before upload.
"""

from __future__ import annotations

from pathlib import Path

# Game / engine dollar-path prefixes that live outside the mod folder.
_ENGINE_PATH_PREFIXES = (
    "$data/",
    "$dataS/",
    "$dataS",
    "$data",
)


def is_engine_dollar_path(relative: str) -> bool:
    """Return True if path points into game data, not the mod root."""
    normalized = relative.replace("\\", "/").lstrip("/")
    lower = normalized.lower()
    return any(lower.startswith(p.lower()) for p in _ENGINE_PATH_PREFIXES)


def normalize_mod_relative(relative: str) -> str:
    """Normalize separators and strip leading ./ or /."""
    cleaned = relative.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def path_exists_case_sensitive(root: Path, relative: str) -> tuple[bool, str]:
    """Check that *relative* exists under *root* with exact casing.

    Returns:
        (True, resolved_posix_path) on success.
        (False, human-readable reason) on failure.
    """
    root = root.resolve()
    relative = normalize_mod_relative(relative)

    if not relative:
        return False, "Empty relative path"

    if is_engine_dollar_path(relative):
        return True, f"(engine path skipped) {relative}"

    current = root
    parts = [p for p in relative.split("/") if p and p != "."]

    if not parts:
        return False, "Empty relative path after normalization"

    built: list[str] = []
    for part in parts:
        if not current.is_dir():
            return False, f"Parent is not a directory: {'/'.join(built) or str(root)}"

        try:
            entries = list(current.iterdir())
        except OSError as exc:
            return False, f"Cannot list '{current}': {exc}"

        exact = next((e for e in entries if e.name == part), None)
        if exact is not None:
            current = exact
            built.append(exact.name)
            continue

        # Case-insensitive hit = casing mismatch (common on Windows).
        ci_match = next((e for e in entries if e.name.lower() == part.lower()), None)
        if ci_match is not None:
            wrong = "/".join([*built, part])
            right = "/".join([*built, ci_match.name])
            return (
                False,
                f"Case mismatch: XML has '{wrong}' but disk has '{right}'",
            )

        missing = "/".join([*built, part])
        return False, f"Missing file or folder: '{missing}'"

    if not current.exists():
        return False, f"Path does not exist: '{relative}'"

    return True, "/".join(built)


def find_path_ignoring_case(root: Path, relative: str) -> Path | None:
    """Locate *relative* under *root* ignoring letter case (None if absent).

    Used to still analyse a file whose path casing is wrong: the casing problem
    itself is reported elsewhere, but its content can still be checked.
    """
    current = root.resolve()
    for part in [p for p in normalize_mod_relative(relative).split("/") if p and p != "."]:
        if not current.is_dir():
            return None
        try:
            match = next(
                (e for e in current.iterdir() if e.name.lower() == part.lower()),
                None,
            )
        except OSError:
            return None
        if match is None:
            return None
        current = match
    return current if current != root.resolve() else None


def resolve_mod_relative_path(mod_root: Path, relative: str) -> Path | None:
    """Return absolute Path if case-sensitive check passes, else None."""
    ok, detail = path_exists_case_sensitive(mod_root, relative)
    if not ok or detail.startswith("(engine path skipped)"):
        return None
    return (mod_root / Path(*detail.split("/"))).resolve()
