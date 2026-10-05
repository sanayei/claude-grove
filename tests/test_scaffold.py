import subprocess
import sys
from pathlib import Path

import grove_core

ROOT = Path(__file__).resolve().parent.parent


def test_version():
    assert grove_core.__version__ == "0.1.0"


def test_launcher_runs_help():
    proc = subprocess.run([sys.executable, str(ROOT / "grove"), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "grove" in proc.stdout
