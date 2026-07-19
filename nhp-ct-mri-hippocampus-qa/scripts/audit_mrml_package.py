#!/usr/bin/env python3
"""Static audit of a packaged MRML scene, references, and critical-node transforms."""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path


DEFAULT_FORBIDDEN = (
    "brainmask_refine",
    "multistart_run",
    "rejected",
    "do_not_use",
    "rigid_v5",
    "affine_v5",
    "penetrate",
    "trajectory",
    "surgical_target",
)

INVENTORY_STATUS = "CANDIDATE_CRITICAL_NODE_INVENTORY"
TRANSFORM_REFERENCE_ROLES = {
    "transform",
    "parenttransform",
    "transformnode",
    "parenttransformnode",
}


def inside(path, root):
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def local_tag(tag):
    return tag.rsplit("}", 1)[-1]


def normalize_identifier(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def parse_node_references(attrs):
    """Return [(role, target_id, source_attribute)] and syntax errors.

    Modern Slicer scenes serialize node references in a semicolon-delimited
    ``references`` attribute (for example ``transform:nodeID;``). Older scenes
    may use attributes such as ``transformNodeRef``. Parse both encodings
    explicitly; do not infer transforms from arbitrary attribute substrings.
    """

    parsed = []
    errors = []
    raw_references = attrs.get("references", "")
    if raw_references:
        for fragment in raw_references.split(";"):
            fragment = fragment.strip()
            if not fragment:
                continue
            if ":" not in fragment:
                errors.append(f"malformed references entry without role separator: {fragment!r}")
                continue
            role, targets_text = fragment.split(":", 1)
            role = role.strip()
            targets = targets_text.split()
            if not role or not targets:
                errors.append(f"malformed references entry: {fragment!r}")
                continue
            parsed.extend((role, target, "references") for target in targets)

    for key, value in attrs.items():
        if not value or key.casefold() == "references":
            continue
        normalized_key = normalize_identifier(key)
        suffix = None
        if normalized_key.endswith("noderefs"):
            suffix = "noderefs"
        elif normalized_key.endswith("noderef"):
            suffix = "noderef"
        if suffix is None:
            continue
        role = normalized_key[: -len(suffix)]
        targets = value.split()
        if not role or not targets:
            errors.append(f"malformed legacy node-reference attribute {key!r}: {value!r}")
            continue
        parsed.extend((role, target, key) for target in targets)
    return parsed, errors


def parent_transform_references(parsed_references):
    refs = []
    for role, target, source in parsed_references:
        if normalize_identifier(role) in TRANSFORM_REFERENCE_ROLES:
            refs.append({"role": role, "target": target, "source": source})
    return refs


def is_coordinate_bearing_node(node):
    """Identify scene data whose world coordinates can be changed by a parent transform."""

    tag = normalize_identifier(node["tag"])
    node_class = re.sub(r"\d+$", "", normalize_identifier(node["id"]))
    if tag in {"volume", "labelmapvolume", "vectorvolume", "segmentation", "model", "roi"}:
        return True
    if tag.startswith("markups"):
        return "display" not in tag and "storage" not in tag
    if tag.endswith("transform") and "storage" not in tag and "display" not in tag:
        return True
    if node_class.endswith("volumenode"):
        return True
    if node_class in {"vtkmrmlsegmentationnode", "vtkmrmlmodelnode", "vtkmrmlroinode"}:
        return True
    if node_class.startswith("vtkmrmlmarkups") and node_class.endswith("node"):
        return not node_class.endswith("displaynode") and not node_class.endswith("storagenode")
    if node_class.endswith("transformnode"):
        return True
    return False


def load_and_validate_inventory(path, package, scene, nodes_by_id, coordinate_node_ids, issues):
    summary = {
        "path": str(path),
        "sha256": None,
        "declared_node_count": 0,
        "coordinate_node_count": len(coordinate_node_ids),
        "verified_node_ids": [],
    }
    if not path.exists():
        issues.append(f"critical-node inventory does not exist: {path}")
        return summary
    if not inside(path, package):
        issues.append("critical-node inventory is outside package root")
    try:
        summary["sha256"] = sha256_file(path)
        inventory = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(inventory, dict):
            raise ValueError("inventory root must be an object")
        if inventory.get("schema_version") != 1:
            issues.append("critical-node inventory schema_version must be 1")
        if inventory.get("status") != INVENTORY_STATUS:
            issues.append(f"critical-node inventory status must be {INVENTORY_STATUS}")

        expected_relative_scene = scene.relative_to(package).as_posix()
        inventory_relative_scene = inventory.get("scene_relative_path")
        if inventory_relative_scene != expected_relative_scene:
            issues.append(
                "critical-node inventory scene_relative_path mismatch: "
                f"{inventory_relative_scene!r} != {expected_relative_scene!r}"
            )
        actual_scene_hash = sha256_file(scene)
        if str(inventory.get("scene_sha256", "")).upper() != actual_scene_hash:
            issues.append("critical-node inventory scene_sha256 does not match the audited scene")

        entries = inventory.get("nodes")
        if not isinstance(entries, list) or not entries:
            issues.append("critical-node inventory nodes must be a non-empty array")
            entries = []
        summary["declared_node_count"] = len(entries)
        declared_ids = set()
        declared_roles = set()
        for index, entry in enumerate(entries):
            where = f"critical-node inventory nodes[{index}]"
            if not isinstance(entry, dict):
                issues.append(f"{where} must be an object")
                continue
            required = ("role", "id", "name", "tag", "expected_parent_transform")
            missing = [key for key in required if key not in entry]
            if missing:
                issues.append(f"{where} missing required fields: {missing}")
                continue
            role = entry["role"]
            node_id = entry["id"]
            if not isinstance(role, str) or not role.strip():
                issues.append(f"{where}.role must be a non-empty string")
            elif role in declared_roles:
                issues.append(f"duplicate critical-node inventory role: {role}")
            else:
                declared_roles.add(role)
            if not isinstance(node_id, str) or not node_id.strip():
                issues.append(f"{where}.id must be a non-empty string")
                continue
            if node_id in declared_ids:
                issues.append(f"duplicate critical-node inventory id: {node_id}")
                continue
            declared_ids.add(node_id)
            if entry["expected_parent_transform"] is not None:
                issues.append(
                    f"{where}.expected_parent_transform must be null; packaged critical nodes must be hardened"
                )
            scene_node = nodes_by_id.get(node_id)
            if scene_node is None:
                issues.append(f"critical-node inventory id not found in scene: {node_id}")
                continue
            if entry["name"] != scene_node["name"]:
                issues.append(
                    f"critical-node inventory name mismatch for {node_id}: "
                    f"{entry['name']!r} != {scene_node['name']!r}"
                )
            if entry["tag"] != scene_node["tag"]:
                issues.append(
                    f"critical-node inventory tag mismatch for {node_id}: "
                    f"{entry['tag']!r} != {scene_node['tag']!r}"
                )
            transform_refs = parent_transform_references(scene_node["references"])
            if transform_refs:
                issues.append(f"critical node has parent transform: {node_id} -> {transform_refs}")
            summary["verified_node_ids"].append(node_id)

        omitted = sorted(coordinate_node_ids - declared_ids)
        if omitted:
            issues.append(f"coordinate-bearing scene nodes omitted from critical-node inventory: {omitted}")
        non_coordinate = sorted(declared_ids - coordinate_node_ids)
        if non_coordinate:
            issues.append(f"critical-node inventory includes non-coordinate nodes: {non_coordinate}")
    except Exception as exc:
        issues.append(f"critical-node inventory {type(exc).__name__}: {exc}")
    summary["verified_node_ids"].sort()
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--critical-node-inventory", required=True)
    parser.add_argument("--report")
    parser.add_argument("--critical-node-name", action="append", default=[])
    parser.add_argument("--forbidden-token", action="append", default=[])
    parser.add_argument("--allow-absolute-inside-package", action="store_true")
    args = parser.parse_args()

    scene = Path(args.scene).resolve()
    package = Path(args.package_root).resolve()
    inventory_path = Path(args.critical_node_inventory).resolve()
    issues = []
    storage_references = []
    node_references = []
    forbidden = tuple(token.casefold() for token in (*DEFAULT_FORBIDDEN, *args.forbidden_token))
    additional_critical_names = {name.casefold(): name for name in args.critical_node_name}
    inventory_summary = None
    try:
        if not scene.exists() or not package.exists():
            raise FileNotFoundError("scene or package root does not exist")
        if not package.is_dir():
            raise NotADirectoryError(f"package root is not a directory: {package}")
        if not inside(scene, package):
            issues.append("scene is outside package root")
        root = ET.parse(scene).getroot()

        nodes = []
        nodes_by_id = {}
        for element in root.iter():
            attrs = dict(element.attrib)
            node_id = attrs.get("id", "")
            if not node_id:
                continue
            node = {
                "id": node_id,
                "name": attrs.get("name", ""),
                "tag": local_tag(element.tag),
                "attrs": attrs,
            }
            refs, ref_errors = parse_node_references(attrs)
            node["references"] = refs
            nodes.append(node)
            if node_id in nodes_by_id:
                issues.append(f"duplicate MRML node id: {node_id}")
            else:
                nodes_by_id[node_id] = node
            for error in ref_errors:
                issues.append(f"{node_id}: {error}")

        all_ids = set(nodes_by_id)
        matched_additional_names = set()
        for node in nodes:
            node_id = node["id"]
            tag = node["tag"]
            attrs = node["attrs"]
            name = node["name"]
            joined = "\n".join([tag, name, *[f"{key}={value}" for key, value in attrs.items()]])
            lower = joined.casefold()
            if "commandlinemodule" in tag.casefold():
                issues.append(f"saved CLI node: {name or tag}")
            matches = sorted({token for token in forbidden if token and token in lower})
            if matches:
                issues.append(f"forbidden token(s) {matches} in node {name or tag}")

            name_key = name.casefold()
            if name_key in additional_critical_names:
                matched_additional_names.add(name_key)
                transform_refs = parent_transform_references(node["references"])
                if transform_refs:
                    issues.append(f"additional critical node has parent transform: {node_id} -> {transform_refs}")

            for role, target, source in node["references"]:
                reference = {"source_node": node_id, "role": role, "target_node": target, "source_attribute": source}
                node_references.append(reference)
                if target not in all_ids:
                    issues.append(
                        f"dangling MRML node reference: {node_id} {role!r} -> {target} ({source})"
                    )

            uri_values = [value for key, value in attrs.items() if "uri" in key.casefold() and value]
            if uri_values:
                issues.append(f"URI storage reference in {name or tag}: {uri_values}")
            file_values = []
            for key, value in attrs.items():
                key_lower = key.casefold()
                if value and (key_lower == "filename" or key_lower.startswith("filelistmember")):
                    file_values.append(value)
            for raw in file_values:
                decoded = urllib.parse.unquote(raw).replace("/", os.sep)
                candidate = Path(decoded)
                is_absolute = candidate.is_absolute()
                if ".." in candidate.parts:
                    issues.append(f"parent-directory storage reference is forbidden: {raw}")
                resolved = candidate.resolve() if is_absolute else (scene.parent / candidate).resolve()
                item = {"node": name or tag, "raw": raw, "resolved": str(resolved), "absolute": is_absolute}
                storage_references.append(item)
                if not inside(resolved, package):
                    issues.append(f"storage reference outside package: {raw} -> {resolved}")
                elif is_absolute and not args.allow_absolute_inside_package:
                    issues.append(f"absolute storage reference reduces portability: {raw}")
                if not resolved.exists():
                    issues.append(f"missing storage file: {raw} -> {resolved}")

        unmatched_names = sorted(set(additional_critical_names) - matched_additional_names)
        if unmatched_names:
            issues.append(
                "additional critical-node name(s) not found exactly in scene: "
                f"{[additional_critical_names[name] for name in unmatched_names]}"
            )

        coordinate_node_ids = {node["id"] for node in nodes if is_coordinate_bearing_node(node)}
        inventory_summary = load_and_validate_inventory(
            inventory_path,
            package,
            scene,
            nodes_by_id,
            coordinate_node_ids,
            issues,
        )
    except Exception as exc:
        issues.append(f"{type(exc).__name__}: {exc}")

    report = {
        "status": "PASS" if not issues else "FAIL",
        "scene": str(scene),
        "package_root": str(package),
        "critical_node_inventory": inventory_summary,
        "storage_reference_count": len(storage_references),
        "storage_references": storage_references,
        "node_reference_count": len(node_references),
        "node_references": node_references,
        "issues": issues,
        "warning": (
            "Static XML audit does not replace reloading the scene and validating arrays/geometry in 3D Slicer. "
            "All outputs remain research candidates and are not approved for surgical use."
        ),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    return 0 if not issues else 2


if __name__ == "__main__":
    sys.exit(main())
