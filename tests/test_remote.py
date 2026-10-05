import io
import json

import pytest

from grove_core import remote
from grove_core.status import append_event


@pytest.fixture
def env(tmp_path, monkeypatch, tmux):
    root = tmp_path / "projects"
    (root / "trading/src").mkdir(parents=True)
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'root = "{root}"\n')
    monkeypatch.setenv("GROVE_CONFIG", str(cfg))
    monkeypatch.setenv("GROVE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("GROVE_TMUX_SOCKET", tmux.base[-1])
    return tmp_path


def call(op, params):
    out = io.StringIO()
    assert remote.remote_main(op, json.dumps(params), out=out) == 0
    return json.loads(out.getvalue().splitlines()[-1])


def test_ok_envelope(env):
    reply = call("ls", {"path": ""})
    assert reply == {"ok": {"path": "", "dirs": ["trading"]}}


def test_error_envelopes(env):
    assert "error" in call("ls", {"path": "../.."})
    assert "unknown operation" in call("explode", {})["error"]
    out = io.StringIO()
    remote.remote_main("ls", "{not json", out=out)
    assert "error" in json.loads(out.getvalue())


def test_confirm_envelope(env, monkeypatch):
    from grove_core.ops import NeedsConfirm

    def needs_confirm(g, op, params):
        raise NeedsConfirm("tab #3 is working; close it anyway with --force")

    monkeypatch.setattr(remote, "dispatch", needs_confirm)
    assert call("close", {"num": 3}) == {"error": "tab #3 is working; close it anyway with --force",
                                         "confirm": True}


def test_stream_events(tmp_path):
    for i in range(3):
        append_event(tmp_path, {"n": i})
    out = io.StringIO()
    remote.stream_events(tmp_path, since=1, follow=False, out=out)
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert lines[0] == {"cursor": 1}
    assert [e["seq"] for e in lines[1:]] == [2, 3]


def test_stream_events_from_now_and_after_reset(tmp_path):
    append_event(tmp_path, {"n": 0})
    out = io.StringIO()
    remote.stream_events(tmp_path, since=None, follow=False, out=out)
    assert out.getvalue().splitlines() == ['{"cursor": 1}']
    out = io.StringIO()
    remote.stream_events(tmp_path, since=50, follow=False, out=out)       # log was reset remotely
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert lines[0] == {"cursor": 0} and lines[1]["seq"] == 1


def test_stream_events_follow_polls(tmp_path):
    out, polls = io.StringIO(), []

    def fake_sleep(_):
        polls.append(1)
        append_event(tmp_path, {"n": len(polls)})

    remote.stream_events(tmp_path, since=0, follow=True, out=out, sleep=fake_sleep, max_polls=2)
    seqs = [json.loads(line).get("seq") for line in out.getvalue().splitlines()[1:]]
    assert seqs == [1, 2]


def test_bad_params_shapes(env):
    assert "error" in call("ls", [1, 2])
    assert "error" in call("events", {"since": "x"})
    assert "error" in call("events", {"since": True})


def test_events_broken_pipe_ends_quietly(env):
    class Dead:
        def write(self, _):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

    assert remote.remote_main("events", json.dumps({"since": 0, "follow": True}), out=Dead()) == 0
