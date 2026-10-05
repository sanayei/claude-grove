"""`grove doctor`: check every prerequisite and print exact fixes."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import Config, state_dir
from .hooks import hooks_installed, settings_path

MIN_TMUX = (3, 2)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    optional: bool = False


def parse_tmux_version(text: str) -> tuple[int, int] | None:
    m = re.search(r"(\d+)\.(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _tmux_check(name: str, text: str) -> Check:
    version = parse_tmux_version(text)
    ok = version is not None and version >= MIN_TMUX
    return Check(name, ok, text or "not installed",
                 "" if ok else "install tmux ≥ 3.2 (Ubuntu: sudo apt install tmux)")


def collect(cfg: Config, which=shutil.which, run=subprocess.run, platform=sys.platform,
            backend=None) -> list[Check]:
    checks = [Check("python", sys.version_info >= (3, 11), sys.version.split()[0],
                    "install Python 3.11 or newer")]
    if cfg.is_local:
        text = run(["tmux", "-V"], capture_output=True, text=True).stdout.strip() if which("tmux") else ""
        checks.append(_tmux_check("tmux", text))
        ok = hooks_installed(settings_path())
        checks.append(Check("claude hooks", ok, str(settings_path()), "" if ok else "run: grove setup"))
    else:
        from .client import RemoteBackend, RemoteError
        backend = backend or RemoteBackend(cfg, state_dir(), run=run)
        try:
            info = backend.request("ping", {})
            checks.append(Check("remote", True, f"{cfg.host}: grove {info['version']}"))
            checks.append(_tmux_check("remote tmux", info["tmux"]))
            checks.append(Check("remote hooks", bool(info["hooks"]), cfg.host,
                                "" if info["hooks"] else f"on {cfg.host} run: grove setup (blank host)"))
        except RemoteError as exc:
            checks.append(Check("remote", False, str(exc),
                                f"check `ssh {cfg.host}` works with your key, and grove is installed there"))
    if platform == "darwin":
        iterm = Path("/Applications/iTerm.app").exists()
        checks.append(Check("iTerm2", iterm, "/Applications/iTerm.app",
                            "" if iterm else "install iTerm2 (https://iterm2.com) for native tabs"))
        tn = which("terminal-notifier")
        checks.append(Check("terminal-notifier", bool(tn), tn or "not installed",
                            "optional: brew install terminal-notifier (click-to-open notifications)",
                            optional=True))
        if cfg.notify:
            from .setup import AGENT_LABEL
            loaded = run(["launchctl", "print", f"gui/{os.getuid()}/{AGENT_LABEL}"],
                         capture_output=True, text=True).returncode == 0
            checks.append(Check("watch agent", loaded, AGENT_LABEL, "" if loaded else "run: grove setup"))
    return checks


def run(cfg: Config) -> int:
    checks = collect(cfg)
    for c in checks:
        mark = "✓" if c.ok else ("–" if c.optional else "✗")
        print(f"{mark} {c.name}: {c.detail}")
        if not c.ok and c.fix:
            print(f"    fix: {c.fix}")
    return 0 if all(c.ok or c.optional for c in checks) else 1
