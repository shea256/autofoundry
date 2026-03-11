#!/usr/bin/env bash
# Clone, install deps, and run autoresearch.
# Works from scratch or with a network volume (skips clone on re-run).
# Usage: autofoundry run scripts/run_autoresearch.sh
set -e

cd /workspace
if [ -d autoresearch ]; then
    cd autoresearch && git pull
else
    git clone https://github.com/karpathy/autoresearch.git && cd autoresearch
fi

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
export UV_LINK_MODE=copy

uv sync
uv run prepare.py
uv run train.py
