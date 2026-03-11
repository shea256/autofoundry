#!/usr/bin/env bash
set -e

cd /workspace
git clone https://github.com/karpathy/autoresearch.git
cd autoresearch

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv sync
uv run prepare.py
uv run train.py
