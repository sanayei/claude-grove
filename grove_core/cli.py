"""Command-line entry point."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from . import config
from .client import LocalBackend, RemoteBackend, RemoteError, attach_argv
from .hooks import run_hook
from .ops import NeedsConfirm, OpError
from .remote import make_grove, remote_main
from .render import render_text
from .tmux import TmuxError
from .workspaces import PathError


def launcher_path() -> str:
    return str(Path(sys.argv[0]).absolute())


def make_backend(cfg: config.Config):
    if cfg.is_local:
        return LocalBackend(make_grove(cfg), launcher_path())
    return RemoteBackend(cfg, config.state_dir())


def normalize_path(cfg: config.Config, path: str, cwd: Path) -> str:
    """Locally, accept '.', relative and absolute paths and make them root-relative."""
    if not cfg.is_local:
        return path
    root = cfg.root_path().resolve()
    candidate = Path(path)
    if path.startswith(".") or candidate.is_absolute():
        absolute = (cwd / candidate).resolve()
        if absolute != root and root in absolute.parents:
            return absolute.relative_to(root).as_posix()
    return path


def open_session(backend, cfg: config.Config, session: str, window_id: str | None,
                 replace: bool = True) -> int:
    argv = attach_argv(cfg, backend, session, window_id,
                       iterm=os.environ.get("TERM_PROGRAM") == "iTerm.app",
                       inside_tmux=bool(os.environ.get("TMUX")))
    if replace:
        os.execvp(argv[0], argv)
    return subprocess.call(argv)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grove",
        description="Keep Claude Code sessions alive in tmux, organised as a tree. "
                    "Run without arguments for the interactive screen.")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    t = sub.add_parser("tree", help="print the tree of workspaces and tabs")
    t.add_argument("path", nargs="?")
    t.add_argument("--all", action="store_true", help="include workspaces without tabs")

    o = sub.add_parser("open", help="open a workspace (or a tab) in your terminal")
    o.add_argument("path", nargs="?")
    o.add_argument("--tab", type=int)

    n = sub.add_parser("new", help="new Claude tab (args after -- go to claude)")
    n.add_argument("path")
    n.add_argument("label", nargs="?", default="")
    n.add_argument("--shell", action="store_true", help="plain shell instead of Claude")
    n.add_argument("--rc", action="store_true", help="start Claude with Remote Control")
    n.add_argument("--no-open", action="store_true", help="do not attach after creating")

    r = sub.add_parser("rename", help="change a tab's label")
    r.add_argument("num", type=int)
    r.add_argument("label")

    for name, text in (("mark", "make a folder a workspace"), ("unmark", "remove a workspace marker")):
        sub.add_parser(name, help=text).add_argument("path")

    c = sub.add_parser("close", help="close a tab")
    c.add_argument("num", type=int)
    c.add_argument("--force", action="store_true")

    sub.add_parser("watch", help="run the Mac notifier (normally started at login)")
    s = sub.add_parser("setup", help="first-time configuration")
    s.add_argument("--uninstall-hooks", action="store_true")
    sub.add_parser("doctor", help="check that everything is set up")

    h = sub.add_parser("hook")          # called by Claude Code, not by people
    h.add_argument("event")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--remote"]:
        return remote_main(argv[1] if len(argv) > 1 else "", argv[2] if len(argv) > 2 else "{}")
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    args = build_parser().parse_args(argv)

    if args.cmd == "hook":
        return run_hook(args.event)
    try:
        cfg = config.load()
    except tomllib.TOMLDecodeError as exc:
        print(f"grove: invalid config file {config.config_path()}: {exc}", file=sys.stderr)
        return 1
    if args.cmd == "setup":
        from . import setup
        return setup.run(cfg, args)
    if args.cmd == "doctor":
        from . import doctor
        return doctor.run(cfg)
    if args.cmd == "watch":
        from . import watch
        return watch.main(cfg)

    try:
        backend = make_backend(cfg)
        if args.cmd is None:
            from . import tui
            return tui.run(backend, cfg)
        return COMMANDS[args.cmd](backend, cfg, args, extra)
    except NeedsConfirm as exc:
        print(f"grove: {exc}", file=sys.stderr)
        return 2
    except (RemoteError, OpError, PathError, TmuxError) as exc:
        print(f"grove: {exc}", file=sys.stderr)
        return 1


def _path(cfg, path: str) -> str:
    return normalize_path(cfg, path, Path.cwd())


def cmd_tree(backend, cfg, args, extra) -> int:
    tree = backend.request("tree", {})
    if args.path:
        prefix = _path(cfg, args.path).rstrip("/")
        tree["workspaces"] = [w for w in tree["workspaces"]
                              if w["path"] == prefix or w["path"].startswith(prefix + "/")]
    print(render_text(tree, show_empty=args.all))
    return 0


def cmd_new(backend, cfg, args, extra) -> int:
    reply = backend.request("new", {"path": _path(cfg, args.path), "label": args.label,
                                    "kind": "shell" if args.shell else "claude",
                                    "claude_args": extra, "rc": args.rc})
    if reply["warning"]:
        print(f"grove: warning: {reply['warning']}", file=sys.stderr)
    print(f"created tab #{reply['window_id'].lstrip('@')} in {reply['session']}")
    if args.no_open:
        return 0
    return open_session(backend, cfg, reply["session"], reply["window_id"])


def cmd_open(backend, cfg, args, extra) -> int:
    if args.tab is not None:
        reply = backend.request("resolve", {"num": args.tab})
    elif args.path:
        reply = backend.request("resolve", {"path": _path(cfg, args.path)})
    else:
        raise PathError("give a folder or --tab N")
    return open_session(backend, cfg, reply["session"], reply["window_id"])


def cmd_rename(backend, cfg, args, extra) -> int:
    backend.request("rename", {"num": args.num, "label": args.label})
    print(f"renamed tab #{args.num}")
    return 0


def cmd_mark(backend, cfg, args, extra) -> int:
    reply = backend.request("mark", {"path": _path(cfg, args.path)})
    print(f"{reply.get('path', args.path)} is now a workspace")
    return 0


def cmd_unmark(backend, cfg, args, extra) -> int:
    reply = backend.request("unmark", {"path": _path(cfg, args.path)})
    print(f"{reply.get('path', args.path)} is no longer a workspace")
    return 0


def cmd_close(backend, cfg, args, extra) -> int:
    backend.request("close", {"num": args.num, "force": args.force})
    print(f"closed tab #{args.num}")
    return 0


COMMANDS = {"tree": cmd_tree, "new": cmd_new, "open": cmd_open, "rename": cmd_rename,
            "mark": cmd_mark, "unmark": cmd_unmark, "close": cmd_close}
