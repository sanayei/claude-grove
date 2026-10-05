#!/bin/sh
# Install grove: link the launcher into ~/.local/bin, then run first-time setup.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
bin="$HOME/.local/bin"
mkdir -p "$bin"
chmod +x "$here/grove"

# true when $1 is our own symlink to this checkout's launcher
ours() {
    [ -L "$1" ] && [ "$(readlink "$1")" = "$here/grove" ]
}
# true when $1 exists (even as a dangling symlink) and is not ours
foreign() {
    { [ -e "$1" ] || [ -L "$1" ]; } && ! ours "$1"
}

name=grove
existing=$(command -v grove 2>/dev/null || true)
if [ -n "$existing" ] && ! ours "$existing"; then
    name=cgrove
    echo "Another 'grove' command exists at $existing; installing this one as 'cgrove'."
elif foreign "$bin/grove"; then
    name=cgrove
    echo "$bin/grove already exists and is not grove; installing this one as 'cgrove'."
fi
if ours "$bin/cgrove"; then
    name=cgrove
fi
if [ "$name" = cgrove ] && foreign "$bin/cgrove"; then
    echo "install.sh: $bin/cgrove already exists and is not grove; not overwriting it." >&2
    echo "Move it (or $bin/grove) out of the way and run ./install.sh again." >&2
    exit 1
fi

ln -sf "$here/grove" "$bin/$name"
echo "Installed $bin/$name"

case ":$PATH:" in
    *":$bin:"*) ;;
    *) echo "Note: add $bin to your PATH." ;;
esac

if [ "${GROVE_SKIP_SETUP:-0}" != "1" ]; then
    "$bin/$name" setup
fi
