#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m openwiki.runner \
  --dataset demo_wiki \
  --docs-root examples/demo_wiki_docs \
  --provider filesystem

