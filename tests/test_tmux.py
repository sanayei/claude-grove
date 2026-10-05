import time

from grove_core.tmux import Window


def wait_for(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_no_server_means_no_windows(tmux):
    assert tmux.windows() == []


def test_session_window_options_roundtrip(tmux, tmp_path):
    first = tmux.new_session("trading", "trading", tmp_path)
    tmux.set_window(first, kind="shell", dir="", label="shell")
    second = tmux.new_window("trading", tmp_path)
    tmux.set_window(second, kind="claude", dir="src", label="it's ö")
    tmux.set_title(second, "src · it's ö")
    wins = {w.id: w for w in tmux.windows()}
    assert set(wins) == {first, second}
    w = wins[second]
    assert (w.session, w.ws, w.kind, w.dir, w.label) == ("trading", "trading", "claude", "src", "it's ö")
    assert w.num == int(second.lstrip("@"))
    assert tmux.run("display-message", "-p", "-t", second, "#{window_name}").strip() == "src · it's ö"


def test_non_grove_sessions_are_ignored(tmux, tmp_path):
    tmux.run("new-session", "-d", "-s", "other")
    tmux.new_session("trading", "trading", tmp_path)
    assert {w.session for w in tmux.windows()} == {"trading"}


def test_has_session_is_exact(tmux, tmp_path):
    tmux.new_session("publications/p1", "publications/p1", tmp_path)
    assert tmux.has_session("publications/p1")
    assert not tmux.has_session("publications")


def test_escaped_session_names_are_accepted(tmux, tmp_path):
    from grove_core.workspaces import session_name
    name = session_name("pubs/v1.2:draft")
    tmux.new_session(name, "pubs/v1.2:draft", tmp_path)
    assert tmux.has_session(name)
    assert tmux.windows()[0].ws == "pubs/v1.2:draft"


def test_window_size_latest(tmux, tmp_path):
    tmux.new_session("trading", "trading", tmp_path)
    assert tmux.run("show-options", "-t", "=trading:", "-v", "window-size").strip() == "latest"


def test_window_of_pane(tmux, tmp_path):
    wid = tmux.new_session("trading", "trading", tmp_path)
    tmux.set_window(wid, kind="claude", dir="", label="")
    pane = tmux.run("display-message", "-p", "-t", wid, "#{pane_id}").strip()
    assert tmux.window_of_pane(pane).id == wid
    assert tmux.window_of_pane("%9999") is None


def test_send_line_and_current_command(tmux, tmp_path):
    wid = tmux.new_session("trading", "trading", tmp_path)
    tmux.send_line(wid, "sleep 30")
    assert wait_for(lambda: tmux.windows()[0].command == "sleep")


def test_kill_window(tmux, tmp_path):
    tmux.new_session("trading", "trading", tmp_path)
    second = tmux.new_window("trading", tmp_path)
    tmux.kill_window(second)
    assert [w.id for w in tmux.windows()] != [] and second not in [w.id for w in tmux.windows()]


def test_window_dataclass_num():
    assert Window("s", "@42", 0, "ws", "claude", "", "", "bash").num == 42
