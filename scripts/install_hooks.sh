#!/bin/sh
# Install the public-content hooks. An existing hook is kept as <name>.local
# and run after the scan. Running this again updates the scan hook in place.

set -eu

root=$(git rev-parse --show-toplevel)
src_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
mkdir -p "$root/.git/hooks"

install_one() {
  name=$1
  dest="$root/.git/hooks/$name"
  src="$src_dir/hooks/$name"
  if [ ! -f "$src" ]; then
    echo "missing hook source: $name" >&2
    exit 1
  fi
  if [ -L "$dest" ]; then
    rm "$dest"
  elif [ -e "$dest" ]; then
    if grep -q "AGENTSCAFFOLD PUBLIC CONTENT HOOK" "$dest"; then
      cp "$src" "$dest"
      chmod +x "$dest"
      return
    fi
    if [ -e "$dest.local" ]; then
      echo "$name and $name.local both exist; leaving them alone" >&2
      exit 1
    fi
    mv "$dest" "$dest.local"
  fi
  cp "$src" "$dest"
  chmod +x "$dest"
}

install_one pre-commit
install_one pre-push
echo "public-content hooks installed"
