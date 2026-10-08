"""Interactive screen. Model and key mapping are pure; curses glue is thin."""
from __future__ import annotations

import contextlib
import curses
import time
from dataclasses import dataclass, field

from .client import RemoteError
from .ops import NeedsConfirm, OpError
from .render import Row, build_rows
from .workspaces import PathError

REFRESH_S = 2.0
HELP = "↑↓ move  ⏎ open  space fold  n new  r rename  m mark  c close  / search  q quit"
SEARCH_HELP = "esc clear search  " + HELP


@dataclass
class Model:
    tree: dict | None = None
    collapsed: set[str] = field(default_factory=set)
    query: str = ""
    cursor: int = 0
    offline: str = ""
    message: str = ""

    def rows(self) -> list[Row]:
        return build_rows(self.tree, self.collapsed, self.query) if self.tree else []

    def selected(self) -> Row | None:
        rows = self.rows()
        return rows[self.cursor] if 0 <= self.cursor < len(rows) else None

    def move(self, delta: int) -> None:
        self.cursor = max(0, min(len(self.rows()) - 1, self.cursor + delta))

    def toggle(self) -> None:
        row = self.selected()
        if row and row.kind == "ws":
            self.collapsed ^= {row.ws_path}

    def needs_input(self) -> int:
        if not self.tree:
            return 0
        return sum(t["status"] == "needs-input" for w in self.tree["workspaces"] for t in w["tabs"])

    def set_tree(self, tree: dict) -> None:
        before = self.selected()
        self.tree, self.offline = tree, ""
        rows = self.rows()
        if before:
            for i, r in enumerate(rows):
                if (r.ws_path, r.tab_id, r.kind) == (before.ws_path, before.tab_id, before.kind):
                    self.cursor = i
                    return
        self.move(0)


def action_for(key: str, row: Row | None, filtering: bool = False) -> tuple:
    if key == "\x1b" and filtering:
        return ("clear",)
    if key in ("q", "\x1b"):
        return ("quit",)
    if key in ("KEY_UP", "k"):
        return ("move", -1)
    if key in ("KEY_DOWN", "j"):
        return ("move", 1)
    if key == "/":
        return ("search",)
    if row is None:
        return {"n": ("new", ""), "m": ("mark", "")}.get(key, ("none",))
    if key in ("\n", "KEY_ENTER", "KEY_RIGHT"):
        return ("open", row.ws_path, row.tab_id)
    if key in (" ", "KEY_LEFT") and row.kind == "ws":
        return ("toggle",)
    if key == "n":
        return ("new", row.ws_path)
    if key == "m":
        return ("mark", row.ws_path)
    if row.kind == "tab" and key == "r":
        return ("rename", row.tab_id)
    if row.kind == "tab" and key == "c":
        return ("close", row.tab_id)
    return ("none",)


# ---- curses glue (manual testing only) -----------------------------------

@contextlib.contextmanager
def _blocking(screen):
    """Block indefinitely on input; restore the refresh timeout afterwards."""
    screen.timeout(-1)
    try:
        yield
    finally:
        screen.timeout(int(REFRESH_S * 1000))


def _prompt(screen, text: str, default: str = "") -> str | None:
    h, w = screen.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    screen.move(h - 1, 0)
    screen.clrtoeol()
    screen.addnstr(h - 1, 0, f"{text} [{default}]: " if default else f"{text}: ", w - 1)
    screen.refresh()
    try:
        with _blocking(screen):
            value = screen.getstr().decode("utf-8", "replace").strip()
    except KeyboardInterrupt:
        value = None
    finally:
        curses.noecho()
        curses.curs_set(0)
    if value is None or "\x1b" in value:
        return None
    return value or default


def _pick_folder(screen, backend, start: str) -> str | None:
    """Browse folders: ⏎ enter, ⌫ up, '.' choose current, + new folder, q cancel."""
    with _blocking(screen):
        return _pick_folder_blocking(screen, backend, start)


def _pick_folder_blocking(screen, backend, start: str) -> str | None:
    path, cursor, message, select = start, 0, "", ""
    while True:
        dirs = backend.request("ls", {"path": path})["dirs"]
        if select in dirs:
            cursor, select = dirs.index(select), ""
        screen.erase()
        h, w = screen.getmaxyx()
        screen.addnstr(0, 0, f"Choose a folder: {path or '(root)'}", w - 1, curses.A_BOLD)
        screen.addnstr(1, 0, "⏎ open  ⌫ up  . choose this folder  + new folder  q cancel", w - 1, curses.A_DIM)
        for i, name in enumerate(dirs[: h - 4]):
            screen.addnstr(i + 2, 2, name + "/", w - 3, curses.A_REVERSE if i == cursor else 0)
        if message:
            screen.addnstr(h - 1, 0, message, w - 1, curses.A_DIM)
        message = ""
        try:
            key = screen.getkey()
        except KeyboardInterrupt:
            return None
        if key in ("q", "\x1b"):
            return None
        if key == "." and path:
            return path
        if key in ("KEY_UP", "k"):
            cursor = max(0, cursor - 1)
        elif key in ("KEY_DOWN", "j"):
            cursor = min(max(0, len(dirs) - 1), cursor + 1)
        elif key in ("\n", "KEY_ENTER", "KEY_RIGHT") and dirs:
            path, cursor = (f"{path}/{dirs[cursor]}" if path else dirs[cursor]), 0
        elif key in ("KEY_BACKSPACE", "\x7f", "KEY_LEFT"):
            path, cursor = path.rpartition("/")[0], 0
        elif key == "+":
            name = _prompt(screen, f"new folder in {path or '(root)'}")
            screen.timeout(-1)                          # _prompt restored the refresh timeout
            if name:
                try:
                    created = backend.request("mkdir", {"path": path, "name": name})["path"]
                except (RemoteError, PathError) as exc:
                    message = f"error: {exc}"
                else:
                    select = created.rpartition("/")[2]
                    message = f"created {created}/ — ⏎ to go in, then . to choose it"


def _draw(screen, model: Model, host: str) -> None:
    screen.erase()
    h, w = screen.getmaxyx()
    badge = f"◆ {model.needs_input()} needs input" if model.needs_input() else ""
    root = model.tree["root"] if model.tree else ""
    screen.addnstr(0, 0, f" grove — {host}:{root}".ljust(max(0, w - len(badge) - 1)) + badge, w - 1, curses.A_BOLD)
    if model.offline:
        screen.addnstr(1, 0, f" offline — retrying ({model.offline})", w - 1, curses.A_REVERSE)
    rows = model.rows()
    top = max(0, model.cursor - (h - 5))
    for i, row in enumerate(rows[top: top + h - 4]):
        line = f"{'  ' * row.depth}{row.text}"
        line = f" {line:<48} {row.status:<14} {row.age}"
        attr = curses.A_REVERSE if top + i == model.cursor else 0
        if row.status.startswith("◆"):
            attr |= curses.A_BOLD
        screen.addnstr(i + 2, 0, line, w - 1, attr)
    footer = model.message or (f"/{model.query}  {SEARCH_HELP}" if model.query else HELP)
    screen.addnstr(h - 1, 0, footer, w - 1, curses.A_DIM)
    screen.refresh()


def _open(screen, backend, cfg, model: Model, reply: dict) -> None:
    """Attach to reply's session/window; come back to the screen when it detaches."""
    from .cli import open_session
    curses.endwin()
    try:
        code = open_session(backend, cfg, reply["session"], reply["window_id"], replace=False)
    except OSError as exc:
        code, model.message = 0, f"error: {exc}"
    screen.refresh()
    if code:
        model.message = f"could not open session (exit {code})"


def _loop(screen, backend, cfg) -> int:
    curses.curs_set(0)
    screen.timeout(int(REFRESH_S * 1000))
    model, last = Model(), 0.0
    host = cfg.host or "local"
    while True:
        if time.time() - last >= REFRESH_S:
            try:
                model.set_tree(backend.request("tree", {}))
            except RemoteError as exc:
                model.offline = str(exc)
            last = time.time()
        _draw(screen, model, host)
        try:
            key = screen.getkey()
        except curses.error:
            continue                                    # timeout: refresh
        except KeyboardInterrupt:
            return 0
        model.message = ""
        action = action_for(key, model.selected(), filtering=bool(model.query))
        try:
            if action[0] == "quit":
                return 0
            if action[0] == "move":
                model.move(action[1])
            elif action[0] == "toggle":
                model.toggle()
            elif action[0] == "clear":
                model.query, model.cursor = "", 0
            elif action[0] == "search":
                model.query = _prompt(screen, "search") or ""
                model.cursor = 0
            elif action[0] == "open":
                reply = backend.request("resolve", {"num": int(action[2][1:])} if action[2]
                                        else {"path": action[1]})
                _open(screen, backend, cfg, model, reply)
                last = 0.0
            elif action[0] == "new":
                folder = _pick_folder(screen, backend, action[1])
                if folder:
                    label = _prompt(screen, "label (optional)")
                    kind_in = _prompt(screen, "claude or shell", "claude") if label is not None else None
                    if kind_in is not None:
                        kind = "shell" if kind_in.startswith("s") else "claude"
                        reply = backend.request("new", {"path": folder, "label": label, "kind": kind})
                        _open(screen, backend, cfg, model, reply)
                        model.message = model.message or reply.get("warning") \
                            or f"created tab #{reply['window_id'][1:]}"
                        last = 0.0
            elif action[0] == "rename":
                label = _prompt(screen, "new label")
                if label is not None:
                    backend.request("rename", {"num": int(action[1][1:]), "label": label})
                    last = 0.0
            elif action[0] == "mark":
                folder = _pick_folder(screen, backend, action[1])
                if folder:
                    backend.request("mark", {"path": folder})
                    last = 0.0
            elif action[0] == "close":
                num = int(action[1][1:])
                try:
                    backend.request("close", {"num": num})
                except NeedsConfirm as exc:
                    if (_prompt(screen, f"{exc} — close anyway? y/N") or "").lower() == "y":
                        backend.request("close", {"num": num, "force": True})
                last = 0.0
        except (RemoteError, OpError, PathError) as exc:
            model.message = f"error: {exc}"


def run(backend, cfg) -> int:
    return curses.wrapper(_loop, backend, cfg)
