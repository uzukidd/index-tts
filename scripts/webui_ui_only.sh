#!/usr/bin/env bash
set -euo pipefail
export NO_PROXY=localhost,127.0.0.1
export no_proxy="$NO_PROXY"
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec conda run --no-capture-output -n indextts python webui.py --ui-only --host 127.0.0.1 --port 7861 "$@"
