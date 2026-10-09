#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$repo_dir/tools/install.py" "$@"
fi
if command -v nix >/dev/null 2>&1; then
    exec nix shell nixpkgs#python3 --command python3 "$repo_dir/tools/install.py" "$@"
fi
echo 'Нужен Python 3. На Arch: sudo pacman -S python' >&2
exit 1
