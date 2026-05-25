# OpenWiki

OpenWiki is an open-source benchmark starter kit for enterprise knowledge bases.

It was extracted from a private knowledge-system project, but this repository only
keeps the parts that are safe to publish:

- a pure-Python BM25 retriever
- a generic benchmark runner
- a filesystem provider for Markdown knowledge bases
- a public demo dataset
- a report writer for side-by-side retrieval and answer scoring

It intentionally does **not** include:

- private personal datasets
- internal chat-doc or personal note exports
- local absolute paths
- historical benchmark runs with real business evidence

## What It Is Good For

- evaluating an internal wiki or handbook before production rollout
- comparing retrieval strategies on a stable question set
- bootstrapping a team-specific benchmark dataset
- validating whether a knowledge base can answer factual and policy questions

## Quick Start

### 1. Run the built-in demo

```bash
cd openwiki
python3 -m openwiki.runner \
  --dataset demo_wiki \
  --docs-root examples/demo_wiki_docs \
  --provider filesystem
```

Reports are written to `runs/<timestamp>-filesystem/`.

### 2. Point it at your own wiki

```bash
python3 -m openwiki.runner \
  --dataset demo_wiki \
  --docs-root /path/to/your/wiki
```

For real usage, replace the demo dataset under `openwiki/datasets/demo_wiki/`
with a dataset that matches your own documentation.

### 3. Optional: compare against mem0

Sync the same public demo docs to a mem0 service:

```bash
python3 -m openwiki.sync_mem0 \
  --docs-root examples/demo_wiki_docs \
  --host <ssh-host> \
  --remote-root '<remote-mem0-root>' \
  --user-id openwiki-demo
```

Then run side-by-side:

```bash
OPENWIKI_MEM0_SSH_HOST=<ssh-host> \
OPENWIKI_MEM0_API_PORT=8788 \
OPENWIKI_MEM0_USER_ID=openwiki-demo \
python3 -m openwiki.runner \
  --dataset demo_wiki \
  --docs-root examples/demo_wiki_docs \
  --provider both
```

This writes:

- one report per provider
- one machine-readable comparison json
- one markdown comparison summary

## Repository Layout

```text
openwiki/
├── examples/demo_wiki_docs/    # safe demo markdown source
├── openwiki/
│   ├── bm25.py
│   ├── runner.py
│   ├── framework/
│   ├── providers/
│   └── datasets/demo_wiki/
├── scripts/run_demo.sh
├── LICENSE
└── README.md
```

## Dataset Format

Each dataset folder contains:

- `dataset.json`: metadata
- `questions.json`: benchmark questions
- `evaluator.py`: optional dataset-specific answer logic

Each question supports:

- `id`
- `question`
- `question_type`
- `ground_truth`
- `source_hints`
- `requires_all_sources`
- `capabilities`

## Provider Model

The first open-source provider is `filesystem`.

It:

- recursively indexes Markdown files
- chunks large files
- retrieves with BM25
- scores retrieval using file path hints

If your team later wants semantic retrieval or a remote vector backend, add a new
provider under `openwiki/providers/` without changing the dataset format.

An optional `mem0` provider is included for side-by-side comparison when a mem0
backend is available.

## Open-Source Boundary

This repo is the sanitized extraction boundary. If you keep iterating from the
private source project, do not copy these categories into OpenWiki:

- personal journals, health, family, or identity data
- company-only docs and benchmarks
- local machine paths
- benchmark run artifacts containing real evidence snippets
- tool-specific local config such as `.claude/` or editor secrets
