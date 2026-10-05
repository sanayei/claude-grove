"""Pure rendering of the tree dict returned by Grove.tree()."""
from __future__ import annotations

from dataclasses import dataclass

GLYPHS = {
    "working": "● working",
    "needs-input": "◆ needs input",
    "idle": "○ idle",
    "exited": "✕ exited",
}
NAME_WIDTH = 48
STATUS_WIDTH = 14


def fmt_age(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def tab_name(dir_rel: str, label: str) -> str:
    base = dir_rel or "root"
    return f"{base} · {label}" if label else base


def tab_names(tabs: list[dict]) -> dict[str, str]:
    seen: dict[str, int] = {}
    names: dict[str, str] = {}
    for t in sorted(tabs, key=lambda t: t["num"]):
        if t["label"]:
            names[t["id"]] = tab_name(t["dir"], t["label"])
            continue
        base = t["dir"] or "root"
        seen[base] = seen.get(base, 0) + 1
        names[t["id"]] = base if seen[base] == 1 else f"{base}-{seen[base]}"
    return names


def _nest(workspaces: list[dict]) -> list[dict]:
    """Group workspaces into a forest by folder nesting."""
    paths = sorted(w["path"] for w in workspaces)
    nodes = {w["path"]: {"ws": w, "parent": None, "children": []} for w in workspaces}
    roots = []
    for path in paths:
        parent = None
        for other in paths:
            if path.startswith(other + "/") and (parent is None or len(other) > len(parent)):
                parent = other
        nodes[path]["parent"] = parent
        (nodes[parent]["children"] if parent else roots).append(nodes[path])
    return roots


def _ws_name(node: dict) -> str:
    path = node["ws"]["path"]
    name = path[len(node["parent"]) + 1:] if node["parent"] else path
    return name + ("  (folder missing)" if node["ws"]["missing"] else "")


def _status(tab: dict, now: float) -> tuple[str, str]:
    if tab["kind"] != "claude":
        return "", ""
    return GLYPHS.get(tab["status"], tab["status"]), fmt_age(now - tab["since"])


def _has_tabs(node: dict) -> bool:
    return bool(node["ws"]["tabs"]) or any(_has_tabs(c) for c in node["children"])


def render_text(tree: dict, show_empty: bool = False) -> str:
    now = tree["now"]
    lines = [f"{tree['host'] or 'local'}:{tree['root']}"]

    def keep(nodes):
        return [n for n in nodes if show_empty or _has_tabs(n)]

    def walk(items: list[tuple[str, dict]], prefix: str, names: dict[str, str]) -> None:
        for i, (kind, item) in enumerate(items):
            last = i == len(items) - 1
            branch = "└─ " if last else "├─ "
            if kind == "tab":
                status, age = _status(item, now)
                left = f"{prefix}{branch}#{item['num']} {names[item['id']]}"
                lines.append(f"{left:<{NAME_WIDTH}} {status:<{STATUS_WIDTH}} {age}".rstrip())
            else:
                lines.append(prefix + branch + _ws_name(item))
                tabs = sorted(item["ws"]["tabs"], key=lambda t: t["num"])
                kids = [("tab", t) for t in tabs] + [("ws", c) for c in keep(item["children"])]
                walk(kids, prefix + ("   " if last else "│  "), tab_names(item["ws"]["tabs"]))

    walk([("ws", n) for n in keep(_nest(tree["workspaces"]))], "", {})
    return "\n".join(lines)


@dataclass(frozen=True)
class Row:
    depth: int
    kind: str              # "ws" or "tab"
    ws_path: str
    tab_id: str | None
    text: str
    status: str
    age: str


def build_rows(tree: dict, collapsed: set[str] = frozenset(), query: str = "") -> list[Row]:
    now, q = tree["now"], query.lower()
    rows: list[Row] = []

    def matches(node: dict) -> bool:
        if not q or q in node["ws"]["path"].lower():
            return True
        names = tab_names(node["ws"]["tabs"]).values()
        return any(q in n.lower() for n in names) or any(matches(c) for c in node["children"])

    def walk(nodes: list[dict], depth: int) -> None:
        for node in nodes:
            if not matches(node):
                continue
            ws = node["ws"]
            expanded = bool(q) or ws["path"] not in collapsed
            rows.append(Row(depth, "ws", ws["path"], None,
                            ("▾ " if expanded else "▸ ") + _ws_name(node), "", ""))
            if not expanded:
                continue
            names = tab_names(ws["tabs"])
            path_hit = q in ws["path"].lower()
            for t in sorted(ws["tabs"], key=lambda t: t["num"]):
                name = names[t["id"]]
                if q and not path_hit and q not in name.lower():
                    continue
                status, age = _status(t, now)
                rows.append(Row(depth + 1, "tab", ws["path"], t["id"], f"#{t['num']} {name}", status, age))
            walk(node["children"], depth + 1)

    walk(_nest(tree["workspaces"]), 0)
    return rows
