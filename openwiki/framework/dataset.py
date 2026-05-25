"""Dataset loading utilities."""
from __future__ import annotations

import importlib.util
import json
import pathlib
from functools import lru_cache
from types import ModuleType


HERE = pathlib.Path(__file__).resolve().parents[1]
DATASETS_DIR = HERE / "datasets"


def dataset_dir(dataset_id: str, datasets_root: str | pathlib.Path | None = None) -> pathlib.Path:
    root = pathlib.Path(datasets_root).expanduser().resolve() if datasets_root else DATASETS_DIR
    path = root / dataset_id
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_id} under {root}")
    return path


def load_dataset_manifest(dataset_id: str, datasets_root: str | pathlib.Path | None = None) -> dict:
    path = dataset_dir(dataset_id, datasets_root) / "dataset.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset_questions(dataset_id: str, datasets_root: str | pathlib.Path | None = None) -> list[dict]:
    path = dataset_dir(dataset_id, datasets_root) / "questions.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset questions: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _load_dataset_evaluator_cached(dataset_id: str, datasets_root_key: str) -> ModuleType | None:
    datasets_root = pathlib.Path(datasets_root_key) if datasets_root_key else None
    manifest = load_dataset_manifest(dataset_id, datasets_root)
    relpath = manifest.get("evaluator")
    if not relpath:
        return None
    path = dataset_dir(dataset_id, datasets_root) / relpath
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset evaluator: {path}")
    module_name = f"openwiki_dataset_evaluator_{dataset_id}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load dataset evaluator from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dataset_evaluator(dataset_id: str, datasets_root: str | pathlib.Path | None = None) -> ModuleType | None:
    key = str(pathlib.Path(datasets_root).expanduser().resolve()) if datasets_root else ""
    return _load_dataset_evaluator_cached(dataset_id, key)
