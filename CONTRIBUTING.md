# Contributing

## Local Smoke Check

Run the built-in demo benchmark before opening a pull request:

```bash
python3 -m openwiki.runner \
  --dataset demo_wiki \
  --docs-root examples/demo_wiki_docs \
  --provider filesystem
```

## Adding a New Dataset

1. Create `openwiki/datasets/<dataset-id>/`
2. Add `dataset.json`
3. Add `questions.json`
4. Add `evaluator.py` only if the default answer judge is not enough
5. Keep all example data safe to publish

## Adding a New Provider

1. Implement `build_index()`
2. Implement `search()`
3. Return stable `stats()`
4. Make sure the provider can run without private paths baked into source

## Open-Source Safety

Do not commit:

- internal company documents
- personal notes or journals
- secrets or editor-local config
- benchmark run outputs containing non-public evidence

