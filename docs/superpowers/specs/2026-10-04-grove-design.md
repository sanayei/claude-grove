# claude-grove — design

Date: 2026-10-04
Status: approved in conversation, pending written-spec review

## 1. Purpose

Long-running Claude Code sessions on a remote Linux machine die when the
laptop that started them sleeps or loses its SSH connection. `grove` keeps
every Claude session alive in tmux on the remote machine, organises the
sessions as a tree that mirrors the folder hierarchy, shows each session's
status, and notifies the Mac when a session needs input or finishes.

It is meant to be shared publicly (GitHub), so nothing is specific to one
person's host, user name or folder layout.

### Success criteria

- Closing the laptop or dropping SSH never stops a running Claude task.
- The user never needs to remember a session name: one command (or the
  interactive screen) shows everything that is running, where, and its state,
  and reopens any of it in one step, from any of the user's Macs.
- The user decides which folders are tree nodes ("workspaces"), at any depth.
- A macOS notification appears when a Claude tab needs input or finishes.
- grove failing or being absent never affects Claude or tmux.

### Out of scope (v1)

- macOS menu-bar icon (planned v1.1, SwiftBar plugin reusing the watch data).
- Phone notifications (the user relies on Claude Code Remote Control instead;
  grove only offers a flag to start Claude with Remote Control on).
- Moving tabs between workspaces.
- Windows support.
- More than one remote host per client config.
- Web dashboard or native Mac app.

## 2. Concepts

- **Root**: the folder under which everything lives (e.g. `~/projects`).
  All user-facing paths are relative to it.
- **Workspace**: a folder that is a node in the tree. A folder is a
  workspace if it contains a `.grove` marker file, or if it is a direct child
  of the root (implicit workspace). One workspace = one tmux session = one
  iTerm2 window.
- **Tab**: a tmux window inside a workspace's session = one iTerm2 tab. Runs
  a shell, in which Claude (or nothing, for `--shell`) is started. A tab has:
  - a **folder** (the directory it runs in, at or below its workspace),
  - an optional, editable **label**,
  - a **number** (`#N`), which is tmux's own window id (`@N`), stable for the
    tab's lifetime,
  - a **status** (see §5).
- **Nearest workspace**: for any folder, walk upward to the first workspace
  (like git finding `.git`). Tabs created in a folder go to its nearest
  workspace.
- **Tab name** shown everywhere: `<folder relative to workspace> · <label>`,
  where the folder of the workspace itself is shown as `root`. Without a
  label, a numeric suffix disambiguates duplicates (`src/api`, `src/api-2`).

## 3. Commands

Paths are relative to the root, with shell completion.

| Command | Behaviour |
|---|---|
| `grove` | Opens the interactive screen (TUI, §7). |
| `grove tree [path]` | Prints the tree (whole or a subtree) with status. |
| `grove open <path>` | Attaches iTerm2 to the nearest workspace of `<path>`, creating the session if needed. |
| `grove new <path> [label] [--shell] [--rc] [-- <claude args>]` | Creates a tab in `<path>` inside its nearest workspace, starts Claude (or only a shell with `--shell`; with Remote Control if `--rc`; extra args passed to `claude`), then opens it. Warns (does not block) when another Claude tab already runs in the same folder. |
| `grove rename <N> <label>` | Sets/edits a tab's label; iTerm2 tab title follows. |
| `grove mark <path>` / `grove unmark <path>` | Creates/removes the `.grove` marker. |
| `grove close <N>` | Closes a tab; asks for confirmation if its status is working or needs-input. |
| `grove watch` | Mac notifier (normally run by a login agent). |
| `grove setup` | Interactive first-time configuration and hook/agent installation. |
| `grove doctor` | Checks every prerequisite and component; prints exact fixes. |

When run on the remote machine itself, the same commands work locally;
Mac-only parts (iTerm2 attach, notifications) are skipped or fall back to a
plain `tmux attach`.

## 4. Architecture

Stdlib-only Python package plus a launcher script. Same code on both ends;
the role is decided by config (`host` empty ⇒ local mode).

```
 Mac                                        Remote
 grove (TUI / commands) ──ssh──────────▶   grove --remote <cmd> --json
 iTerm2 ◀── ssh -t … tmux -CC attach ──▶   tmux server ─ claude in each tab
 grove watch (launchd) ◀──ssh──────────    ~/.local/state/grove/{status/,events.log}
                                               ▲ written by Claude hooks
```

### Modules (`grove_core/`)

| Module | Responsibility | Depends on |
|---|---|---|
| `config` | Load/save `~/.config/grove/config.toml` (`host`, `root`, `notify`, `ssh_opts`). Read with `tomllib`, write with a tiny serializer. | — |
| `workspaces` | Marker discovery, nearest-workspace resolution, scanning the root for workspaces, path↔session-name encoding (tmux forbids `.` and `:`; reversible encoding). | config |
| `tmux` | Thin wrapper over the `tmux` CLI: create session (`-c dir`), new window, set/get window user options (`@grove_dir`, `@grove_label`, `@grove_kind`), list windows (`list-windows -a -F`), kill, current pane command. Sets `window-size latest` on grove sessions. | — |
| `status` | Read/write per-tab status files atomically; append to and rotate `events.log`; reconcile stored status with reality (see §5). | tmux |
| `hooks` | `grove hook <event>` entry point invoked by Claude Code; installing/uninstalling hook entries into `~/.claude/settings.json` by merge, with a timestamped backup. | status, tmux |
| `client` | Runs commands on the remote over ssh with a persistent ControlMaster connection; JSON in/out; 5 s connect timeout; builds the iTerm2 attach command. | config |
| `render` | Pure functions: tree model → text (for `tree` and the TUI). | — |
| `watch` | Follows the remote event log over ssh from a saved cursor, reconnects with backoff, posts macOS notifications. | client |
| `tui` | `curses` interactive screen using the same command functions. | client, render |
| `cli` | Argument parsing and dispatch. | all |

The tree for display is built on the remote in one call (`grove --remote
tree --json`) and rendered on the Mac.

## 5. Status tracking

Claude Code hooks installed in the remote user's `~/.claude/settings.json`:

| Claude hook | grove status |
|---|---|
| `UserPromptSubmit` | `working` |
| `Notification` (permission / idle prompt) | `needs-input` |
| `Stop` | `idle` (event: `finished`) |
| `SessionStart` | `idle` |
| `SessionEnd` | `exited` |

Hook command: `grove hook <event>`. It:

1. Exits immediately (0) unless `$TMUX_PANE` is set and the pane's window has
   `@grove_kind` set (i.e. it is a grove tab). Claude used elsewhere is untouched.
2. Writes `~/.local/state/grove/status/<window_id>.json`
   (`{status, since, event}`) via write-to-temp + rename.
3. Appends one JSON line to `events.log`
   (`{seq, ts, window_id, workspace, tab_name, status}`), rotating at ~1 MB
   (keep the newest half, `seq` keeps increasing).
4. Never blocks: total timeout 1 s; any error is written to
   `~/.local/state/grove/grove.log` and the hook still exits 0.

**Reconciliation on every read**: if a tab's pane is not currently running
`claude`, its status is shown as `exited` regardless of the file; status
files for windows that no longer exist are deleted.

Status shown in the tree: `● working`, `◆ needs input`, `○ idle`,
`✕ exited`, with elapsed time since the last change.

## 6. Notifications (Mac only)

- `grove watch` runs as a launchd user agent (`KeepAlive`), installed by
  `grove setup` on the Mac.
- It runs `ssh <host> grove --remote events --follow --since <seq>`,
  persisting the last seen `seq` in `~/.local/state/grove/watch.cursor`.
- On disconnect it retries with backoff (1 s → 60 s). On reconnect it
  replays missed events; events older than 10 minutes are shown as "(late)".
- Notifies on `needs-input` and `finished`.
- With `terminal-notifier` installed, clicking a notification runs
  `grove open --tab <N>`; otherwise it uses `osascript display notification`
  (no click action).
- `notify = false` in config disables it.

**Invariant**: the remote never waits on the Mac. The Mac only reads.

## 7. Interactive screen (TUI)

`grove` with no arguments opens a `curses` screen:

```
 grove — fidelity:~/projects                    ◆ 1 needs input
 ───────────────────────────────────────────────────────────────
 ▾ trading                                [workspace]
     #12 root · refactor-api             ● working      2h 14m
   ▸ #15 src/backtest · speed up         ◆ needs input  12m
 ▸ publications                           [workspace]
 ───────────────────────────────────────────────────────────────
 ↑↓ move  ⏎ open  n new  r rename  m mark  c close  / search  q quit
```

- `⏎` on a tab: open that tab; on a workspace: open the workspace.
- `n`: pick a folder from a browsable folder list (starting at the selected
  workspace), optional label, Claude or shell.
- `r`, `m`, `c`: same as the commands, with inline prompts/confirmation.
- `/`: filter by text.
- Refreshes every 2 s. Shows an "offline — retrying" banner when the remote
  is unreachable.

## 8. Opening in iTerm2

`grove open` / `new` on the Mac run:

```
ssh -t <host> 'tmux select-window -t <target> 2>/dev/null; tmux -CC new -A -s <session> -c <dir>'
```

iTerm2's tmux integration turns the session into a native window with one
tab per tmux window. Without iTerm2 (or on the remote itself) it falls back to
a plain `tmux new -A -s …`.

## 9. Error handling

| Situation | Behaviour |
|---|---|
| Remote unreachable | Commands fail within ~5 s with a clear message; nothing half-done remotely. TUI shows an offline banner and retries. |
| Laptop sleeps / SSH drops | Remote unaffected. Watch reconnects and replays from cursor. |
| Claude exits or crashes | Tab stays open (Claude runs inside a shell) with output visible; status `exited`. |
| Missed hook / stale status | Reconciled against the pane's actual command on every read. |
| Remote reboots | Tabs are lost (unavoidable). Stale status cleaned. Resume with `grove new <folder> -- --resume`. |
| Two Macs attached | Both see the same tabs; `window-size latest` avoids the smaller screen shrinking the other. |
| Second Claude in the same folder | One-line warning recommending git worktrees; not blocked. |
| Marking a folder whose tabs live in a parent workspace | Existing tabs stay; new tabs go to the new workspace. |
| Workspace folder renamed/moved | Tree shows `(folder missing)`; tabs keep running. |
| Hook failure | 1 s timeout, exit 0, error only in grove's log. |
| `events.log` growth | Rotated at ~1 MB. |
| Existing `~/.claude/settings.json` | Merged, never overwritten; timestamped backup; `grove setup --uninstall-hooks` removes only grove's entries. |

## 10. Install and configuration

```
git clone https://github.com/<owner>/claude-grove && cd claude-grove && ./install.sh
```

- `install.sh` symlinks the launcher into `~/.local/bin` as `grove`, or
  `cgrove` if another `grove` is on `PATH`.
- Then runs `grove setup`:
  - asks for the remote host (blank = this machine is the remote) and root;
  - on the remote: installs Claude hooks, ensures `~/.local/bin` is on `PATH`
    for non-interactive ssh (needed for `claude` and `grove` over ssh),
    creates the state directory;
  - on the Mac: installs the launchd watch agent, checks iTerm2 and
    `terminal-notifier`, sets up the ssh ControlMaster options in grove's own
    ssh invocation (does not edit `~/.ssh/config`).
- Requirements: Python ≥ 3.11 on both ends, tmux ≥ 3.2 on the remote, ssh with
  key-based access to the remote, iTerm2 on the Mac for native tabs.
  Optional: `terminal-notifier`.

## 11. Testing

- **Unit (pytest, no tmux needed)**: workspace resolution and marker rules,
  session-name encoding round-trip, tab naming/disambiguation, status
  reconciliation, event log append/rotation/replay from cursor, settings.json
  merge/unmerge, tree rendering.
- **Integration (real tmux on an isolated socket via `tmux -L grove-test`)**:
  create workspace sessions and tabs, labels and rename, close, hook
  invocations with simulated Claude events, end-to-end `tree --json`.
- **Manual checklist**: iTerm2 native tabs via `-CC`, macOS notifications and
  click-to-open, closing the lid mid-task and reconnecting, second Mac
  attaching to the same session.

## 12. Repository layout

```
claude-grove/
├─ grove                 launcher
├─ grove_core/           config, workspaces, tmux, status, hooks, client,
│                        render, watch, tui, cli
├─ tests/
├─ install.sh
├─ README.md
├─ LICENSE               (MIT)
└─ docs/superpowers/specs/2026-10-04-grove-design.md
```

Development happens on the remote (`~/projects/claude-grove`); the repository
is published as a public GitHub repo named `claude-grove`.
