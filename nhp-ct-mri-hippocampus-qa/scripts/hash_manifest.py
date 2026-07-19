#!/usr/bin/env python3
"""Freeze or verify file/directory SHA-256 manifests."""

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_regular(path):
    if path.is_symlink():
        raise ValueError(f"symlinks are not accepted: {path}")
    if not path.exists():
        raise FileNotFoundError(path)


def directory_entry(path):
    files = []
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix().casefold()):
        if item.is_dir():
            continue
        assert_regular(item)
        relative = item.relative_to(path).as_posix()
        files.append({"relative_path": relative, "size": item.stat().st_size, "sha256": sha256(item)})
    tree = hashlib.sha256()
    for item in files:
        tree.update(item["relative_path"].encode("utf-8"))
        tree.update(b"\0")
        tree.update(str(item["size"]).encode("ascii"))
        tree.update(b"\0")
        tree.update(item["sha256"].encode("ascii"))
        tree.update(b"\n")
    return {"kind": "directory", "path": str(path), "file_count": len(files), "tree_sha256": tree.hexdigest(), "files": files}


def build_entry(role, raw_path):
    path = Path(raw_path).resolve()
    assert_regular(path)
    if path.is_dir():
        entry = directory_entry(path)
    elif path.is_file():
        entry = {"kind": "file", "path": str(path), "size": path.stat().st_size, "sha256": sha256(path)}
    else:
        raise ValueError(f"not a regular file or directory: {path}")
    entry["role"] = role
    return entry


def parse_entries(values):
    parsed = []
    roles = set()
    for value in values:
        if "=" not in value:
            raise ValueError(f"entry must be ROLE=PATH: {value}")
        role, path = value.split("=", 1)
        role = role.strip()
        if not role or role in roles:
            raise ValueError(f"blank or duplicate role: {role}")
        roles.add(role)
        parsed.append((role, path))
    return parsed


def freeze(args):
    output = Path(args.output).resolve()
    parsed = parse_entries(args.entry)
    for _, raw_path in parsed:
        source = Path(raw_path).resolve()
        if source.is_dir() and os.path.commonpath([source, output]) == str(source):
            raise ValueError("manifest output must not be inside a frozen input directory")
        if source == output:
            raise ValueError("manifest output must not overwrite an input")
    manifest = {
        "schema_version": 1,
        "status": "FROZEN_INPUTS",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "entries": [build_entry(role, path) for role, path in parsed],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps({"status": "PASS", "manifest": str(output), "entry_count": len(manifest["entries"])}, indent=2))
    return 0


def verify_file(entry, errors):
    path = Path(entry["path"])
    try:
        assert_regular(path)
        if not path.is_file():
            raise ValueError("expected file")
        actual = sha256(path)
        if actual != entry["sha256"] or path.stat().st_size != entry["size"]:
            errors.append(f"file mismatch: {path}")
    except Exception as exc:
        errors.append(f"{path}: {type(exc).__name__}: {exc}")


def verify_directory(entry, errors):
    path = Path(entry["path"])
    try:
        assert_regular(path)
        if not path.is_dir():
            raise ValueError("expected directory")
        actual = directory_entry(path)
        if actual["tree_sha256"] != entry["tree_sha256"] or actual["files"] != entry["files"]:
            errors.append(f"directory mismatch: {path}")
    except Exception as exc:
        errors.append(f"{path}: {type(exc).__name__}: {exc}")


def verify(args):
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("status") != "FROZEN_INPUTS":
        raise ValueError("unsupported or non-frozen manifest")
    errors = []
    roles = set()
    for entry in manifest.get("entries", []):
        role = entry.get("role")
        if not role or role in roles:
            errors.append(f"blank or duplicate role: {role}")
            continue
        roles.add(role)
        if entry.get("kind") == "file":
            verify_file(entry, errors)
        elif entry.get("kind") == "directory":
            verify_directory(entry, errors)
        else:
            errors.append(f"unknown entry kind for role {role}")
    report = {"status": "PASS" if not errors else "FAIL", "manifest": str(manifest_path), "verified_roles": sorted(roles), "errors": errors}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--output", required=True)
    freeze_parser.add_argument("--entry", action="append", required=True, help="ROLE=PATH; repeat as needed")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    try:
        return freeze(args) if args.command == "freeze" else verify(args)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
