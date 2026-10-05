from types import SimpleNamespace

from grove_core import doctor
from grove_core.client import RemoteError
from grove_core.config import Config


def test_parse_tmux_version():
    assert doctor.parse_tmux_version("tmux 3.6a") == (3, 6)
    assert doctor.parse_tmux_version("tmux next-3.7") == (3, 7)
    assert doctor.parse_tmux_version("nonsense") is None


def names(checks):
    return {c.name: c for c in checks}


def test_local_linux_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="tmux 3.1\n", stderr="")
    checks = names(doctor.collect(Config(), which=lambda n: "/usr/bin/" + n, run=run, platform="linux"))
    assert checks["python"].ok
    assert not checks["tmux"].ok and "3.2" in checks["tmux"].fix
    assert not checks["claude hooks"].ok and "grove setup" in checks["claude hooks"].fix
    assert "iTerm2" not in checks


def test_remote_mac_checks():
    class Backend:
        def request(self, op, params):
            return {"version": "0.1.0", "tmux": "tmux 3.6a", "hooks": True}

    run = lambda argv, **kw: SimpleNamespace(returncode=1, stdout="", stderr="")
    checks = names(doctor.collect(Config(host="fidelity"), which=lambda n: None, run=run,
                                  platform="darwin", backend=Backend()))
    assert checks["remote"].ok and checks["remote tmux"].ok and checks["remote hooks"].ok
    assert checks["terminal-notifier"].optional and not checks["terminal-notifier"].ok
    assert not checks["watch agent"].ok


def test_remote_unreachable():
    class Backend:
        def request(self, op, params):
            raise RemoteError("cannot reach fidelity: timed out")

    checks = names(doctor.collect(Config(host="fidelity"), which=lambda n: None,
                                  run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
                                  platform="linux", backend=Backend()))
    assert not checks["remote"].ok and "timed out" in checks["remote"].detail


def test_remote_reply_missing_keys():
    class Backend:
        def request(self, op, params):
            return {}

    checks = names(doctor.collect(Config(host="fidelity"), which=lambda n: None,
                                  run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
                                  platform="linux", backend=Backend()))
    assert not checks["remote tmux"].ok and not checks["remote hooks"].ok
