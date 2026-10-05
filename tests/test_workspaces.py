import pytest

from grove_core.workspaces import (
    PathError, is_workspace, list_workspaces, mark, nearest_workspace,
    resolve_in_root, session_name, unmark,
)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "projects"
    for d in ["trading/src/api", "publications/p1/figures", "publications/p2",
              ".hidden/x", "data/node_modules/pkg", "pub"]:
        (r / d).mkdir(parents=True)
    (r / "publications/p1/.grove").touch()
    (r / "data/node_modules/pkg/.grove").touch()   # inside a skipped dir
    return r


def test_top_level_folders_are_workspaces(root):
    assert is_workspace(root / "trading", root)
    assert not is_workspace(root / "trading/src", root)


def test_marker_makes_a_workspace(root):
    assert is_workspace(root / "publications/p1", root)
    assert not is_workspace(root / "publications/p2", root)


def test_nearest_workspace_walks_up(root):
    assert nearest_workspace(root / "publications/p1/figures", root) == (root / "publications/p1").resolve()
    assert nearest_workspace(root / "publications/p2", root) == (root / "publications").resolve()
    assert nearest_workspace(root / "trading/src/api", root) == (root / "trading").resolve()


def test_nearest_workspace_outside_root_fails(root, tmp_path):
    with pytest.raises(PathError):
        nearest_workspace(tmp_path, root)


def test_list_workspaces_skips_hidden_and_vendor_dirs(root):
    assert list_workspaces(root) == ["data", "pub", "publications", "publications/p1", "trading"]


@pytest.mark.parametrize("bad", ["", ".", "..", "../..", "/etc", "trading/../..", "nope", "trading/src/api/missing"])
def test_resolve_rejects_root_outside_and_missing(root, bad):
    with pytest.raises(PathError):
        resolve_in_root(root, bad)


def test_resolve_accepts_spaces_quotes_and_unicode(root):
    folder = root / "trading" / "it's my notes ö"
    folder.mkdir()
    assert resolve_in_root(root, "trading/it's my notes ö") == folder.resolve()


def test_mark_and_unmark(root):
    assert mark(root, "publications/p2") == "publications/p2"
    assert (root / "publications/p2/.grove").is_file()
    assert unmark(root, "publications/p2") == "publications/p2"
    assert not (root / "publications/p2/.grove").exists()
    with pytest.raises(PathError):
        unmark(root, "publications/p2")          # not marked
    with pytest.raises(PathError):
        mark(root, "trading")                    # already a workspace (top level)


def test_session_name_escapes_tmux_specials():
    assert session_name("a.b:c%d/e") == "grove/a%2Eb%3Ac%25d/e"
    assert session_name("pubs/v1.2") != session_name("pubs/v1_2")
    assert session_name("trading") == "grove/trading"
    assert session_name("publications/p1") == "grove/publications/p1"


def test_list_workspaces_skips_symlinks_out_of_and_inside_root(root, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "deep").mkdir(parents=True)
    (elsewhere / "deep/.grove").touch()
    (root / "ext").symlink_to(elsewhere)
    (root / "alias").symlink_to(root / "trading")
    (root / "trading/link-out").symlink_to(elsewhere)
    assert list_workspaces(root) == ["data", "pub", "publications", "publications/p1", "trading"]
