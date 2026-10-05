import json
import shlex
from types import SimpleNamespace

import pytest

from grove_core import client
from grove_core.client import LocalBackend, RemoteBackend, RemoteError, attach_argv, parse_reply
from grove_core.config import Config
from grove_core.ops import NeedsConfirm, OpError
from grove_core.tmux import TmuxError
from grove_core.workspaces import PathError

CFG = Config(host="fidelity", ssh_opts=["-p", "2222"])


def test_parse_reply_tolerates_banners():
    out = "Welcome to Ubuntu\nsome motd\n" + json.dumps({"ok": {"a": 1}}) + "\n"
    assert parse_reply(0, out, "", "fidelity") == {"a": 1}


def test_parse_reply_errors():
    with pytest.raises(RemoteError, match="cannot reach fidelity: Connection timed out"):
        parse_reply(255, "", "ssh: connect to host fidelity port 22: Connection timed out\n", "fidelity")
    with pytest.raises(RemoteError, match="grove doctor"):
        parse_reply(127, "", "bash: /home/u/.local/bin/grove: No such file or directory", "fidelity")
    with pytest.raises(NeedsConfirm, match="is working"):
        parse_reply(0, json.dumps({"error": "tab #3 is working", "confirm": True}), "", "fidelity")
    with pytest.raises(RemoteError, match="boom"):
        parse_reply(0, json.dumps({"error": "boom"}), "", "fidelity")


def test_request_builds_safe_ssh_command(tmp_path):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": {}}), stderr="")

    params = {"path": "trading/it's my ö", "label": 'say "hi"; rm -rf ~'}
    RemoteBackend(CFG, tmp_path, run=fake_run).request("new", params)
    argv = seen["argv"]
    assert argv[0] == "ssh" and "ConnectTimeout=5" in argv and "-p" in argv
    assert any(a.startswith(f"ControlPath={tmp_path}/ssh-") for a in argv)
    assert argv[-2] == "fidelity"
    words = shlex.split(argv[-1])
    assert words[:3] == ["~/.local/bin/grove", "--remote", "new"]
    assert json.loads(words[3]) == params


def test_stream_argv(tmp_path):
    argv = RemoteBackend(CFG, tmp_path).stream_argv(since=7)
    words = shlex.split(argv[-1])
    assert words[2] == "events" and json.loads(words[3]) == {"since": 7, "follow": True}


def test_attach_argv_remote_iterm(tmp_path):
    backend = RemoteBackend(CFG, tmp_path)
    argv = attach_argv(CFG, backend, "pubs/v1%2E2", "@12", iterm=True, inside_tmux=False)
    assert argv[0] == "ssh" and "-t" in argv and argv[-2] == "fidelity"
    assert argv[-1] == "tmux select-window -t @12 2>/dev/null; exec tmux -CC attach -t =pubs/v1%2E2"


def test_attach_argv_local_variants():
    local = Config()
    assert attach_argv(local, None, "trading", None, iterm=False, inside_tmux=False) == \
        ["sh", "-c", "exec tmux attach -t =trading"]
    assert attach_argv(local, None, "trading", "@3", iterm=False, inside_tmux=True) == \
        ["sh", "-c", "tmux select-window -t @3 2>/dev/null; exec tmux switch-client -t =trading"]


def test_ssh_argv_batch_only_when_not_tty(tmp_path):
    backend = RemoteBackend(CFG, tmp_path)
    plain = backend.ssh_argv()
    assert "-n" in plain and "BatchMode=yes" in plain and "-t" not in plain
    assert "-n" in backend.stream_argv(None) and "BatchMode=yes" in backend.stream_argv(None)
    assert "ServerAliveInterval=10" in plain and "ServerAliveCountMax=2" in plain
    tty = backend.ssh_argv(tty=True)
    assert "ServerAliveInterval=10" in tty and "ServerAliveCountMax=2" in tty
    assert "-t" in tty and "-n" not in tty and "BatchMode=yes" not in tty


def test_request_uses_devnull_stdin(tmp_path):
    import subprocess
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": {}}), stderr="")

    RemoteBackend(CFG, tmp_path, run=fake_run).request("ls", {})
    assert seen["stdin"] is subprocess.DEVNULL


def test_parse_reply_without_ok_or_error():
    with pytest.raises(RemoteError, match="unexpected reply"):
        parse_reply(0, json.dumps({"hello": 1}), "", "fidelity")


def test_parse_reply_shows_last_stderr_line_on_crash():
    trace = "Traceback (most recent call last):\n  File \"x\", line 1\nZeroDivisionError: division by zero\n\n"
    with pytest.raises(RemoteError, match="ZeroDivisionError: division by zero") as info:
        parse_reply(1, "", trace, "fidelity")
    assert "Traceback" not in str(info.value)
    with pytest.raises(RemoteError, match="unexpected reply from fidelity: last words —"):
        parse_reply(1, "banner\nlast words\n\n", "", "fidelity")
    with pytest.raises(RemoteError, match="no output"):
        parse_reply(1, "", "  \n", "fidelity")


@pytest.mark.parametrize("exc", [OpError("op"), PathError("path"), TmuxError("tmux"),
                                 ValueError("value"), KeyError("key"), OSError("os")])
def test_local_backend_converts_errors(monkeypatch, exc):
    def boom(g, op, params):
        raise exc
    monkeypatch.setattr(client, "dispatch", boom)
    with pytest.raises(RemoteError) as info:
        LocalBackend(None, "/u/grove").request("tree", {})
    assert str(exc.args[0]) in str(info.value)


def test_local_backend_keeps_needs_confirm(monkeypatch):
    def boom(g, op, params):
        raise NeedsConfirm("tab #3 is working")
    monkeypatch.setattr(client, "dispatch", boom)
    with pytest.raises(NeedsConfirm, match="is working"):
        LocalBackend(None, "/u/grove").request("close", {"num": 3})
