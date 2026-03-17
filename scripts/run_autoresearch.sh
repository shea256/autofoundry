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

PYTHON_BIN="${AUTORESEARCH_PYTHON:-$(command -v python3 || command -v python3.10)}"
if [ -z "$PYTHON_BIN" ]; then
    echo "No Python interpreter found (python3/python3.10)." >&2
    exit 1
fi

# Install uv (needed for both fast and full paths).
UV="${UV_BIN:-$HOME/.local/bin/uv}"
UV_REQUIRED_VERSION="0.10.10"
UV_FORCE_PINNED_INSTALL=0
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

# Detect pre-built autoresearch image (torch + CUDA pre-installed).
PREBUILT_IMAGE="${AUTOFOUNDRY_IMAGE:-}"
IS_PREBUILT=0
case "$PREBUILT_IMAGE" in
    *autoresearch*) IS_PREBUILT=1 ;;
esac

# Use persistent path for venv so it survives stop/start cycles.
# /workspace persists on RunPod/Vast.ai; fall back to /tmp otherwise.
if [ -d /workspace ]; then
    VENV_DIR="/workspace/.autoresearch_venv"
else
    VENV_DIR="$HOME/.autoresearch_venv"
fi

# Fast resume: if venv exists and torch is importable, skip setup entirely.
if [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -c "import torch" 2>/dev/null; then
    echo "Existing venv found with torch — skipping setup."
    PYTHON_BIN="$VENV_DIR/bin/python"
elif [ "$IS_PREBUILT" = "1" ]; then
    # Pre-built image: inherit system torch via --system-site-packages.
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"
    echo "Pre-built image detected — installing lightweight deps only."
    $PYTHON_BIN -m venv --system-site-packages "$VENV_DIR"
    PYTHON_BIN="$VENV_DIR/bin/python"
    $UV pip install --python "$PYTHON_BIN" --no-deps --no-build-isolation . 2>/dev/null || true
    $PYTHON_BIN - <<'EXTRACT_LIGHT' > /tmp/af_requirements.txt
import re
skip = re.compile(r"^(torch|nvidia|triton)", re.IGNORECASE)
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
    if s and not skip.match(s):
        print(s)
EXTRACT_LIGHT
    $UV pip install --python "$PYTHON_BIN" -r /tmp/af_requirements.txt
    rm -f /tmp/af_requirements.txt
else
    # Fresh install: isolated venv with all deps including torch.
    # Retry loop: cloud provider filesystems (RunPod /workspace, etc.) can
    # return "Stale file handle" (os error 116) on transient storage hiccups.
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"
    MAX_ATTEMPTS=3
    for attempt in $(seq 1 $MAX_ATTEMPTS); do
        echo "Installing all dependencies (including torch)... (attempt $attempt/$MAX_ATTEMPTS)"
        $UV venv --python "$PYTHON_BIN" "$VENV_DIR"
        PYTHON_BIN="$VENV_DIR/bin/python"
        $UV pip install --python "$PYTHON_BIN" --no-deps --no-build-isolation . 2>/dev/null || true
        $PYTHON_BIN - <<'EXTRACT_DEPS' > /tmp/af_requirements.txt
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
        if $UV pip install --python "$PYTHON_BIN" -r /tmp/af_requirements.txt; then
            rm -f /tmp/af_requirements.txt
            break
        fi
        rm -f /tmp/af_requirements.txt
        echo "Install failed (attempt $attempt/$MAX_ATTEMPTS)."
        if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
            echo "Cleaning up venv and retrying in 5s..."
            rm -rf "$VENV_DIR"
            PYTHON_BIN="${AUTORESEARCH_PYTHON:-$(command -v python3 || command -v python3.10)}"
            sleep 5
        else
            echo "All $MAX_ATTEMPTS attempts failed." >&2
            exit 1
        fi
    done
fi

$PYTHON_BIN prepare.py
$PYTHON_BIN train.py
