"""Thin wrapper over the tmux command line."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

FIELDS = ["session_name", "window_id", "window_index", "@grove_ws", "@grove_kind",
          "@grove_dir", "@grove_label", "pane_current_command"]
SEP = "\x1f"
FORMAT = SEP.join("#{%s}" % f for f in FIELDS)
NO_SERVER = ("no server running", "error connecting", "no current client")


class TmuxError(RuntimeError):
    pass


@dataclass(frozen=True)
class Window:
    session: str
    id: str          # tmux window id, e.g. "@12"
    index: int
    ws: str          # workspace path relative to root
    kind: str        # "claude" or "shell"
    dir: str         # folder relative to the workspace ("" = workspace itself)
    label: str
    command: str     # pane_current_command

    @property
    def num(self) -> int:
        return int(self.id.lstrip("@"))


def _parse(line: str) -> Window | None:
    p = line.split(SEP)
    if len(p) != len(FIELDS) or not p[3]:
        return None                      # not a grove session
    return Window(p[0], p[1], int(p[2]), p[3], p[4], p[5], p[6], p[7])


class Tmux:
    def __init__(self, socket: str | None = None):
        self.base = ["tmux"] + (["-L", socket] if socket else [])

    def run(self, *args: str) -> str:
        proc = subprocess.run([*self.base, *args], capture_output=True, text=True)
        if proc.returncode != 0:
            raise TmuxError(proc.stderr.strip() or f"tmux {args[0]} failed")
        return proc.stdout

    def version(self) -> str:
        return subprocess.run(["tmux", "-V"], capture_output=True, text=True).stdout.strip()

    def has_session(self, name: str) -> bool:
        proc = subprocess.run([*self.base, "has-session", "-t", f"={name}"], capture_output=True)
        return proc.returncode == 0

    def new_session(self, name: str, ws_rel: str, cwd: Path) -> str:
        wid = self.run("new-session", "-d", "-s", name, "-c", str(cwd), "-P", "-F", "#{window_id}").strip()
        self.run("set-option", "-t", f"={name}:", "@grove_ws", ws_rel)
        self.run("set-option", "-t", f"={name}:", "window-size", "latest")
        return wid

    def new_window(self, session: str, cwd: Path) -> str:
        return self.run("new-window", "-d", "-t", f"={session}:", "-c", str(cwd),
                        "-P", "-F", "#{window_id}").strip()

    def set_window(self, window_id: str, **opts: str) -> None:
        for key, value in opts.items():
            self.run("set-option", "-w", "-t", window_id, f"@grove_{key}", value)

    def set_title(self, window_id: str, title: str) -> None:
        self.run("rename-window", "-t", window_id, title)

    def send_line(self, window_id: str, text: str) -> None:
        self.run("send-keys", "-t", window_id, "-l", text)
        self.run("send-keys", "-t", window_id, "Enter")

    def kill_window(self, window_id: str) -> None:
        self.run("kill-window", "-t", window_id)

    def windows(self) -> list[Window]:
        try:
            out = self.run("list-windows", "-a", "-F", FORMAT)
        except TmuxError as exc:
            if any(s in str(exc) for s in NO_SERVER):
                return []
            raise
        return [w for w in map(_parse, out.splitlines()) if w is not None]

    def window_of_pane(self, pane_id: str) -> Window | None:
        try:
            out = self.run("display-message", "-p", "-t", pane_id, FORMAT)
        except TmuxError:
            return None
        return _parse(out.rstrip("\n"))
