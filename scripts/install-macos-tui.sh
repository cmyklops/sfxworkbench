#!/usr/bin/env bash
set -euo pipefail

step() {
  printf '\n==> %s\n' "$1"
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

echo "sfxworkbench macOS installer"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is for macOS. Use the Windows PowerShell installer on Windows." >&2
  exit 1
fi

step "Preparing user folder"
cd "$HOME"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if ! has_command git; then
  echo "Git is not available. macOS will now prompt to install Apple Command Line Tools." >&2
  xcode-select --install >/dev/null 2>&1 || true
  echo "After Command Line Tools finishes installing, run this command again." >&2
  exit 1
fi

if ! has_command uv; then
  step "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! has_command uv; then
  echo "uv was installed but is not visible yet. Open a fresh Terminal window and run this command again." >&2
  exit 1
fi

step "Using tools"
git --version
uv --version

repo_dir="$HOME/sfxworkbench"
if [[ -e "$repo_dir" ]]; then
  if [[ ! -d "$repo_dir/.git" ]]; then
    echo "$repo_dir already exists but is not a git checkout. Rename that folder, then run this command again." >&2
    exit 1
  fi
  step "Updating sfxworkbench"
  git -C "$repo_dir" pull --ff-only
else
  step "Cloning sfxworkbench"
  git clone https://github.com/cmyklops/sfxworkbench.git "$repo_dir"
fi

cd "$repo_dir"

printf '\nNext time, run this local launcher to update and start:\n  %s/scripts/run-macos-tui.sh\n' "$repo_dir"

launcher="$repo_dir/scripts/run-macos-tui.sh"
if [[ ! -x "$launcher" ]]; then
  chmod +x "$launcher" 2>/dev/null || true
fi
if [[ ! -x "$launcher" ]]; then
  echo "Expected launcher was not created at $launcher." >&2
  exit 1
fi
"$launcher"
