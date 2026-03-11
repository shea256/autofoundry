#!/usr/bin/env bash
# Full script: clone, install deps, and run (no pre-built image needed).
# Use with: autofoundry run scripts/run_autoresearch_full.sh
set -e

cd /workspace
git clone https://github.com/karpathy/autoresearch.git
cd autoresearch

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
export UV_LINK_MODE=copy

uv sync
uv run prepare.py
uv run train.py
