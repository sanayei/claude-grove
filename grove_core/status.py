"""Per-tab status files and the append-only event log."""
from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .tmux import Window

SHELLS = {"bash", "zsh", "sh", "dash", "fish", "ksh", "tcsh", "-bash", "-zsh", "-sh"}
LIVE = {"working", "needs-input"}
MAX_EVENTS_BYTES = 1_000_000
CREATED_GRACE_S = 15      # a new tab's pane is still a shell until claude starts


@dataclass(frozen=True)
class Status:
    status: str
    since: float
    event: str


def _status_dir(state: Path) -> Path:
    path = state / "status"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_status(state: Path, window_id: str, status: str, event: str, now: float) -> None:
    directory = _status_dir(state)
    tmp = directory / f".{window_id}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"status": status, "since": now, "event": event}))
    os.replace(tmp, directory / f"{window_id}.json")


def read_status(state: Path, window_id: str) -> Status | None:
    try:
        data = json.loads((_status_dir(state) / f"{window_id}.json").read_text())
        return Status(data["status"], float(data["since"]), data.get("event", ""))
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return None


def remove_status(state: Path, window_id: str) -> None:
    (_status_dir(state) / f"{window_id}.json").unlink(missing_ok=True)


def reconcile(windows: list[Window], state: Path, now: float) -> dict[str, Status]:
    """Status of every claude tab, corrected against what the pane really runs."""
    result: dict[str, Status] = {}
    for w in windows:
        if w.kind != "claude":
            continue
        st = read_status(state, w.id) or Status("idle", now, "")
        starting = st.event == "created" and now - st.since < CREATED_GRACE_S
        if w.command in SHELLS and st.status != "exited" and not starting:
            st = Status("exited", now, "reconciled")
            write_status(state, w.id, st.status, st.event, now)
        result[w.id] = st
    alive = {w.id for w in windows}
    for path in _status_dir(state).glob("@*.json"):
        if path.stem not in alive:
            path.unlink(missing_ok=True)
    return result


def _last_seq_in(log: Path) -> int:
    if not log.exists():
        return 0
    size = log.stat().st_size
    with open(log, "rb") as f:
        f.seek(max(0, size - 8192))
        tail = f.read().splitlines()
    for line in reversed(tail):
        try:
            return int(json.loads(line)["seq"])
        except (ValueError, KeyError, TypeError):
            continue
    return 0


def _rotate(log: Path) -> None:
    lines = log.read_bytes().splitlines(keepends=True)
    tmp = log.with_suffix(".tmp")
    tmp.write_bytes(b"".join(lines[len(lines) // 2:]))
    os.replace(tmp, log)


def append_event(state: Path, record: dict, max_bytes: int = MAX_EVENTS_BYTES) -> int:
    state.mkdir(parents=True, exist_ok=True)
    log = state / "events.log"
    with open(state / "events.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        seq = _last_seq_in(log) + 1
        with open(log, "a") as f:
            f.write(json.dumps({"seq": seq, **record}) + "\n")
        if log.stat().st_size > max_bytes:
            _rotate(log)
    return seq


def read_events(state: Path, since: int) -> list[dict]:
    log = state / "events.log"
    if not log.exists():
        return []
    events = []
    for line in log.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("seq", 0) > since:
            events.append(event)
    return events


def last_seq(state: Path) -> int:
    return _last_seq_in(state / "events.log")
