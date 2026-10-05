from grove_core import config


def test_load_missing_returns_defaults(tmp_path):
    cfg = config.load(tmp_path / "none.toml")
    assert cfg == config.Config()
    assert cfg.is_local
    assert cfg.root == "~/projects"
    assert cfg.remote_cmd == "~/.local/bin/grove"


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    cfg = config.Config(
        host="fidelity", root="~/work dir/ö", notify=False,
        remote_cmd="~/.local/bin/cgrove", ssh_opts=["-p", "2222"],
    )
    config.save(cfg, path)
    assert config.load(path) == cfg
    assert not config.load(path).is_local


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('host = "box"\ncolour = "red"\n')
    assert config.load(path).host == "box"


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("GROVE_CONFIG", str(tmp_path / "x.toml"))
    monkeypatch.setenv("GROVE_STATE_DIR", str(tmp_path / "state"))
    assert config.config_path() == tmp_path / "x.toml"
    assert config.state_dir() == tmp_path / "state"
    assert (tmp_path / "state").is_dir()


def test_root_path_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.Config(root="~/p").root_path() == tmp_path / "p"
