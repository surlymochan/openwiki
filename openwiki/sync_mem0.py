"""Sync markdown docs into a remote mem0 stack."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

from openwiki.memory_manifest import build_memory_items, write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync a public markdown docs tree into mem0")
    parser.add_argument("--docs-root", required=True, help="Markdown docs root")
    parser.add_argument("--host", default=os.getenv("OPENWIKI_MEM0_SSH_HOST", ""))
    parser.add_argument("--remote-root", default=os.getenv("OPENWIKI_MEM0_REMOTE_ROOT", "~/mem0-api"))
    parser.add_argument("--user-id", default=os.getenv("OPENWIKI_MEM0_USER_ID", "openwiki-demo"))
    parser.add_argument("--manifest-out", default="")
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args()

    if not args.host:
        raise SystemExit("OPENWIKI_MEM0_SSH_HOST or --host is required")

    docs_root = pathlib.Path(args.docs_root).resolve()
    items = build_memory_items(docs_root, exclude_dirs={".git", ".obsidian", "node_modules", "__pycache__"})
    manifest_path = pathlib.Path(args.manifest_out) if args.manifest_out else pathlib.Path("/tmp/openwiki_sync_manifest.jsonl")
    count = write_manifest(manifest_path, items)
    print(f"[mem0-sync] built manifest with {count} items -> {manifest_path}")

    remote_manifest = f"{args.remote_root}/data/openwiki_sync_manifest.jsonl"
    subprocess.run(["ssh", args.host, f"mkdir -p {args.remote_root}/data"], check=True, text=True)
    subprocess.run(["scp", str(manifest_path), f"{args.host}:{remote_manifest}"], check=True, text=True)

    payload = {"manifest_path": remote_manifest, "user_id": args.user_id, "reset": not args.no_reset}
    script = f"""
import json
import pathlib
import yaml
from mem0 import Memory

payload = json.loads({json.dumps(json.dumps(payload), ensure_ascii=False)})
with open("mem0_config.yaml", "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle)
memory = Memory.from_config(cfg)
if payload["reset"]:
    memory.delete_all(user_id=payload["user_id"])

manifest_path = pathlib.Path(payload["manifest_path"])
if str(manifest_path).startswith("~"):
    manifest_path = pathlib.Path(str(manifest_path).replace("~", str(pathlib.Path.home()), 1))

synced = 0
with manifest_path.open("r", encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        memory.add(
            item["text"],
            user_id=payload["user_id"],
            metadata={{
                "doc_id": item["id"],
                "source_path": item["source_path"],
                "source_type": item["source_type"],
                "tags": item["tags"],
            }},
            infer=False,
        )
        synced += 1
print(json.dumps({{"synced": synced, "user_id": payload["user_id"]}}, ensure_ascii=False))
"""
    completed = subprocess.run(
        ["ssh", args.host, f"cd {args.remote_root} && . .venv/bin/activate && python -"],
        input=script,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, end="", file=sys.stdout)
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        raise SystemExit(completed.returncode)
    print(f"[mem0-sync] {completed.stdout.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
