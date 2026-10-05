import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_install(home, path_dirs):
    env = {"HOME": str(home), "PATH": ":".join(path_dirs), "GROVE_SKIP_SETUP": "1"}
    return subprocess.run(["sh", str(ROOT / "install.sh")], env=env, capture_output=True, text=True)


def test_installs_as_grove(tmp_path):
    proc = run_install(tmp_path, ["/usr/bin", "/bin"])
    assert proc.returncode == 0, proc.stderr
    link = tmp_path / ".local/bin/grove"
    assert link.is_symlink() and os.path.realpath(link) == str(ROOT / "grove")


def test_falls_back_to_cgrove_when_grove_exists(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "grove").write_text("#!/bin/sh\n")
    (other / "grove").chmod(0o755)
    proc = run_install(tmp_path, [str(other), "/usr/bin", "/bin"])
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / ".local/bin/cgrove").is_symlink()
    assert not (tmp_path / ".local/bin/grove").exists()
    assert "cgrove" in proc.stdout


def test_reinstall_keeps_name(tmp_path):
    run_install(tmp_path, ["/usr/bin", "/bin"])
    proc = run_install(tmp_path, [str(tmp_path / ".local/bin"), "/usr/bin", "/bin"])
    assert proc.returncode == 0 and (tmp_path / ".local/bin/grove").is_symlink()
