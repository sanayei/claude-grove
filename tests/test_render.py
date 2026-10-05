from grove_core.render import build_rows, fmt_age, render_text, tab_name, tab_names

NOW = 10_000.0


def tab(num, dir="", label="", kind="claude", status="idle", age=0):
    return {"id": f"@{num}", "num": num, "dir": dir, "label": label,
            "kind": kind, "status": status, "since": NOW - age}


def ws(path, tabs=(), missing=False):
    return {"path": path, "session": path, "missing": missing, "tabs": list(tabs)}


TREE = {"root": "/home/u/projects", "host": "fidelity", "now": NOW, "workspaces": [
    ws("data"),
    ws("pub", [tab(30, label="x")]),
    ws("publications", [tab(20, label="readme")]),
    ws("publications/p1", [tab(21, "figures", "regen", status="needs-input", age=720)]),
    ws("trading", [tab(11, kind="shell", label="shell"),
                   tab(12, label="refactor-api", status="working", age=8040),
                   tab(15, "src/backtest", status="exited")]),
]}


def test_fmt_age():
    assert [fmt_age(s) for s in (-5, 45, 720, 8040, 90_000)] == ["0s", "45s", "12m", "2h 14m", "1d 1h"]


def test_tab_name():
    assert tab_name("", "") == "root"
    assert tab_name("src/api", "fix auth") == "src/api · fix auth"


def test_tab_names_disambiguates_unlabelled_duplicates():
    tabs = [tab(1, "src"), tab(2, "src"), tab(3, "src", "x"), tab(4)]
    assert tab_names(tabs) == {"@1": "src", "@2": "src-2", "@3": "src · x", "@4": "root"}


def test_render_text_structure():
    lines = render_text(TREE).splitlines()
    assert lines[0] == "fidelity:/home/u/projects"
    assert not any("data" in line for line in lines)            # empty workspace hidden
    assert lines[1] == "├─ pub"
    assert lines[3] == "├─ publications"
    assert lines[4].startswith("│  ├─ #20 root · readme") and "○ idle" in lines[4]
    assert lines[5] == "│  └─ p1"                                 # nested under publications, not under pub
    assert lines[6].startswith("│     └─ #21 figures · regen")
    assert "◆ needs input" in lines[6] and lines[6].endswith("12m")
    assert lines[7] == "└─ trading"
    assert lines[8].rstrip() == "   ├─ #11 root · shell"            # shell tabs have no status
    assert "● working" in lines[9] and lines[9].endswith("2h 14m")
    assert lines[10].startswith("   └─ #15 src/backtest") and "✕ exited" in lines[10]


def test_render_text_show_empty_and_missing():
    tree = dict(TREE, workspaces=TREE["workspaces"] + [ws("gone", [tab(40)], missing=True)])
    text = render_text(tree, show_empty=True)
    assert "├─ data" in text
    assert "gone  (folder missing)" in text


def test_build_rows_order_and_depth():
    rows = build_rows(TREE)
    assert [(r.depth, r.kind, r.text) for r in rows][:6] == [
        (0, "ws", "▾ data"),
        (0, "ws", "▾ pub"),
        (1, "tab", "#30 root · x"),
        (0, "ws", "▾ publications"),
        (1, "tab", "#20 root · readme"),
        (1, "ws", "▾ p1"),
    ]
    needs = [r for r in rows if r.tab_id == "@21"][0]
    assert (needs.status, needs.age, needs.ws_path) == ("◆ needs input", "12m", "publications/p1")


def test_build_rows_collapsed_hides_tabs_and_children():
    rows = build_rows(TREE, collapsed={"publications"})
    texts = [r.text for r in rows]
    assert "▸ publications" in texts
    assert "#20 root · readme" not in texts and "▾ p1" not in texts


def test_build_rows_query_filters_but_keeps_ancestors():
    rows = build_rows(TREE, query="REGEN")
    assert [r.text for r in rows] == ["▾ publications", "▾ p1", "#21 figures · regen"]
