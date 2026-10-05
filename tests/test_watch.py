import io
import json
import subprocess
from types import SimpleNamespace

from grove_core.watch import Watcher, message_for, notify_mac


def ev(seq, event, ts=1000.0, wid="@3"):
    return {"seq": seq, "ts": ts, "window_id": wid, "num": int(wid[1:]), "workspace": "trading",
            "tab": "src · fix", "status": "idle", "event": event}


def test_message_for():
    assert message_for(ev(1, "finished"), 1000.0) == ("grove · trading", "#3 src · fix — finished")
    assert message_for(ev(1, "needs-input"), 1000.0) == ("grove · trading", "#3 src · fix — needs your input")
    assert message_for(ev(1, "working"), 1000.0) is None
    assert message_for(ev(1, "finished", ts=0.0), 1000.0)[1].endswith("(late)")


class Stream:
    def __init__(self, lines):
        self.stdout = io.StringIO("".join(json.dumps(l) + "\n" for l in lines) + "garbage\n")

    def wait(self):
        return 0


def make(tmp_path, lines, clock=lambda: 1000.0):
    sent, argvs, kwargs = [], [], []

    def popen(argv, **kw):
        kwargs.append(kw)
        return Stream(lines)

    backend = SimpleNamespace(stream_argv=lambda since: argvs.append(since) or ["x"])
    w = Watcher(backend, tmp_path, notify=lambda title, text, num: sent.append((text, num)),
                popen=popen, sleep=lambda s: None, clock=clock)
    w.popen_kwargs = kwargs
    return w, sent, argvs


def test_run_once_notifies_and_saves_cursor(tmp_path):
    w, sent, argvs = make(tmp_path, [{"cursor": 4}, ev(5, "finished"), ev(6, "working")])
    w.run_once()
    assert argvs == [None]
    assert sent == [("#3 src · fix — finished", 3)]
    assert w.load_cursor() == 6


def test_run_once_never_reads_the_terminal(tmp_path):
    w, _, _ = make(tmp_path, [{"cursor": 1}])
    w.run_once()
    kw = w.popen_kwargs[0]
    assert kw["stdin"] == subprocess.DEVNULL
    assert kw["stdout"] == subprocess.PIPE
    assert kw["text"] is True


def test_resumes_from_saved_cursor(tmp_path):
    w, _, argvs = make(tmp_path, [{"cursor": 6}])
    w.save_cursor(6)
    w.run_once()
    assert argvs == [6]


def test_needs_input_right_after_finished_is_suppressed(tmp_path):
    w, sent, _ = make(tmp_path, [{"cursor": 0}, ev(1, "finished", ts=1000.0),
                                 ev(2, "needs-input", ts=1060.0),
                                 ev(3, "needs-input", ts=1060.0, wid="@4"),
                                 ev(4, "needs-input", ts=1300.0)])
    w.run_once()
    assert [n for _, n in sent] == [3, 4, 3]


def test_run_forever_backs_off_on_failures(tmp_path):
    sleeps = []
    backend = SimpleNamespace(stream_argv=lambda since: ["x"])

    def boom(argv, **kw):
        raise OSError("ssh missing")

    w = Watcher(backend, tmp_path, notify=lambda *a: None, popen=boom,
                sleep=sleeps.append, clock=lambda: 0.0)
    w.run_forever(max_rounds=8)
    assert sleeps == [1, 2, 4, 8, 16, 32, 60, 60]


def test_notify_mac_plain_and_clickable():
    calls = []
    notify_mac('He said "hi"', "text", 3, "/u/grove", run=lambda argv, **kw: calls.append(argv),
               which=lambda name: None)
    assert calls[0][:2] == ["osascript", "-e"]
    assert 'with title "He said \\"hi\\""' in calls[0][2]
    calls.clear()
    notify_mac("t", "x", 3, "/u/grove", run=lambda argv, **kw: calls.append(argv),
               which=lambda name: "/usr/local/bin/terminal-notifier")
    argv = calls[0]
    assert argv[0] == "/usr/local/bin/terminal-notifier"
    assert "/u/grove open --tab 3" in argv[argv.index("-execute") + 1]
