"""Workspaces: folders that are nodes in the tree (one tmux session each)."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = ".grove"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__"}
MAX_DEPTH = 6


class PathError(ValueError):
    """A user-supplied path is not usable."""


def resolve_in_root(root: Path, rel_path: str) -> Path:
    """Turn a root-relative path into an existing folder strictly inside root."""
    root = root.resolve()
    target = (root / rel_path).resolve()
    if target == root or root not in target.parents:
        raise PathError(f"{rel_path!r} is not a folder inside {root}")
    if not target.is_dir():
        raise PathError(f"{rel_path!r} does not exist (or is not a folder) under {root}")
    return target


def is_workspace(folder: Path, root: Path) -> bool:
    return folder.parent == root or (folder / MARKER).is_file()


def nearest_workspace(folder: Path, root: Path) -> Path:
    root, folder = root.resolve(), folder.resolve()
    for candidate in [folder, *folder.parents]:
        if candidate == root:
            break
        if is_workspace(candidate, root):
            return candidate
    raise PathError(f"{folder} is not inside {root}")


def rel(root: Path, folder: Path) -> str:
    return folder.resolve().relative_to(root.resolve()).as_posix()


def _inside(root: Path, folder: Path) -> bool:
    return root in folder.resolve().parents


def list_workspaces(root: Path) -> list[str]:
    root = root.resolve()
    found: list[Path] = []
    # top-level symlinks are skipped: outside root they escape it, inside they duplicate a workspace
    tops = sorted(p for p in root.iterdir()
                  if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
                  and _inside(root, p))
    for top in tops:
        found.append(top)
        for dirpath, dirnames, filenames in os.walk(top):
            here = Path(dirpath)
            depth = len(here.relative_to(top).parts)
            if depth >= MAX_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            if here != top and MARKER in filenames and _inside(root, here):
                found.append(here)
    return sorted(rel(root, p) for p in found)


def mark(root: Path, rel_path: str) -> str:
    folder = resolve_in_root(root, rel_path)
    if folder.parent == root.resolve():
        raise PathError(f"{rel_path!r} is a top-level folder and already a workspace")
    (folder / MARKER).touch()
    return rel(root, folder)


def unmark(root: Path, rel_path: str) -> str:
    folder = resolve_in_root(root, rel_path)
    marker = folder / MARKER
    if not marker.is_file():
        raise PathError(f"{rel_path!r} is not marked as a workspace")
    marker.unlink()
    return rel(root, folder)


SESSION_PREFIX = "grove/"


def session_name(ws_rel: str) -> str:
    """'grove/' + the workspace path; tmux forbids '.' and ':' in names, so escape them reversibly."""
    return SESSION_PREFIX + ws_rel.replace("%", "%25").replace(".", "%2E").replace(":", "%3A")
