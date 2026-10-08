#!/usr/bin/env bash
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
#
# SAJHA local test lab: three SAJHA instances in one SAJHA Net on this machine.
#   deployment/local-lab/lab.sh start|stop|status|kill|reset [instance ...]
# Runs lab.py with the Python you run SAJHA with: $PYTHON, else the checkout's .venv, else python3.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
py="${PYTHON:-}"
if [[ -z "$py" ]]; then
  if [[ -x "$repo/.venv/bin/python" ]]; then py="$repo/.venv/bin/python"; else py="python3"; fi
fi
exec "$py" "$here/lab.py" "$@"
