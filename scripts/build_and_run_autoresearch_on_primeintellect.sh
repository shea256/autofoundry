#!/usr/bin/env bash
# Build autofoundry and run autoresearch on PRIME Intellect.
set -e

uv pip install -e .
source .venv/bin/activate
autofoundry run scripts/run_autoresearch.sh -g H100 --provider primeintellect --region US --auto
