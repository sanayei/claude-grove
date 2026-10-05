import json

import pytest

from grove_core import cli
from grove_core.client import RemoteError
from grove_core.config import Config
from grove_core.ops import NeedsConfirm

TREE = {"root": "/r", "host": "h", "now": 100.0, "workspaces": [
    {"path": "trading", "session": "grove/trading", "missing": False, "tabs": [
        {"id": "@12", "num": 12, "dir": "", "label": "x", "kind": "claude", "status": "working", "since": 40.0}]},
    {"path": "publications", "session": "grove/publications", "missing": False, "tabs": [
        {"id": "@13", "num": 13, "dir": "", "label": "y", "kind": "claude", "status": "idle", "since": 40.0}]},
]}
TREE_JSON = json.dumps(TREE)          # pristine copy: cmd_tree filters its reply in place


class FakeBackend:
    def __init__(self, replies=None, error=None):
        self.calls, self.replies, self.error = [], replies or {}, error

    def request(self, op, params):
        self.calls.append((op, params))
        if self.error:
            raise self.error
        return self.replies.get(op, {})


@pytest.fixture
def fake(monkeypatch):
    backend = FakeBackend({"tree": TREE,
                           "new": {"session": "grove/trading", "window_id": "@14", "warning": ""},
                           "resolve": {"session": "grove/trading", "window_id": None}})
    monkeypatch.setattr(cli, "make_backend", lambda cfg: backend)
    monkeypatch.setattr(cli.config, "load", lambda: Config(host="h"))
    opened = []
    monkeypatch.setattr(cli, "open_session", lambda b, c, s, w, replace=True: opened.append((s, w)) or 0)
    backend.opened = opened
    return backend


def test_tree(fake, capsys):
    assert cli.main(["tree"]) == 0
    out = capsys.readouterr().out
    assert "#12 root · x" in out and "#13 root · y" in out


def test_tree_subpath(fake, capsys):
    cli.main(["tree", "trading"])
    out = capsys.readouterr().out
    assert "#12" in out and "#13" not in out


def test_new_passes_everything_after_double_dash(fake, capsys):
    assert cli.main(["new", "trading/src", "fix auth", "--rc", "--", "--resume", "--model", "x"]) == 0
    assert fake.calls[-1] == ("new", {"path": "trading/src", "label": "fix auth", "kind": "claude",
                                      "claude_args": ["--resume", "--model", "x"], "rc": True})
    assert fake.opened == [("grove/trading", "@14")]
    assert "created tab #14" in capsys.readouterr().out


def test_new_shell_no_open_and_warning(fake, capsys):
    fake.replies["new"] = {"session": "grove/trading", "window_id": "@15", "warning": "careful"}
    assert cli.main(["new", "trading", "--shell", "--no-open"]) == 0
    assert fake.calls[-1][1]["kind"] == "shell"
    assert fake.opened == []
    assert "warning: careful" in capsys.readouterr().err


def test_open_requires_target(fake, capsys):
    assert cli.main(["open"]) == 1
    assert "folder or --tab" in capsys.readouterr().err


def test_open_by_path_and_tab(fake):
    cli.main(["open", "trading"])
    cli.main(["open", "--tab", "12"])
    assert fake.calls == [("resolve", {"path": "trading"}), ("resolve", {"num": 12})]
    assert len(fake.opened) == 2


def test_rename_mark_unmark_close(fake, capsys):
    cli.main(["rename", "12", "new label"])
    cli.main(["mark", "publications/p1"])
    cli.main(["unmark", "publications/p1"])
    cli.main(["close", "12", "--force"])
    assert [c[0] for c in fake.calls] == ["rename", "mark", "unmark", "close"]
    assert fake.calls[0][1] == {"num": 12, "label": "new label"}
    assert fake.calls[3][1] == {"num": 12, "force": True}


def test_close_needing_confirmation_exits_2(fake, monkeypatch, capsys):
    fake.error = NeedsConfirm("tab #12 is working; close it anyway with --force")
    assert cli.main(["close", "12"]) == 2
    assert "--force" in capsys.readouterr().err


def test_remote_errors_are_one_line(fake, capsys):
    fake.error = RemoteError("cannot reach h: Connection timed out")
    assert cli.main(["tree"]) == 1
    err = capsys.readouterr().err
    assert err.strip() == "grove: cannot reach h: Connection timed out"


def test_remote_entry_point(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(cli, "remote_main", lambda op, params: seen.append((op, params)) or 0)
    assert cli.main(["--remote", "tree", "{}"]) == 0
    assert seen == [("tree", "{}")]


def test_normalize_path(tmp_path):
    root = tmp_path / "projects"
    (root / "trading/src").mkdir(parents=True)
    local = Config(root=str(root))
    assert cli.normalize_path(local, ".", root / "trading/src") == "trading/src"
    assert cli.normalize_path(local, str(root / "trading"), tmp_path) == "trading"
    assert cli.normalize_path(local, "trading/src", tmp_path) == "trading/src"
    assert cli.normalize_path(Config(host="h"), ".", root / "trading") == "."   # remote: untouched


def test_invalid_config_file(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "config.toml"
    bad.write_text("this is = = not toml\n")
    monkeypatch.setenv("GROVE_CONFIG", str(bad))
    assert cli.main(["tree"]) == 1
    assert capsys.readouterr().err.startswith(f"grove: invalid config file {bad}: ")


def test_tree_path_is_normalized_locally(tmp_path, monkeypatch, capsys):
    root = tmp_path / "projects"
    (root / "trading/src").mkdir(parents=True)
    backend = FakeBackend({"tree": json.loads(TREE_JSON)})
    monkeypatch.setattr(cli, "make_backend", lambda cfg: backend)
    monkeypatch.setattr(cli.config, "load", lambda: Config(root=str(root)))
    monkeypatch.chdir(root / "trading/src")
    assert cli.main(["tree", ".."]) == 0
    out = capsys.readouterr().out
    assert "#12" in out and "#13" not in out
    backend.replies["tree"] = json.loads(TREE_JSON)            # cmd_tree filters the reply in place
    assert cli.main(["tree", str(root / "publications")]) == 0
    out = capsys.readouterr().out
    assert "#13" in out and "#12" not in out
