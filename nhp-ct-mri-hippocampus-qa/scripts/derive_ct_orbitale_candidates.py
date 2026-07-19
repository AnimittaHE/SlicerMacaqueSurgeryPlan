#!/usr/bin/env python3
"""Derive unverified bilateral orbitale seeds from a configured native CT.

The algorithm is deliberately semi-automatic: ray direction, inferior direction,
thresholds, bilateral search regions, and component seeds must be reviewed and
configured for each subject. Outputs are not surgical landmarks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import nrrd
import numpy as np
from scipy import ndimage


SIDE_NAMES = ("coordinate_side_A", "coordinate_side_B")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ct", required=True, type=Path, help="Native CT NRRD")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markups", type=Path)
    parser.add_argument("--qa-image", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_space(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def reject_placeholder(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a text string")
    text = value.strip()
    if not text or text.upper().startswith(
        ("REPLACE", "ABSOLUTE_PATH", "PREDECLARE", "YYYY", "TODO", "TBD")
    ):
        raise ValueError(f"{name} must be completed with case-specific evidence")


def valid_sha256(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(char in "0123456789abcdefABCDEF" for char in text)


def verified_file_record(record: object, role: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{role} must be an object with path and sha256")
    path = Path(str(record.get("path", "")))
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{role}.path must be an existing absolute file")
    recorded_hash = str(record.get("sha256", "")).strip()
    if not valid_sha256(recorded_hash) or recorded_hash.casefold() != sha256(path).casefold():
        raise ValueError(f"{role}.sha256 does not match the current file")
    return path


def parse_mrml_references(raw: str, node_label: str) -> dict[str, list[str]]:
    references: dict[str, list[str]] = {}
    for field in str(raw or "").split(";"):
        field = field.strip()
        if not field:
            continue
        role, separator, ids = field.partition(":")
        if not separator or not role.strip() or not ids.strip():
            raise ValueError(f"malformed MRML references on {node_label}: {field!r}")
        references.setdefault(role.strip(), []).extend(ids.split())
    return references


def same_path(first: Path, second: Path) -> bool:
    return str(first.resolve()).casefold() == str(second.resolve()).casefold()


def volume_storage_path(root: ET.Element, volume: ET.Element, scene_path: Path) -> Path:
    references = parse_mrml_references(
        volume.attrib.get("references", ""), volume.attrib.get("name", "unnamed volume")
    )
    storage_ids = list(references.get("storage", []))
    for legacy_key in ("storageNodeRef", "storageNodeID"):
        storage_ids.extend(str(volume.attrib.get(legacy_key, "")).split())
    storage_ids = list(dict.fromkeys(storage_ids))
    if len(storage_ids) != 1:
        raise ValueError(
            f"named volume {volume.attrib.get('name')!r} must reference exactly one storage node"
        )
    matches = [
        element
        for element in root.iter()
        if element.attrib.get("id") == storage_ids[0]
        and element.tag.rsplit("}", 1)[-1].endswith("Storage")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"storage node {storage_ids[0]!r} for volume {volume.attrib.get('name')!r} "
            "is not unique"
        )
    if any(
        "uri" in key.casefold() and str(value).strip()
        for key, value in matches[0].attrib.items()
    ):
        raise ValueError(
            f"storage node {storage_ids[0]!r} uses a URI; provenance requires a local file"
        )
    file_name = str(matches[0].attrib.get("fileName", "")).strip()
    if not file_name:
        raise ValueError(f"storage node {storage_ids[0]!r} has no fileName")
    storage_path = Path(file_name)
    if not storage_path.is_absolute():
        storage_path = scene_path.parent / storage_path
    if not storage_path.is_file():
        raise ValueError(f"MRML storage file does not exist: {storage_path}")
    return storage_path.resolve()


def parent_transform_ids(element: ET.Element) -> set[str]:
    references = parse_mrml_references(
        element.attrib.get("references", ""), element.attrib.get("name", "unnamed node")
    )
    values = references.get("transform", []) + references.get("parentTransform", [])
    for legacy_key in ("transformNodeRef", "parentTransformNodeRef"):
        values.extend(str(element.attrib.get(legacy_key, "")).split())
    return set(values)


def verify_transform_source(
    config: dict,
    matrix: np.ndarray,
    moving_volume_path: Path,
    fixed_volume_path: Path,
) -> None:
    source = config.get("transform_source")
    source_path = verified_file_record(source, "transform_source")
    if source.get("kind") != "MRML_LINEAR_TRANSFORM_TO_PARENT_RAS":
        raise ValueError(
            "transform_source.kind must be MRML_LINEAR_TRANSFORM_TO_PARENT_RAS "
            "for matrix binding"
        )
    reject_placeholder(source.get("node_name"), "transform_source.node_name")
    node_name = source["node_name"].strip()
    root = ET.parse(source_path).getroot()
    matches = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "LinearTransform"
        and element.attrib.get("name") == node_name
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one MRML LinearTransform named {node_name!r}; found {len(matches)}"
        )
    raw_matrix = matches[0].attrib.get("matrixTransformToParent", "")
    transform_id = matches[0].attrib.get("id", "")
    if not transform_id:
        raise ValueError("MRML transform node has no id")
    if parent_transform_ids(matches[0]):
        raise ValueError("MRML transform node has a parent transform; full chain is not flattened")
    values = np.asarray([float(value) for value in raw_matrix.split()], dtype=float)
    if values.size != 16:
        raise ValueError("MRML transform matrix does not contain 16 values")
    source_matrix = values.reshape(4, 4)
    if not np.allclose(source_matrix, matrix, atol=1e-7, rtol=0.0):
        raise ValueError("configured CT-to-output matrix does not match the hashed MRML node")
    reject_placeholder(
        source.get("moving_volume_node_name"),
        "transform_source.moving_volume_node_name",
    )
    reject_placeholder(
        source.get("fixed_volume_node_name"),
        "transform_source.fixed_volume_node_name",
    )
    moving_name = source["moving_volume_node_name"].strip()
    fixed_name = source["fixed_volume_node_name"].strip()
    reject_placeholder(source.get("binding_id"), "transform_source.binding_id")
    volumes = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "Volume"]
    moving = [element for element in volumes if element.attrib.get("name") == moving_name]
    fixed = [element for element in volumes if element.attrib.get("name") == fixed_name]
    if len(moving) != 1 or len(fixed) != 1:
        raise ValueError("could not uniquely identify moving CT and fixed MRI nodes in MRML")
    if parent_transform_ids(moving[0]) != {transform_id}:
        raise ValueError("configured transform is not the parent of the named moving CT node")
    if parent_transform_ids(fixed[0]):
        raise ValueError("named fixed MRI node has a parent transform")
    scene_moving_path = volume_storage_path(root, moving[0], source_path)
    scene_fixed_path = volume_storage_path(root, fixed[0], source_path)
    if not same_path(scene_moving_path, moving_volume_path):
        raise ValueError(
            "named moving CT storage does not match the CT input: "
            f"scene={scene_moving_path}, input={moving_volume_path.resolve()}"
        )
    if not same_path(scene_fixed_path, fixed_volume_path):
        raise ValueError(
            "named fixed MRI storage does not match output_reference_volume: "
            f"scene={scene_fixed_path}, input={fixed_volume_path.resolve()}"
        )


def validate_config(
    config: dict,
    ct_shape: tuple[int, int, int],
    ct_space: str,
    ct_path: Path,
) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("config schema_version must be 1")
    if config.get("research_only") is not True:
        raise ValueError("config research_only must be true")
    if config.get("status") != "UNVERIFIED_CANDIDATE":
        raise ValueError("config status must be UNVERIFIED_CANDIDATE")
    if config.get("expert_review_required") is not True:
        raise ValueError("expert_review_required must be true")
    reject_placeholder(config.get("subject_id"), "subject_id")
    reject_placeholder(config.get("front_direction_evidence"), "front_direction_evidence")
    reject_placeholder(config.get("inferior_direction_evidence"), "inferior_direction_evidence")
    reject_placeholder(
        config.get("voxel_ray_alignment_justification"),
        "voxel_ray_alignment_justification",
    )
    reject_placeholder(config.get("anatomical_definition"), "anatomical_definition")
    if config.get("physical_units") != "mm":
        raise ValueError("physical_units must explicitly be mm")
    reject_placeholder(config.get("physical_units_evidence"), "physical_units_evidence")
    if config.get("ct_intensity_units") != "HU":
        raise ValueError("ct_intensity_units must explicitly be HU")
    reject_placeholder(config.get("ct_hu_calibration_evidence"), "ct_hu_calibration_evidence")
    expected_space = normalized_space(config.get("ct_space_expected"))
    if expected_space != ct_space:
        raise ValueError(f"CT space mismatch: config={expected_space!r}, header={ct_space!r}")

    ray_axis = config.get("ray_axis")
    inferior_axis = config.get("inferior_axis")
    if isinstance(ray_axis, bool) or ray_axis not in (0, 1, 2):
        raise ValueError("ray_axis must be 0, 1, or 2")
    if (
        isinstance(inferior_axis, bool)
        or inferior_axis not in (0, 1, 2)
        or inferior_axis == ray_axis
    ):
        raise ValueError("inferior_axis must be a non-ray axis")
    if config.get("front_index_direction") not in ("high_to_low", "low_to_high"):
        raise ValueError("front_index_direction must be high_to_low or low_to_high")
    if config.get("inferior_index_direction") not in ("low", "high"):
        raise ValueError("inferior_index_direction must be low or high")

    threshold = config.get("bone_threshold_hu")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not np.isfinite(float(threshold))
    ):
        raise ValueError("bone_threshold_hu must be a finite number")
    depth_thresholds = config.get("depth_thresholds_index")
    if not isinstance(depth_thresholds, list) or len(depth_thresholds) < 3:
        raise ValueError("depth_thresholds_index must contain at least three values")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in depth_thresholds):
        raise ValueError("depth thresholds must be exact JSON integers")
    if len(set(depth_thresholds)) < 3:
        raise ValueError("depth_thresholds_index must contain at least three distinct values")
    if any(value < 0 or value >= ct_shape[ray_axis] for value in depth_thresholds):
        raise ValueError("a depth threshold lies outside the ray-axis index range")
    quantile = config.get("boundary_quantile")
    if (
        isinstance(quantile, bool)
        or not isinstance(quantile, (int, float))
        or not np.isfinite(float(quantile))
        or not 0 < float(quantile) < 0.5
    ):
        raise ValueError("boundary_quantile must be between 0 and 0.5")
    if isinstance(config.get("rim_offset_index"), bool) or not isinstance(
        config.get("rim_offset_index"), int
    ):
        raise ValueError("rim_offset_index must be an integer")
    if (
        isinstance(config.get("minimum_component_voxels"), bool)
        or not isinstance(config.get("minimum_component_voxels"), int)
        or config["minimum_component_voxels"] < 10
    ):
        raise ValueError("minimum_component_voxels must be an integer >= 10")

    plane_axes = [axis for axis in (0, 1, 2) if axis != ray_axis]
    sides = config.get("sides")
    if not isinstance(sides, dict) or set(sides) != set(SIDE_NAMES):
        raise ValueError(f"sides must contain exactly {SIDE_NAMES}")
    for side_name in SIDE_NAMES:
        side = sides[side_name]
        raw_roi_min = side.get("plane_roi_min_inclusive")
        raw_roi_max = side.get("plane_roi_max_exclusive")
        raw_seed = side.get("component_seed_in_plane")
        if any(
            not isinstance(value, list)
            or len(value) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
            for value in (raw_roi_min, raw_roi_max, raw_seed)
        ):
            raise ValueError(f"{side_name} ROI and seed values must be exact JSON integers")
        roi_min = np.asarray(raw_roi_min, dtype=int)
        roi_max = np.asarray(raw_roi_max, dtype=int)
        seed = np.asarray(raw_seed, dtype=int)
        if roi_min.shape != (2,) or roi_max.shape != (2,) or seed.shape != (2,):
            raise ValueError(f"{side_name} ROI and seed must each contain two indices")
        plane_shape = np.asarray([ct_shape[axis] for axis in plane_axes], dtype=int)
        if np.any(roi_min < 0) or np.any(roi_max > plane_shape) or np.any(roi_min >= roi_max):
            raise ValueError(f"{side_name} ROI is invalid for plane shape {plane_shape.tolist()}")
        if np.any(seed < roi_min) or np.any(seed >= roi_max):
            raise ValueError(f"{side_name} component seed lies outside its ROI")

    if config.get("transform_direction") != "CT_NATIVE_RAS_TO_OUTPUT_RAS":
        raise ValueError("transform_direction must be CT_NATIVE_RAS_TO_OUTPUT_RAS")
    matrix = np.asarray(config.get("ct_native_ras_to_output_ras_4x4"), dtype=float)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError("ct_native_ras_to_output_ras_4x4 must be a finite 4x4 matrix")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-9):
        raise ValueError("transform matrix last row must be [0,0,0,1]")
    if config.get("matrix_must_be_proper_rigid") is not True:
        raise ValueError("matrix_must_be_proper_rigid must be true")
    linear = matrix[:3, :3]
    determinant = float(np.linalg.det(linear))
    orthogonality_error = float(np.linalg.norm(linear.T @ linear - np.eye(3), ord="fro"))
    if determinant <= 0 or abs(determinant - 1.0) > 1e-3 or orthogonality_error > 1e-3:
        raise ValueError(
            "CT-to-output matrix is not a proper rigid transform: "
            f"det={determinant}, orthogonality_error={orthogonality_error}"
        )
    reject_placeholder(config.get("output_space_name"), "output_space_name")
    output_reference = config.get("output_reference_volume")
    output_reference_path = verified_file_record(
        output_reference, "output_reference_volume"
    )
    if output_reference.get("physical_units") != "mm":
        raise ValueError("output_reference_volume.physical_units must be mm")
    reject_placeholder(
        output_reference.get("physical_units_evidence"),
        "output_reference_volume.physical_units_evidence",
    )
    verify_transform_source(
        config,
        matrix,
        moving_volume_path=ct_path,
        fixed_volume_path=output_reference_path,
    )


def make_front_depth(bone: np.ndarray, ray_axis: int, direction: str) -> np.ndarray:
    has_bone = bone.any(axis=ray_axis)
    front = np.full(has_bone.shape, np.nan, dtype=np.float64)
    if direction == "high_to_low":
        first = bone.shape[ray_axis] - 1 - np.argmax(np.flip(bone, axis=ray_axis), axis=ray_axis)
    else:
        first = np.argmax(bone, axis=ray_axis)
    front[has_bone] = first[has_bone]
    return front


def choose_component(
    mask: np.ndarray, seed_local: tuple[int, int], minimum_voxels: int
) -> tuple[np.ndarray, int]:
    labels, count = ndimage.label(mask)
    if count == 0:
        raise RuntimeError("no recessed component found in a configured orbital ROI")
    label_id = int(labels[seed_local])
    if label_id == 0:
        raise RuntimeError(
            "configured component seed is not inside a recessed component; "
            "review the subject-specific ROI, seed, and depth threshold"
        )
    component = labels == label_id
    count_voxels = int(component.sum())
    if count_voxels < minimum_voxels:
        raise RuntimeError(
            f"selected recessed component has {count_voxels} voxels; "
            f"minimum is {minimum_voxels}"
        )
    return component, count_voxels


def candidate_for_threshold(
    front: np.ndarray,
    config: dict,
    side: dict,
    depth_threshold: float,
    plane_axes: list[int],
) -> tuple[np.ndarray, dict]:
    roi_min = np.asarray(side["plane_roi_min_inclusive"], dtype=int)
    roi_max = np.asarray(side["plane_roi_max_exclusive"], dtype=int)
    seed = np.asarray(side["component_seed_in_plane"], dtype=int)
    slices = tuple(slice(int(roi_min[pos]), int(roi_max[pos])) for pos in range(2))
    local_depth = front[slices]
    if config["front_index_direction"] == "high_to_low":
        recessed = np.isfinite(local_depth) & (local_depth < depth_threshold)
    else:
        recessed = np.isfinite(local_depth) & (local_depth > depth_threshold)
    component, component_voxels = choose_component(
        recessed,
        tuple((seed - roi_min).tolist()),
        config["minimum_component_voxels"],
    )

    local_coords = np.asarray(np.where(component)).T
    plane_coords = local_coords + roi_min
    inferior_pos = plane_axes.index(config["inferior_axis"])
    other_pos = 1 - inferior_pos
    boundary: list[tuple[int, int]] = []
    for other_value in np.unique(plane_coords[:, other_pos]):
        inferior_values = plane_coords[plane_coords[:, other_pos] == other_value, inferior_pos]
        if config["inferior_index_direction"] == "low":
            inferior_boundary = int(inferior_values.min())
        else:
            inferior_boundary = int(inferior_values.max())
        boundary.append((int(other_value), inferior_boundary))
    boundary_array = np.asarray(boundary, dtype=int)
    q = float(config["boundary_quantile"])
    if config["inferior_index_direction"] == "low":
        cutoff = float(np.quantile(boundary_array[:, 1], q))
        robust = boundary_array[boundary_array[:, 1] <= cutoff]
    else:
        cutoff = float(np.quantile(boundary_array[:, 1], 1.0 - q))
        robust = boundary_array[boundary_array[:, 1] >= cutoff]
    other_candidate = int(round(float(np.median(robust[:, 0]))))
    inferior_opening = int(round(float(np.median(robust[:, 1]))))
    inferior_bone = inferior_opening + int(config["rim_offset_index"])

    plane_candidate = np.zeros(2, dtype=int)
    plane_candidate[other_pos] = other_candidate
    plane_candidate[inferior_pos] = inferior_bone
    if np.any(plane_candidate < 0) or np.any(plane_candidate >= np.asarray(front.shape)):
        raise RuntimeError("configured rim offset moved a candidate outside the depth map")
    ray_index = front[tuple(plane_candidate)]
    if not np.isfinite(ray_index):
        raise RuntimeError("no front-most bone exists at the configured rim offset")

    ijk = np.zeros(3, dtype=int)
    ijk[config["ray_axis"]] = int(round(float(ray_index)))
    for plane_pos, source_axis in enumerate(plane_axes):
        ijk[source_axis] = int(plane_candidate[plane_pos])
    details = {
        "depth_threshold_index": float(depth_threshold),
        "component_voxels_in_projection": component_voxels,
        "boundary_cutoff_index": cutoff,
        "candidate_native_ct_ijk": ijk.tolist(),
    }
    return ijk, details


def ijk_to_physical(ijk: np.ndarray, origin: np.ndarray, directions: np.ndarray) -> np.ndarray:
    return origin + np.asarray(ijk, dtype=float) @ directions


def physical_to_ras(point: np.ndarray, space: str) -> np.ndarray:
    if space in ("left-posterior-superior", "lps"):
        return np.asarray([-point[0], -point[1], point[2]], dtype=float)
    if space in ("right-anterior-superior", "ras"):
        return np.asarray(point, dtype=float)
    raise ValueError(f"unsupported CT physical space: {space}")


def ras_to_reference_ijk(reference_header: dict, point_ras: np.ndarray) -> np.ndarray:
    reference_space = normalized_space(reference_header.get("space"))
    if reference_space in ("right-anterior-superior", "ras"):
        physical = np.asarray(point_ras, dtype=float)
    elif reference_space in ("left-posterior-superior", "lps"):
        physical = np.asarray([-point_ras[0], -point_ras[1], point_ras[2]], dtype=float)
    else:
        raise ValueError("output reference NRRD must explicitly declare LPS or RAS")
    directions = np.asarray(reference_header.get("space directions"), dtype=float)
    origin = np.asarray(reference_header.get("space origin"), dtype=float)
    sizes = np.asarray(reference_header.get("sizes"), dtype=int)
    if directions.shape != (3, 3) or origin.shape != (3,) or sizes.shape != (3,):
        raise ValueError("output reference NRRD lacks valid 3D geometry")
    ijk = np.linalg.solve(directions.T, physical - origin)
    if np.any(ijk < -0.5) or np.any(ijk > sizes - 0.5):
        raise ValueError(f"mapped candidate lies outside the output reference volume: IJK={ijk}")
    return ijk


def ras_to_lps(point: np.ndarray) -> list[float]:
    return [-float(point[0]), -float(point[1]), float(point[2])]


def physical_distance(delta_ijk: np.ndarray, directions: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(delta_ijk, dtype=float) @ directions))


def choose_medoid(candidates: np.ndarray, directions: np.ndarray) -> int:
    totals = []
    for index, candidate in enumerate(candidates):
        total = sum(physical_distance(candidate - other, directions) for other in candidates)
        totals.append(total)
    return int(np.argmin(totals))


def markups_payload(results: dict, output_space_name: str) -> dict:
    control_points = []
    for index, side_name in enumerate(SIDE_NAMES, start=1):
        ras = np.asarray(results[side_name]["output_world_ras_mm"], dtype=float)
        control_points.append(
            {
                "id": str(index),
                "label": f"CT_orbitale_{side_name}_UNVERIFIED",
                "description": (
                    "CT projection-derived inferior bony orbital-rim search candidate; "
                    "requires native CT and expert review."
                ),
                "associatedNodeID": "",
                "position": ras_to_lps(ras),
                "orientation": [-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0],
                "selected": True,
                "locked": False,
                "visibility": True,
                "positionStatus": "defined",
            }
        )
    return {
        "@schema": "https://raw.githubusercontent.com/slicer/slicer/master/Modules/Loadable/Markups/Resources/Schema/markups-schema-v1.0.3.json#",
        "markups": [
            {
                "type": "Fiducial",
                "coordinateSystem": "LPS",
                "coordinateUnits": "mm",
                "locked": False,
                "fixedNumberOfControlPoints": False,
                "labelFormat": "%N-%d",
                "lastUsedControlPointNumber": 2,
                "controlPoints": control_points,
                "measurements": [],
                "display": {
                    "visibility": True,
                    "opacity": 1.0,
                    "color": [1.0, 0.15, 0.85],
                    "selectedColor": [1.0, 0.85, 0.1],
                    "pointLabelsVisibility": True,
                    "textScale": 2.5,
                    "glyphType": "Sphere3D",
                    "glyphScale": 3.5,
                    "useGlyphScale": True,
                    "sliceProjection": True,
                    "sliceProjectionUseFiducialColor": True,
                    "sliceProjectionOutlinedBehindSlicePlane": True,
                },
                "description": (
                    f"UNVERIFIED CT orbitale candidates in {output_space_name}; "
                    "coordinates already mapped, so use no parent transform."
                ),
            }
        ],
    }


def render_qa(
    path: Path,
    ct: np.ndarray,
    front: np.ndarray,
    results: dict,
    plane_axes: list[int],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def normalized(image: np.ndarray) -> np.ndarray:
        return np.clip((image.astype(np.float32) + 500.0) / 2500.0, 0.0, 1.0)

    fig, axes = plt.subplots(2, 4, figsize=(18, 9), constrained_layout=True)
    for row, side_name in enumerate(SIDE_NAMES):
        ijk = np.asarray(results[side_name]["native_ct_ijk"], dtype=int)
        ax = axes[row, 0]
        ax.imshow(front.T, cmap="turbo", origin="lower")
        plane_point = [ijk[plane_axes[0]], ijk[plane_axes[1]]]
        ax.plot(plane_point[0], plane_point[1], "x", color="white", ms=12, mew=2.5)
        ax.set_title(f"Front-bone depth plane axes {plane_axes}")

        i, j, k = ijk.tolist()
        axes[row, 1].imshow(normalized(ct[i, :, :]).T, cmap="gray", origin="lower")
        axes[row, 1].plot(j, k, "x", color="magenta", ms=12, mew=2.5)
        axes[row, 1].set_title(f"I-index plane i={i}")
        axes[row, 2].imshow(normalized(ct[:, j, :]).T, cmap="gray", origin="lower")
        axes[row, 2].plot(i, k, "x", color="magenta", ms=12, mew=2.5)
        axes[row, 2].set_title(f"J-index plane j={j}")
        axes[row, 3].imshow(normalized(ct[:, :, k]).T, cmap="gray", origin="lower")
        axes[row, 3].plot(i, j, "x", color="magenta", ms=12, mew=2.5)
        axes[row, 3].set_title(f"K-index plane k={k}")
        axes[row, 0].set_ylabel(side_name)
    fig.suptitle(
        "UNVERIFIED native-CT orbitale search candidates\n"
        "Voxel-index planes are not anatomical labels; adjacent slices and 3D expert review remain required"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    for path in (args.ct, args.config):
        if not path.is_file():
            raise FileNotFoundError(path)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    ct, header = nrrd.read(str(args.ct))
    if ct.ndim != 3:
        raise ValueError(f"expected a 3D CT; found shape {ct.shape}")
    ct_space = normalized_space(header.get("space"))
    if ct_space not in ("left-posterior-superior", "lps", "right-anterior-superior", "ras"):
        raise ValueError(f"CT NRRD must explicitly declare LPS or RAS; found {header.get('space')!r}")
    directions = np.asarray(header.get("space directions"), dtype=float)
    origin = np.asarray(header.get("space origin"), dtype=float)
    if directions.shape != (3, 3) or origin.shape != (3,):
        raise ValueError("CT NRRD lacks valid 3D physical geometry")
    if abs(float(np.linalg.det(directions))) < 1e-10:
        raise ValueError("CT space directions are singular")
    header_units = header.get("space units")
    if header_units is not None:
        units = [str(value).strip().lower() for value in header_units]
        if any(value not in ("mm", "millimeter", "millimeters") for value in units):
            raise ValueError(f"CT NRRD physical units are not millimetres: {header_units}")
    validate_config(
        config,
        tuple(int(value) for value in ct.shape),
        ct_space,
        args.ct,
    )

    ray_axis = int(config["ray_axis"])
    plane_axes = [axis for axis in (0, 1, 2) if axis != ray_axis]
    bone = ct >= float(config["bone_threshold_hu"])
    front = make_front_depth(bone, ray_axis, config["front_index_direction"])
    transform = np.asarray(config["ct_native_ras_to_output_ras_4x4"], dtype=float)
    output_reference_path = Path(config["output_reference_volume"]["path"])
    output_reference_header = nrrd.read_header(str(output_reference_path))
    output_reference_sizes = np.asarray(output_reference_header.get("sizes"), dtype=float)
    if output_reference_sizes.shape != (3,) or np.any(output_reference_sizes <= 0):
        raise ValueError("output reference volume must declare three positive voxel dimensions")
    output_reference_units = output_reference_header.get("space units")
    if output_reference_units is not None:
        units = [str(value).strip().lower() for value in output_reference_units]
        if any(value not in ("mm", "millimeter", "millimeters") for value in units):
            raise ValueError(
                f"output reference physical units are not millimetres: {output_reference_units}"
            )

    results: dict[str, dict] = {}
    for side_name in SIDE_NAMES:
        candidates = []
        runs = []
        for depth_threshold in config["depth_thresholds_index"]:
            ijk, details = candidate_for_threshold(
                front, config, config["sides"][side_name], float(depth_threshold), plane_axes
            )
            if float(ct[tuple(ijk)]) < float(config["bone_threshold_hu"]):
                raise RuntimeError(f"{side_name} candidate is not on thresholded bone")
            candidates.append(ijk)
            runs.append(details)
        stack = np.stack(candidates)
        medoid_index = choose_medoid(stack, directions)
        consensus_ijk = stack[medoid_index]
        pairwise = [
            physical_distance(stack[a] - stack[b], directions)
            for a in range(len(stack))
            for b in range(a + 1, len(stack))
        ]
        native_physical = ijk_to_physical(consensus_ijk, origin, directions)
        native_ras = physical_to_ras(native_physical, ct_space)
        output_ras = (transform @ np.r_[native_ras, 1.0])[:3]
        output_reference_ijk = ras_to_reference_ijk(output_reference_header, output_ras)
        if np.any(output_reference_ijk < -0.5) or np.any(
            output_reference_ijk > output_reference_sizes - 0.5
        ):
            raise ValueError(
                f"{side_name} maps outside output_reference_volume; check transform direction"
            )
        results[side_name] = {
            "candidate_status": "UNVERIFIED_CT_DERIVED_RESEARCH_ONLY",
            "native_ct_ijk": consensus_ijk.astype(int).tolist(),
            "native_ct_physical_space": ct_space,
            "native_ct_physical_mm": native_physical.tolist(),
            "native_ct_ras_mm": native_ras.tolist(),
            "output_space_name": config["output_space_name"],
            "output_world_ras_mm": output_ras.tolist(),
            "output_reference_ijk_continuous": output_reference_ijk.tolist(),
            "ct_value_hu_at_candidate_voxel": float(ct[tuple(consensus_ijk)]),
            "consensus_method": "physical-distance medoid of threshold runs",
            "selected_threshold_run_index": medoid_index,
            "multi_threshold_max_pairwise_shift_mm": max(pairwise, default=0.0),
            "threshold_runs": runs,
        }

    linear = transform[:3, :3]
    report = {
        "schema_version": 1,
        "status": "UNVERIFIED_CT_DERIVED_RESEARCH_ONLY",
        "accepted_for_surgical_use": False,
        "subject_id": config["subject_id"],
        "output_space_name": config["output_space_name"],
        "source_ct": str(args.ct.resolve()),
        "source_ct_sha256": sha256(args.ct),
        "config": str(args.config.resolve()),
        "config_sha256": sha256(args.config),
        "method": (
            "Native CT bone threshold, configured front-most-bone depth projection, "
            "bilateral recessed-component selection, robust inferior boundary, and "
            "multi-threshold physical medoid."
        ),
        "plane_axes_after_ray_reduction": plane_axes,
        "ct_native_ras_to_output_ras_4x4": transform.tolist(),
        "transform_direction": config["transform_direction"],
        "transform_source": config["transform_source"],
        "output_reference_volume": config["output_reference_volume"],
        "common_reference_sha256": config["output_reference_volume"]["sha256"],
        "transform_determinant": float(np.linalg.det(linear)),
        "transform_orthogonality_error_fro": float(
            np.linalg.norm(linear.T @ linear - np.eye(3), ord="fro")
        ),
        "configuration": config,
        "results": results,
        "limitations": [
            "Outputs are coordinate-side search candidates; biological laterality is not inferred.",
            "Every ray direction, ROI, seed, threshold, boundary rule, and offset is subject-specific.",
            "Projection and threshold stability measure repeatability of this rule, not orbitale accuracy.",
            "Expert confirmation on native CT adjacent slices and 3D bone rendering is required.",
            "These points do not approve a frame, craniotomy, trajectory, target, or safety margin.",
        ],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    if args.output_markups:
        args.output_markups.parent.mkdir(parents=True, exist_ok=True)
        args.output_markups.write_text(
            json.dumps(
                markups_payload(results, config["output_space_name"]),
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
    if args.qa_image:
        render_qa(args.qa_image, ct, front, results, plane_axes)
    print(f"Wrote report: {args.output_json}")
    if args.output_markups:
        print(f"Wrote markups: {args.output_markups}")
    if args.qa_image:
        print(f"Wrote QA preview: {args.qa_image}")
    print("Status: UNVERIFIED CT-derived orbitale search candidates")


if __name__ == "__main__":
    main()
