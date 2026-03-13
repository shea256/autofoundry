#!/usr/bin/env bash
# Build autofoundry and run autoresearch on PRIME Intellect.
set -e

uv venv
source .venv/bin/activate
uv pip install -e .
autofoundry run scripts/run_autoresearch.sh -g H100 --provider primeintellect --region US --auto
