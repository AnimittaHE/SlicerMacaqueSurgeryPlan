"""Compute guarded independent CT-to-MRI landmark TRE inside 3D Slicer.

Set NHP_TRE_CONFIG to a completed tre-run-config JSON and execute this file
inside 3D Slicer. Results remain research QA and never constitute surgical
approval.
"""

import csv
import datetime
import hashlib
import json
import math
import os
import sys
import traceback


CONFIG_ENV = "NHP_TRE_CONFIG"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def config_path():
    value = os.environ.get(CONFIG_ENV)
    if value:
        return os.path.abspath(value)
    for index, argument in enumerate(sys.argv):
        if argument.startswith("--nhp-tre-config="):
            return os.path.abspath(argument.split("=", 1)[1])
        if argument == "--nhp-tre-config" and index + 1 < len(sys.argv):
            return os.path.abspath(sys.argv[index + 1])
    raise RuntimeError(f"Set {CONFIG_ENV} or pass --nhp-tre-config PATH")


def load_spec(path):
    with open(path, "r", encoding="utf-8") as stream:
        spec = json.load(stream)
    if spec.get("schema_version") != 1 or spec.get("status") != "APPROVED_FOR_THIS_PROTOCOL":
        raise RuntimeError("landmark spec must be schema 1 and APPROVED_FOR_THIS_PROTOCOL")
    for key in ("protocol_name", "approved_by", "approver_role", "approval_date"):
        if not str(spec.get(key, "")).strip():
            raise RuntimeError(f"approved landmark spec is missing {key}")
    minimum = spec.get("minimum_paired_points")
    if not isinstance(minimum, int) or minimum < 4:
        raise RuntimeError("minimum_paired_points must be an integer >= 4")
    for key in ("minimum_extent_each_axis_mm", "minimum_smallest_singular_value_mm"):
        value = spec.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise RuntimeError(f"approved landmark spec requires positive {key}")
    landmarks = spec.get("landmarks", [])
    if len(landmarks) < minimum:
        raise RuntimeError("landmark list is shorter than minimum_paired_points")
    labels = []
    sides = {}
    for item in landmarks:
        label = str(item.get("label", "")).strip()
        definition = str(item.get("definition", "")).strip()
        side = item.get("side")
        if not label or not definition or "REPLACE" in definition.upper():
            raise RuntimeError("landmark labels and definitions must be completed")
        if side not in ("midline", "biological_left", "biological_right", "unpaired"):
            raise RuntimeError(f"invalid side for {label}: {side}")
        labels.append(label)
        sides[label] = side
    if len(labels) != len(set(labels)):
        raise RuntimeError("landmark labels must be unique")
    return spec, labels, sides


def hash_directory(path):
    tree = hashlib.sha256()
    files = []
    for root, _, names in os.walk(path):
        for name in names:
            full = os.path.join(root, name)
            if os.path.islink(full):
                raise RuntimeError(f"symlink in frozen directory: {full}")
            relative = os.path.relpath(full, path).replace(os.sep, "/")
            files.append((relative, full))
    for relative, full in sorted(files, key=lambda item: item[0].casefold()):
        size = os.path.getsize(full)
        digest = sha256(full)
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(str(size).encode("ascii"))
        tree.update(b"\0")
        tree.update(digest.encode("ascii"))
        tree.update(b"\n")
    return tree.hexdigest(), len(files)


def verify_frozen_manifest(path, required_roles, expected_role_paths):
    with open(path, "r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("schema_version") != 1 or manifest.get("status") != "FROZEN_INPUTS":
        raise RuntimeError("frozen hash manifest is unsupported or not FROZEN_INPUTS")
    entries = {}
    for entry in manifest.get("entries", []):
        role = entry.get("role")
        if not role or role in entries:
            raise RuntimeError(f"blank or duplicate frozen role: {role}")
        entries[role] = entry
    missing = sorted(set(required_roles) - set(entries))
    if missing:
        raise RuntimeError(f"frozen hash manifest is missing required roles: {missing}")
    verified = {}
    for role in required_roles:
        entry = entries[role]
        actual_path = os.path.abspath(entry.get("path", ""))
        expected_path = expected_role_paths.get(role)
        if expected_path and os.path.normcase(actual_path) != os.path.normcase(os.path.abspath(expected_path)):
            raise RuntimeError(f"frozen path mismatch for {role}: {actual_path} != {expected_path}")
        if entry.get("kind") == "file":
            if not os.path.isfile(actual_path):
                raise RuntimeError(f"frozen file is missing for {role}: {actual_path}")
            digest = sha256(actual_path)
            if digest != entry.get("sha256") or os.path.getsize(actual_path) != entry.get("size"):
                raise RuntimeError(f"frozen file hash/size mismatch for {role}")
            verified[role] = {"path": actual_path, "sha256": digest}
        elif entry.get("kind") == "directory":
            if not os.path.isdir(actual_path):
                raise RuntimeError(f"frozen directory is missing for {role}: {actual_path}")
            digest, count = hash_directory(actual_path)
            if digest != entry.get("tree_sha256") or count != entry.get("file_count"):
                raise RuntimeError(f"frozen directory tree mismatch for {role}")
            verified[role] = {"path": actual_path, "tree_sha256": digest, "file_count": count}
        else:
            raise RuntimeError(f"unknown frozen entry kind for {role}")
    return verified


def assert_no_parent(node, description):
    transform_id = node.GetTransformNodeID()
    if transform_id:
        raise RuntimeError(f"{description} has parent transform {transform_id}; refusing possible double transform")


def extract_points(node, expected_labels, description, slicer, np):
    assert_no_parent(node, description)
    seen = {}
    for index in range(node.GetNumberOfControlPoints()):
        raw = node.GetNthControlPointLabel(index)
        label = raw.strip()
        if not label or label != raw:
            raise RuntimeError(f"{description}: blank or whitespace-altered label")
        if label in seen:
            raise RuntimeError(f"{description}: duplicate label {label}")
        if label not in expected_labels:
            raise RuntimeError(f"{description}: unknown label {label}")
        point = None
        status = node.GetNthControlPointPositionStatus(index)
        if status == slicer.vtkMRMLMarkupsNode.PositionDefined:
            position = [0.0, 0.0, 0.0]
            node.GetNthControlPointPositionWorld(index, position)
            point = np.asarray(position, dtype=float)
            if not np.all(np.isfinite(point)):
                raise RuntimeError(f"{description}: non-finite coordinate for {label}")
        seen[label] = point
    if set(seen) != set(expected_labels):
        raise RuntimeError(f"{description}: labels do not exactly match the approved spec")
    return seen


def require_laterality(path):
    if not path or not os.path.isfile(path):
        raise RuntimeError("lateralized landmarks require an independent biological laterality confirmation file")
    with open(path, "r", encoding="utf-8") as stream:
        record = json.load(stream)
    if record.get("status") != "CONFIRMED":
        raise RuntimeError("biological laterality status is not CONFIRMED")
    required = (
        "confirmed_by",
        "role",
        "date",
        "evidence",
        "ct_biological_left_identification",
        "mri_biological_left_identification",
    )
    missing = [key for key in required if not str(record.get(key, "")).strip()]
    if missing or str(record.get("unresolved_conflicts", "")).strip():
        raise RuntimeError(f"biological laterality confirmation is incomplete or conflicted: {missing}")
    return record


def load_thresholds(path, protocol_name):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as stream:
        thresholds = json.load(stream)
    if thresholds.get("status") != "APPROVED_FOR_THIS_PROTOCOL":
        raise RuntimeError("thresholds file is not APPROVED_FOR_THIS_PROTOCOL")
    if thresholds.get("protocol_name") != protocol_name:
        raise RuntimeError("threshold protocol does not match the landmark protocol")
    for key in ("approved_by", "approver_role", "approval_date"):
        if not str(thresholds.get(key, "")).strip():
            raise RuntimeError(f"approved thresholds are missing {key}")
    limits = thresholds.get("limits_mm", {})
    for key in ("rms_tre_max", "maximum_tre_max", "absolute_mean_axis_error_max"):
        value = limits.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise RuntimeError(f"invalid approved threshold: {key}")
    return thresholds


def main(config):
    import numpy as np
    import slicer
    import vtk

    section = config.get("compute", {})
    required_keys = (
        "native_ct",
        "native_mri",
        "ct_blank_template",
        "mri_blank_template",
        "ct_markups",
        "mri_markups",
        "ct_to_mri_transform",
        "landmark_spec",
        "frozen_hash_manifest",
        "output_dir",
    )
    missing = [key for key in required_keys if not str(section.get(key, "")).strip()]
    if missing:
        raise RuntimeError(f"compute config is missing: {missing}")
    if section.get("transform_direction") != "CT_NATIVE_TO_MRI_NATIVE":
        raise RuntimeError("transform_direction must be CT_NATIVE_TO_MRI_NATIVE")

    paths = {key: os.path.abspath(section[key]) for key in required_keys}
    for key, path in paths.items():
        if key != "output_dir" and not os.path.exists(path):
            raise RuntimeError(f"required path does not exist for {key}: {path}")
    output_dir = paths["output_dir"]
    os.makedirs(output_dir, exist_ok=True)
    result_json = os.path.join(output_dir, "TRE_RESULT.json")
    result_csv = os.path.join(output_dir, "TRE_RESULT.csv")
    error_file = os.path.join(output_dir, "TRE_COMPUTE_ERROR.txt")
    for stale in (result_json, result_csv, error_file):
        if os.path.exists(stale):
            os.remove(stale)

    spec, labels, sides = load_spec(paths["landmark_spec"])
    required_roles = section.get("required_frozen_roles", [])
    expected_role_paths = {
        "native_ct": paths["native_ct"],
        "native_mri": paths["native_mri"],
        "ct_to_mri_transform": paths["ct_to_mri_transform"],
        "landmark_spec": paths["landmark_spec"],
        "ct_blank_template": paths["ct_blank_template"],
        "mri_blank_template": paths["mri_blank_template"],
    }
    if set(required_roles) != set(expected_role_paths):
        raise RuntimeError(f"required_frozen_roles must be exactly {sorted(expected_role_paths)}")
    verified_frozen = verify_frozen_manifest(paths["frozen_hash_manifest"], required_roles, expected_role_paths)

    slicer.mrmlScene.Clear(0)
    ct_node = slicer.util.loadMarkups(paths["ct_markups"])
    mri_node = slicer.util.loadMarkups(paths["mri_markups"])
    transform_node = slicer.util.loadTransform(paths["ct_to_mri_transform"])
    if not all((ct_node, mri_node, transform_node)):
        raise RuntimeError("could not load markups or CT-to-MRI transform")
    ct_points = extract_points(ct_node, labels, "CT markups", slicer, np)
    mri_points = extract_points(mri_node, labels, "MRI markups", slicer, np)
    paired = [label for label in labels if ct_points[label] is not None and mri_points[label] is not None]
    only_ct = [label for label in labels if ct_points[label] is not None and mri_points[label] is None]
    only_mri = [label for label in labels if ct_points[label] is None and mri_points[label] is not None]
    if len(paired) < spec["minimum_paired_points"]:
        raise RuntimeError(
            f"only {len(paired)} paired landmarks; need {spec['minimum_paired_points']}; "
            f"CT-only={only_ct}, MRI-only={only_mri}"
        )
    used_lateral = [label for label in paired if sides[label] in ("biological_left", "biological_right")]
    laterality_record = None
    laterality_path = section.get("laterality_confirmation")
    if used_lateral:
        laterality_record = require_laterality(os.path.abspath(laterality_path) if laterality_path else None)

    assert_no_parent(transform_node, "CT-to-MRI transform")
    matrix_vtk = vtk.vtkMatrix4x4()
    if not transform_node.GetMatrixTransformToParent(matrix_vtk):
        raise RuntimeError("CT-to-MRI transform is not linear")
    matrix = np.array([[matrix_vtk.GetElement(row, col) for col in range(4)] for row in range(4)], dtype=float)
    if not np.all(np.isfinite(matrix)) or not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-6):
        raise RuntimeError("invalid homogeneous transform matrix")
    rotation = matrix[:3, :3]
    determinant = float(np.linalg.det(rotation))
    orthogonality_error = float(np.max(np.abs(rotation.T @ rotation - np.eye(3))))
    if abs(determinant - 1.0) > 1e-4 or orthogonality_error > 1e-4:
        raise RuntimeError("transform is not a proper rigid transform")

    rows = []
    errors = []
    vectors = []
    mri_coverage = []
    for label in paired:
        transformed = (matrix @ np.r_[ct_points[label], 1.0])[:3]
        vector = transformed - mri_points[label]
        error = float(np.linalg.norm(vector))
        errors.append(error)
        vectors.append(vector)
        mri_coverage.append(mri_points[label])
        rows.append(
            {
                "label": label,
                "side": sides[label],
                "CT_native_world_RAS_mm": ct_points[label].tolist(),
                "CT_transformed_to_MRI_world_RAS_mm": transformed.tolist(),
                "MRI_native_world_RAS_mm": mri_points[label].tolist(),
                "error_vector_RAS_mm": vector.tolist(),
                "TRE_mm": error,
            }
        )
    errors = np.asarray(errors, dtype=float)
    vectors = np.asarray(vectors, dtype=float)
    mri_coverage = np.asarray(mri_coverage, dtype=float)
    extent = np.ptp(mri_coverage, axis=0)
    centered = mri_coverage - np.mean(mri_coverage, axis=0)
    singular_values = np.linalg.svd(centered, compute_uv=False)
    if np.any(extent < float(spec["minimum_extent_each_axis_mm"])):
        raise RuntimeError(f"landmark extent is below approved coverage minimum: {extent.tolist()}")
    if singular_values[-1] < float(spec["minimum_smallest_singular_value_mm"]):
        raise RuntimeError(f"landmark 3D dispersion is below approved minimum: {singular_values.tolist()}")

    rms = float(math.sqrt(np.mean(errors**2)))
    median = float(np.median(errors))
    p95 = float(np.percentile(errors, 95))
    maximum = float(np.max(errors))
    mean_vector = np.mean(vectors, axis=0)
    thresholds_path = section.get("thresholds_file")
    thresholds = load_thresholds(os.path.abspath(thresholds_path), spec["protocol_name"]) if thresholds_path else None
    if thresholds:
        limits = thresholds["limits_mm"]
        passed = (
            rms <= limits["rms_tre_max"]
            and maximum <= limits["maximum_tre_max"]
            and float(np.max(np.abs(mean_vector))) <= limits["absolute_mean_axis_error_max"]
        )
        threshold_status = "RESEARCH_QA_TRIGGER_PASS" if passed else "QA_FAILED_TRIGGER"
    else:
        threshold_status = "NO_APPROVED_ACCEPTANCE_THRESHOLDS"

    runtime_hashes = {
        os.path.basename(path): sha256(path)
        for path in (
            paths["ct_markups"],
            paths["mri_markups"],
            paths["ct_to_mri_transform"],
            paths["landmark_spec"],
            paths["frozen_hash_manifest"],
        )
    }
    if laterality_record is not None:
        runtime_hashes[os.path.basename(os.path.abspath(laterality_path))] = sha256(os.path.abspath(laterality_path))
    if thresholds is not None:
        runtime_hashes[os.path.basename(os.path.abspath(thresholds_path))] = sha256(os.path.abspath(thresholds_path))
    report = {
        "status": "INDEPENDENT_TRE_RESULT_REQUIRES_EXPERT_INTERPRETATION",
        "run_time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "slicer_application_version": str(getattr(slicer.app, "applicationVersion", "unknown")),
        "protocol_name": spec["protocol_name"],
        "transform_direction": "CT native world RAS -> MRI native world RAS",
        "transform_matrix": matrix.tolist(),
        "transform_determinant": determinant,
        "transform_orthogonality_max_abs_error": orthogonality_error,
        "paired_landmark_count": len(paired),
        "labels": paired,
        "defined_only_in_CT": only_ct,
        "defined_only_in_MRI": only_mri,
        "used_lateralized_labels": used_lateral,
        "biological_laterality_confirmation": laterality_record,
        "MRI_landmark_extent_RAS_mm": extent.tolist(),
        "MRI_landmark_centered_singular_values_mm": singular_values.tolist(),
        "RMS_TRE_mm": rms,
        "median_TRE_mm": median,
        "p95_TRE_mm": p95,
        "maximum_TRE_mm": maximum,
        "mean_error_vector_RAS_mm": mean_vector.tolist(),
        "threshold_status": threshold_status,
        "approved_thresholds": thresholds,
        "verified_frozen_inputs": verified_frozen,
        "runtime_input_SHA256": runtime_hashes,
        "points": rows,
        "warning": "Research QA only. TRE does not equal hippocampal target error or the full stereotactic error budget and cannot approve surgery.",
    }
    with open(result_json, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    with open(result_csv, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["label", "side", "TRE_mm", "dR_mm", "dA_mm", "dS_mm"])
        for row in rows:
            writer.writerow([row["label"], row["side"], row["TRE_mm"], *row["error_vector_RAS_mm"]])
        writer.writerow([])
        writer.writerow(["RMS_TRE_mm", rms])
        writer.writerow(["median_TRE_mm", median])
        writer.writerow(["p95_TRE_mm", p95])
        writer.writerow(["maximum_TRE_mm", maximum])
        writer.writerow(["threshold_status", threshold_status])
    return output_dir


try:
    config_file = config_path()
    with open(config_file, "r", encoding="utf-8") as stream:
        configuration = json.load(stream)
    result_dir = main(configuration)
except Exception:
    try:
        fallback_dir = os.path.abspath(configuration.get("compute", {}).get("output_dir", os.getcwd()))
    except Exception:
        fallback_dir = os.getcwd()
    os.makedirs(fallback_dir, exist_ok=True)
    for stale_name in ("TRE_RESULT.json", "TRE_RESULT.csv"):
        stale = os.path.join(fallback_dir, stale_name)
        if os.path.exists(stale):
            os.remove(stale)
    with open(os.path.join(fallback_dir, "TRE_COMPUTE_ERROR.txt"), "w", encoding="utf-8") as stream:
        stream.write(traceback.format_exc())
    import slicer

    slicer.app.exit(1)
else:
    import slicer

    error_file = os.path.join(result_dir, "TRE_COMPUTE_ERROR.txt")
    if os.path.exists(error_file):
        os.remove(error_file)
    slicer.app.exit(0)
