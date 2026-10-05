import json
import plistlib
import sys
from pathlib import Path
from types import SimpleNamespace

from grove_core import setup
from grove_core.config import Config, load
from grove_core.hooks import hooks_installed


def answers(*values):
    it = iter(values)
    return lambda prompt: next(it)


def test_local_setup_writes_config_and_installs_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    said = []
    code = setup.run(Config(), SimpleNamespace(uninstall_hooks=False),
                     ask=answers("", "~/work"), say=said.append, platform="linux")
    assert code == 0
    assert load() == Config(root="~/work")
    assert hooks_installed(tmp_path / "claude" / "settings.json")


def test_uninstall_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    setup.run(Config(), SimpleNamespace(uninstall_hooks=False), ask=answers("", ""),
              say=lambda s: None, platform="linux")
    setup.run(Config(), SimpleNamespace(uninstall_hooks=True), ask=answers(), say=lambda s: None,
              platform="linux")
    assert not hooks_installed(tmp_path / "claude" / "settings.json")


def test_remote_setup_on_mac_installs_agent_and_reports_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setenv("GROVE_STATE_DIR", str(tmp_path / "state"))
    commands, said = [], []

    def fake_run(argv, **kw):
        commands.append(argv)
        return SimpleNamespace(returncode=255, stdout="", stderr="ssh: connect: timed out")

    code = setup.run(Config(), SimpleNamespace(uninstall_hooks=False),
                     ask=answers("fidelity", ""), say=said.append, platform="darwin",
                     home=tmp_path, run_cmd=fake_run)
    assert code == 0
    assert load().host == "fidelity" and load().remote_cmd == "~/.local/bin/grove"
    assert any("cannot reach fidelity" in s for s in said)
    plist = tmp_path / "Library/LaunchAgents/io.github.claude-grove.watch.plist"
    assert plistlib.loads(plist.read_bytes())["ProgramArguments"][1:] == [
        str(Path(sys.argv[0]).absolute()), "watch"]
    assert any(c[:2] == ["launchctl", "bootstrap"] for c in commands)


def test_agent_plist():
    data = plistlib.loads(setup.agent_plist("/u/.local/bin/grove", "/u/log", python="/opt/py/bin/python3"))
    assert data["Label"] == "io.github.claude-grove.watch"
    assert data["ProgramArguments"] == ["/opt/py/bin/python3", "/u/.local/bin/grove", "watch"]
    assert data["KeepAlive"] == {"SuccessfulExit": False} and data["RunAtLoad"] is True


def test_agent_plist_defaults_to_current_interpreter():
    data = plistlib.loads(setup.agent_plist("/u/grove", "/u/log"))
    assert data["ProgramArguments"][0] == sys.executable


def test_install_watch_agent_pins_interpreter(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_STATE_DIR", str(tmp_path / "state"))
    ok = lambda argv, **kw: SimpleNamespace(returncode=0)
    path, _ = setup.install_watch_agent("/u/grove", tmp_path, 501, run=ok, python="/py3")
    assert plistlib.loads(path.read_bytes())["ProgramArguments"] == ["/py3", "/u/grove", "watch"]


def test_remote_ping_summary_tolerates_missing_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setenv("GROVE_STATE_DIR", str(tmp_path / "state"))
    said = []
    fake = lambda argv, **kw: SimpleNamespace(returncode=0, stdout=json.dumps({"ok": {}}), stderr="")
    code = setup.run(Config(host="fidelity"), SimpleNamespace(uninstall_hooks=False),
                     ask=answers("", ""), say=said.append, platform="linux", run_cmd=fake)
    assert code == 0
    assert "fidelity: grove ?, tmux missing, hooks NOT installed — run grove setup there." in said


def test_answering_local_returns_to_local_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    code = setup.run(Config(host="fidelity"), SimpleNamespace(uninstall_hooks=False),
                     ask=answers("Local", ""), say=lambda s: None, platform="linux")
    assert code == 0
    assert load().is_local
    assert hooks_installed(tmp_path / "claude" / "settings.json")


def test_blank_keeps_remote_host(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setenv("GROVE_STATE_DIR", str(tmp_path / "state"))
    fake = lambda argv, **kw: SimpleNamespace(returncode=255, stdout="", stderr="x")
    setup.run(Config(host="fidelity"), SimpleNamespace(uninstall_hooks=False),
              ask=answers("", ""), say=lambda s: None, platform="linux", run_cmd=fake)
    assert load().host == "fidelity"


def test_watch_agent_load_result(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_STATE_DIR", str(tmp_path / "state"))
    ok = lambda argv, **kw: SimpleNamespace(returncode=0)
    bad = lambda argv, **kw: SimpleNamespace(returncode=5 if argv[1] == "bootstrap" else 0)
    assert setup.install_watch_agent("/u/grove", tmp_path, 501, run=ok)[1] == 0
    assert setup.install_watch_agent("/u/grove", tmp_path, 501, run=bad)[1] == 5


def test_setup_reports_agent_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setenv("GROVE_STATE_DIR", str(tmp_path / "state"))
    said = []
    fake = lambda argv, **kw: SimpleNamespace(returncode=5, stdout="", stderr="")
    setup.run(Config(host="fidelity"), SimpleNamespace(uninstall_hooks=False),
              ask=answers("", ""), say=said.append, platform="darwin", home=tmp_path, run_cmd=fake)
    assert any("Could not load the notifier agent (launchctl exit 5)" in s for s in said)
    assert not any(s.startswith("Installed the notifier") for s in said)


def test_uninstall_without_backup_message(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    said = []
    setup.run(Config(), SimpleNamespace(uninstall_hooks=True), ask=answers(), say=said.append,
              platform="linux")
    assert said == ["Removed grove's Claude hooks."]
