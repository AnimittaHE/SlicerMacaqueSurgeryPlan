#!/usr/bin/env python3
"""Map full-head-template ear-bar-axis seeds into an individual MRI.

Outputs are unverified research search candidates, not bony or mechanical
ear-bar contacts and not surgical coordinates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import h5py
import nrrd
import numpy as np


ALLOWED_EVIDENCE_STATUS = "CONFIRMED_FOR_SEARCH_SEED_POINT_PROPAGATION"
PLACEHOLDER_PREFIXES = (
    "REPLACE",
    "ABSOLUTE_PATH",
    "PREDECLARE",
    "YYYY",
    "TODO",
    "TBD",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map two EBZ-axis template seeds into a subject MRI."
    )
    parser.add_argument("--mri", required=True, type=Path, help="Subject MRI NRRD")
    parser.add_argument("--subject-id", required=True)
    parser.add_argument("--output-space-name", required=True)
    parser.add_argument("--template", required=True, type=Path, help="Full-head template")
    parser.add_argument("--template-version", required=True)
    parser.add_argument("--transform", required=True, type=Path, help="Single-affine ITK H5")
    parser.add_argument("--direction-evidence-json", required=True, type=Path)
    parser.add_argument(
        "--transform-direction",
        required=True,
        choices=("moving-to-fixed", "fixed-to-moving"),
        help="Point-map role of the stored H5; never infer from its filename.",
    )
    parser.add_argument(
        "--template-side-a-ras",
        nargs=3,
        type=float,
        default=(-18.0, 0.0, 0.0),
        metavar=("R", "A", "S"),
    )
    parser.add_argument(
        "--template-side-b-ras",
        nargs=3,
        type=float,
        default=(18.0, 0.0, 0.0),
        metavar=("R", "A", "S"),
    )
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markups", type=Path)
    parser.add_argument(
        "--slicer-script",
        type=Path,
        help="Optional generated Slicer Python script containing the mapped seeds.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_affine(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    with h5py.File(path, "r") as stream:
        if "TransformGroup" not in stream:
            raise ValueError("H5 does not contain TransformGroup")
        groups = list(stream["TransformGroup"].keys())
        if groups != ["0"]:
            raise ValueError(
                f"Expected one affine group named '0'; found {groups}. "
                "Handle composite or nonlinear transforms explicitly."
            )
        group = stream["TransformGroup"]["0"]
        raw_type = np.asarray(group["TransformType"][()]).ravel()[0]
        transform_type = raw_type.decode("utf-8") if isinstance(raw_type, bytes) else str(raw_type)
        if "AffineTransform" not in transform_type:
            raise ValueError(f"Unsupported transform type: {transform_type}")
        parameters = np.asarray(group["TransformParameters"][()], dtype=float)
        center = np.asarray(group["TransformFixedParameters"][()], dtype=float)
    if parameters.size != 12 or center.size != 3:
        raise ValueError("Expected 12 affine parameters and 3 center values")
    matrix = parameters[:9].reshape(3, 3)
    translation = parameters[9:12]
    determinant = float(np.linalg.det(matrix))
    condition = float(np.linalg.cond(matrix))
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(translation)):
        raise ValueError("Affine contains non-finite values")
    if determinant <= 0:
        raise ValueError(f"Affine reflection or singularity detected (det={determinant})")
    if condition > 100:
        raise ValueError(f"Affine is ill-conditioned (condition={condition})")
    return matrix, translation, center, transform_type


def apply_affine(
    point: np.ndarray, matrix: np.ndarray, translation: np.ndarray, center: np.ndarray
) -> np.ndarray:
    return matrix @ (point - center) + center + translation


def invert_affine(
    point: np.ndarray, matrix: np.ndarray, translation: np.ndarray, center: np.ndarray
) -> np.ndarray:
    return np.linalg.solve(matrix, point - center - translation) + center


def ras_to_lps(point: np.ndarray) -> np.ndarray:
    return np.asarray([-point[0], -point[1], point[2]], dtype=float)


def lps_to_ras(point: np.ndarray) -> np.ndarray:
    return np.asarray([-point[0], -point[1], point[2]], dtype=float)


def normalized_space(header: dict) -> str:
    return str(header.get("space", "")).strip().lower().replace("_", "-")


def subject_lps_to_ijk(header: dict, subject_lps: np.ndarray) -> np.ndarray:
    space = normalized_space(header)
    if space in ("left-posterior-superior", "lps"):
        physical = subject_lps
    elif space in ("right-anterior-superior", "ras"):
        physical = lps_to_ras(subject_lps)
    else:
        raise ValueError(
            f"MRI NRRD space must explicitly be LPS or RAS; found {header.get('space')!r}"
        )
    origin = np.asarray(header.get("space origin"), dtype=float)
    raw_directions = np.asarray(header.get("space directions"), dtype=float)
    if origin.shape != (3,) or raw_directions.shape != (3, 3):
        raise ValueError("MRI NRRD lacks a valid 3-vector origin or 3x3 space directions")
    ijk_to_physical = raw_directions.T
    if abs(float(np.linalg.det(ijk_to_physical))) < 1e-8:
        raise ValueError("MRI IJK-to-physical matrix is singular")
    return np.linalg.solve(ijk_to_physical, physical - origin)


def valid_sha256(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(char in "0123456789abcdefABCDEF" for char in text)


def require_completed_text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a text string")
    text = value.strip()
    if not text or text.upper().startswith(PLACEHOLDER_PREFIXES):
        raise ValueError(f"{name} must be completed with case-specific evidence")
    return text


def same_path(first: Path, second: Path) -> bool:
    return str(first.resolve()).casefold() == str(second.resolve()).casefold()


def validate_file_record(record: object, actual_path: Path, role: str) -> dict:
    if not isinstance(record, dict):
        raise ValueError(f"direction evidence {role} must be an object")
    recorded_path = Path(str(record.get("path", "")))
    if not recorded_path.is_absolute() or not same_path(recorded_path, actual_path):
        raise ValueError(f"direction evidence {role} path does not match the current input")
    recorded_hash = str(record.get("sha256", "")).strip()
    if not valid_sha256(recorded_hash) or recorded_hash.casefold() != sha256(actual_path).casefold():
        raise ValueError(f"direction evidence {role} SHA256 does not match the current input")
    return record


def validate_direction_evidence(
    path: Path,
    declared_direction: str,
    subject_id: str,
    mri_path: Path,
    template_path: Path,
    transform_path: Path,
) -> dict:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence.get("schema_version") != 1:
        raise ValueError("direction evidence schema_version must be 1")
    if evidence.get("status") != ALLOWED_EVIDENCE_STATUS:
        raise ValueError(f"direction evidence status must be {ALLOWED_EVIDENCE_STATUS}")
    if evidence.get("subject_id") != subject_id:
        raise ValueError("direction evidence subject_id does not match --subject-id")
    fixed = validate_file_record(evidence.get("fixed_image"), mri_path, "fixed_image")
    moving = validate_file_record(evidence.get("moving_image"), template_path, "moving_image")
    stored_transform = validate_file_record(
        evidence.get("stored_transform"), transform_path, "stored_transform"
    )
    if stored_transform.get("point_map_direction") != declared_direction:
        raise ValueError("direction evidence contradicts --transform-direction")
    resampled = evidence.get("resampled_image")
    if not isinstance(resampled, dict):
        raise ValueError("direction evidence resampled_image must be an object")
    resampled_path = Path(str(resampled.get("path", "")))
    if not resampled_path.is_absolute() or not resampled_path.is_file():
        raise ValueError("direction evidence resampled_image path must exist")
    resampled_hash = str(resampled.get("sha256", ""))
    if not valid_sha256(resampled_hash) or resampled_hash.casefold() != sha256(
        resampled_path
    ).casefold():
        raise ValueError("direction evidence resampled_image SHA256 does not match")
    for image_role, image_record in (("fixed_image", fixed), ("moving_image", moving)):
        if image_record.get("physical_units") != "mm":
            raise ValueError(f"{image_role} physical units must explicitly be mm")
        require_completed_text(
            image_record.get("physical_units_evidence"),
            f"{image_role}.physical_units_evidence",
        )
    for key in ("evidence", "reviewed_by", "role", "date"):
        require_completed_text(evidence.get(key), f"direction_evidence.{key}")
    try:
        dt.date.fromisoformat(evidence["date"])
    except ValueError as exc:
        raise ValueError("direction_evidence.date must be an ISO YYYY-MM-DD date") from exc
    return evidence


def make_slicer_script(
    points_ras: list[np.ndarray], midpoint_ras: np.ndarray, output_space_name: str
) -> str:
    side_a = tuple(float(value) for value in points_ras[0])
    side_b = tuple(float(value) for value in points_ras[1])
    midpoint = tuple(float(value) for value in midpoint_ras)
    return f'''\
"""Add unverified template-propagated ear-axis search seeds to 3D Slicer."""
import slicer
import vtk

SIDE_A_RAS = {side_a!r}
SIDE_B_RAS = {side_b!r}
MIDPOINT_RAS = {midpoint!r}
OUTPUT_SPACE_NAME = {output_space_name!r}

def add_point(node, ras, label, description):
    index = node.AddControlPointWorld(vtk.vtkVector3d(*ras), label)
    node.SetNthControlPointDescription(index, description)
    return index

ears = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLMarkupsFiducialNode", "Ear_Axis_Search_Seeds_UNVERIFIED"
)
ears.SetAttribute("CandidateStatus", "UNVERIFIED_TEMPLATE_SEARCH_SEED_ONLY")
ears.SetAttribute("CoordinateSpace", OUTPUT_SPACE_NAME + "; Slicer world RAS mm; no parent transform")
ears.CreateDefaultDisplayNodes()
add_point(ears, SIDE_A_RAS, "ear_coordinate_side_A", "Template search seed; verify native bony anatomy and apparatus")
add_point(ears, SIDE_B_RAS, "ear_coordinate_side_B", "Template search seed; verify native bony anatomy and apparatus")
ears.GetDisplayNode().SetColor(1.0, 0.35, 0.05)
ears.GetDisplayNode().SetSelectedColor(1.0, 0.75, 0.0)
ears.GetDisplayNode().SetPointLabelsVisibility(True)
ears.GetDisplayNode().SetGlyphScale(2.8)

mid = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLMarkupsFiducialNode", "Ear_Midpoint_Search_Seed_UNVERIFIED"
)
mid.SetAttribute("CandidateStatus", "UNVERIFIED_TEMPLATE_SEARCH_SEED_ONLY")
mid.SetAttribute("CoordinateSpace", OUTPUT_SPACE_NAME + "; Slicer world RAS mm; no parent transform")
mid.CreateDefaultDisplayNodes()
add_point(mid, MIDPOINT_RAS, "ear_midpoint_candidate", "Theoretical midpoint search seed, not mechanical or surgical zero")
mid.GetDisplayNode().SetColor(0.1, 1.0, 1.0)
mid.GetDisplayNode().SetPointLabelsVisibility(True)
mid.GetDisplayNode().SetGlyphScale(3.2)

line = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLMarkupsLineNode", "Ear_Axis_Search_Line_UNVERIFIED"
)
line.SetAttribute("CandidateStatus", "UNVERIFIED_TEMPLATE_SEARCH_SEED_ONLY")
line.CreateDefaultDisplayNodes()
line.AddControlPointWorld(vtk.vtkVector3d(*SIDE_A_RAS), "A")
line.AddControlPointWorld(vtk.vtkVector3d(*SIDE_B_RAS), "B")
line.GetDisplayNode().SetColor(0.2, 0.8, 1.0)
line.GetDisplayNode().SetPointLabelsVisibility(False)

try:
    slicer.modules.markups.logic().JumpSlicesToLocation(*MIDPOINT_RAS, True)
except Exception as exc:
    print(f"Points added; slice centering unavailable: {{exc}}")

print("Added UNVERIFIED template ear-axis search seeds; scene was not saved.")
'''


def make_markups_payload(
    points_ras: list[np.ndarray], midpoint_ras: np.ndarray, output_space_name: str
) -> dict:
    specs = (
        ("ear_coordinate_side_A", points_ras[0], "Template search seed; verify bony anatomy and apparatus"),
        ("ear_coordinate_side_B", points_ras[1], "Template search seed; verify bony anatomy and apparatus"),
        ("ear_midpoint_candidate", midpoint_ras, "Theoretical midpoint search seed, not mechanical or surgical zero"),
    )
    control_points = []
    for index, (label, ras, description) in enumerate(specs, start=1):
        control_points.append(
            {
                "id": str(index),
                "label": label,
                "description": description,
                "associatedNodeID": "",
                "position": ras_to_lps(np.asarray(ras, dtype=float)).tolist(),
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
                "lastUsedControlPointNumber": 3,
                "controlPoints": control_points,
                "measurements": [],
                "description": (
                    f"UNVERIFIED template ear-axis search seeds in {output_space_name}; "
                    "coordinates already mapped, so use no parent transform."
                ),
                "display": {
                    "visibility": True,
                    "opacity": 1.0,
                    "color": [1.0, 0.35, 0.05],
                    "selectedColor": [1.0, 0.75, 0.0],
                    "pointLabelsVisibility": True,
                    "glyphType": "Sphere3D",
                    "glyphScale": 3.0,
                    "useGlyphScale": True,
                    "sliceProjection": True,
                },
            }
        ],
    }


def main() -> None:
    args = parse_args()
    for path in (args.mri, args.template, args.transform, args.direction_evidence_json):
        if not path.is_file():
            raise FileNotFoundError(path)

    header = nrrd.read_header(str(args.mri))
    sizes = np.asarray(header.get("sizes"), dtype=int)
    if sizes.shape != (3,) or np.any(sizes <= 0):
        raise ValueError("MRI NRRD must declare three positive sizes")
    header_units = header.get("space units")
    if header_units is not None:
        normalized_units = [str(value).strip().lower() for value in header_units]
        if any(value not in ("mm", "millimeter", "millimeters") for value in normalized_units):
            raise ValueError(f"MRI NRRD physical units are not millimetres: {header_units}")
    if not str(args.template_version).strip() or str(args.template_version).upper().startswith(
        "REPLACE"
    ):
        raise ValueError("template-version must be completed")
    for value, name in (
        (args.subject_id, "subject-id"),
        (args.output_space_name, "output-space-name"),
    ):
        if not str(value).strip() or str(value).upper().startswith("REPLACE"):
            raise ValueError(f"{name} must be completed")
    direction_evidence = validate_direction_evidence(
        args.direction_evidence_json,
        args.transform_direction,
        args.subject_id,
        args.mri,
        args.template,
        args.transform,
    )
    matrix, translation, center, transform_type = load_affine(args.transform)

    mapped: list[dict] = []
    seed_specs = (
        ("coordinate_side_A", np.asarray(args.template_side_a_ras, dtype=float)),
        ("coordinate_side_B", np.asarray(args.template_side_b_ras, dtype=float)),
    )
    seed_array = np.stack([item[1] for item in seed_specs])
    if not np.all(np.isfinite(seed_array)):
        raise ValueError("template seed coordinates must be finite")
    if np.linalg.norm(seed_array[0] - seed_array[1]) <= 1e-6:
        raise ValueError("template side-A and side-B seeds must be distinct")
    for seed_id, template_ras in seed_specs:
        template_lps = ras_to_lps(template_ras)
        if args.transform_direction == "moving-to-fixed":
            subject_lps = apply_affine(template_lps, matrix, translation, center)
        else:
            subject_lps = invert_affine(template_lps, matrix, translation, center)
        subject_ijk = subject_lps_to_ijk(header, subject_lps)
        if np.any(subject_ijk < -0.5) or np.any(subject_ijk > sizes - 0.5):
            raise ValueError(f"{seed_id} maps outside the MRI volume: IJK={subject_ijk}")
        mapped.append(
            {
                "name": seed_id,
                "template_ras_mm": template_ras.tolist(),
                "subject_lps_mm": subject_lps.tolist(),
                "subject_slicer_ras_mm": lps_to_ras(subject_lps).tolist(),
                "subject_ijk_continuous": subject_ijk.tolist(),
                "subject_ijk_nearest_voxel": np.rint(subject_ijk).astype(int).tolist(),
            }
        )

    point_lps = [np.asarray(item["subject_lps_mm"], dtype=float) for item in mapped]
    midpoint_lps = (point_lps[0] + point_lps[1]) / 2.0
    midpoint_ijk = subject_lps_to_ijk(header, midpoint_lps)
    midpoint_ras = lps_to_ras(midpoint_lps)
    determinant = float(np.linalg.det(matrix))
    orthogonality_error = float(np.linalg.norm(matrix.T @ matrix - np.eye(3), ord="fro"))

    report = {
        "schema_version": 1,
        "status": "UNVERIFIED_TEMPLATE_SEARCH_SEEDS_NOT_ACCEPTED_FOR_SURGERY",
        "accepted_for_surgical_use": False,
        "subject_id": args.subject_id,
        "output_space_name": args.output_space_name,
        "mri": str(args.mri.resolve()),
        "mri_sha256": sha256(args.mri),
        "common_reference_sha256": sha256(args.mri),
        "mri_space": str(header.get("space", "unknown")),
        "template": str(args.template.resolve()),
        "template_sha256": sha256(args.template),
        "template_version": args.template_version,
        "transform": str(args.transform.resolve()),
        "transform_sha256": sha256(args.transform),
        "stored_transform_type": transform_type,
        "declared_transform_direction": args.transform_direction,
        "direction_evidence_json": str(args.direction_evidence_json.resolve()),
        "direction_evidence_sha256": sha256(args.direction_evidence_json),
        "direction_evidence": direction_evidence,
        "affine_determinant": determinant,
        "affine_condition_number": float(np.linalg.cond(matrix)),
        "affine_orthogonality_error_fro": orthogonality_error,
        "candidate_points": mapped,
        "candidate_midpoint_search_seed": {
            "subject_lps_mm": midpoint_lps.tolist(),
            "subject_slicer_ras_mm": midpoint_ras.tolist(),
            "subject_ijk_continuous": midpoint_ijk.tolist(),
            "subject_ijk_nearest_voxel": np.rint(midpoint_ijk).astype(int).tolist(),
        },
        "intercandidate_distance_mm": float(np.linalg.norm(point_lps[0] - point_lps[1])),
        "laterality_note": "Seed identity is preserved as coordinate side A/B; biological laterality is not inferred.",
        "limitations": [
            "Template points are search seeds, not individualized bony EAM or mechanical ear-bar contacts.",
            "Transform-direction evidence must still be reviewed with the resampled template.",
            "Affine scaling/shear changes distances; report it as seed-model sensitivity, not apparatus geometry.",
            "The midpoint alone does not define signed AP/ML/DV axes.",
            "No independent landmark repeatability, frame calibration, or surgical authorization is included.",
        ],
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    mapped_points_ras = [
        np.asarray(item["subject_slicer_ras_mm"], dtype=float) for item in mapped
    ]
    if args.output_markups:
        args.output_markups.parent.mkdir(parents=True, exist_ok=True)
        args.output_markups.write_text(
            json.dumps(
                make_markups_payload(mapped_points_ras, midpoint_ras, args.output_space_name),
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
    if args.slicer_script:
        args.slicer_script.parent.mkdir(parents=True, exist_ok=True)
        args.slicer_script.write_text(
            make_slicer_script(
                mapped_points_ras, midpoint_ras, args.output_space_name
            ),
            encoding="utf-8",
        )

    print(f"Wrote report: {args.output_json}")
    if args.output_markups:
        print(f"Wrote markups: {args.output_markups}")
    if args.slicer_script:
        print(f"Wrote Slicer script: {args.slicer_script}")
    print("Status: unverified template search seeds only")


if __name__ == "__main__":
    main()
