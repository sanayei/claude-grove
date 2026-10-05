from grove_core.render import Row
from grove_core.tui import Model, action_for
from tests.test_render import TREE

WS = Row(0, "ws", "trading", None, "▾ trading", "", "")
TAB = Row(1, "tab", "trading", "@12", "#12 root · x", "● working", "1m")


def test_model_cursor_moves_and_clamps():
    m = Model()
    m.set_tree(TREE)
    m.move(-5)
    assert m.cursor == 0
    m.move(1000)
    assert m.cursor == len(m.rows()) - 1


def test_model_toggle_collapses_selected_workspace():
    m = Model()
    m.set_tree(TREE)
    m.cursor = [r.text for r in m.rows()].index("▾ publications")
    before = len(m.rows())
    m.toggle()
    assert "publications" in m.collapsed and len(m.rows()) < before
    m.toggle()
    assert len(m.rows()) == before


def test_model_keeps_selection_on_refresh():
    m = Model()
    m.set_tree(TREE)
    m.cursor = [r.tab_id for r in m.rows()].index("@21")
    m.set_tree(TREE)
    assert m.selected().tab_id == "@21"


def test_needs_input_count():
    m = Model()
    m.set_tree(TREE)
    assert m.needs_input() == 1


def test_action_for():
    assert action_for("q", TAB) == ("quit",)
    assert action_for("KEY_UP", TAB) == ("move", -1)
    assert action_for("j", TAB) == ("move", 1)
    assert action_for("\n", TAB) == ("open", "trading", "@12")
    assert action_for("\n", WS) == ("open", "trading", None)
    assert action_for(" ", WS) == ("toggle",)
    assert action_for("n", TAB) == ("new", "trading")
    assert action_for("r", TAB) == ("rename", "@12")
    assert action_for("r", WS) == ("none",)
    assert action_for("m", TAB) == ("mark", "trading")
    assert action_for("c", TAB) == ("close", "@12")
    assert action_for("/", None) == ("search",)
    assert action_for("\n", None) == ("none",)
