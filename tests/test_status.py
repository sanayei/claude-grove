import json
import multiprocessing

from grove_core.status import (
    Status, append_event, last_seq, read_events, read_status, reconcile,
    remove_status, write_status,
)
from grove_core.tmux import Window


def win(wid, kind="claude", command="claude"):
    return Window("trading", wid, 0, "trading", kind, "", "", command)


def test_write_read_remove(tmp_path):
    write_status(tmp_path, "@1", "working", "UserPromptSubmit", 100.0)
    assert read_status(tmp_path, "@1") == Status("working", 100.0, "UserPromptSubmit")
    remove_status(tmp_path, "@1")
    assert read_status(tmp_path, "@1") is None


def test_corrupt_status_reads_as_none(tmp_path):
    write_status(tmp_path, "@1", "idle", "x", 1.0)
    (tmp_path / "status" / "@1.json").write_text("{not json")
    assert read_status(tmp_path, "@1") is None


def test_reconcile_keeps_live_status_while_claude_runs(tmp_path):
    write_status(tmp_path, "@1", "working", "UserPromptSubmit", 100.0)
    assert reconcile([win("@1", command="claude")], tmp_path, 500.0)["@1"].status == "working"


def test_reconcile_marks_exited_when_pane_is_back_at_a_shell(tmp_path):
    write_status(tmp_path, "@1", "working", "UserPromptSubmit", 100.0)
    first = reconcile([win("@1", command="bash")], tmp_path, 500.0)["@1"]
    assert first == Status("exited", 500.0, "reconciled")
    later = reconcile([win("@1", command="bash")], tmp_path, 900.0)["@1"]
    assert later.since == 500.0                       # persisted, age keeps growing


def test_reconcile_defaults_and_skips_shell_tabs(tmp_path):
    result = reconcile([win("@1"), win("@2", kind="shell", command="bash")], tmp_path, 50.0)
    assert result == {"@1": Status("idle", 50.0, "")}


def test_reconcile_deletes_status_of_vanished_windows(tmp_path):
    write_status(tmp_path, "@9", "idle", "x", 1.0)
    reconcile([win("@1")], tmp_path, 2.0)
    assert read_status(tmp_path, "@9") is None


def test_events_sequence_and_since(tmp_path):
    seqs = [append_event(tmp_path, {"n": i}) for i in range(3)]
    assert seqs == [1, 2, 3]
    assert [e["n"] for e in read_events(tmp_path, 1)] == [1, 2]
    assert last_seq(tmp_path) == 3


def test_rotation_keeps_newest_and_sequence(tmp_path):
    for i in range(200):
        append_event(tmp_path, {"pad": "x" * 50, "n": i}, max_bytes=4000)
    assert (tmp_path / "events.log").stat().st_size <= 4000 + 200
    events = read_events(tmp_path, 0)
    assert events[-1]["seq"] == 200 and events[-1]["n"] == 199
    assert events[0]["seq"] > 1
    assert last_seq(tmp_path) == 200


def test_partial_line_is_ignored(tmp_path):
    append_event(tmp_path, {"n": 0})
    with open(tmp_path / "events.log", "a") as f:
        f.write('{"seq": 2, "n"')                       # torn write
    assert [e["seq"] for e in read_events(tmp_path, 0)] == [1]


def _append_many(state, count):
    for _ in range(count):
        append_event(state, {"pid": 1})


def test_concurrent_appends_get_unique_sequence_numbers(tmp_path):
    procs = [multiprocessing.Process(target=_append_many, args=(tmp_path, 25)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    seqs = [json.loads(line)["seq"] for line in (tmp_path / "events.log").read_text().splitlines()]
    assert sorted(seqs) == list(range(1, 101))
