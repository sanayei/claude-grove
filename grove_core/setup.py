"""First-time configuration: config file, Claude hooks, Mac login agent."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

from .config import Config, save, state_dir
from .hooks import SettingsError, settings_path, update_settings_file

AGENT_LABEL = "io.github.claude-grove.watch"


def agent_plist(launcher: str, log: str, python: str = sys.executable) -> bytes:
    return plistlib.dumps({
        "Label": AGENT_LABEL,
        # pin the interpreter setup ran with: launchd's PATH may find an older python3
        "ProgramArguments": [python, launcher, "watch"],
        "RunAtLoad": True,
        # restart after crashes only; `notify = false` makes watch exit 0 and stay stopped
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": {"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"},
    })


def install_watch_agent(launcher: str, home: Path, uid: int, run=subprocess.run,
                        python: str = sys.executable) -> tuple[Path, int]:
    """Write the plist and load it. Returns (path, launchctl bootstrap exit code)."""
    path = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(agent_plist(launcher, str(state_dir() / "watch.log"), python))
    run(["launchctl", "bootout", f"gui/{uid}/{AGENT_LABEL}"], capture_output=True)
    proc = run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], capture_output=True)
    return path, proc.returncode


def run(cfg: Config, args, ask=input, say=print, now=time.time, platform=sys.platform,
        home: Path | None = None, run_cmd=subprocess.run) -> int:
    from .cli import launcher_path
    launcher = launcher_path()

    if args.uninstall_hooks:
        backup = update_settings_file(settings_path(), None, now())
        say("Removed grove's Claude hooks" + (f" (backup: {backup})" if backup else "") + ".")
        return 0

    answer = ask(f'Machine that runs the Claude sessions (ssh host, or "local" for this machine) '
                 f'[{cfg.host or "local"}]: ').strip()
    if answer.lower() == "local":
        cfg.host = ""
    elif answer:
        cfg.host = answer
    if cfg.is_local:
        cfg.root = ask(f"Folder that holds your projects [{cfg.root}]: ").strip() or cfg.root
    else:
        cfg.remote_cmd = ask(f"Path of grove on {cfg.host} [{cfg.remote_cmd}]: ").strip() or cfg.remote_cmd
    save(cfg)
    say("Saved configuration.")

    if cfg.is_local:
        try:
            backup = update_settings_file(settings_path(), launcher, now())
        except SettingsError as exc:
            say(f"Could not install Claude hooks: {exc}")
            return 1
        say("Installed Claude hooks" + (f" (backup: {backup})" if backup else "") + ".")
    else:
        from .client import RemoteBackend, RemoteError
        try:
            reply = RemoteBackend(cfg, state_dir(), run=run_cmd).request("ping", {})
            say(f"{cfg.host}: grove {reply.get('version', '?')}, {reply.get('tmux') or 'tmux missing'}, "
                f"hooks {'installed' if reply.get('hooks', False) else 'NOT installed — run grove setup there'}.")
        except RemoteError as exc:
            say(f"{exc}\nInstall grove on {cfg.host} (clone + ./install.sh, answer \"local\"), then run grove doctor here.")

    if platform == "darwin" and cfg.notify:
        path, code = install_watch_agent(launcher, home or Path.home(), os.getuid(), run=run_cmd)
        if code == 0:
            say(f"Installed the notifier login agent ({path}).")
        else:
            say(f"Could not load the notifier agent (launchctl exit {code}); run grove doctor")
    say("Done. Check everything with: grove doctor")
    return 0
