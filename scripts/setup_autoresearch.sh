#!/usr/bin/env bash
# Setup script: clone repo and install all dependencies.
# Bake this into a Docker image with: autofoundry build scripts/setup_autoresearch.sh -t youruser/autoresearch:latest
set -e

cd /workspace
git clone https://github.com/karpathy/autoresearch.git
cd autoresearch

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
export UV_LINK_MODE=copy

uv sync
