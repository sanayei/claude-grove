"""Claude Code hooks: record status changes of grove tabs; settings.json merge."""
from __future__ import annotations

import copy
import json
import os
import shlex
import signal
import stat
import sys
import time
import traceback
from collections.abc import Mapping
from pathlib import Path

from .config import state_dir
from .render import tab_name
from .status import append_event, read_status, write_status
from .tmux import Tmux

EVENT_STATUS = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "Notification": "needs-input",
    "Stop": "idle",
    "SessionEnd": "exited",
    "PostToolUse": "working",          # only when it follows needs-input (see handle_hook)
}
# Notification also fires for idle prompts and auth success; only real input requests count.
MATCHERS = {"Notification": "permission_prompt|elicitation_dialog"}
EVENT_NAME = {"Stop": "finished"}          # otherwise the event name is the status
TAG = "# grove-hook"
HOOK_TIMEOUT_S = 1
INTERNAL_BUDGET_S = 0.8


class SettingsError(Exception):
    pass


def handle_hook(event: str, env: Mapping[str, str], tmux: Tmux, state: Path, now: float) -> bool:
    if event not in EVENT_STATUS or not env.get("TMUX_PANE"):
        return False
    win = tmux.window_of_pane(env["TMUX_PANE"])
    if win is None or win.kind != "claude":
        return False
    status = EVENT_STATUS[event]
    if event == "PostToolUse":         # fires after every tool: only clear a pending input request
        current = read_status(state, win.id)
        if current is None or current.status != "needs-input":
            return False
    write_status(state, win.id, status, event, now)
    append_event(state, {
        "ts": now, "window_id": win.id, "num": win.num, "workspace": win.ws,
        "tab": tab_name(win.dir, win.label), "status": status,
        "event": EVENT_NAME.get(event, status),
    })
    return True


def _log_error(message: str) -> None:
    try:
        d = state_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "grove.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:                              # noqa: BLE001 - logging must never raise
        pass


def run_hook(event: str) -> int:
    """Entry point for `grove hook <event>`. Never fails, never blocks Claude."""
    def _timeout(signum, frame):
        raise TimeoutError("grove hook exceeded its time budget")

    signal.signal(signal.SIGALRM, _timeout)
    signal.setitimer(signal.ITIMER_REAL, INTERNAL_BUDGET_S)
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()                       # drain Claude's JSON payload
        handle_hook(event, os.environ, Tmux(), state_dir(), time.time())
    except Exception:                              # noqa: BLE001 - must never propagate
        _log_error(f"hook {event} failed:\n{traceback.format_exc()}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return 0


def hook_command(launcher: str, event: str) -> str:
    return f"{shlex.quote(launcher)} hook {event} {TAG}"


def _is_grove_group(group: dict) -> bool:
    return any(TAG in h.get("command", "") for h in group.get("hooks", []))


def install_hooks(settings: dict, launcher: str) -> dict:
    result = copy.deepcopy(settings)
    all_hooks = result.setdefault("hooks", {})
    for event in EVENT_STATUS:
        groups = [g for g in all_hooks.get(event, []) if not _is_grove_group(g)]
        group = {"matcher": MATCHERS[event]} if event in MATCHERS else {}
        group["hooks"] = [{"type": "command", "command": hook_command(launcher, event),
                           "timeout": HOOK_TIMEOUT_S}]
        groups.append(group)
        all_hooks[event] = groups
    return result


def uninstall_hooks(settings: dict) -> dict:
    result = copy.deepcopy(settings)
    all_hooks = result.get("hooks", {})
    for event in list(all_hooks):
        groups = [g for g in all_hooks[event] if not _is_grove_group(g)]
        if groups:
            all_hooks[event] = groups
        else:
            del all_hooks[event]
    if "hooks" in result and not result["hooks"]:
        del result["hooks"]
    return result


def settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "settings.json"


def hooks_installed(path: Path) -> bool:
    try:
        all_hooks = json.loads(path.read_text(encoding="utf-8")).get("hooks", {})
    except (OSError, ValueError, AttributeError):
        return False
    return all(any(_is_grove_group(g) for g in all_hooks.get(e, [])) for e in EVENT_STATUS)


def _write_with_mode(path: Path, text: str, mode: int) -> None:
    """Write text to path; the file never has looser permissions than `mode`."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(fd, mode)
        f.write(text)


def update_settings_file(path: Path, launcher: str | None, now: float) -> Path | None:
    """Install (launcher given) or uninstall (None) grove's hooks. Returns the backup path."""
    real = Path(os.path.realpath(path))
    backup = None
    mode = 0o600
    if real.exists():
        mode = stat.S_IMODE(real.stat().st_mode)
        text = real.read_text(encoding="utf-8")
        try:
            settings = json.loads(text)
        except ValueError as exc:
            raise SettingsError(f"{path} is not valid JSON ({exc}); leaving it untouched") from exc
        if not isinstance(settings, dict):
            raise SettingsError(f"{path} is not a JSON object; leaving it untouched")
        backup = real.with_name(f"{real.name}.grove-backup-{int(now)}")
        _write_with_mode(backup, text, mode)
    else:
        if launcher is None:
            return None
        settings = {}
    updated = install_hooks(settings, launcher) if launcher else uninstall_hooks(settings)
    real.parent.mkdir(parents=True, exist_ok=True)
    tmp = real.with_name(real.name + ".tmp")
    _write_with_mode(tmp, json.dumps(updated, indent=2, ensure_ascii=False) + "\n", mode)
    os.replace(tmp, real)
    return backup
