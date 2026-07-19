#!/usr/bin/env python3
"""Build an unverified origin and orthonormal candidate frame from four RAS points."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np


POINT_NAMES = (
    "ear_coordinate_side_A",
    "ear_coordinate_side_B",
    "orbitale_coordinate_side_A",
    "orbitale_coordinate_side_B",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--slicer-script", type=Path)
    parser.add_argument("--output-markups-dir", type=Path)
    parser.add_argument("--display-axis-length-mm", type=float, default=20.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nonplaceholder(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a text string")
    text = value.strip()
    if not text or text.upper().startswith(
        ("REPLACE", "ABSOLUTE_PATH", "PREDECLARE", "YYYY", "TODO", "TBD")
    ):
        raise ValueError(f"{name} must be completed")
    return text


def valid_sha256(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(char in "0123456789abcdefABCDEF" for char in text)


def require_iso_date(value: object, name: str) -> str:
    text = nonplaceholder(value, name)
    try:
        dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO YYYY-MM-DD date") from exc
    return text


def load_file_record(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be an object")
    path = Path(str(record.get("path", "")))
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{label} path must be an existing absolute file")
    recorded_hash = str(record.get("sha256", "")).strip()
    if not valid_sha256(recorded_hash) or recorded_hash.casefold() != sha256(path).casefold():
        raise ValueError(f"{label} SHA256 does not match the current file")
    return path


def load_json_file_record(record: object, label: str) -> tuple[Path, dict]:
    path = load_file_record(record, label)
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} is not readable JSON: {exc}") from exc


def load_verified_json(record: object, role: str) -> tuple[Path, dict]:
    if not isinstance(record, dict) or record.get("role") != role:
        raise ValueError(f"point_source_reports must contain role {role!r}")
    return load_json_file_record(record, f"{role} report")


def extract_report_points(report: dict, role: str) -> dict[str, np.ndarray]:
    if report.get("schema_version") != 1:
        raise ValueError(f"{role} report schema_version must be 1")
    if report.get("accepted_for_surgical_use") is not False:
        raise ValueError(f"{role} report must explicitly remain unacceptable for surgical use")
    if role == "ear_candidates":
        status = report.get("status")
        if status == "UNVERIFIED_TEMPLATE_SEARCH_SEEDS_NOT_ACCEPTED_FOR_SURGERY":
            values = {}
            for item in report.get("candidate_points", []):
                name = item.get("name")
                if name in ("coordinate_side_A", "coordinate_side_B"):
                    values[f"ear_{name}"] = np.asarray(
                        item.get("subject_slicer_ras_mm"), dtype=float
                    )
        elif status in (
            "UNVERIFIED_MANUAL_CT_BONY_EAM_CANDIDATES",
            "UNVERIFIED_MECHANICAL_EAR_BAR_CONTACT_CANDIDATES",
        ):
            values = {
                f"ear_{name}": np.asarray(item.get("output_world_ras_mm"), dtype=float)
                for name, item in report.get("results", {}).items()
                if name in ("coordinate_side_A", "coordinate_side_B")
            }
        else:
            raise ValueError("ear report status is not a supported bundled ear report")
        expected = {"ear_coordinate_side_A", "ear_coordinate_side_B"}
    else:
        if report.get("status") != "UNVERIFIED_CT_DERIVED_RESEARCH_ONLY":
            raise ValueError("orbitale report status is not a bundled CT-orbitale report")
        values = {
            f"orbitale_{name}": np.asarray(item.get("output_world_ras_mm"), dtype=float)
            for name, item in report.get("results", {}).items()
            if name in ("coordinate_side_A", "coordinate_side_B")
        }
        expected = {"orbitale_coordinate_side_A", "orbitale_coordinate_side_B"}
    if set(values) != expected or any(
        point.shape != (3,) or not np.all(np.isfinite(point)) for point in values.values()
    ):
        raise ValueError(f"{role} report does not contain exactly two finite coordinate-side points")
    return values


def unit(vector: np.ndarray, name: str, minimum_norm: float = 1e-6) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= minimum_norm:
        raise ValueError(f"{name} is degenerate (norm={norm})")
    return vector / norm


def validate_orbitale_review(
    config: dict,
    orbitale_report_record: dict,
    ear_input_policy: str,
) -> tuple[dict, str]:
    _, review = load_json_file_record(
        config.get("orbitale_review_evidence"), "orbitale_review_evidence"
    )
    if review.get("schema_version") != 1:
        raise ValueError("orbitale review schema_version must be 1")
    if review.get("status") != "ORBITALE_CANDIDATE_QA_RECORDED":
        raise ValueError("orbitale review status must be ORBITALE_CANDIDATE_QA_RECORDED")
    if review.get("accepted_for_surgical_use") is not False:
        raise ValueError("orbitale review must remain unacceptable for surgical use")
    if review.get("subject_id") != config.get("subject_id"):
        raise ValueError("orbitale review subject_id does not match")
    review_source = review.get("source_orbitale_report")
    if not isinstance(review_source, dict) or any(
        str(review_source.get(key, "")).casefold()
        != str(orbitale_report_record.get(key, "")).casefold()
        for key in ("path", "sha256")
    ):
        raise ValueError("orbitale review does not bind the frame's orbitale report")
    for key in ("reviewed_by", "role", "date", "evidence"):
        nonplaceholder(review.get(key), f"orbitale_review_evidence.{key}")
    require_iso_date(review.get("date"), "orbitale_review_evidence.date")
    for qa_role in ("native_ct_adjacent_slice_qa", "ct_bone_3d_qa"):
        records = review.get(qa_role)
        if not isinstance(records, list) or not records:
            raise ValueError(f"orbitale review requires at least one {qa_role} artifact")
        for index, record in enumerate(records):
            load_file_record(record, f"orbitale review {qa_role}[{index}]")
    expert_status = review.get("expert_anatomical_review_status")
    if expert_status not in ("PENDING", "REVIEWED_WITHIN_RECORDED_SCOPE"):
        raise ValueError("orbitale expert review status is invalid")
    if expert_status == "PENDING":
        nonplaceholder(
            review.get("unresolved_questions"),
            "orbitale_review_evidence.unresolved_questions",
        )
        if ear_input_policy != "ALLOW_TEMPLATE_SEARCH_SEEDS_FOR_VISUALIZATION_ONLY":
            raise ValueError(
                "CT-bony or mechanical frame candidates require orbitale expert review"
            )
    else:
        nonplaceholder(
            review.get("expert_review_scope"),
            "orbitale_review_evidence.expert_review_scope",
        )
        if str(review.get("unresolved_conflicts", "")).strip():
            raise ValueError("orbitale expert review contains unresolved conflicts")
    return review, expert_status


def validate_and_load(config: dict) -> tuple[dict[str, np.ndarray], bool, dict]:
    if config.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if config.get("research_only") is not True:
        raise ValueError("research_only must be true")
    if config.get("status") != "UNVERIFIED_CANDIDATE":
        raise ValueError("status must be UNVERIFIED_CANDIDATE")
    if config.get("coordinate_system") != "SLICER_RAS_MM":
        raise ValueError("coordinate_system must be SLICER_RAS_MM")
    if config.get("construction_rule") != "INTERAURAL_AXIS_PLUS_ORBITALE_MIDPOINT":
        raise ValueError("unsupported construction_rule")
    ear_input_policy = config.get("ear_input_policy")
    allowed_ear_policies = {
        "REQUIRE_CT_BONY_EAM",
        "REQUIRE_MECHANICAL_EAR_BAR_CONTACT",
        "ALLOW_TEMPLATE_SEARCH_SEEDS_FOR_VISUALIZATION_ONLY",
    }
    if ear_input_policy not in allowed_ear_policies:
        raise ValueError(f"ear_input_policy must be one of {sorted(allowed_ear_policies)}")
    if config.get("expert_review_required") is not True:
        raise ValueError("expert_review_required must be true")
    nonplaceholder(config.get("subject_id"), "subject_id")
    nonplaceholder(config.get("common_space_name"), "common_space_name")
    reports = config.get("point_source_reports")
    if not isinstance(reports, list) or len(reports) != 2:
        raise ValueError("point_source_reports must contain exactly ear and orbitale reports")
    records_by_role = {
        item.get("role"): item for item in reports if isinstance(item, dict)
    }
    if set(records_by_role) != {"ear_candidates", "orbitale_candidates"}:
        raise ValueError("point_source_reports roles must be ear_candidates and orbitale_candidates")
    source_points: dict[str, np.ndarray] = {}
    common_reference_hashes = set()
    ear_report = None
    source_reports = {}
    for role in ("ear_candidates", "orbitale_candidates"):
        _, report = load_verified_json(records_by_role[role], role)
        source_reports[role] = report
        if report.get("subject_id") != config.get("subject_id"):
            raise ValueError(f"{role} report subject_id does not match frame input")
        if report.get("output_space_name") != config.get("common_space_name"):
            raise ValueError(f"{role} report output space does not match common_space_name")
        common_reference_hash = str(report.get("common_reference_sha256", "")).casefold()
        if not valid_sha256(common_reference_hash):
            raise ValueError(f"{role} report lacks a valid common-reference SHA256")
        common_reference_hashes.add(common_reference_hash)
        if role == "ear_candidates":
            ear_report = report
            status = report.get("status")
            expected_status_by_policy = {
                "ALLOW_TEMPLATE_SEARCH_SEEDS_FOR_VISUALIZATION_ONLY": (
                    "UNVERIFIED_TEMPLATE_SEARCH_SEEDS_NOT_ACCEPTED_FOR_SURGERY"
                ),
                "REQUIRE_CT_BONY_EAM": "UNVERIFIED_MANUAL_CT_BONY_EAM_CANDIDATES",
                "REQUIRE_MECHANICAL_EAR_BAR_CONTACT": (
                    "UNVERIFIED_MECHANICAL_EAR_BAR_CONTACT_CANDIDATES"
                ),
            }
            if status != expected_status_by_policy[ear_input_policy]:
                raise ValueError(
                    f"ear report status {status!r} is incompatible with "
                    f"ear_input_policy {ear_input_policy}"
                )
        source_points.update(extract_report_points(report, role))
    if len(common_reference_hashes) != 1:
        raise ValueError("ear and orbitale reports do not reference the same hashed output volume")
    common_reference_hash = next(iter(common_reference_hashes))

    ear_status = (ear_report or {}).get("status")
    if ear_status in (
        "UNVERIFIED_MANUAL_CT_BONY_EAM_CANDIDATES",
        "UNVERIFIED_MECHANICAL_EAR_BAR_CONTACT_CANDIDATES",
    ):
        orbitale_report = source_reports["orbitale_candidates"]
        ear_ct = (ear_report or {}).get("source_ct", {})
        if not isinstance(ear_ct, dict) or not valid_sha256(ear_ct.get("sha256")):
            raise ValueError("CT-based ear report lacks a valid native CT SHA256")
        load_file_record(ear_ct, "CT-based ear source_ct")
        orbitale_ct_record = {
            "path": orbitale_report.get("source_ct"),
            "sha256": orbitale_report.get("source_ct_sha256"),
        }
        load_file_record(orbitale_ct_record, "orbitale source_ct")
        if str(ear_ct.get("sha256", "")).casefold() != str(
            orbitale_report.get("source_ct_sha256", "")
        ).casefold():
            raise ValueError("ear and orbitale reports do not use the same native CT")
        ear_transform_source = (ear_report or {}).get("transform_source", {})
        orbit_transform_source = orbitale_report.get("transform_source", {})
        if not isinstance(ear_transform_source, dict) or not isinstance(
            orbit_transform_source, dict
        ):
            raise ValueError("ear and orbitale reports require structured transform sources")
        for label, source in (
            ("ear", ear_transform_source),
            ("orbitale", orbit_transform_source),
        ):
            load_file_record(source, f"{label} transform_source")
            for key in (
                "node_name",
                "moving_volume_node_name",
                "fixed_volume_node_name",
                "binding_id",
            ):
                nonplaceholder(source.get(key), f"{label} transform_source.{key}")
        for key in (
            "path",
            "sha256",
            "node_name",
            "moving_volume_node_name",
            "fixed_volume_node_name",
            "binding_id",
        ):
            if str(ear_transform_source.get(key, "")).casefold() != str(
                orbit_transform_source.get(key, "")
            ).casefold():
                raise ValueError(f"ear/orbitale transform provenance differs at {key}")
        for label, report in (("ear", ear_report), ("orbitale", orbitale_report)):
            config_record = {
                "path": report.get("config"),
                "sha256": report.get("config_sha256"),
            }
            load_file_record(config_record, f"{label} source configuration")
        ear_matrix = np.asarray(
            (ear_report or {}).get("ct_native_ras_to_output_ras_4x4"), dtype=float
        )
        orbit_matrix = np.asarray(
            orbitale_report.get("ct_native_ras_to_output_ras_4x4"), dtype=float
        )
        if ear_matrix.shape != (4, 4) or orbit_matrix.shape != (4, 4) or not np.allclose(
            ear_matrix, orbit_matrix, atol=1e-7, rtol=0.0
        ):
            raise ValueError("ear and orbitale reports use different CT-to-output matrices")

    orbitale_review, orbitale_expert_status = validate_orbitale_review(
        config,
        records_by_role["orbitale_candidates"],
        ear_input_policy,
    )

    pairing = config.get("side_pairing_evidence")
    if not isinstance(pairing, dict) or pairing.get("status") != (
        "CONFIRMED_SAME_COORDINATE_SIDE_PAIRING"
    ):
        raise ValueError("side_pairing_evidence status is not confirmed")
    for key in ("evidence", "reviewed_by", "role", "date"):
        nonplaceholder(pairing.get(key), f"side_pairing_evidence.{key}")
    require_iso_date(pairing.get("date"), "side_pairing_evidence.date")

    raw_points = config.get("points_ras_mm")
    if not isinstance(raw_points, dict) or set(raw_points) != set(POINT_NAMES):
        raise ValueError(f"points_ras_mm must contain exactly {POINT_NAMES}")
    points: dict[str, np.ndarray] = {}
    for name in POINT_NAMES:
        point = np.asarray(raw_points[name], dtype=float)
        if point.shape != (3,) or not np.all(np.isfinite(point)):
            raise ValueError(f"{name} must be a finite RAS 3-vector")
        if not np.allclose(point, source_points[name], atol=1e-6, rtol=0.0):
            raise ValueError(f"{name} does not match the hashed source report")
        points[name] = point

    signs_confirmed = config.get("biological_axis_signs_confirmed") is True
    if ear_input_policy == "ALLOW_TEMPLATE_SEARCH_SEEDS_FOR_VISUALIZATION_ONLY":
        if signs_confirmed:
            raise ValueError(
                "template search seeds are visualization-only and cannot emit anatomical ML/AP/DV axes"
            )
        if config.get("apparatus_calibrated") is True:
            raise ValueError(
                "template search seeds cannot carry an apparatus-calibration claim"
            )
    if signs_confirmed:
        if config.get("biological_laterality_confirmed") is not True:
            raise ValueError("axis-sign confirmation requires biological laterality confirmation")
        _, sign_evidence = load_json_file_record(
            config.get("axis_sign_evidence"), "axis_sign_evidence"
        )
        if sign_evidence.get("schema_version") != 1:
            raise ValueError("axis_sign_evidence schema_version must be 1")
        if sign_evidence.get("status") != "AXIS_SIGNS_REVIEWED_WITHIN_RECORDED_SCOPE":
            raise ValueError("axis_sign_evidence has the wrong status")
        if sign_evidence.get("accepted_for_surgical_use") is not False:
            raise ValueError("axis_sign_evidence must remain unacceptable for surgical use")
        if sign_evidence.get("subject_id") != config.get("subject_id"):
            raise ValueError("axis_sign_evidence subject_id does not match")
        if sign_evidence.get("ear_input_policy") != ear_input_policy:
            raise ValueError("axis_sign_evidence ear_input_policy does not match")
        if str(sign_evidence.get("common_reference_sha256", "")).casefold() != (
            common_reference_hash
        ):
            raise ValueError("axis_sign_evidence common reference does not match")
        expected_binding_id = (ear_report or {}).get("transform_source", {}).get(
            "binding_id"
        )
        if sign_evidence.get("transform_binding_id") != expected_binding_id:
            raise ValueError("axis_sign_evidence transform binding does not match")
        sign_sources = sign_evidence.get("source_reports")
        if not isinstance(sign_sources, dict) or set(sign_sources) != {
            "ear_candidates",
            "orbitale_candidates",
        }:
            raise ValueError("axis_sign_evidence must bind both source reports")
        for role in ("ear_candidates", "orbitale_candidates"):
            if any(
                str(sign_sources[role].get(key, "")).casefold()
                != str(records_by_role[role].get(key, "")).casefold()
                for key in ("path", "sha256")
            ):
                raise ValueError(f"axis_sign_evidence does not bind {role}")
        sign_orbitale_review = sign_evidence.get("orbitale_review_evidence")
        frame_orbitale_review = config.get("orbitale_review_evidence")
        if not isinstance(sign_orbitale_review, dict) or any(
            str(sign_orbitale_review.get(key, "")).casefold()
            != str(frame_orbitale_review.get(key, "")).casefold()
            for key in ("path", "sha256")
        ):
            raise ValueError("axis_sign_evidence does not bind orbitale review evidence")
        if str(sign_evidence.get("unresolved_conflicts", "")).strip():
            raise ValueError("axis_sign_evidence contains unresolved conflicts")
        _, laterality = load_json_file_record(
            sign_evidence.get("laterality_confirmation"), "laterality_confirmation"
        )
        if laterality.get("schema_version") != 1:
            raise ValueError("laterality confirmation schema_version must be 1")
        if laterality.get("subject_id") != config.get("subject_id"):
            raise ValueError("laterality confirmation subject_id does not match")
        if laterality.get("status") != "CONFIRMED":
            raise ValueError("laterality confirmation status must be CONFIRMED")
        if str(laterality.get("unresolved_conflicts", "")).strip():
            raise ValueError("laterality confirmation contains unresolved conflicts")
        for key in (
            "confirmed_by",
            "role",
            "date",
            "evidence",
            "ct_biological_left_identification",
            "mri_biological_left_identification",
        ):
            nonplaceholder(laterality.get(key), f"laterality_confirmation.{key}")
        require_iso_date(laterality.get("date"), "laterality_confirmation.date")
        for key in ("evidence", "reviewed_by", "role", "date"):
            nonplaceholder(sign_evidence.get(key), f"axis_sign_evidence.{key}")
        require_iso_date(sign_evidence.get("date"), "axis_sign_evidence.date")
        for key in (
            "side_A_to_B_is_positive_ml",
            "ear_mid_to_orbitale_mid_is_positive_ap",
            "cross_product_is_positive_dv",
        ):
            if not isinstance(config.get(key), bool):
                raise ValueError(f"{key} must be true or false")
            if sign_evidence.get(key) is not config.get(key):
                raise ValueError(f"axis_sign_evidence.{key} contradicts frame input")
    if ear_input_policy == "REQUIRE_MECHANICAL_EAR_BAR_CONTACT":
        if config.get("apparatus_calibrated") is not True:
            raise ValueError("mechanical ear contacts require apparatus_calibrated=true")
        _, apparatus_payload = load_json_file_record(
            config.get("apparatus_and_calibration_record"),
            "apparatus_and_calibration_record",
        )
        if apparatus_payload.get("schema_version") != 1:
            raise ValueError("apparatus calibration record schema_version must be 1")
        if apparatus_payload.get("status") != "CALIBRATION_AND_CONTACT_EVIDENCE_REVIEWED":
            raise ValueError("apparatus calibration/contact record has the wrong status")
        if apparatus_payload.get("accepted_for_surgical_use") is not False:
            raise ValueError("apparatus record must remain unacceptable for surgical use")
        if apparatus_payload.get("subject_id") != config.get("subject_id"):
            raise ValueError("apparatus calibration/contact record subject_id does not match")
        if str(apparatus_payload.get("unresolved_conflicts", "")).strip():
            raise ValueError("apparatus calibration/contact record has unresolved conflicts")
        for key in (
            "frame_model_and_identifier",
            "ear_bar_geometry_and_insertion_definition",
            "mechanical_contact_definition",
            "mechanical_contact_derivation_evidence",
            "reviewed_by",
            "role",
            "date",
        ):
            nonplaceholder(apparatus_payload.get(key), f"apparatus record.{key}")
        require_iso_date(apparatus_payload.get("date"), "apparatus record.date")
        calibration = apparatus_payload.get("image_to_apparatus_calibration")
        load_file_record(calibration, "apparatus image_to_apparatus_calibration")
        if calibration.get("transform_direction") not in (
            "APPARATUS_TO_CT_NATIVE",
            "CT_NATIVE_TO_APPARATUS",
        ):
            raise ValueError("apparatus calibration transform_direction is invalid")
        apparatus_points = apparatus_payload.get(
            "mechanical_contact_points_native_ct_ijk"
        )
        if not isinstance(apparatus_points, dict) or set(apparatus_points) != {
            "coordinate_side_A",
            "coordinate_side_B",
        }:
            raise ValueError("apparatus record lacks the two native-CT contact points")
        for side_name in ("coordinate_side_A", "coordinate_side_B"):
            report_point = (ear_report or {}).get("results", {}).get(side_name, {}).get(
                "native_ct_ijk_continuous"
            )
            evidence_point = np.asarray(apparatus_points[side_name], dtype=float)
            if evidence_point.shape != (3,) or not np.all(np.isfinite(evidence_point)):
                raise ValueError(f"apparatus record {side_name} is not a finite IJK point")
            if not np.allclose(
                evidence_point,
                np.asarray(report_point, dtype=float),
                atol=1e-9,
                rtol=0.0,
            ):
                raise ValueError(
                    f"apparatus record {side_name} does not match the mechanical-ear report"
                )
        report_apparatus = (ear_report or {}).get("apparatus_contact_evidence")
        config_apparatus = config.get("apparatus_and_calibration_record")
        if not isinstance(report_apparatus, dict) or any(
            str(report_apparatus.get(key, "")).casefold()
            != str(config_apparatus.get(key, "")).casefold()
            for key in ("path", "sha256")
        ):
            raise ValueError(
                "frame apparatus record does not match the hashed mechanical-ear report"
            )
    elif config.get("apparatus_calibrated") is True:
        raise ValueError(
            "apparatus_calibrated may be true only with REQUIRE_MECHANICAL_EAR_BAR_CONTACT"
        )
    ear_landmark_class = {
        "UNVERIFIED_TEMPLATE_SEARCH_SEEDS_NOT_ACCEPTED_FOR_SURGERY": (
            "TEMPLATE_SEARCH_SEED_ONLY"
        ),
        "UNVERIFIED_MANUAL_CT_BONY_EAM_CANDIDATES": (
            "BONY_EAM_ANATOMICAL_CANDIDATE"
        ),
        "UNVERIFIED_MECHANICAL_EAR_BAR_CONTACT_CANDIDATES": (
            "MECHANICAL_EAR_BAR_CONTACT_CANDIDATE"
        ),
    }[ear_status]
    return points, signs_confirmed, {
        "ear_report_status": ear_status,
        "ear_landmark_class": ear_landmark_class,
        "orbitale_review_evidence": config.get("orbitale_review_evidence"),
        "orbitale_expert_review_status": orbitale_expert_status,
        "orbitale_review": orbitale_review,
    }


def angle_degrees(a: np.ndarray, b: np.ndarray) -> float:
    cosine = float(np.clip(abs(np.dot(unit(a, "vector a"), unit(b, "vector b"))), -1.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def make_slicer_script(
    points: dict[str, np.ndarray],
    origin: np.ndarray,
    orbit_mid: np.ndarray,
    axes: dict[str, np.ndarray],
    signs_confirmed: bool,
    axis_length: float,
    common_space: str,
    input_hash: str,
    ear_input_policy: str,
    frame_status: str,
    ear_landmark_class: str,
    orbitale_review_status: str,
) -> str:
    point_literals = {key: tuple(float(v) for v in value) for key, value in points.items()}
    origin_literal = tuple(float(v) for v in origin)
    orbit_literal = tuple(float(v) for v in orbit_mid)
    axis_literals = {key: tuple(float(v) for v in value) for key, value in axes.items()}
    return f'''\
"""Add an unverified cranial-landmark origin and candidate frame to Slicer."""
import slicer
import vtk

POINTS = {point_literals!r}
ORIGIN = {origin_literal!r}
ORBITALE_MID = {orbit_literal!r}
AXES = {axis_literals!r}
AXIS_LENGTH_MM = {float(axis_length)!r}
SIGNS_CONFIRMED = {bool(signs_confirmed)!r}
COMMON_SPACE = {common_space!r}
FRAME_INPUT_SHA256 = {input_hash!r}
EAR_INPUT_POLICY = {ear_input_policy!r}
FRAME_STATUS = {frame_status!r}
EAR_LANDMARK_CLASS = {ear_landmark_class!r}
ORBITALE_EXPERT_REVIEW_STATUS = {orbitale_review_status!r}

def add_point(node, ras, label, description):
    index = node.AddControlPointWorld(vtk.vtkVector3d(*ras), label)
    node.SetNthControlPointDescription(index, description)
    return index

def tag_candidate(node):
    node.SetAttribute("CandidateStatus", FRAME_STATUS)
    node.SetAttribute("EarInputPolicy", EAR_INPUT_POLICY)
    node.SetAttribute("EarLandmarkClass", EAR_LANDMARK_CLASS)
    node.SetAttribute("OrbitaleExpertReviewStatus", ORBITALE_EXPERT_REVIEW_STATUS)
    node.SetAttribute("CoordinateSpace", COMMON_SPACE + "; Slicer world RAS mm; no parent transform")
    node.SetAttribute("FrameInputSHA256", FRAME_INPUT_SHA256)

landmarks = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLMarkupsFiducialNode", "Cranial_Landmark_Candidates_UNVERIFIED"
)
tag_candidate(landmarks)
landmarks.CreateDefaultDisplayNodes()
for name, ras in POINTS.items():
    add_point(landmarks, ras, name, "Candidate source point; requires native anatomy and expert review")
landmarks.GetDisplayNode().SetColor(1.0, 0.3, 0.8)
landmarks.GetDisplayNode().SetPointLabelsVisibility(True)
landmarks.GetDisplayNode().SetGlyphScale(3.0)

midpoints = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLMarkupsFiducialNode", "Cranial_Midpoint_Candidates_UNVERIFIED"
)
tag_candidate(midpoints)
midpoints.CreateDefaultDisplayNodes()
add_point(midpoints, ORIGIN, "ear_midpoint_candidate", "Theoretical origin candidate, not mechanical or surgical zero")
add_point(midpoints, ORBITALE_MID, "orbitale_midpoint_candidate", "Mean of two unverified orbitale candidates")
midpoints.GetDisplayNode().SetColor(0.1, 1.0, 1.0)
midpoints.GetDisplayNode().SetPointLabelsVisibility(True)
midpoints.GetDisplayNode().SetGlyphScale(3.4)

axis_colors = [(0.2, 0.8, 1.0), (1.0, 0.65, 0.1), (0.4, 1.0, 0.3)]
for (name, direction), color in zip(AXES.items(), axis_colors):
    end = tuple(ORIGIN[i] + AXIS_LENGTH_MM * direction[i] for i in range(3))
    line = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLMarkupsLineNode", name + "_UNVERIFIED"
    )
    tag_candidate(line)
    line.SetAttribute("AxisSignsConfirmed", str(SIGNS_CONFIRMED).lower())
    line.CreateDefaultDisplayNodes()
    line.AddControlPointWorld(vtk.vtkVector3d(*ORIGIN), "origin")
    line.AddControlPointWorld(vtk.vtkVector3d(*end), name)
    line.GetDisplayNode().SetColor(*color)
    line.GetDisplayNode().SetPointLabelsVisibility(False)

connector = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLMarkupsLineNode", "EarMid_to_OrbitaleMid_UNVERIFIED"
)
tag_candidate(connector)
connector.CreateDefaultDisplayNodes()
connector.AddControlPointWorld(vtk.vtkVector3d(*ORIGIN), "ear_mid")
connector.AddControlPointWorld(vtk.vtkVector3d(*ORBITALE_MID), "orbitale_mid")
connector.GetDisplayNode().SetColor(1.0, 1.0, 0.2)
connector.GetDisplayNode().SetPointLabelsVisibility(False)

try:
    slicer.modules.markups.logic().JumpSlicesToLocation(*ORIGIN, True)
except Exception as exc:
    print(f"Nodes added; slice centering unavailable: {{exc}}")

print("Added UNVERIFIED cranial landmark/frame candidates; scene was not saved.")
'''


def ras_to_lps(point: np.ndarray) -> list[float]:
    return [-float(point[0]), -float(point[1]), float(point[2])]


def control_point(identifier: int, label: str, point_ras: np.ndarray, description: str) -> dict:
    return {
        "id": str(identifier),
        "label": label,
        "description": description,
        "associatedNodeID": "",
        "position": ras_to_lps(point_ras),
        "orientation": [-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0],
        "selected": True,
        "locked": False,
        "visibility": True,
        "positionStatus": "defined",
    }


def save_markup(path: Path, markup_type: str, points: list[dict], color: list[float], description: str) -> None:
    payload = {
        "@schema": "https://raw.githubusercontent.com/slicer/slicer/master/Modules/Loadable/Markups/Resources/Schema/markups-schema-v1.0.3.json#",
        "markups": [
            {
                "type": markup_type,
                "coordinateSystem": "LPS",
                "coordinateUnits": "mm",
                "locked": False,
                "fixedNumberOfControlPoints": markup_type == "Line",
                "labelFormat": "%N-%d",
                "lastUsedControlPointNumber": len(points),
                "controlPoints": points,
                "measurements": [],
                "description": description,
                "display": {
                    "visibility": True,
                    "opacity": 1.0,
                    "color": color,
                    "selectedColor": [1.0, 1.0, 0.0],
                    "pointLabelsVisibility": markup_type == "Fiducial",
                    "glyphType": "Sphere3D",
                    "glyphScale": 3.0,
                    "useGlyphScale": True,
                    "sliceProjection": True,
                    "lineThickness": 0.5,
                },
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def write_markups_directory(
    output_dir: Path,
    points: dict[str, np.ndarray],
    origin: np.ndarray,
    orbit_mid: np.ndarray,
    axes: dict[str, np.ndarray],
    axis_length: float,
    common_space: str,
    input_hash: str,
    ear_input_policy: str,
    frame_status: str,
    ear_landmark_class: str,
    orbitale_review_status: str,
) -> list[str]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(
            f"output-markups-dir must be new or empty to prevent stale competing axes: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = (
        f"{frame_status}; EarInputPolicy={ear_input_policy}; "
        f"EarLandmarkClass={ear_landmark_class}; "
        f"OrbitaleExpertReviewStatus={orbitale_review_status}; "
        f"space={common_space}; Slicer world RAS mm; no parent transform; "
        f"frame input SHA256={input_hash}."
    )
    fiducials = [
        control_point(index, name, point, "Candidate source point; expert review required")
        for index, (name, point) in enumerate(points.items(), start=1)
    ]
    fiducials.extend(
        [
            control_point(5, "ear_midpoint_candidate", origin, "Not mechanical or surgical zero"),
            control_point(6, "orbitale_midpoint_candidate", orbit_mid, "Mean of orbitale candidates"),
        ]
    )
    paths = [output_dir / "cranial_landmarks_and_midpoints_UNVERIFIED.mrk.json"]
    save_markup(paths[0], "Fiducial", fiducials, [1.0, 0.3, 0.8], provenance)
    colors = ([0.2, 0.8, 1.0], [1.0, 0.65, 0.1], [0.4, 1.0, 0.3])
    for (name, direction), color in zip(axes.items(), colors):
        end = origin + axis_length * direction
        axis_path = output_dir / f"{name}_UNVERIFIED.mrk.json"
        save_markup(
            axis_path,
            "Line",
            [
                control_point(1, "origin", origin, provenance),
                control_point(2, name, end, provenance),
            ],
            list(color),
            provenance,
        )
        paths.append(axis_path)
    connector_path = output_dir / "ear_mid_to_orbitale_mid_UNVERIFIED.mrk.json"
    save_markup(
        connector_path,
        "Line",
        [
            control_point(1, "ear_midpoint_candidate", origin, provenance),
            control_point(2, "orbitale_midpoint_candidate", orbit_mid, provenance),
        ],
        [1.0, 1.0, 0.2],
        provenance,
    )
    paths.append(connector_path)
    return [str(path) for path in paths]


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    if not np.isfinite(args.display_axis_length_mm) or args.display_axis_length_mm <= 0:
        raise ValueError("display-axis-length-mm must be positive")
    config = json.loads(args.input.read_text(encoding="utf-8"))
    input_hash = sha256(args.input)
    points, signs_confirmed, validation_context = validate_and_load(config)

    ear_a = points["ear_coordinate_side_A"]
    ear_b = points["ear_coordinate_side_B"]
    orbit_a = points["orbitale_coordinate_side_A"]
    orbit_b = points["orbitale_coordinate_side_B"]
    origin = (ear_a + ear_b) / 2.0
    orbit_mid = (orbit_a + orbit_b) / 2.0
    ear_pair = ear_b - ear_a
    orbit_pair = orbit_b - orbit_a
    ear_axis_raw = unit(ear_pair, "inter-ear vector", minimum_norm=1.0)
    forward = orbit_mid - origin
    forward_projected = forward - np.dot(forward, ear_axis_raw) * ear_axis_raw
    forward_axis_raw = unit(
        forward_projected, "ear-midpoint to orbitale-midpoint projection", minimum_norm=1.0
    )
    normal_raw = unit(np.cross(ear_axis_raw, forward_axis_raw), "candidate plane normal")

    if signs_confirmed:
        ml = ear_axis_raw if config["side_A_to_B_is_positive_ml"] else -ear_axis_raw
        ap = forward_axis_raw if config["ear_mid_to_orbitale_mid_is_positive_ap"] else -forward_axis_raw
        cross = unit(np.cross(ml, ap), "signed ML/AP cross product")
        dv = cross if config["cross_product_is_positive_dv"] else -cross
        axes = {"ML_axis_candidate": ml, "AP_axis_candidate": ap, "DV_axis_candidate": dv}
        label_mode = "ANATOMICAL_AXIS_NAMES_WITH_RECORDED_SIGN_EVIDENCE"
    else:
        axes = {
            "side_A_to_B_axis_candidate": ear_axis_raw,
            "ear_mid_to_orbitale_mid_axis_candidate": forward_axis_raw,
            "plane_normal_candidate": normal_raw,
        }
        label_mode = "NEUTRAL_AXIS_NAMES_SIGNS_UNCONFIRMED"

    basis = np.column_stack(list(axes.values()))
    orthogonality = basis.T @ basis
    basis_determinant = float(np.linalg.det(basis))
    if signs_confirmed and abs(basis_determinant - 1.0) > 1e-6:
        raise ValueError(
            "confirmed anatomical axes would form a reflected/non-right-handed basis; "
            "resolve the sign convention before naming ML/AP/DV"
        )
    plane_normal = list(axes.values())[2]
    four_points = np.stack([ear_a, ear_b, orbit_a, orbit_b])
    plane_distances = (four_points - origin) @ plane_normal
    if config["ear_input_policy"] == "ALLOW_TEMPLATE_SEARCH_SEEDS_FOR_VISUALIZATION_ONLY":
        frame_status = "UNVERIFIED_TEMPLATE_SEARCH_SEED_FRAME_VISUALIZATION_ONLY"
    else:
        frame_status = "UNVERIFIED_CANDIDATE_FRAME_NOT_ACCEPTED_FOR_SURGERY"
    generated_markups_files = []
    if args.output_markups_dir:
        generated_markups_files = write_markups_directory(
            args.output_markups_dir,
            points,
            origin,
            orbit_mid,
            axes,
            args.display_axis_length_mm,
            config["common_space_name"],
            input_hash,
            config["ear_input_policy"],
            frame_status,
            validation_context["ear_landmark_class"],
            validation_context["orbitale_expert_review_status"],
        )
    report = {
        "schema_version": 1,
        "status": frame_status,
        "accepted_for_surgical_use": False,
        "input": str(args.input.resolve()),
        "input_sha256": input_hash,
        "subject_id": config["subject_id"],
        "coordinate_system": config["coordinate_system"],
        "common_space_name": config["common_space_name"],
        "construction_rule": config["construction_rule"],
        "ear_input_policy": config["ear_input_policy"],
        "ear_report_status": validation_context["ear_report_status"],
        "ear_landmark_class": validation_context["ear_landmark_class"],
        "orbitale_review_evidence": validation_context["orbitale_review_evidence"],
        "orbitale_expert_review_status": validation_context[
            "orbitale_expert_review_status"
        ],
        "source_points_ras_mm": {key: value.tolist() for key, value in points.items()},
        "ear_midpoint_origin_candidate_ras_mm": origin.tolist(),
        "orbitale_midpoint_candidate_ras_mm": orbit_mid.tolist(),
        "ear_midpoint_to_orbitale_midpoint_vector_ras_mm": forward.tolist(),
        "axes": {key: value.tolist() for key, value in axes.items()},
        "axis_label_mode": label_mode,
        "biological_laterality_confirmed": config.get("biological_laterality_confirmed") is True,
        "biological_axis_signs_confirmed": signs_confirmed,
        "axis_sign_evidence": config.get("axis_sign_evidence"),
        "apparatus_calibrated": config.get("apparatus_calibrated") is True,
        "apparatus_and_calibration_record": config.get(
            "apparatus_and_calibration_record", ""
        ),
        "diagnostics": {
            "interear_distance_mm": float(np.linalg.norm(ear_pair)),
            "interorbitale_distance_mm": float(np.linalg.norm(orbit_pair)),
            "ear_to_orbitale_midpoint_distance_mm": float(np.linalg.norm(forward)),
            "orthogonalized_forward_distance_mm": float(np.linalg.norm(forward_projected)),
            "ear_vs_orbitale_pair_unsigned_angle_deg": angle_degrees(ear_pair, orbit_pair),
            "ear_vs_orbitale_pair_signed_unit_dot": float(
                np.dot(unit(ear_pair, "ear pair"), unit(orbit_pair, "orbitale pair"))
            ),
            "basis_gram_matrix": orthogonality.tolist(),
            "basis_orthogonality_error_fro": float(
                np.linalg.norm(orthogonality - np.eye(3), ord="fro")
            ),
            "basis_determinant_handedness": basis_determinant,
            "four_point_plane_signed_distances_mm": plane_distances.tolist(),
            "four_point_plane_rms_mm": float(np.sqrt(np.mean(plane_distances**2))),
        },
        "provenance": config["point_source_reports"],
        "side_pairing_evidence": config["side_pairing_evidence"],
        "generated_markups_files": generated_markups_files,
        "limitations": [
            "The origin is the mean of two candidate ear points, not a verified mechanical or surgical zero.",
            "The construction uses the interaural axis plus orbitale midpoint, not a least-squares four-point plane.",
            "Landmark localization, CT-MRI registration, axis signs, and apparatus calibration have separate uncertainties.",
            "The frame must be rebuilt after any source point or transform change.",
            "Do not use this output alone to choose a craniotomy, trajectory, target, or safety margin.",
        ],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    if args.slicer_script:
        args.slicer_script.parent.mkdir(parents=True, exist_ok=True)
        args.slicer_script.write_text(
            make_slicer_script(
                points,
                origin,
                orbit_mid,
                axes,
                signs_confirmed,
                args.display_axis_length_mm,
                config["common_space_name"],
                input_hash,
                config["ear_input_policy"],
                frame_status,
                validation_context["ear_landmark_class"],
                validation_context["orbitale_expert_review_status"],
            ),
            encoding="utf-8",
        )
    print(f"Wrote report: {args.output_json}")
    if args.output_markups_dir:
        print(f"Wrote {len(generated_markups_files)} markup files: {args.output_markups_dir}")
    if args.slicer_script:
        print(f"Wrote Slicer script: {args.slicer_script}")
    print("Status: unverified candidate frame only")


if __name__ == "__main__":
    main()
