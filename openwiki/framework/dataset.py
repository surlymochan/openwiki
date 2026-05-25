"""Dataset loading utilities."""
from __future__ import annotations

import importlib.util
import json
import pathlib
from functools import lru_cache
from types import ModuleType


HERE = pathlib.Path(__file__).resolve().parents[1]
DATASETS_DIR = HERE / "datasets"


def dataset_dir(dataset_id: str) -> pathlib.Path:
    path = DATASETS_DIR / dataset_id
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_id}")
    return path


def load_dataset_manifest(dataset_id: str) -> dict:
    path = dataset_dir(dataset_id) / "dataset.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset_questions(dataset_id: str) -> list[dict]:
    path = dataset_dir(dataset_id) / "questions.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_dataset_evaluator(dataset_id: str) -> ModuleType | None:
    manifest = load_dataset_manifest(dataset_id)
    relpath = manifest.get("evaluator")
    if not relpath:
        return None
    path = dataset_dir(dataset_id) / relpath
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset evaluator: {path}")
    module_name = f"openwiki_dataset_evaluator_{dataset_id}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load dataset evaluator from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

