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

# Ensure python3-dev is installed (needed for Triton/torch.compile on bare images).
# Skip apt traffic when it is already present.
if dpkg -s python3-dev >/dev/null 2>&1; then
    echo "python3-dev already installed; skipping apt step."
else
    echo "Installing python3-dev..."
    apt-get update -qq 2>/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-dev 2>/dev/null || true
fi

# Use /workspace if it exists (RunPod, Vast.ai), otherwise fall back to home dir
if [ -d /workspace ]; then
    cd /workspace
else
    cd ~
fi
if [ -d autoresearch ]; then
    cd autoresearch
    if [ "${AUTORESEARCH_UPDATE_REPO:-0}" = "1" ]; then
        if [ -d .git ]; then
            echo "Updating existing autoresearch checkout..."
            git pull --ff-only
        else
            echo "Skipping git pull (autoresearch exists but is not a git repository)."
        fi
    else
        echo "Skipping git pull (set AUTORESEARCH_UPDATE_REPO=1 to refresh)."
    fi
else
    git clone https://github.com/karpathy/autoresearch.git && cd autoresearch
fi

UV="${UV_BIN:-$HOME/.local/bin/uv}"
UV_REQUIRED_VERSION="0.10.10"
UV_FORCE_PINNED_INSTALL=0
PYTHON_BIN="${AUTORESEARCH_PYTHON:-$(command -v python3.10 || command -v python3)}"
if [ -z "$PYTHON_BIN" ]; then
    echo "No Python interpreter found (python3.10/python3)." >&2
    exit 1
fi
if [ -x "$UV" ]; then
    UV_CURRENT_VERSION="$($UV --version | awk '{print $2}')"
    if [ "$UV_CURRENT_VERSION" != "$UV_REQUIRED_VERSION" ]; then
        echo "Warning: uv ${UV_CURRENT_VERSION} found, but script is pinned to ${UV_REQUIRED_VERSION}."
        echo "         Continuing with existing uv."
    fi
fi
if [ ! -x "$UV" ] || [ "$UV_FORCE_PINNED_INSTALL" = "1" ]; then
    if [ "$UV_FORCE_PINNED_INSTALL" = "1" ] && [ -x "$UV" ]; then
        echo "UV_FORCE_PINNED_INSTALL is set; reinstalling pinned uv ${UV_REQUIRED_VERSION}."
        UV_ARCH="$(uname -m)"
        if [ "$UV_ARCH" = "aarch64" ]; then
            UV_ARCH="aarch64-unknown-linux-gnu"
        else
            UV_ARCH="x86_64-unknown-linux-gnu"
        fi
        UV_DOWNLOAD_URL="https://releases.astral.sh/github/uv/releases/download/${UV_REQUIRED_VERSION}/uv-${UV_ARCH}.tar.gz"
    fi
    curl -fsSL https://astral.sh/uv/install.sh | UV_DOWNLOAD_URL="$UV_DOWNLOAD_URL" INSTALLER_NO_MODIFY_PATH=1 sh
fi
export UV_LINK_MODE=copy

# Install project deps into system Python. We use --no-build-isolation and
# --no-build to skip building the project itself (autoresearch isn't a proper
# installable package — it's just loose scripts). Torch is already pre-installed
# on the provider image, so uv's resolver skips it.
$UV pip install --system --python "$PYTHON_BIN" --no-deps --no-build-isolation . 2>/dev/null || true
# Now install the actual dependencies from pyproject.toml using uv's
# requirements extraction.
$PYTHON_BIN - <<'EXTRACT_DEPS' > /tmp/af_requirements.txt
import re
in_deps = False
for line in open("pyproject.toml"):
    s = line.strip()
    if not in_deps:
        if s.startswith("dependencies") and s.endswith("["):
            in_deps = True
        continue
    if s.startswith("]"):
        break
    s = s.strip().rstrip(",").strip().strip('"').strip("'")
    if s:
        print(s)
EXTRACT_DEPS
$UV pip install --system --python "$PYTHON_BIN" -r /tmp/af_requirements.txt
rm -f /tmp/af_requirements.txt

$PYTHON_BIN prepare.py
$PYTHON_BIN train.py
