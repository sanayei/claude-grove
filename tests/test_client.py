import json
import shlex
from types import SimpleNamespace

import pytest

from grove_core.client import RemoteBackend, RemoteError, attach_argv, parse_reply
from grove_core.config import Config
from grove_core.ops import NeedsConfirm

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
