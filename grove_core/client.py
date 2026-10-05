"""Backends used by the CLI/TUI: in-process (local) or over ssh (remote)."""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from .config import Config
from .ops import Grove, NeedsConfirm, OpError, dispatch
from .tmux import TmuxError
from .workspaces import PathError


class RemoteError(RuntimeError):
    pass


def parse_reply(code: int, stdout: str, stderr: str, host: str) -> dict:
    if code == 255:
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else "ssh failed"
        detail = detail.split(": ")[-1] if detail.startswith("ssh:") else detail
        raise RemoteError(f"cannot reach {host}: {detail}")
    lines = stdout.strip().splitlines()
    try:
        reply = json.loads(lines[-1]) if lines else None
    except ValueError:
        reply = None
    if not isinstance(reply, dict):
        # a crash prints a traceback: its last line says what went wrong
        said = [l.strip() for l in stderr.splitlines() if l.strip()] \
            or [l.strip() for l in stdout.splitlines() if l.strip()]
        shown = said[-1][:200] if said else "no output"
        raise RemoteError(f"unexpected reply from {host}: {shown} — is grove installed there? "
                          "(run: grove doctor)")
    if "error" in reply:
        raise (NeedsConfirm if reply.get("confirm") else RemoteError)(reply["error"])
    if "ok" not in reply:
        raise RemoteError(f"unexpected reply from {host}: {json.dumps(reply)[:200]}")
    return reply["ok"]


class LocalBackend:
    def __init__(self, grove: Grove, launcher: str):
        self.grove = grove
        self.launcher = launcher

    def request(self, op: str, params: dict) -> dict:
        # same error contract as RemoteBackend (remote_main): everything but NeedsConfirm -> RemoteError
        try:
            return dispatch(self.grove, op, params)
        except NeedsConfirm:
            raise
        except (OpError, PathError, TmuxError, ValueError, KeyError, OSError) as exc:
            raise RemoteError(str(exc) or exc.__class__.__name__) from exc

    def stream_argv(self, since: int | None) -> list[str]:
        return [self.launcher, "--remote", "events", json.dumps({"since": since, "follow": True})]


class RemoteBackend:
    def __init__(self, cfg: Config, state: Path, run=subprocess.run):
        self.cfg = cfg
        self.state = state
        self.run = run

    def ssh_argv(self, tty: bool = False) -> list[str]:
        # non-interactive calls must never read the terminal or prompt for a password
        mode = ["-t"] if tty else ["-n", "-o", "BatchMode=yes"]
        return ["ssh", "-o", "ControlMaster=auto", "-o", f"ControlPath={self.state}/ssh-%C",
                "-o", "ControlPersist=10m", "-o", "ConnectTimeout=5",
                "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2", *self.cfg.ssh_opts, *mode]

    def _remote_command(self, op: str, params: dict) -> str:
        # remote_cmd stays unquoted so the remote shell expands "~"
        return " ".join([self.cfg.remote_cmd, "--remote", shlex.quote(op), shlex.quote(json.dumps(params))])

    def request(self, op: str, params: dict) -> dict:
        argv = [*self.ssh_argv(), "--", self.cfg.host, self._remote_command(op, params)]
        try:
            proc = self.run(argv, capture_output=True, text=True, timeout=60,
                            stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            raise RemoteError(f"{self.cfg.host} did not answer within 60 s") from exc
        return parse_reply(proc.returncode, proc.stdout, proc.stderr, self.cfg.host)

    def stream_argv(self, since: int | None) -> list[str]:
        return [*self.ssh_argv(), "--", self.cfg.host,
                self._remote_command("events", {"since": since, "follow": True})]


def attach_argv(cfg: Config, backend, session: str, window_id: str | None,
                iterm: bool, inside_tmux: bool) -> list[str]:
    target = shlex.quote(f"={session}")
    select = f"tmux select-window -t {shlex.quote(window_id)} 2>/dev/null; " if window_id else ""
    if cfg.is_local:
        verb = f"switch-client -t {target}" if inside_tmux else f"{'-CC ' if iterm else ''}attach -t {target}"
        return ["sh", "-c", f"{select}exec tmux {verb}"]
    return [*backend.ssh_argv(tty=True), "--", cfg.host,
            f"{select}exec tmux {'-CC ' if iterm else ''}attach -t {target}"]
