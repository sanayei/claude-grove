import plistlib
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
    assert plistlib.loads(plist.read_bytes())["ProgramArguments"][1] == "watch"
    assert any(c[:2] == ["launchctl", "bootstrap"] for c in commands)


def test_agent_plist():
    data = plistlib.loads(setup.agent_plist("/u/.local/bin/grove", "/u/log"))
    assert data["Label"] == "io.github.claude-grove.watch"
    assert data["ProgramArguments"] == ["/u/.local/bin/grove", "watch"]
    assert data["KeepAlive"] is True and data["RunAtLoad"] is True
