#!/bin/bash
set -e
cd "$(dirname "$0")/.."
uv venv
source .venv/bin/activate
uv pip install -e .
autofoundry run scripts/run_autoresearch.sh -g H100 --provider lambdalabs --region US --auto
