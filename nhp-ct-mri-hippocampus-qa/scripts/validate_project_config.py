#!/usr/bin/env python3
"""Validate a research-only NHP CT/MRI project configuration."""

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
from pathlib import Path


PLACEHOLDER_PREFIXES = (
    "REPLACE",
    "ABSOLUTE_PATH",
    "PREDECLARE_",
    "YYYY",
    "TODO",
    "TBD",
)
ALLOWED_STATES = {
    "UNVERIFIED_CANDIDATE",
    "QA_FAILED",
    "RESEARCH_QA_PASS",
    "EXPERT_REVIEWED",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_sha256(value):
    text = str(value or "").strip()
    return len(text) == 64 and all(char in "0123456789abcdefABCDEF" for char in text)


def verified_file_record(record, label, errors, allow_missing_paths=False):
    if not isinstance(record, dict):
        errors.append(f"{label} must be an object with path and sha256")
        return None
    path = Path(str(record.get("path", "")))
    recorded_hash = str(record.get("sha256", "")).strip()
    if not path.is_absolute():
        errors.append(f"{label}.path must be absolute")
        return path
    if not valid_sha256(recorded_hash):
        errors.append(f"{label}.sha256 must be a 64-character SHA256")
    if not path.exists():
        if not allow_missing_paths:
            errors.append(f"{label} does not exist: {path}")
        return path
    if not path.is_file():
        errors.append(f"{label}.path must be a regular file: {path}")
        return path
    if valid_sha256(recorded_hash) and recorded_hash.casefold() != sha256(path).casefold():
        errors.append(f"{label}.sha256 does not match the file")
        return path
    return path


def verified_json_record(record, label, errors, allow_missing_paths=False):
    path = verified_file_record(record, label, errors, allow_missing_paths)
    if path is None or not path.is_file():
        return path, None
    try:
        return path, load_json(path)
    except (OSError, ValueError) as exc:
        errors.append(f"{label} is not readable JSON: {exc}")
        return path, None


def is_placeholder(value):
    if not isinstance(value, str):
        return True
    text = value.strip()
    upper = text.upper()
    return not text or any(upper.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def valid_iso_date(value):
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value.strip())
    except ValueError:
        return False
    return True


def nested(data, *keys):
    value = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise KeyError(".".join(keys))
        value = value[key]
    return value


def validate_axis_sign_payload(
    payload, subject_id, project_laterality, errors, allow_missing_paths=False
):
    if not isinstance(payload, dict):
        errors.append("axis sign evidence payload must be a JSON object")
        return
    if payload.get("schema_version") != 1:
        errors.append("axis sign evidence schema_version must be 1")
    if payload.get("status") != "AXIS_SIGNS_REVIEWED_WITHIN_RECORDED_SCOPE":
        errors.append(
            "axis sign evidence status must be AXIS_SIGNS_REVIEWED_WITHIN_RECORDED_SCOPE"
        )
    if payload.get("accepted_for_surgical_use") is not False:
        errors.append("axis sign evidence must remain unacceptable for surgical use")
    if payload.get("subject_id") != subject_id:
        errors.append("axis sign evidence subject_id does not match project")
    if payload.get("ear_input_policy") not in (
        "REQUIRE_CT_BONY_EAM",
        "REQUIRE_MECHANICAL_EAR_BAR_CONTACT",
    ):
        errors.append("axis sign evidence ear_input_policy is invalid for signed axes")
    if not valid_sha256(payload.get("common_reference_sha256")):
        errors.append("axis sign evidence common_reference_sha256 is invalid")
    if is_placeholder(payload.get("transform_binding_id")):
        errors.append("axis sign evidence transform_binding_id must be completed")
    source_reports = payload.get("source_reports")
    if not isinstance(source_reports, dict) or set(source_reports) != {
        "ear_candidates",
        "orbitale_candidates",
    }:
        errors.append("axis sign evidence must bind ear and orbitale source reports")
    else:
        for role in ("ear_candidates", "orbitale_candidates"):
            _, report = verified_json_record(
                source_reports[role],
                f"axis_sign_evidence.source_reports.{role}",
                errors,
                allow_missing_paths,
            )
            if report is not None and report.get("subject_id") != subject_id:
                errors.append(f"axis sign evidence {role} subject_id does not match")
    verified_json_record(
        payload.get("orbitale_review_evidence"),
        "axis_sign_evidence.orbitale_review_evidence",
        errors,
        allow_missing_paths,
    )
    if str(payload.get("unresolved_conflicts", "")).strip():
        errors.append("axis sign evidence contains unresolved conflicts")
    for key in (
        "side_A_to_B_is_positive_ml",
        "ear_mid_to_orbitale_mid_is_positive_ap",
        "cross_product_is_positive_dv",
    ):
        if not isinstance(payload.get(key), bool):
            errors.append(f"axis sign evidence {key} must be true or false")
    for key in ("evidence", "reviewed_by", "role", "date"):
        if is_placeholder(payload.get(key)):
            errors.append(f"axis sign evidence {key} must be completed")
    if not valid_iso_date(payload.get("date")):
        errors.append("axis sign evidence date must be ISO YYYY-MM-DD")
    _, laterality = verified_json_record(
        payload.get("laterality_confirmation"),
        "axis_sign_evidence.laterality_confirmation",
        errors,
        allow_missing_paths,
    )
    if laterality is None:
        return
    if laterality.get("schema_version") != 1:
        errors.append("axis-sign laterality confirmation schema_version must be 1")
    if laterality.get("subject_id") != subject_id:
        errors.append("axis-sign laterality confirmation subject_id does not match")
    if laterality.get("status") != "CONFIRMED":
        errors.append("axis-sign laterality confirmation status must be CONFIRMED")
    if str(laterality.get("unresolved_conflicts", "")).strip():
        errors.append("axis-sign laterality confirmation contains unresolved conflicts")
    for key in (
        "confirmed_by",
        "role",
        "date",
        "evidence",
        "ct_biological_left_identification",
        "mri_biological_left_identification",
    ):
        if is_placeholder(laterality.get(key)):
            errors.append(f"axis-sign laterality confirmation {key} must be completed")
    if not valid_iso_date(laterality.get("date")):
        errors.append("axis-sign laterality confirmation date must be ISO YYYY-MM-DD")
    for key in (
        "ct_biological_left_identification",
        "mri_biological_left_identification",
    ):
        if laterality.get(key) != project_laterality.get(key):
            errors.append(f"axis-sign laterality confirmation {key} contradicts project")


def validate_module_gate_record(
    record,
    module_name,
    subject_id,
    project_id,
    approved_protocol,
    chosen_transform,
    errors,
    allow_missing_paths=False,
):
    _, payload = verified_json_record(
        record,
        f"qa.module_gate_records.{module_name}",
        errors,
        allow_missing_paths,
    )
    if payload is None:
        return
    if payload.get("schema_version") != 1:
        errors.append(f"{module_name} gate record schema_version must be 1")
    if payload.get("status") != "TECHNICAL_GATE_REVIEWED_FOR_RESEARCH_QA":
        errors.append(
            f"{module_name} gate status must be TECHNICAL_GATE_REVIEWED_FOR_RESEARCH_QA"
        )
    if payload.get("accepted_for_surgical_use") is not False:
        errors.append(f"{module_name} gate must remain unacceptable for surgical use")
    if payload.get("subject_id") != subject_id:
        errors.append(f"{module_name} gate subject_id does not match project")
    if payload.get("project_id") != project_id:
        errors.append(f"{module_name} gate project_id does not match project")
    if payload.get("approved_protocol") != approved_protocol:
        errors.append(f"{module_name} gate approved_protocol does not match project")
    if payload.get("module") != module_name:
        errors.append(f"{module_name} gate record names the wrong module")
    gate_transform = payload.get("locked_transform")
    if not isinstance(gate_transform, dict) or any(
        str(gate_transform.get(key, "")).casefold()
        != str(chosen_transform.get(key, "")).casefold()
        for key in ("path", "sha256", "binding_id")
    ):
        errors.append(f"{module_name} gate does not bind the locked chosen transform")
    if str(payload.get("unresolved_conflicts", "")).strip():
        errors.append(f"{module_name} gate record contains unresolved conflicts")
    for key in ("reviewed_by", "role", "date", "evidence"):
        if is_placeholder(payload.get(key)):
            errors.append(f"{module_name} gate record {key} must be completed")
    if not valid_iso_date(payload.get("date")):
        errors.append(f"{module_name} gate record date must be ISO YYYY-MM-DD")
    source_outputs = payload.get("source_outputs")
    if not isinstance(source_outputs, list) or not source_outputs:
        errors.append(f"{module_name} gate record requires source_outputs")
        return
    for index, source_record in enumerate(source_outputs):
        verified_file_record(
            source_record,
            f"{module_name} gate source_outputs[{index}]",
            errors,
            allow_missing_paths,
        )


def validate_apparatus_payload(
    payload, subject_id, errors, allow_missing_paths=False
):
    if not isinstance(payload, dict):
        errors.append("apparatus calibration/contact payload must be a JSON object")
        return
    if payload.get("schema_version") != 1:
        errors.append("apparatus calibration record schema_version must be 1")
    if payload.get("subject_id") != subject_id:
        errors.append("apparatus calibration record subject_id does not match")
    if payload.get("status") != "CALIBRATION_AND_CONTACT_EVIDENCE_REVIEWED":
        errors.append("apparatus calibration/contact record has the wrong status")
    if payload.get("accepted_for_surgical_use") is not False:
        errors.append("apparatus record must remain unacceptable for surgical use")
    if str(payload.get("unresolved_conflicts", "")).strip():
        errors.append("apparatus calibration/contact record contains unresolved conflicts")
    for key in (
        "frame_model_and_identifier",
        "ear_bar_geometry_and_insertion_definition",
        "mechanical_contact_definition",
        "mechanical_contact_derivation_evidence",
        "reviewed_by",
        "role",
        "date",
    ):
        if is_placeholder(payload.get(key)):
            errors.append(f"apparatus calibration/contact record {key} must be completed")
    if not valid_iso_date(payload.get("date")):
        errors.append("apparatus calibration/contact record date must be ISO YYYY-MM-DD")
    calibration = payload.get("image_to_apparatus_calibration")
    verified_file_record(
        calibration,
        "apparatus image_to_apparatus_calibration",
        errors,
        allow_missing_paths,
    )
    if not isinstance(calibration, dict) or calibration.get("transform_direction") not in (
        "APPARATUS_TO_CT_NATIVE",
        "CT_NATIVE_TO_APPARATUS",
    ):
        errors.append("apparatus calibration transform_direction is invalid")
    points = payload.get("mechanical_contact_points_native_ct_ijk")
    expected_sides = {"coordinate_side_A", "coordinate_side_B"}
    if not isinstance(points, dict) or set(points) != expected_sides:
        errors.append("apparatus record requires exactly two native-CT contact points")
    else:
        for side_name in expected_sides:
            point = points[side_name]
            if (
                not isinstance(point, list)
                or len(point) != 3
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in point
                )
            ):
                errors.append(f"apparatus record {side_name} must be a numeric IJK point")


def validate_orbitale_review_payload(
    payload,
    subject_id,
    source_orbitale_record,
    ear_method,
    errors,
    allow_missing_paths=False,
):
    if not isinstance(payload, dict):
        errors.append("orbitale review payload must be a JSON object")
        return
    if payload.get("schema_version") != 1:
        errors.append("orbitale review schema_version must be 1")
    if payload.get("status") != "ORBITALE_CANDIDATE_QA_RECORDED":
        errors.append("orbitale review has the wrong status")
    if payload.get("accepted_for_surgical_use") is not False:
        errors.append("orbitale review must remain unacceptable for surgical use")
    if payload.get("subject_id") != subject_id:
        errors.append("orbitale review subject_id does not match project")
    review_source = payload.get("source_orbitale_report")
    if not isinstance(review_source, dict) or any(
        str(review_source.get(key, "")).casefold()
        != str(source_orbitale_record.get(key, "")).casefold()
        for key in ("path", "sha256")
    ):
        errors.append("orbitale review does not bind the candidate frame orbitale report")
    for key in ("reviewed_by", "role", "date", "evidence"):
        if is_placeholder(payload.get(key)):
            errors.append(f"orbitale review {key} must be completed")
    if not valid_iso_date(payload.get("date")):
        errors.append("orbitale review date must be ISO YYYY-MM-DD")
    for qa_role in ("native_ct_adjacent_slice_qa", "ct_bone_3d_qa"):
        records = payload.get(qa_role)
        if not isinstance(records, list) or not records:
            errors.append(f"orbitale review requires at least one {qa_role} artifact")
        else:
            for index, record in enumerate(records):
                verified_file_record(
                    record,
                    f"orbitale review {qa_role}[{index}]",
                    errors,
                    allow_missing_paths,
                )
    expert_status = payload.get("expert_anatomical_review_status")
    if expert_status not in ("PENDING", "REVIEWED_WITHIN_RECORDED_SCOPE"):
        errors.append("orbitale expert anatomical review status is invalid")
    elif expert_status == "PENDING":
        if is_placeholder(payload.get("unresolved_questions")):
            errors.append("pending orbitale review requires unresolved_questions")
        if ear_method != "TEMPLATE_MRI_SEARCH_SEED":
            errors.append("CT-bony or mechanical frame requires orbitale expert review")
    else:
        if is_placeholder(payload.get("expert_review_scope")):
            errors.append("reviewed orbitale evidence requires expert_review_scope")
        if str(payload.get("unresolved_conflicts", "")).strip():
            errors.append("orbitale expert review contains unresolved conflicts")


def validate(config, allow_missing_paths=False):
    errors = []
    warnings = []

    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if config.get("research_only") is not True:
        errors.append("research_only must be true")
    status = config.get("status")
    if status not in ALLOWED_STATES:
        errors.append(f"status must be one of {sorted(ALLOWED_STATES)}")
    if allow_missing_paths and status in ("RESEARCH_QA_PASS", "EXPERT_REVIEWED"):
        errors.append(
            "--allow-missing-paths is forbidden for RESEARCH_QA_PASS or EXPERT_REVIEWED"
        )
    if any(word in str(status).upper() for word in ("FINAL", "SURGICAL", "APPROVED")):
        errors.append("automatic final/surgical/approved status is forbidden")

    for key in ("project_id", "subject_id", "species"):
        if is_placeholder(config.get(key)):
            errors.append(f"{key} must be completed")

    modules = config.get("modules")
    if not isinstance(modules, dict):
        errors.append("modules must be an object")
        modules = {}
    else:
        required_modules = (
            "ct_mri_registration",
            "hippocampal_candidate",
            "cranial_landmark_candidates",
            "candidate_stereotactic_frame",
            "independent_tre",
        )
        for module_name in required_modules:
            if not isinstance(modules.get(module_name), bool):
                errors.append(f"modules.{module_name} must be true or false")
        if modules.get("ct_mri_registration") is not True:
            errors.append("modules.ct_mri_registration must be true for this core workflow")
        if modules.get("candidate_stereotactic_frame") and not modules.get(
            "cranial_landmark_candidates"
        ):
            errors.append(
                "candidate_stereotactic_frame requires cranial_landmark_candidates"
            )

    input_paths = {}
    for modality in ("ct", "mri"):
        try:
            item = nested(config, "inputs", modality)
        except KeyError:
            errors.append(f"inputs.{modality} is required")
            continue
        for key in ("path", "format", "series_uid_or_acquisition_id"):
            if is_placeholder(item.get(key)):
                errors.append(f"inputs.{modality}.{key} must be completed")
        raw_path = str(item.get("path", ""))
        if raw_path:
            path = Path(raw_path)
            input_paths[modality] = path
            if not path.is_absolute():
                errors.append(f"inputs.{modality}.path must be absolute")
            elif not allow_missing_paths and not path.exists():
                errors.append(f"inputs.{modality}.path does not exist: {path}")

    registration = config.get("registration", {})
    expected = {
        "fixed_modality": "MRI",
        "moving_modality": "CT",
        "transform_direction": "CT_NATIVE_TO_MRI_NATIVE",
        "default_model": "RIGID_6DOF",
    }
    for key, value in expected.items():
        if registration.get(key) != value:
            errors.append(f"registration.{key} must be {value}")
    for key in ("affine_allowed", "nonlinear_allowed"):
        if not isinstance(registration.get(key), bool):
            errors.append(f"registration.{key} must be true or false")
    if registration.get("affine_allowed") is True and is_placeholder(
        registration.get("affine_justification")
    ):
        errors.append("affine_allowed requires a case-specific justification")
    if registration.get("nonlinear_allowed") is True:
        errors.append("nonlinear registration is not allowed by the core workflow")
    starts = registration.get("minimum_multistarts")
    if not isinstance(starts, int) or starts < 3:
        errors.append("registration.minimum_multistarts must be an integer >= 3")
    if is_placeholder(registration.get("selection_rule")):
        errors.append("registration.selection_rule must be predeclared")
    chosen_transform = registration.get("chosen_transform", {})
    chosen_status = chosen_transform.get("status")
    if chosen_status not in ("NOT_YET_SELECTED", "LOCKED_CANDIDATE"):
        errors.append(
            "registration.chosen_transform.status must be NOT_YET_SELECTED or LOCKED_CANDIDATE"
        )
    if chosen_status == "LOCKED_CANDIDATE":
        chosen_path = Path(str(chosen_transform.get("path", "")))
        if not chosen_path.is_absolute():
            errors.append("registration.chosen_transform.path must be absolute")
        elif not allow_missing_paths and not chosen_path.exists():
            errors.append(f"chosen transform does not exist: {chosen_path}")
        elif chosen_path.exists() and not chosen_path.is_file():
            errors.append("registration.chosen_transform.path must be a regular file")
        chosen_hash = str(chosen_transform.get("sha256", "")).strip()
        if not valid_sha256(chosen_hash):
            errors.append("registration.chosen_transform.sha256 must be a 64-character SHA256")
        elif chosen_path.is_file() and chosen_hash.casefold() != sha256(chosen_path).casefold():
            errors.append("registration.chosen_transform.sha256 does not match the file")
        for key in ("source_node_or_record", "direction_evidence", "binding_id"):
            if is_placeholder(chosen_transform.get(key)):
                errors.append(f"locked chosen transform requires {key}")
    if status in ("RESEARCH_QA_PASS", "EXPERT_REVIEWED") and chosen_status != (
        "LOCKED_CANDIDATE"
    ):
        errors.append(f"{status} requires a locked, hash-verified chosen transform")

    laterality = config.get("laterality", {})
    laterality_status = laterality.get("status")
    if laterality_status not in ("UNCONFIRMED", "CONFIRMED"):
        errors.append("laterality.status must be UNCONFIRMED or CONFIRMED")
    if laterality_status == "CONFIRMED":
        required = (
            "confirmed_by",
            "role",
            "date",
            "evidence",
            "ct_biological_left_identification",
            "mri_biological_left_identification",
        )
        missing = [key for key in required if is_placeholder(laterality.get(key))]
        if missing:
            errors.append(f"confirmed laterality is incomplete: {missing}")
        if not valid_iso_date(laterality.get("date")):
            errors.append("confirmed laterality date must be ISO YYYY-MM-DD")
        if "unresolved_conflicts" not in laterality:
            errors.append("confirmed laterality requires unresolved_conflicts field")
        elif str(laterality.get("unresolved_conflicts", "")).strip():
            errors.append("confirmed laterality contains unresolved conflicts")
    else:
        warnings.append("biological laterality is unconfirmed; anatomical side labels are blocked")

    atlas = config.get("atlas", {})
    atlas_status = atlas.get("status")
    if atlas_status not in (
        "NOT_SELECTED",
        "CANDIDATE_SOURCE_DOCUMENTED",
        "NOT_APPLICABLE_MANUAL_SEGMENTATION",
    ):
        errors.append(
            "atlas.status must be NOT_SELECTED, CANDIDATE_SOURCE_DOCUMENTED, "
            "or NOT_APPLICABLE_MANUAL_SEGMENTATION"
        )
    if atlas_status == "CANDIDATE_SOURCE_DOCUMENTED":
        required = (
            "name",
            "version",
            "species",
            "resolution_mm",
            "in_vivo_or_ex_vivo",
            "source",
            "license",
            "hippocampal_labels",
        )
        missing = [key for key in required if atlas.get(key) in (None, "", [])]
        if missing:
            errors.append(f"documented atlas metadata is incomplete: {missing}")
        if str(atlas.get("species", "")).casefold() != str(config.get("species", "")).casefold():
            if is_placeholder(atlas.get("applicability_justification")):
                errors.append("atlas/subject species mismatch requires explicit applicability justification")
            else:
                warnings.append("atlas/subject species differ; expert applicability review is mandatory")
    if atlas_status == "NOT_APPLICABLE_MANUAL_SEGMENTATION" and is_placeholder(
        atlas.get("applicability_justification")
    ):
        errors.append("manual hippocampal segmentation requires a case-specific justification")
    if modules.get("hippocampal_candidate") and atlas_status == "NOT_SELECTED":
        errors.append(
            "hippocampal_candidate module requires a documented atlas source or "
            "NOT_APPLICABLE_MANUAL_SEGMENTATION"
        )

    cranial = config.get("cranial_landmarks", {})
    manual_ear_payload = None
    cranial_requested = bool(modules.get("cranial_landmark_candidates"))
    allowed_cranial_states = {
        "NOT_REQUESTED",
        "PLANNED",
        "CANDIDATES_GENERATED",
        "EXPERT_REVIEWED",
    }
    if cranial.get("status") not in allowed_cranial_states:
        errors.append(
            f"cranial_landmarks.status must be one of {sorted(allowed_cranial_states)}"
        )
    if cranial.get("accepted_for_surgical_use") is not False:
        errors.append("cranial_landmarks.accepted_for_surgical_use must be false")
    if cranial_requested:
        if cranial.get("status") == "NOT_REQUESTED":
            errors.append("cranial landmark module is enabled but status is NOT_REQUESTED")
        if cranial.get("status") in ("CANDIDATES_GENERATED", "EXPERT_REVIEWED") and (
            chosen_status != "LOCKED_CANDIDATE"
        ):
            errors.append("generated cranial candidates require a locked chosen transform")
        if cranial.get("expert_landmark_review_required") is not True:
            errors.append("cranial landmark candidates require expert landmark review")
        for key in (
            "ear_candidate_method",
            "ear_landmark_operational_definition",
            "orbitale_candidate_method",
            "orbitale_operational_definition",
            "common_point_space",
            "candidate_frame_rule",
        ):
            if is_placeholder(cranial.get(key)) or cranial.get(key) == "NOT_SELECTED":
                errors.append(f"cranial_landmarks.{key} must be completed")
        allowed_ear_methods = {
            "TEMPLATE_MRI_SEARCH_SEED",
            "MANUAL_CT_BONY_EAM",
            "MECHANICAL_EAR_BAR_CONTACT",
        }
        ear_method = cranial.get("ear_candidate_method")
        if ear_method not in allowed_ear_methods:
            errors.append(
                f"cranial_landmarks.ear_candidate_method must be one of {sorted(allowed_ear_methods)}"
            )
        orbitale_config = cranial.get("ct_orbitale_config")
        if cranial.get("orbitale_candidate_method") == "CT_FRONT_DEPTH_PROJECTION":
            if not orbitale_config:
                errors.append("CT orbitale method requires cranial_landmarks.ct_orbitale_config")
            else:
                _, orbitale_payload = verified_json_record(
                    orbitale_config,
                    "cranial_landmarks.ct_orbitale_config",
                    errors,
                    allow_missing_paths,
                )
                if orbitale_payload is not None:
                    if orbitale_payload.get("subject_id") != config.get("subject_id"):
                        errors.append("CT orbitale config subject_id does not match project")
                    source = orbitale_payload.get("transform_source", {})
                    if source.get("binding_id") != chosen_transform.get("binding_id"):
                        errors.append(
                            "CT orbitale config transform binding_id does not match locked chosen transform"
                        )
        elif cranial.get("orbitale_candidate_method") != "NOT_SELECTED":
            errors.append(
                "bundled project validation currently supports CT_FRONT_DEPTH_PROJECTION orbitale candidates"
            )
        if ear_method == "TEMPLATE_MRI_SEARCH_SEED":
            if is_placeholder(cranial.get("ear_template_name_version_hash")):
                errors.append(
                    "template ear search requires cranial_landmarks.ear_template_name_version_hash"
                )
            _, ear_direction_payload = verified_json_record(
                cranial.get("ear_transform_direction_evidence"),
                "cranial_landmarks.ear_transform_direction_evidence",
                errors,
                allow_missing_paths,
            )
            if ear_direction_payload is not None:
                if ear_direction_payload.get("subject_id") != config.get("subject_id"):
                    errors.append("template ear direction evidence subject_id does not match")
                if ear_direction_payload.get("status") != (
                    "CONFIRMED_FOR_SEARCH_SEED_POINT_PROPAGATION"
                ):
                    errors.append("template ear direction evidence has the wrong status")
        elif ear_method in ("MANUAL_CT_BONY_EAM", "MECHANICAL_EAR_BAR_CONTACT"):
            _, manual_ear_payload = verified_json_record(
                cranial.get("manual_ct_ear_config"),
                "cranial_landmarks.manual_ct_ear_config",
                errors,
                allow_missing_paths,
            )
            if manual_ear_payload is not None:
                expected_class = {
                    "MANUAL_CT_BONY_EAM": "BONY_EAM_ANATOMICAL_CANDIDATE",
                    "MECHANICAL_EAR_BAR_CONTACT": (
                        "MECHANICAL_EAR_BAR_CONTACT_CANDIDATE"
                    ),
                }[ear_method]
                if manual_ear_payload.get("subject_id") != config.get("subject_id"):
                    errors.append("manual CT ear config subject_id does not match project")
                if manual_ear_payload.get("landmark_class") != expected_class:
                    errors.append("manual CT ear config landmark_class contradicts ear method")
                source = manual_ear_payload.get("transform_source", {})
                if source.get("binding_id") != chosen_transform.get("binding_id"):
                    errors.append(
                        "manual CT ear config transform binding_id does not match locked chosen transform"
                    )
        if ear_method == "MECHANICAL_EAR_BAR_CONTACT":
            if cranial.get("apparatus_calibrated") is not True:
                errors.append(
                    "mechanical ear-bar contact method requires apparatus_calibrated=true"
                )
            _, apparatus_payload = verified_json_record(
                cranial.get("apparatus_and_calibration_record"),
                "cranial_landmarks.apparatus_and_calibration_record",
                errors,
                allow_missing_paths,
            )
            if apparatus_payload is not None:
                validate_apparatus_payload(
                    apparatus_payload,
                    config.get("subject_id"),
                    errors,
                    allow_missing_paths,
                )
                ear_apparatus = (manual_ear_payload or {}).get(
                    "apparatus_contact_evidence"
                )
                project_apparatus = cranial.get("apparatus_and_calibration_record")
                if not isinstance(ear_apparatus, dict) or any(
                    str(ear_apparatus.get(key, "")).casefold()
                    != str(project_apparatus.get(key, "")).casefold()
                    for key in ("path", "sha256")
                ):
                    errors.append(
                        "project apparatus record does not match the mechanical-ear config"
                    )
        elif cranial.get("apparatus_calibrated") is not False:
            errors.append(
                "apparatus_calibrated may be true only for MECHANICAL_EAR_BAR_CONTACT"
            )
    elif cranial.get("status") != "NOT_REQUESTED":
        warnings.append("cranial landmark module is disabled but its status is not NOT_REQUESTED")

    if modules.get("candidate_stereotactic_frame"):
        if cranial.get("candidate_frame_rule") != "INTERAURAL_AXIS_PLUS_ORBITALE_MIDPOINT":
            errors.append(
                "the bundled candidate-frame script requires "
                "INTERAURAL_AXIS_PLUS_ORBITALE_MIDPOINT"
            )
        frame_input_record = cranial.get("candidate_frame_input")
        frame_input_payload = None
        frame_source_records_by_role = None
        frame_ear_report = None
        if cranial.get("status") in ("CANDIDATES_GENERATED", "EXPERT_REVIEWED"):
            _, frame_input_payload = verified_json_record(
                frame_input_record,
                "cranial_landmarks.candidate_frame_input",
                errors,
                allow_missing_paths,
            )
            if frame_input_payload is not None:
                if frame_input_payload.get("schema_version") != 1:
                    errors.append("candidate frame input schema_version must be 1")
                if frame_input_payload.get("status") != "UNVERIFIED_CANDIDATE":
                    errors.append("candidate frame input status must be UNVERIFIED_CANDIDATE")
                if frame_input_payload.get("subject_id") != config.get("subject_id"):
                    errors.append("candidate frame input subject_id does not match project")
                if frame_input_payload.get("common_space_name") != cranial.get(
                    "common_point_space"
                ):
                    errors.append("candidate frame input common space does not match project")
                if frame_input_payload.get("construction_rule") != cranial.get(
                    "candidate_frame_rule"
                ):
                    errors.append("candidate frame construction rule contradicts project")
                expected_policy = {
                    "TEMPLATE_MRI_SEARCH_SEED": (
                        "ALLOW_TEMPLATE_SEARCH_SEEDS_FOR_VISUALIZATION_ONLY"
                    ),
                    "MANUAL_CT_BONY_EAM": "REQUIRE_CT_BONY_EAM",
                    "MECHANICAL_EAR_BAR_CONTACT": (
                        "REQUIRE_MECHANICAL_EAR_BAR_CONTACT"
                    ),
                }.get(cranial.get("ear_candidate_method"))
                if frame_input_payload.get("ear_input_policy") != expected_policy:
                    errors.append(
                        "candidate frame ear_input_policy contradicts project ear method"
                    )
                source_records = frame_input_payload.get("point_source_reports")
                if not isinstance(source_records, list) or len(source_records) != 2:
                    errors.append("candidate frame input must bind ear and orbitale reports")
                else:
                    by_role = {
                        item.get("role"): item
                        for item in source_records
                        if isinstance(item, dict)
                    }
                    if set(by_role) != {"ear_candidates", "orbitale_candidates"}:
                        errors.append(
                            "candidate frame input report roles must be ear_candidates and orbitale_candidates"
                        )
                    else:
                        frame_source_records_by_role = by_role
                        _, ear_report = verified_json_record(
                            by_role["ear_candidates"],
                            "candidate_frame_input ear report",
                            errors,
                            allow_missing_paths,
                        )
                        _, orbitale_report = verified_json_record(
                            by_role["orbitale_candidates"],
                            "candidate_frame_input orbitale report",
                            errors,
                            allow_missing_paths,
                        )
                        frame_ear_report = ear_report
                        expected_ear_status = {
                            "TEMPLATE_MRI_SEARCH_SEED": (
                                "UNVERIFIED_TEMPLATE_SEARCH_SEEDS_NOT_ACCEPTED_FOR_SURGERY"
                            ),
                            "MANUAL_CT_BONY_EAM": (
                                "UNVERIFIED_MANUAL_CT_BONY_EAM_CANDIDATES"
                            ),
                            "MECHANICAL_EAR_BAR_CONTACT": (
                                "UNVERIFIED_MECHANICAL_EAR_BAR_CONTACT_CANDIDATES"
                            ),
                        }.get(cranial.get("ear_candidate_method"))
                        if ear_report is not None and ear_report.get("status") != expected_ear_status:
                            errors.append("candidate frame ear report contradicts project method")
                        for label, report in (
                            ("ear", ear_report),
                            ("orbitale", orbitale_report),
                        ):
                            if report is not None:
                                if report.get("subject_id") != config.get("subject_id"):
                                    errors.append(f"candidate frame {label} report subject mismatch")
                                if report.get("output_space_name") != cranial.get(
                                    "common_point_space"
                                ):
                                    errors.append(f"candidate frame {label} report space mismatch")
                _, frame_orbitale_review_payload = verified_json_record(
                    frame_input_payload.get("orbitale_review_evidence"),
                    "candidate_frame_input orbitale_review_evidence",
                    errors,
                    allow_missing_paths,
                )
                if (
                    frame_orbitale_review_payload is not None
                    and frame_source_records_by_role is not None
                ):
                    validate_orbitale_review_payload(
                        frame_orbitale_review_payload,
                        config.get("subject_id"),
                        frame_source_records_by_role["orbitale_candidates"],
                        cranial.get("ear_candidate_method"),
                        errors,
                        allow_missing_paths,
                    )
        else:
            warnings.append(
                "candidate frame is planned but no generated frame input is yet required"
            )
        if cranial.get("biological_axis_signs_confirmed"):
            if laterality_status != "CONFIRMED":
                errors.append("confirmed axis signs require confirmed biological laterality")
            _, sign_payload = verified_json_record(
                cranial.get("axis_sign_evidence"),
                "cranial_landmarks.axis_sign_evidence",
                errors,
                allow_missing_paths,
            )
            if sign_payload is not None:
                validate_axis_sign_payload(
                    sign_payload,
                    config.get("subject_id"),
                    laterality,
                    errors,
                    allow_missing_paths,
                )
                if frame_input_payload is not None:
                    frame_sign_record = frame_input_payload.get("axis_sign_evidence")
                    project_sign_record = cranial.get("axis_sign_evidence")
                    if not isinstance(frame_sign_record, dict) or any(
                        str(frame_sign_record.get(key, "")).casefold()
                        != str(project_sign_record.get(key, "")).casefold()
                        for key in ("path", "sha256")
                    ):
                        errors.append(
                            "candidate frame axis-sign evidence does not match project"
                        )
                    if frame_source_records_by_role is not None:
                        sign_sources = sign_payload.get("source_reports", {})
                        for role in ("ear_candidates", "orbitale_candidates"):
                            if not isinstance(sign_sources.get(role), dict) or any(
                                str(sign_sources[role].get(key, "")).casefold()
                                != str(frame_source_records_by_role[role].get(key, "")).casefold()
                                for key in ("path", "sha256")
                            ):
                                errors.append(
                                    f"axis-sign evidence does not bind candidate frame {role}"
                                )
                    if sign_payload.get("ear_input_policy") != frame_input_payload.get(
                        "ear_input_policy"
                    ):
                        errors.append("axis-sign evidence policy does not match frame input")
                    if sign_payload.get("orbitale_review_evidence") != frame_input_payload.get(
                        "orbitale_review_evidence"
                    ):
                        errors.append(
                            "axis-sign evidence orbitale review does not match frame input"
                        )
                    frame_binding_id = (frame_ear_report or {}).get(
                        "transform_source", {}
                    ).get("binding_id")
                    if sign_payload.get("transform_binding_id") != frame_binding_id:
                        errors.append(
                            "axis-sign evidence transform binding does not match frame input"
                        )
                    frame_common_hash = (frame_ear_report or {}).get(
                        "common_reference_sha256"
                    )
                    if str(sign_payload.get("common_reference_sha256", "")).casefold() != str(
                        frame_common_hash or ""
                    ).casefold():
                        errors.append(
                            "axis-sign evidence common reference does not match frame input"
                        )
        else:
            warnings.append(
                "axis signs are unconfirmed; only neutral candidate-axis names may be used"
            )
        if cranial.get("ear_candidate_method") == "TEMPLATE_MRI_SEARCH_SEED":
            if cranial.get("biological_axis_signs_confirmed"):
                errors.append(
                    "template ear search seeds cannot authorize anatomical ML/AP/DV axis names"
                )
            if cranial.get("apparatus_calibrated"):
                errors.append(
                    "template ear search seeds cannot carry an apparatus-calibration claim"
                )
        if not cranial.get("apparatus_calibrated"):
            warnings.append(
                "apparatus is not calibrated; candidate frame is not a mechanical/surgical frame"
            )

    qa = config.get("qa", {})
    for key in ("independent_reviewer_required", "expert_hf_review_required"):
        if not isinstance(qa.get(key), bool):
            errors.append(f"qa.{key} must be true or false")
    if qa.get("independent_reviewer_required") is not True:
        errors.append("qa.independent_reviewer_required must be true")
    if modules.get("hippocampal_candidate") and qa.get("expert_hf_review_required") is not True:
        errors.append("qa.expert_hf_review_required must be true")
    if status in ("RESEARCH_QA_PASS", "EXPERT_REVIEWED") and is_placeholder(
        qa.get("approved_protocol")
    ):
        errors.append(f"{status} requires qa.approved_protocol")
    if status in ("RESEARCH_QA_PASS", "EXPERT_REVIEWED"):
        gate_records = qa.get("module_gate_records")
        if not isinstance(gate_records, dict):
            errors.append(f"{status} requires qa.module_gate_records")
        else:
            for module_name, enabled in modules.items():
                if enabled:
                    validate_module_gate_record(
                        gate_records.get(module_name),
                        module_name,
                        config.get("subject_id"),
                        config.get("project_id"),
                        qa.get("approved_protocol"),
                        chosen_transform,
                        errors,
                        allow_missing_paths,
                    )
    threshold_file = qa.get("tre_thresholds_file")
    if status in ("RESEARCH_QA_PASS", "EXPERT_REVIEWED") and modules.get(
        "independent_tre"
    ) and not threshold_file:
        errors.append(f"{status} with independent_tre requires qa.tre_thresholds_file")
    if threshold_file:
        threshold_path = Path(threshold_file)
        if not threshold_path.is_absolute():
            errors.append("qa.tre_thresholds_file must be absolute")
        elif not allow_missing_paths and not threshold_path.exists():
            errors.append(f"TRE thresholds file does not exist: {threshold_path}")
        elif threshold_path.exists() and not threshold_path.is_file():
            errors.append("qa.tre_thresholds_file must be a regular JSON file")
        elif threshold_path.is_file():
            try:
                thresholds = load_json(threshold_path)
            except (OSError, ValueError) as exc:
                errors.append(f"TRE thresholds file is not readable JSON: {exc}")
            else:
                if thresholds.get("status") != "APPROVED_FOR_THIS_PROTOCOL":
                    errors.append("TRE thresholds file is not APPROVED_FOR_THIS_PROTOCOL")

    expert_review = config.get("expert_review", {})
    expert_status = expert_review.get("status")
    if expert_status not in ("NOT_REVIEWED", "REVIEWED_WITHIN_RECORDED_SCOPE"):
        errors.append(
            "expert_review.status must be NOT_REVIEWED or REVIEWED_WITHIN_RECORDED_SCOPE"
        )
    if status == "EXPERT_REVIEWED":
        if expert_status != "REVIEWED_WITHIN_RECORDED_SCOPE":
            errors.append("EXPERT_REVIEWED requires a reviewed expert_review record")
        required = (
            "reviewed_by",
            "role",
            "date",
            "scope",
            "evidence_record",
            "authorization_basis",
        )
        missing = [key for key in required if is_placeholder(expert_review.get(key))]
        if missing:
            errors.append(f"EXPERT_REVIEWED expert record is incomplete: {missing}")
        if not valid_iso_date(expert_review.get("date")):
            errors.append("EXPERT_REVIEWED date must be ISO YYYY-MM-DD")
    elif expert_status == "REVIEWED_WITHIN_RECORDED_SCOPE":
        warnings.append(
            "an expert review record exists but the overall state is not EXPERT_REVIEWED"
        )

    software = config.get("software", {})
    if is_placeholder(software.get("slicer_version")):
        errors.append("software.slicer_version must be completed")
    slicer_path = Path(str(software.get("slicer_executable", "")))
    if not slicer_path.is_absolute():
        errors.append("software.slicer_executable must be absolute")
    elif not allow_missing_paths and not slicer_path.exists():
        errors.append(f"Slicer executable does not exist: {slicer_path}")

    output_raw = str(config.get("output_dir", ""))
    if is_placeholder(output_raw):
        errors.append("output_dir must be completed")
    else:
        output = Path(output_raw)
        if not output.is_absolute():
            errors.append("output_dir must be absolute")
        for modality, source in input_paths.items():
            try:
                source_resolved = source.resolve(strict=False)
                output_resolved = output.resolve(strict=False)
                if source.is_dir() and os.path.commonpath([source_resolved, output_resolved]) == str(source_resolved):
                    errors.append(f"output_dir must not be inside the {modality} source directory")
                if source_resolved == output_resolved:
                    errors.append(f"output_dir must differ from the {modality} source")
            except (OSError, ValueError):
                warnings.append(f"could not compare output path with {modality} source")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--allow-missing-paths", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    try:
        config = load_json(args.config)
        errors, warnings = validate(config, args.allow_missing_paths)
        report = {
            "status": "PASS" if not errors else "FAIL",
            "config": str(Path(args.config).resolve()),
            "errors": errors,
            "warnings": warnings,
        }
    except Exception as exc:
        report = {"status": "FAIL", "errors": [f"{type(exc).__name__}: {exc}"], "warnings": []}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
