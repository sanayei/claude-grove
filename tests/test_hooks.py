import json

import pytest

from grove_core import hooks
from grove_core.hooks import (
    EVENT_STATUS, SettingsError, handle_hook, hook_command, hooks_installed,
    install_hooks, run_hook, uninstall_hooks, update_settings_file,
)
from grove_core.status import read_events, read_status

LAUNCHER = "/home/u/.local/bin/grove"


def pane_of(tmux, wid):
    return tmux.run("display-message", "-p", "-t", wid, "#{pane_id}").strip()


@pytest.fixture
def claude_tab(tmux, tmp_path):
    wid = tmux.new_session("trading", "trading", tmp_path)
    tmux.set_window(wid, kind="claude", dir="src", label="fix")
    return wid


def test_hook_outside_tmux_does_nothing(tmux, tmp_path):
    assert handle_hook("Stop", {}, tmux, tmp_path / "s", 1.0) is False
    assert not (tmp_path / "s").exists()


def test_hook_in_a_non_grove_tmux_session_does_nothing(tmux, tmp_path):
    tmux.run("new-session", "-d", "-s", "mine")
    pane = tmux.run("display-message", "-p", "-t", "=mine", "#{pane_id}").strip()
    assert handle_hook("Stop", {"TMUX_PANE": pane}, tmux, tmp_path / "s", 1.0) is False
    assert not (tmp_path / "s").exists()


def test_hook_in_a_grove_shell_tab_does_nothing(tmux, tmp_path):
    wid = tmux.new_session("trading", "trading", tmp_path)
    tmux.set_window(wid, kind="shell", dir="", label="shell")
    assert handle_hook("Stop", {"TMUX_PANE": pane_of(tmux, wid)}, tmux, tmp_path / "s", 1.0) is False


def test_stop_in_a_claude_tab_records_finished(tmux, tmp_path, claude_tab):
    state = tmp_path / "s"
    assert handle_hook("Stop", {"TMUX_PANE": pane_of(tmux, claude_tab)}, tmux, state, 50.0)
    assert read_status(state, claude_tab).status == "idle"
    (event,) = read_events(state, 0)
    assert event["event"] == "finished" and event["status"] == "idle"
    assert event["tab"] == "src · fix" and event["workspace"] == "trading"
    assert event["num"] == int(claude_tab[1:]) and event["window_id"] == claude_tab and event["ts"] == 50.0


@pytest.mark.parametrize("event,status,name", [
    ("UserPromptSubmit", "working", "working"),
    ("Notification", "needs-input", "needs-input"),
    ("SessionStart", "idle", "idle"),
    ("SessionEnd", "exited", "exited"),
])
def test_event_mapping(tmux, tmp_path, claude_tab, event, status, name):
    state = tmp_path / "s"
    handle_hook(event, {"TMUX_PANE": pane_of(tmux, claude_tab)}, tmux, state, 1.0)
    assert read_status(state, claude_tab).status == status
    assert read_events(state, 0)[0]["event"] == name


def test_unknown_event_is_ignored(tmux, tmp_path, claude_tab):
    assert handle_hook("PreToolUse", {"TMUX_PANE": pane_of(tmux, claude_tab)}, tmux, tmp_path / "s", 1.0) is False


def test_run_hook_never_fails(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("GROVE_STATE_DIR", str(blocker / "state"))   # cannot be created
    monkeypatch.setenv("TMUX_PANE", "%99999")
    monkeypatch.setattr("sys.stdin", open("/dev/null"))
    assert run_hook("Stop") == 0


def test_hook_command_quotes_launcher():
    assert hook_command("/x/my dir/grove", "Stop") == "'/x/my dir/grove' hook Stop # grove-hook"


def test_install_preserves_user_hooks_and_is_idempotent():
    mine = {"hooks": [{"type": "command", "command": "say done"}]}
    settings = {"theme": "dark", "hooks": {"Stop": [mine]}}
    once = install_hooks(settings, LAUNCHER)
    twice = install_hooks(once, LAUNCHER)
    assert once == twice
    assert twice["theme"] == "dark"
    assert twice["hooks"]["Stop"][0] == mine
    assert len(twice["hooks"]["Stop"]) == 2
    for event in EVENT_STATUS:
        (group,) = [g for g in twice["hooks"][event] if hooks.TAG in g["hooks"][0]["command"]]
        assert group["hooks"][0] == {"type": "command", "command": hook_command(LAUNCHER, event), "timeout": 1}
    assert settings == {"theme": "dark", "hooks": {"Stop": [mine]}}       # input untouched


def test_uninstall_removes_only_grove_entries():
    mine = {"hooks": [{"type": "command", "command": "say done"}]}
    installed = install_hooks({"hooks": {"Stop": [mine]}}, LAUNCHER)
    assert uninstall_hooks(installed) == {"hooks": {"Stop": [mine]}}
    assert uninstall_hooks(install_hooks({}, LAUNCHER)) == {}


def test_update_settings_file_creates_backs_up_and_detects(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    assert update_settings_file(path, LAUNCHER, 5.0) is None            # created, nothing to back up
    assert hooks_installed(path)
    original = path.read_text()
    backup = update_settings_file(path, None, 6.0)
    assert backup.read_text() == original and backup.name == "settings.json.grove-backup-6"
    assert not hooks_installed(path)


def test_update_settings_file_refuses_invalid_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ broken")
    with pytest.raises(SettingsError):
        update_settings_file(path, LAUNCHER, 1.0)
    assert path.read_text() == "{ broken"


def test_hooks_installed_false_for_missing_or_broken(tmp_path):
    assert not hooks_installed(tmp_path / "none.json")
    (tmp_path / "b.json").write_text("nope")
    assert not hooks_installed(tmp_path / "b.json")


def test_settings_path_honours_claude_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert hooks.settings_path() == tmp_path / "settings.json"


def test_run_hook_bogus_pane_returns_zero_and_does_not_log(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("GROVE_STATE_DIR", str(state))
    monkeypatch.setenv("TMUX_PANE", "%99999")
    monkeypatch.setattr("sys.stdin", open("/dev/null"))
    assert run_hook("Stop") == 0
    assert not (state / "grove.log").exists()


def test_run_hook_logs_traceback_when_handler_raises(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("GROVE_STATE_DIR", str(state))
    monkeypatch.setattr("sys.stdin", open("/dev/null"))

    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(hooks, "handle_hook", boom)
    assert run_hook("Stop") == 0
    assert "kaboom" in (state / "grove.log").read_text()


def test_run_hook_survives_state_dir_failure(monkeypatch):
    monkeypatch.setattr("sys.stdin", open("/dev/null"))

    def boom(*a, **k):
        raise RuntimeError("no home")
    monkeypatch.setattr(hooks, "state_dir", boom)
    assert run_hook("Stop") == 0


def test_symlinked_settings_stays_symlink(tmp_path):
    target = tmp_path / "dotfiles" / "settings.json"
    target.parent.mkdir()
    target.write_text("{}")
    link = tmp_path / "settings.json"
    link.symlink_to(target)
    update_settings_file(link, LAUNCHER, 1.0)
    assert link.is_symlink()
    assert hooks_installed(target)


def test_settings_permissions_preserved(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}")
    path.chmod(0o600)
    update_settings_file(path, LAUNCHER, 1.0)
    assert path.stat().st_mode & 0o777 == 0o600


def test_non_object_settings_refused_before_backup(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[]")
    with pytest.raises(SettingsError):
        update_settings_file(path, LAUNCHER, 1.0)
    assert list(tmp_path.iterdir()) == [path]


def test_uninstall_on_missing_file_is_noop(tmp_path):
    path = tmp_path / "sub" / "settings.json"
    assert update_settings_file(path, None, 1.0) is None
    assert not path.exists() and not path.parent.exists()


def test_settings_written_without_ascii_escaping(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"name": "é"}', encoding="utf-8")
    update_settings_file(path, LAUNCHER, 1.0)
    assert "é" in path.read_text(encoding="utf-8")
