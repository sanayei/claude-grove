import shutil

import pytest

from grove_core.ops import Grove, NeedsConfirm, OpError, dispatch
from grove_core.status import read_status, write_status
from grove_core.workspaces import PathError
from tests.test_tmux import wait_for


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "projects"
    for d in ["trading/src", "publications/p1/figures", "publications/p2", "trading/it's ö"]:
        (r / d).mkdir(parents=True)
    (r / "publications/p1/.grove").touch()
    return r


@pytest.fixture
def grove(tmux, root, tmp_path):
    return Grove(root, tmux, tmp_path / "state", clock=lambda: 1000.0,
                 host_label="test", claude_cmd=["sleep", "30"])


def tabs_of(tree, path):
    return [w for w in tree["workspaces"] if w["path"] == path][0]["tabs"]


def test_new_tab_creates_session_with_shell_tab(grove):
    reply = grove.new_tab("trading/src", "fix auth")
    assert reply["session"] == "trading" and reply["warning"] == ""
    tabs = tabs_of(grove.tree(), "trading")
    assert [(t["kind"], t["dir"], t["label"]) for t in tabs] == [("shell", "", "shell"), ("claude", "src", "fix auth")]
    assert grove.tmux.run("display-message", "-p", "-t", reply["window_id"], "#{window_name}").strip() == "src · fix auth"


def test_new_tab_goes_to_nearest_marked_workspace(grove):
    reply = grove.new_tab("publications/p1/figures")
    assert reply["session"] == "publications/p1"
    assert tabs_of(grove.tree(), "publications/p1")[-1]["dir"] == "figures"


def test_new_tab_handles_quotes_and_unicode(grove):
    reply = grove.new_tab("trading/it's ö", "naïve label")
    assert tabs_of(grove.tree(), "trading")[-1]["dir"] == "it's ö"
    assert reply["window_id"].startswith("@")


def test_new_tab_rejects_paths_outside_root_before_touching_tmux(grove):
    with pytest.raises(PathError):
        grove.new_tab("../..")
    assert grove.tmux.windows() == []


def test_second_claude_in_same_folder_warns(grove):
    first = grove.new_tab("trading/src")
    assert wait_for(lambda: [w for w in grove.tmux.windows() if w.id == first["window_id"]][0].command == "sleep")
    assert "git worktree" in grove.new_tab("trading/src")["warning"]
    assert grove.new_tab("trading/src", kind="shell")["warning"] == ""


def test_claude_command():
    g = Grove.__new__(Grove)
    g.claude_cmd = ["claude"]
    assert g.claude_command(["--resume"], rc=True) == ["claude", "--remote-control", "--resume"]
    assert g.claude_command([], rc=False) == ["claude"]


def test_rename(grove):
    num = int(grove.new_tab("trading/src", "a")["window_id"][1:])
    grove.rename(num, "b")
    assert tabs_of(grove.tree(), "trading")[-1]["label"] == "b"


def test_close_asks_for_confirmation_when_live(grove):
    wid = grove.new_tab("trading/src")["window_id"]
    assert wait_for(lambda: [w for w in grove.tmux.windows() if w.id == wid][0].command == "sleep")
    write_status(grove.state, wid, "working", "UserPromptSubmit", 1000.0)
    with pytest.raises(NeedsConfirm):
        grove.close(int(wid[1:]))
    grove.close(int(wid[1:]), force=True)
    assert wid not in [w.id for w in grove.tmux.windows()]
    assert read_status(grove.state, wid) is None


def test_close_idle_tab_without_confirmation(grove):
    wid = grove.new_tab("trading/src", kind="shell")["window_id"]
    grove.close(int(wid[1:]))
    assert wid not in [w.id for w in grove.tmux.windows()]


def test_unknown_tab_number(grove):
    with pytest.raises(OpError):
        grove.rename(99999, "x")


def test_resolve_by_path_and_number(grove):
    assert grove.resolve(path="publications/p2") == {"session": "publications", "window_id": None}
    assert grove.tmux.has_session("publications")
    wid = grove.new_tab("trading/src")["window_id"]
    assert grove.resolve(num=int(wid[1:])) == {"session": "trading", "window_id": wid}


def test_mark_invalidates_workspace_cache(grove):
    assert "publications/p2" not in grove.workspaces()
    grove.mark("publications/p2")
    assert "publications/p2" in grove.workspaces()
    grove.unmark("publications/p2")
    assert "publications/p2" not in grove.workspaces()


def test_tree_lists_all_workspaces_and_missing_folders(grove, root):
    grove.new_tab("publications/p1")
    shutil.rmtree(root / "publications/p1")
    tree = grove.tree()
    assert tree["host"] == "test" and tree["now"] == 1000.0
    p1 = [w for w in tree["workspaces"] if w["path"] == "publications/p1"][0]
    assert p1["missing"] is True and p1["tabs"]
    assert {"trading", "publications"} <= {w["path"] for w in tree["workspaces"]}


def test_listdir(grove):
    assert grove.listdir("") == {"path": "", "dirs": ["publications", "trading"]}
    assert grove.listdir("trading")["dirs"] == ["it's ö", "src"]


def test_dispatch(grove):
    assert dispatch(grove, "ls", {"path": "trading"})["dirs"] == ["it's ö", "src"]
    reply = dispatch(grove, "new", {"path": "trading/src", "label": "x", "kind": "shell"})
    assert reply["session"] == "trading"
    assert dispatch(grove, "ping", {})["version"] == "0.1.0"
    with pytest.raises(OpError):
        dispatch(grove, "explode", {})
