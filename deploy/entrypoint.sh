#!/bin/sh
set -e

LUARC="$HOME/.config/darktable/luarc"
MARKER='require "photonforge/main"'

if [ ! -f "$LUARC" ] || ! grep -qF "$MARKER" "$LUARC"; then
    echo "$MARKER" >> "$LUARC"
fi

exec "$@"
