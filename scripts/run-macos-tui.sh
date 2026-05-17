#!/usr/bin/env bash
set -euo pipefail

step() {
  printf '\n==> %s\n' "$1"
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
cd "$repo_dir"

if [[ ! -d "$repo_dir/.git" ]]; then
  echo "$repo_dir is not a git checkout. Run the one-line installer again." >&2
  exit 1
fi
if ! has_command git; then
  echo "Git is not available. Run the one-line installer again." >&2
  exit 1
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! has_command uv; then
  echo "uv is not available. Run the one-line installer again, then reopen Terminal if asked." >&2
  exit 1
fi

step "Checking GitHub for sfxworkbench updates"
git -C "$repo_dir" fetch --prune origin main
branch="$(git -C "$repo_dir" rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "main" ]]; then
  git -C "$repo_dir" pull --ff-only origin main
else
  git -C "$repo_dir" pull --ff-only
fi

step "Syncing Python 3.11 and dependencies"
uv python install 3.11
uv sync --python 3.11 --extra dev --extra metadata --extra tui

mkdir -p reports
export PYTHONUTF8=1

sfx="$repo_dir/.venv/bin/sfx"
if [[ ! -x "$sfx" ]]; then
  echo "Expected launcher was not created at $sfx." >&2
  exit 1
fi

step "Launching sfxworkbench"
"$sfx" tui --db ./mac_test.db --report ./reports
