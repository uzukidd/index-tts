#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "${1:-}" == "--browser" ]]; then
  export INDEXTTS_UI_TESTS=1
  shift
fi
exec conda run --no-capture-output -n indextts python -m pytest -q tests/test_webui_syntax.py tests/test_webui_handlers.py tests/test_webui_batch.py tests/test_webui_batch_ui.py "$@"
