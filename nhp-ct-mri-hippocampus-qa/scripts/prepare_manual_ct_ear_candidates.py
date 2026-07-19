#!/usr/bin/env python3
"""Package expert-marked native-CT ear candidates with transform provenance."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import nrrd
import numpy as np

from derive_ct_orbitale_candidates import (
    normalized_space,
    physical_to_ras,
    ras_to_lps,
    ras_to_reference_ijk,
    reject_placeholder,
    sha256,
    valid_sha256,
    verified_file_record,
    verify_transform_source,
)


SIDE_NAMES = ("coordinate_side_A", "coordinate_side_B")


def verify_nrrd_header_units_mm(header: dict, label: str) -> None:
    units = header.get("space units")
    if units is None:
        return
    normalized = [str(value).strip().lower() for value in units]
    if len(normalized) != 3 or any(
        value not in ("mm", "millimeter", "millimeters") for value in normalized
    ):
        raise ValueError(f"{label} NRRD header physical units are not millimetres: {units}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markups", required=True, type=Path)
    return parser.parse_args()


def verify_review(record: object, label: str) -> dict:
    if not isinstance(record, dict) or record.get("status") != "REVIEWED_AS_UNVERIFIED_CANDIDATE":
        raise ValueError(f"{label}.status must be REVIEWED_AS_UNVERIFIED_CANDIDATE")
    for key in ("reviewed_by", "role", "date", "evidence"):
        reject_placeholder(record.get(key), f"{label}.{key}")
    try:
        dt.date.fromisoformat(record["date"])
    except ValueError as exc:
        raise ValueError(f"{label}.date must be an ISO YYYY-MM-DD date") from exc
    return record


def verify_apparatus_evidence(
    record: object, subject_id: str, expected_points: dict[str, np.ndarray]
) -> dict:
    path = verified_file_record(record, "apparatus_contact_evidence")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("apparatus evidence schema_version must be 1")
    if payload.get("status") != "CALIBRATION_AND_CONTACT_EVIDENCE_REVIEWED":
        raise ValueError("apparatus evidence status is not reviewed")
    if payload.get("accepted_for_surgical_use") is not False:
        raise ValueError("apparatus evidence must remain unacceptable for surgical use")
    if payload.get("subject_id") != subject_id:
        raise ValueError("apparatus evidence subject_id does not match")
    for key in (
        "frame_model_and_identifier",
        "ear_bar_geometry_and_insertion_definition",
        "mechanical_contact_definition",
        "mechanical_contact_derivation_evidence",
        "reviewed_by",
        "role",
        "date",
    ):
        reject_placeholder(payload.get(key), f"apparatus evidence {key}")
    try:
        dt.date.fromisoformat(payload["date"])
    except ValueError as exc:
        raise ValueError("apparatus evidence date must be an ISO YYYY-MM-DD date") from exc
    calibration = payload.get("image_to_apparatus_calibration")
    verified_file_record(calibration, "apparatus image_to_apparatus_calibration")
    if calibration.get("transform_direction") not in (
        "APPARATUS_TO_CT_NATIVE",
        "CT_NATIVE_TO_APPARATUS",
    ):
        raise ValueError("apparatus calibration transform_direction is invalid")
    contact_points = payload.get("mechanical_contact_points_native_ct_ijk")
    if not isinstance(contact_points, dict) or set(contact_points) != set(SIDE_NAMES):
        raise ValueError("apparatus evidence must contain exactly two native-CT contact points")
    for side_name in SIDE_NAMES:
        raw = contact_points[side_name]
        if (
            not isinstance(raw, list)
            or len(raw) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not np.isfinite(float(value))
                for value in raw
            )
        ):
            raise ValueError(f"apparatus evidence {side_name} is not a finite IJK point")
        if not np.allclose(
            np.asarray(raw, dtype=float), expected_points[side_name], atol=1e-9, rtol=0.0
        ):
            raise ValueError(
                f"apparatus evidence {side_name} does not match the configured CT point"
            )
    if str(payload.get("unresolved_conflicts", "")).strip():
        raise ValueError("apparatus evidence contains unresolved conflicts")
    return {"path": str(path), "sha256": sha256(path), "record": payload}


def make_markups(results: dict, output_space: str, source_hash: str) -> dict:
    control_points = []
    for index, side_name in enumerate(SIDE_NAMES, start=1):
        ras = np.asarray(results[side_name]["output_world_ras_mm"], dtype=float)
        control_points.append(
            {
                "id": str(index),
                "label": f"ear_{side_name}_UNVERIFIED",
                "description": (
                    "Expert-marked native-CT ear candidate; review report and apparatus status; "
                    f"config SHA256={source_hash}"
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
                "description": (
                    f"UNVERIFIED expert-marked CT ear candidates in {output_space}; "
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
    if not args.config.is_file():
        raise FileNotFoundError(args.config)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1 or config.get("status") != "UNVERIFIED_CANDIDATE":
        raise ValueError("config must be schema 1 and UNVERIFIED_CANDIDATE")
    if config.get("research_only") is not True or config.get("accepted_for_surgical_use") is not False:
        raise ValueError("config must be research-only and not accepted for surgical use")
    reject_placeholder(config.get("subject_id"), "subject_id")
    subject_id = config["subject_id"].strip()
    landmark_class = config.get("landmark_class")
    if landmark_class not in (
        "BONY_EAM_ANATOMICAL_CANDIDATE",
        "MECHANICAL_EAR_BAR_CONTACT_CANDIDATE",
    ):
        raise ValueError("unsupported landmark_class")
    reject_placeholder(config.get("operational_definition"), "operational_definition")
    expert_review = verify_review(config.get("expert_point_review"), "expert_point_review")

    source_ct = config.get("source_ct")
    ct_path = verified_file_record(source_ct, "source_ct")
    if source_ct.get("physical_units") != "mm":
        raise ValueError("source_ct.physical_units must be mm")
    reject_placeholder(source_ct.get("physical_units_evidence"), "source_ct.physical_units_evidence")
    ct_header = nrrd.read_header(str(ct_path))
    verify_nrrd_header_units_mm(ct_header, "source CT")
    ct_space = normalized_space(ct_header.get("space"))
    if ct_space != normalized_space(source_ct.get("space_expected")):
        raise ValueError("source CT space does not match config")
    directions = np.asarray(ct_header.get("space directions"), dtype=float)
    origin = np.asarray(ct_header.get("space origin"), dtype=float)
    sizes = np.asarray(ct_header.get("sizes"), dtype=int)
    if directions.shape != (3, 3) or origin.shape != (3,) or sizes.shape != (3,):
        raise ValueError("source CT lacks valid 3D physical geometry")
    if abs(float(np.linalg.det(directions))) < 1e-10:
        raise ValueError("source CT directions are singular")

    raw_points = config.get("points_native_ct_ijk")
    if not isinstance(raw_points, dict) or set(raw_points) != set(SIDE_NAMES):
        raise ValueError(f"points_native_ct_ijk must contain exactly {SIDE_NAMES}")
    points = {}
    for side_name in SIDE_NAMES:
        raw = raw_points[side_name]
        if (
            not isinstance(raw, list)
            or len(raw) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not np.isfinite(float(value))
                for value in raw
            )
        ):
            raise ValueError(f"{side_name} must contain three finite native-CT IJK values")
        ijk = np.asarray(raw, dtype=float)
        if np.any(ijk < 0) or np.any(ijk >= sizes):
            raise ValueError(f"{side_name} lies outside the native CT")
        points[side_name] = ijk
    if np.allclose(points[SIDE_NAMES[0]], points[SIDE_NAMES[1]], atol=1e-9, rtol=0.0):
        raise ValueError("bilateral ear candidates must be distinct")

    if config.get("transform_direction") != "CT_NATIVE_RAS_TO_OUTPUT_RAS":
        raise ValueError("transform_direction must be CT_NATIVE_RAS_TO_OUTPUT_RAS")
    matrix = np.asarray(config.get("ct_native_ras_to_output_ras_4x4"), dtype=float)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError("CT-to-output matrix must be a finite 4x4")
    linear = matrix[:3, :3]
    if (
        not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-9)
        or abs(float(np.linalg.det(linear)) - 1.0) > 1e-3
        or float(np.linalg.norm(linear.T @ linear - np.eye(3), ord="fro")) > 1e-3
    ):
        raise ValueError("CT-to-output matrix must be a proper rigid transform")
    output_reference = config.get("output_reference_volume")
    reference_path = verified_file_record(output_reference, "output_reference_volume")
    if output_reference.get("physical_units") != "mm":
        raise ValueError("output reference physical units must be mm")
    reject_placeholder(
        output_reference.get("physical_units_evidence"),
        "output_reference_volume.physical_units_evidence",
    )
    reference_header = nrrd.read_header(str(reference_path))
    verify_nrrd_header_units_mm(reference_header, "output reference")
    verify_transform_source(
        config,
        matrix,
        moving_volume_path=ct_path,
        fixed_volume_path=reference_path,
    )
    reject_placeholder(config.get("output_space_name"), "output_space_name")
    output_space = config["output_space_name"].strip()

    apparatus = None
    if landmark_class == "MECHANICAL_EAR_BAR_CONTACT_CANDIDATE":
        apparatus = verify_apparatus_evidence(
            config.get("apparatus_contact_evidence"), subject_id, points
        )
        status = "UNVERIFIED_MECHANICAL_EAR_BAR_CONTACT_CANDIDATES"
    else:
        if config.get("apparatus_contact_evidence") is not None:
            raise ValueError("bony EAM candidates must not masquerade as apparatus contacts")
        status = "UNVERIFIED_MANUAL_CT_BONY_EAM_CANDIDATES"

    results = {}
    for side_name in SIDE_NAMES:
        ijk = points[side_name]
        native_physical = origin + ijk @ directions
        native_ras = physical_to_ras(native_physical, ct_space)
        output_ras = (matrix @ np.r_[native_ras, 1.0])[:3]
        output_ijk = ras_to_reference_ijk(reference_header, output_ras)
        reference_sizes = np.asarray(reference_header.get("sizes"), dtype=float)
        if reference_sizes.shape != (3,) or np.any(output_ijk < -0.5) or np.any(
            output_ijk > reference_sizes - 0.5
        ):
            raise ValueError(
                f"{side_name} maps outside output_reference_volume; check transform direction"
            )
        results[side_name] = {
            "native_ct_ijk_continuous": ijk.tolist(),
            "native_ct_ijk_nearest_voxel": np.rint(ijk).astype(int).tolist(),
            "native_ct_physical_space": ct_space,
            "native_ct_physical_mm": native_physical.tolist(),
            "native_ct_ras_mm": native_ras.tolist(),
            "output_world_ras_mm": output_ras.tolist(),
            "output_reference_ijk_continuous": output_ijk.tolist(),
        }

    config_hash = sha256(args.config)
    report = {
        "schema_version": 1,
        "status": status,
        "accepted_for_surgical_use": False,
        "subject_id": subject_id,
        "landmark_class": landmark_class,
        "operational_definition": config["operational_definition"],
        "source_ct": source_ct,
        "output_space_name": output_space,
        "output_reference_volume": output_reference,
        "common_reference_sha256": output_reference["sha256"],
        "transform_direction": config["transform_direction"],
        "ct_native_ras_to_output_ras_4x4": matrix.tolist(),
        "transform_source": config["transform_source"],
        "expert_point_review": expert_review,
        "apparatus_contact_evidence": apparatus,
        "config": str(args.config.resolve()),
        "config_sha256": config_hash,
        "results": results,
        "limitations": [
            "Points are expert-marked candidates; this script validates geometry and provenance, not anatomy.",
            "Mapped markups are already in output-world RAS and must have no parent transform.",
            "Bony EAM points are not mechanical contacts unless a hashed apparatus record is supplied.",
            "No candidate authorizes surgery, craniotomy, trajectory, target, or safety margin.",
        ],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markups.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    args.output_markups.write_text(
        json.dumps(
            make_markups(results, output_space, config_hash), indent=2, allow_nan=False
        ),
        encoding="utf-8",
    )
    print(f"Wrote report: {args.output_json}")
    print(f"Wrote markups: {args.output_markups}")
    print(f"Status: {status}")


if __name__ == "__main__":
    main()
