"""Operations that run where the tmux sessions live."""
from __future__ import annotations

import json
import shlex
import time
from pathlib import Path

from . import __version__
from .render import tab_name
from .status import LIVE, SHELLS, read_status, reconcile, remove_status, write_status
from .tmux import Tmux, TmuxError, Window
from .workspaces import (
    PathError, list_workspaces, mark, nearest_workspace, rel, resolve_in_root,
    session_name, unmark,
)

CACHE_TTL = 30.0
SAME_FOLDER_WARNING = ("{n} other Claude tab(s) already run in this folder; parallel edits can "
                       "overwrite each other — consider a git worktree.")


class OpError(Exception):
    pass


class NeedsConfirm(OpError):
    pass


class Grove:
    def __init__(self, root: Path, tmux: Tmux, state: Path, clock=time.time,
                 host_label: str = "", claude_cmd: list[str] | None = None):
        self.root = root.expanduser().resolve()
        self.tmux = tmux
        self.state = state
        self.clock = clock
        self.host_label = host_label
        self.claude_cmd = claude_cmd or ["claude"]
        state.mkdir(parents=True, exist_ok=True)

    # ---- workspaces -------------------------------------------------------
    def _cache(self) -> Path:
        return self.state / "workspaces.json"

    def workspaces(self, fresh: bool = False) -> list[str]:
        try:
            cached = json.loads(self._cache().read_text())
            if (not fresh and cached["root"] == str(self.root)
                    and time.time() - cached["at"] < CACHE_TTL):
                return cached["paths"]
        except (FileNotFoundError, ValueError, KeyError):
            pass
        paths = list_workspaces(self.root)
        self._cache().write_text(json.dumps({"root": str(self.root), "at": time.time(), "paths": paths}))
        return paths

    def _invalidate(self) -> None:
        self._cache().unlink(missing_ok=True)

    # ---- reading ----------------------------------------------------------
    def tree(self) -> dict:
        now = self.clock()
        windows = self.tmux.windows()
        statuses = reconcile(windows, self.state, now)
        by_ws: dict[str, list[dict]] = {}
        for w in windows:
            st = statuses.get(w.id)
            by_ws.setdefault(w.ws, []).append({
                "id": w.id, "num": w.num, "dir": w.dir, "label": w.label, "kind": w.kind,
                "status": st.status if st else "", "since": st.since if st else now,
            })
        paths = sorted(set(self.workspaces()) | set(by_ws))
        return {
            "root": str(self.root), "host": self.host_label, "now": now,
            "workspaces": [{"path": p, "session": session_name(p),
                            "missing": not (self.root / p).is_dir(),
                            "tabs": by_ws.get(p, [])} for p in paths],
        }

    def listdir(self, path: str = "") -> dict:
        folder = resolve_in_root(self.root, path) if path else self.root
        dirs = sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))
        return {"path": path, "dirs": dirs}

    # ---- sessions and tabs ------------------------------------------------
    def ensure_session(self, ws_rel: str) -> str:
        name = session_name(ws_rel)
        if self.tmux.has_session(name):
            try:
                owner = self.tmux.run("show-options", "-t", f"={name}:", "-v", "@grove_ws").strip()
            except TmuxError:
                owner = ""
            if owner != ws_rel:
                raise OpError(f"tmux session {name} exists and is not a grove session")
        else:
            wid = self.tmux.new_session(name, ws_rel, self.root / ws_rel)
            self.tmux.set_window(wid, kind="shell", dir="", label="shell")
            self.tmux.set_title(wid, tab_name("", "shell"))
        return name

    def claude_command(self, args: list[str], rc: bool) -> list[str]:
        # --remote-control takes an optional value, so it must come last
        return [*self.claude_cmd, *args, *(["--remote-control"] if rc else [])]

    def _window(self, num: int) -> Window:
        for w in self.tmux.windows():
            if w.num == num:
                return w
        raise OpError(f"there is no tab #{num}")

    def new_tab(self, path: str, label: str = "", kind: str = "claude",
                claude_args: list[str] = (), rc: bool = False) -> dict:
        folder = resolve_in_root(self.root, path)
        ws = nearest_workspace(folder, self.root)
        ws_rel = rel(self.root, ws)
        dir_rel = "" if folder == ws else folder.relative_to(ws).as_posix()
        warning = ""
        if kind == "claude":
            same = [w for w in self.tmux.windows()
                    if w.kind == "claude" and w.command not in SHELLS
                    and (self.root / w.ws / w.dir).resolve() == folder]
            if same:
                warning = SAME_FOLDER_WARNING.format(n=len(same))
        session = self.ensure_session(ws_rel)
        wid = self.tmux.new_window(session, folder)
        self.tmux.set_window(wid, kind=kind, dir=dir_rel, label=label)
        self.tmux.set_title(wid, tab_name(dir_rel, label))
        if kind == "claude":
            write_status(self.state, wid, "idle", "created", self.clock())
            self.tmux.send_line(wid, shlex.join(self.claude_command(list(claude_args), rc)))
        return {"session": session, "window_id": wid, "warning": warning}

    def rename(self, num: int, label: str) -> dict:
        w = self._window(num)
        self.tmux.set_window(w.id, label=label)
        self.tmux.set_title(w.id, tab_name(w.dir, label))
        return {}

    def close(self, num: int, force: bool = False) -> dict:
        w = self._window(num)
        if w.kind == "claude" and w.command not in SHELLS and not force:
            st = read_status(self.state, w.id)
            if st and st.status in LIVE:
                raise NeedsConfirm(f"tab #{num} is {st.status}; close it anyway with --force")
        self.tmux.kill_window(w.id)
        remove_status(self.state, w.id)
        return {}

    def mark(self, path: str) -> dict:
        result = mark(self.root, path)
        self._invalidate()
        return {"path": result}

    def unmark(self, path: str) -> dict:
        result = unmark(self.root, path)
        self._invalidate()
        return {"path": result}

    def resolve(self, path: str | None = None, num: int | None = None) -> dict:
        if num is not None:
            w = self._window(num)
            return {"session": w.session, "window_id": w.id}
        if not path:
            raise PathError("give a folder or a tab number")
        folder = resolve_in_root(self.root, path)
        ws_rel = rel(self.root, nearest_workspace(folder, self.root))
        return {"session": self.ensure_session(ws_rel), "window_id": None}


def dispatch(g: Grove, op: str, p: dict) -> dict:
    if op == "tree":
        return g.tree()
    if op == "new":
        return g.new_tab(p["path"], p.get("label", ""), p.get("kind", "claude"),
                         p.get("claude_args", []), bool(p.get("rc", False)))
    if op == "rename":
        return g.rename(int(p["num"]), p["label"])
    if op == "close":
        return g.close(int(p["num"]), bool(p.get("force", False)))
    if op == "mark":
        return g.mark(p["path"])
    if op == "unmark":
        return g.unmark(p["path"])
    if op == "resolve":
        return g.resolve(p.get("path"), p.get("num"))
    if op == "ls":
        return g.listdir(p.get("path", ""))
    if op == "ping":
        from .hooks import hooks_installed, settings_path
        return {"version": __version__, "tmux": g.tmux.version(),
                "hooks": hooks_installed(settings_path())}
    raise OpError(f"unknown operation {op!r}")
