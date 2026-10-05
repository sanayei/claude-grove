"""User configuration (~/.config/grove/config.toml) and the state directory."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    host: str = ""                       # empty: this machine runs the sessions
    root: str = "~/projects"
    notify: bool = True
    remote_cmd: str = "~/.local/bin/grove"
    ssh_opts: list[str] = field(default_factory=list)

    @property
    def is_local(self) -> bool:
        return not self.host

    def root_path(self) -> Path:
        return Path(self.root).expanduser()


def config_path() -> Path:
    env = os.environ.get("GROVE_CONFIG")
    return Path(env) if env else Path.home() / ".config" / "grove" / "config.toml"


def state_dir() -> Path:
    env = os.environ.get("GROVE_STATE_DIR")
    path = Path(env) if env else Path.home() / ".local" / "state" / "grove"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    names = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in data.items() if k in names})


def save(cfg: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"host = {json.dumps(cfg.host)}",
        f"root = {json.dumps(cfg.root)}",
        f"notify = {'true' if cfg.notify else 'false'}",
        f"remote_cmd = {json.dumps(cfg.remote_cmd)}",
        "ssh_opts = [" + ", ".join(json.dumps(o) for o in cfg.ssh_opts) + "]",
    ]
    path.write_text("\n".join(lines) + "\n")
