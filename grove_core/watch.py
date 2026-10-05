"""Mac notifier: follow the remote event log over ssh and post notifications."""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import Config, state_dir

LATE_AFTER = 600
DEDUPE_WINDOW = 120
MAX_DELAY = 60
NOTIFY_EVENTS = {"needs-input": "needs your input", "finished": "finished"}


def message_for(event: dict, now: float) -> tuple[str, str] | None:
    what = NOTIFY_EVENTS.get(event.get("event", ""))
    if what is None:
        return None
    text = f"#{event['num']} {event['tab']} — {what}"
    if now - event["ts"] > LATE_AFTER:
        text += " (late)"
    return f"grove · {event['workspace']}", text


def _applescript_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify_mac(title: str, text: str, num: int, launcher: str,
               run=subprocess.run, which=shutil.which, python: str = sys.executable) -> None:
    notifier = which("terminal-notifier")
    if notifier:
        script = ('tell application "iTerm" to create window with default profile command '
                  + _applescript_string(f"{shlex.quote(python)} {shlex.quote(launcher)} open --tab {num}"))
        run([notifier, "-title", title, "-message", text, "-group", f"grove-{num}",
             "-execute", f"osascript -e {shlex.quote(script)}"], check=False)
    else:
        run(["osascript", "-e", f"display notification {_applescript_string(text)} "
                                f"with title {_applescript_string(title)}"], check=False)


class Watcher:
    def __init__(self, backend, state: Path, notify, popen=subprocess.Popen,
                 sleep=time.sleep, clock=time.time):
        self.backend = backend
        self.cursor_file = state / "watch.cursor"
        self.notify = notify
        self.popen = popen
        self.sleep = sleep
        self.clock = clock
        self.last_finished: dict[str, float] = {}

    def load_cursor(self) -> int | None:
        try:
            return int(self.cursor_file.read_text())
        except (FileNotFoundError, ValueError):
            return None

    def save_cursor(self, seq: int) -> None:
        self.cursor_file.write_text(str(seq))

    def handle(self, event: dict) -> None:
        try:
            self._handle(event)
        except (KeyError, TypeError, ValueError) as exc:
            print(f"grove watch: skipping malformed event: {exc!r}", file=sys.stderr)
            try:
                self.save_cursor(int(event["seq"]))
            except (KeyError, TypeError, ValueError):
                pass

    def _handle(self, event: dict) -> None:
        if "heartbeat" in event:                  # keep-alive from the remote: no cursor change
            return
        if "cursor" in event:
            self.save_cursor(int(event["cursor"]))
            return
        wid = event.get("window_id", "")
        kind = event.get("event")
        if kind == "working":
            self.last_finished.pop(wid, None)
        if kind == "finished":
            self.last_finished[wid] = event["ts"]
        recent = event["ts"] - self.last_finished.get(wid, float("-inf")) < DEDUPE_WINDOW
        if not (kind == "needs-input" and recent):
            message = message_for(event, self.clock())
            if message:
                try:
                    self.notify(message[0], message[1], event["num"])
                except Exception as exc:  # a failing notifier must not stall the stream
                    print(f"grove watch: notify failed: {exc!r}", file=sys.stderr)
        self.save_cursor(int(event["seq"]))

    def run_once(self) -> None:
        proc = self.popen(self.backend.stream_argv(self.load_cursor()),
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    self.handle(event)
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
            proc.wait()

    def run_forever(self, max_rounds: int | None = None) -> None:
        delay, rounds = 1, 0
        while max_rounds is None or rounds < max_rounds:
            started = self.clock()
            try:
                self.run_once()
            except OSError as exc:
                print(f"grove watch: {exc}", file=sys.stderr)
            delay = 1 if self.clock() - started > MAX_DELAY else delay
            self.sleep(delay)
            delay = min(delay * 2, MAX_DELAY)
            rounds += 1


def main(cfg: Config) -> int:
    if not cfg.notify:
        print("grove watch: notifications are disabled (notify = false)")
        return 0
    from .cli import launcher_path, make_backend
    launcher = launcher_path()
    watcher = Watcher(make_backend(cfg), state_dir(),
                      notify=lambda title, text, num: notify_mac(title, text, num, launcher))
    watcher.run_forever()
    return 0
