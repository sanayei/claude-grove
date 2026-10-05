#!/bin/sh
# Install grove: link the launcher into ~/.local/bin, then run first-time setup.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
bin="$HOME/.local/bin"
mkdir -p "$bin"
chmod +x "$here/grove"

name=grove
existing=$(command -v grove 2>/dev/null || true)
if [ -n "$existing" ]; then
    target=$(readlink "$existing" 2>/dev/null || true)
    if [ "$target" != "$here/grove" ]; then
        name=cgrove
        echo "Another 'grove' command exists at $existing; installing this one as 'cgrove'."
    fi
fi
if [ -L "$bin/cgrove" ] && [ "$(readlink "$bin/cgrove")" = "$here/grove" ]; then
    name=cgrove
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
