#!/bin/bash
uv pip install -e .
source .venv/bin/activate
autofoundry run scripts/run_autoresearch.sh -g H100 --provider runpod --region US --auto
