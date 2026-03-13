#!/usr/bin/env bash
# Clone, install deps, and run autoresearch.
# Works from scratch or with a network volume (skips clone on re-run).
# Usage: autofoundry run scripts/run_autoresearch.sh
set -e

# Ensure ~/.config is writable (PI's Ubuntu image has broken perms)
mkdir -p "$HOME/.config" 2>/dev/null
if ! touch "$HOME/.config/.writetest" 2>/dev/null; then
    export XDG_CONFIG_HOME=/tmp/xdg_config
    mkdir -p "$XDG_CONFIG_HOME"
else
    rm -f "$HOME/.config/.writetest"
fi

# Ensure python3-dev is installed (needed for Triton/torch.compile on bare images)
# Always install — idempotent, fast if already present, avoids false-positive checks
echo "Ensuring python3-dev is installed..."
apt-get update -qq 2>/dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-dev 2>/dev/null || true

# Use /workspace if it exists (RunPod, Vast.ai), otherwise fall back to home dir
if [ -d /workspace ]; then
    cd /workspace
else
    cd ~
fi
if [ -d autoresearch ]; then
    cd autoresearch && git pull
else
    git clone https://github.com/karpathy/autoresearch.git && cd autoresearch
fi

curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh
export PATH="$HOME/.local/bin:$PATH"
export UV_LINK_MODE=copy

uv sync
uv run prepare.py
uv run train.py
