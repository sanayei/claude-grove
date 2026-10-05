import shutil
import subprocess
import uuid

import pytest


@pytest.fixture
def tmux(monkeypatch):
    """A Tmux bound to a private, throw-away tmux server."""
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    from grove_core.tmux import Tmux

    monkeypatch.delenv("TMUX", raising=False)
    socket = f"grove-test-{uuid.uuid4().hex[:8]}"
    yield Tmux(socket)
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)
