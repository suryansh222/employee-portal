#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Install Python 3.10 or newer, then run this script again.' >&2
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10 or newer is required"'
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import importlib.metadata as m; assert m.version("fastapi")=="0.128.2"; assert m.version("uvicorn")=="0.48.0"; assert m.version("python-multipart")=="0.0.29"' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python server.py "$@"
