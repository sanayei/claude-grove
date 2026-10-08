# claude-grove

`grove` keeps your Claude Code sessions alive in tmux on a remote machine and shows them as one tree, so you can close the laptop, switch Macs, and come back to the same running sessions. Each project folder is a workspace (one tmux session, one iTerm2 window); each Claude session is a tab. Hooks track whether a tab is working, waiting for you, or done, and the Mac pops a notification when it needs you. Stdlib-only Python; no daemon on the remote.

```
 grove — fidelity:~/projects                                   ◆ 1 needs input

 ▾ publications
   #20 p2                                         ○ idle         16m
   ▸ p1
 ▾ trading
   #12 root · refactor-api                        ● working      2h 14m
   #15 src/backtest · speed up                    ◆ needs input  12m
   #16 root · shell

↑↓ move  ⏎ open  space fold  n new  r rename  m mark  c close  / search  q quit
```

## Requirements

- Python 3.11 or newer on both the remote machine and the Mac
- tmux 3.2 or newer on the remote
- ssh with key-based access from the Mac to the remote
- iTerm2 on the Mac (for native tabs)
- Optional: [`terminal-notifier`](https://github.com/julienXX/terminal-notifier) for click-to-open notifications (`brew install terminal-notifier`)

## Install

On the **remote** machine (the one that runs Claude):

```sh
git clone https://github.com/sanayei/claude-grove && cd claude-grove && ./install.sh
```

At the prompts, answer `local` for the machine and give your projects folder (default `~/projects`). Setup installs Claude hooks into `~/.claude/settings.json`. Then check it:

```sh
grove doctor
```

On the **Mac**:

```sh
git clone https://github.com/sanayei/claude-grove && cd claude-grove && ./install.sh
```

Answer the remote's ssh host (an alias from `~/.ssh/config`, or an IP), then the path of grove on the remote if it is not `~/.local/bin/grove`. Setup also installs a login agent for notifications. Then:

```sh
grove doctor
```

`install.sh` links the launcher into `~/.local/bin` (add that to your `PATH` if it says so). If another `grove` command already exists it installs as `cgrove` instead; it never overwrites a file it did not create (if `cgrove` is taken too, it stops and tells you). Re-run `grove setup` any time; blank answers keep the current value.

## Daily use

| Command | What it does |
|---|---|
| `grove` | Interactive screen |
| `grove tree [path] [--all]` | Print the tree with status (`--all` includes workspaces without tabs) |
| `grove open <path>` | Open the nearest workspace of `<path>` in iTerm2 |
| `grove open --tab N` | Open tab `#N` |
| `grove new <path> [label] [--shell] [--rc] [--no-open] [-- <claude args>]` | New tab; starts Claude, or only a shell with `--shell`; `--rc` enables Remote Control |
| `grove rename N <label>` | Change a tab's label |
| `grove mark <path>` / `grove unmark <path>` | Make a folder a workspace / undo |
| `grove close N [--force]` | Close a tab (asks for `--force` if it is working or needs input) |
| `grove watch` | Mac notifier (started at login by setup) |
| `grove setup` / `grove doctor` | Configure / check everything |

Each Claude is started with `--name <folder> · <label>` (e.g. `publications/p3 · draft`), so it is easy to find in Remote Control on claude.ai or the Claude app, and in `/resume`; a `--name` you pass after `--` wins. Renaming a grove tab does not rename the Claude session; use Claude's `/rename` for that.

Paths are relative to the root. On the remote itself, `.` and absolute paths also work. After a remote reboot, tabs are gone; resume with `grove new <folder> -- --resume`.

Keys in the interactive screen:

| Key | Action |
|---|---|
| `↑` `↓` (or `k` `j`) | Move |
| `⏎` (or `→`) | Open the tab or workspace |
| `space` (or `←`) | Fold/unfold a workspace |
| `n` | New tab: pick a folder (`⏎` go in, `.` choose it, `+` create a folder here), then label and claude/shell; the tab opens |
| `r` | Rename the selected tab |
| `m` | Mark a folder as a workspace (folder picker; `+` creates a folder) |
| `c` | Close the selected tab |
| `/` | Filter by text; `esc` clears the filter |
| `q` (or `esc` with no filter) | Quit |

Close the laptop any time. Claude keeps running on the remote; run `grove` again from either Mac and everything is still there.

## Workspaces

Every top-level folder under the root is a workspace automatically, including one you create with `+` in the folder picker at `(root)`. To make any deeper folder a workspace, run `grove mark <folder>` (it creates a `.grove` file; `grove unmark` removes it).

A tab belongs to the **nearest** workspace above its folder, like git finding `.git`. With `publications` as a top-level workspace:

```sh
grove new publications/p1 "intro"     # tab "p1 · intro" in workspace publications
grove mark publications/p1
grove new publications/p1 "intro 2"   # tab "root · intro 2" in workspace publications/p1
```

Existing tabs stay where they are when you mark a folder; only new tabs use the new workspace.

## Status and notifications

| Glyph | Meaning |
|---|---|
| `● working` | Claude is running a prompt |
| `◆ needs input` | Waiting for a permission or an answer |
| `○ idle` | Finished, waiting for your next prompt |
| `✕ exited` | Claude is no longer running in the tab |

Setup adds hooks to `~/.claude/settings.json` on the remote (merged with your own, with a timestamped backup). The hook is `grove hook <event>`; it does nothing outside grove tabs, never blocks Claude, and writes status plus an event log under `~/.local/state/grove`. Remove only grove's entries with:

```sh
grove setup --uninstall-hooks
```

On the Mac, `grove watch` (a launchd agent) follows the event log over ssh and notifies when a tab needs input or finishes. After a disconnect it catches up; events older than 10 minutes are marked "(late)". With `terminal-notifier` installed, clicking a notification opens that tab; without it you get plain notifications. Set `notify = false` in `~/.config/grove/config.toml` to turn notifications off.

## Parallel Claude sessions

Two Claudes in the same folder step on each other's files. grove warns when you start a second one but does not block it. Give each its own checkout instead:

```sh
git worktree add ../myproj-feature-x -b feature-x
grove new myproj-feature-x "feature x"
```

## Uninstall

```sh
grove setup --uninstall-hooks                              # on the remote
launchctl bootout gui/$(id -u)/io.github.claude-grove.watch   # on the Mac
rm ~/Library/LaunchAgents/io.github.claude-grove.watch.plist
rm ~/.local/bin/grove        # or cgrove
rm -r ~/.config/grove ~/.local/state/grove
```

Run the hook removal and the `rm` of config/state on each machine where you installed grove.

## Manual test checklist

These need a real iTerm2 and a real remote, so they are not covered by the automated tests.

- [ ] iTerm2 native tabs: `grove new <folder> "test"` opens an iTerm2 window with one native tab per grove tab.
- [ ] Notifications and click-to-open: when Claude needs input or finishes, a macOS notification appears; with `terminal-notifier`, clicking it opens the tab.
- [ ] Lid closed mid-task: start a long prompt, close the laptop for a couple of minutes, reopen, run `grove`; the tab is alive and any missed notification appears (marked "(late)" if older than 10 minutes).
- [ ] Second Mac: attach to the same workspace from another Mac; both see the same tabs and neither shrinks the other's window.

## Licence

MIT. See [LICENSE](LICENSE).
