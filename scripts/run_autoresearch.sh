#!/usr/bin/env bash
# Run script: execute the experiment (assumes deps are already installed).
# Use with a pre-built image: autofoundry run scripts/run_autoresearch.sh --image youruser/autoresearch:latest
# Or standalone (installs everything from scratch):
#   autofoundry run scripts/run_autoresearch_full.sh
set -e

cd /workspace/autoresearch
export PATH="$HOME/.local/bin:$PATH"

uv run prepare.py
uv run train.py
