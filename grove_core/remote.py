"""`grove --remote <op> <json>`: the machine-facing side of the ssh protocol."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .config import Config, load, state_dir
from .ops import Grove, NeedsConfirm, OpError, dispatch
from .status import last_seq, read_events
from .tmux import Tmux, TmuxError
from .workspaces import PathError


def make_grove(cfg: Config) -> Grove:
    return Grove(cfg.root_path(), Tmux(os.environ.get("GROVE_TMUX_SOCKET")), state_dir(),
                 host_label=os.uname().nodename)


def stream_events(state: Path, since: int | None, follow: bool, out=sys.stdout,
                  sleep=time.sleep, max_polls: int | None = None) -> int:
    newest = last_seq(state)
    cursor = newest if since is None else (0 if since > newest else since)
    out.write(json.dumps({"cursor": cursor}) + "\n")
    out.flush()
    polls = 0
    while True:
        for event in read_events(state, cursor):
            out.write(json.dumps(event) + "\n")
            cursor = event["seq"]
        out.flush()
        if not follow or (max_polls is not None and polls >= max_polls):
            return 0
        sleep(1)
        polls += 1


def remote_main(op: str, params_json: str, out=sys.stdout) -> int:
    try:
        params = json.loads(params_json)
        if op == "events":
            return stream_events(state_dir(), params.get("since"), bool(params.get("follow")), out=out)
        reply = {"ok": dispatch(make_grove(load()), op, params)}
    except NeedsConfirm as exc:
        reply = {"error": str(exc), "confirm": True}
    except (OpError, PathError, TmuxError, ValueError, KeyError, OSError) as exc:
        reply = {"error": str(exc) or exc.__class__.__name__}
    out.write(json.dumps(reply) + "\n")
    out.flush()
    return 0
