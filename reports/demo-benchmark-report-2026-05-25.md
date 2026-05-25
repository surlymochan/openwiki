# Demo Benchmark Report

Date: `2026-05-25`

## Scope

This report benchmarks the public `demo_wiki` dataset included in this repository.

- Dataset: `openwiki/datasets/demo_wiki`
- Documents indexed: `4`
- Questions: `8`
- Question types covered:
  - `fact_recall`
  - `abstention_strict`
  - `temporal_reasoning`
  - `policy_boundary`
  - `multi_hop_reasoning`

## Providers Compared

- `filesystem`: pure-Python BM25 over local markdown
- `mem0`: mem0 backend over the same public demo docs after sync

## Reproduction Commands

Sync the demo docs into mem0:

```bash
python3 -m openwiki.sync_mem0 \
  --docs-root examples/demo_wiki_docs \
  --host <ssh-host> \
  --remote-root '<remote-mem0-root>' \
  --user-id openwiki-demo
```

Run the comparison:

```bash
OPENWIKI_MEM0_SSH_HOST=<ssh-host> \
OPENWIKI_MEM0_API_PORT=8788 \
OPENWIKI_MEM0_USER_ID=openwiki-demo \
python3 -m openwiki.runner \
  --dataset demo_wiki \
  --docs-root examples/demo_wiki_docs \
  --provider both
```

## Overall Scores

| Provider | Accuracy | Recall@1 | Recall@3 | Recall@5 | MRR | Correct | Partial | Incorrect |
|----------|----------|----------|----------|----------|-----|---------|---------|-----------|
| filesystem | 41.2% | 0.875 | 1.000 | 1.000 | 0.917 | 1 | 5 | 2 |
| mem0 | 40.9% | 0.875 | 1.000 | 1.000 | 0.938 | 1 | 5 | 2 |

## By Question Type

| Provider | Type | Count | Accuracy | Recall@1 | Recall@3 | Recall@5 | MRR |
|----------|------|-------|----------|----------|----------|----------|-----|
| filesystem | abstention_strict | 1 | 100.0% | 1.000 | 1.000 | 1.000 | 1.000 |
| filesystem | fact_recall | 4 | 33.3% | 1.000 | 1.000 | 1.000 | 1.000 |
| filesystem | multi_hop_reasoning | 1 | 25.4% | 0.000 | 1.000 | 1.000 | 0.333 |
| filesystem | policy_boundary | 1 | 37.5% | 1.000 | 1.000 | 1.000 | 1.000 |
| filesystem | temporal_reasoning | 1 | 33.3% | 1.000 | 1.000 | 1.000 | 1.000 |
| mem0 | abstention_strict | 1 | 100.0% | 1.000 | 1.000 | 1.000 | 1.000 |
| mem0 | fact_recall | 4 | 33.0% | 1.000 | 1.000 | 1.000 | 1.000 |
| mem0 | multi_hop_reasoning | 1 | 25.4% | 0.000 | 1.000 | 1.000 | 0.500 |
| mem0 | policy_boundary | 1 | 34.1% | 1.000 | 1.000 | 1.000 | 1.000 |
| mem0 | temporal_reasoning | 1 | 35.3% | 1.000 | 1.000 | 1.000 | 1.000 |

## Interpretation

- On the current public demo dataset, `filesystem` and `mem0` are close on retrieval and answer quality.
- `mem0` has a slightly better overall MRR because it covers the multi-hop source set earlier.
- The answer score is an extractive baseline: it measures whether retrieved snippets overlap with the expected answer without using an LLM synthesis step.
- This dataset is useful as a smoke benchmark, but not yet a stress benchmark for differentiating retrieval architectures.
- The next meaningful optimization step is to add a harder public dataset with:
  - more cross-document aggregation
  - more semantic gap questions
  - more freshness and conflict cases

## Confidence Statement

This report is based on live runs against the repository's public demo docs, not on hand-entered scores.
Both providers were evaluated on the same dataset and question set.
The demo evaluator does not return canned answers by question id; answer scores come from retrieved evidence snippets and keyword-overlap judging.
