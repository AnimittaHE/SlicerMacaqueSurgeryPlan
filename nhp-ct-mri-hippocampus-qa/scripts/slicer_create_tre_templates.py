"""Create verified undefined Slicer TRE markups from an approved landmark spec.

Set environment variable NHP_TRE_CONFIG to a completed tre-run-config JSON, then
execute this file inside 3D Slicer.
"""

import datetime
import hashlib
import json
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


def load_approved_spec(path):
    with open(path, "r", encoding="utf-8") as stream:
        spec = json.load(stream)
    if spec.get("schema_version") != 1:
        raise RuntimeError("landmark spec schema_version must be 1")
    if spec.get("status") != "APPROVED_FOR_THIS_PROTOCOL":
        raise RuntimeError("landmark spec is not APPROVED_FOR_THIS_PROTOCOL")
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
    landmarks = spec.get("landmarks")
    if not isinstance(landmarks, list) or len(landmarks) < minimum:
        raise RuntimeError("landmark list is shorter than minimum_paired_points")
    labels = []
    for item in landmarks:
        label = str(item.get("label", "")).strip()
        definition = str(item.get("definition", "")).strip()
        side = item.get("side")
        if not label or not definition or "REPLACE" in definition.upper():
            raise RuntimeError("every landmark needs a completed label and definition")
        if side not in ("midline", "biological_left", "biological_right", "unpaired"):
            raise RuntimeError(f"invalid side for {label}: {side}")
        labels.append(label)
    if len(labels) != len(set(labels)):
        raise RuntimeError("landmark labels must be unique")
    return spec


def main(config):
    import slicer
    import vtk

    section = config.get("template", {})
    required = ("landmark_spec", "output_dir", "ct_source", "mri_source")
    missing = [key for key in required if not str(section.get(key, "")).strip()]
    if missing:
        raise RuntimeError(f"template config is missing: {missing}")
    spec_path = os.path.abspath(section["landmark_spec"])
    output_dir = os.path.abspath(section["output_dir"])
    ct_source = os.path.abspath(section["ct_source"])
    mri_source = os.path.abspath(section["mri_source"])
    for path in (spec_path, ct_source, mri_source):
        if not os.path.isfile(path):
            raise RuntimeError(f"required file does not exist: {path}")
    spec = load_approved_spec(spec_path)
    os.makedirs(output_dir, exist_ok=True)
    error_path = os.path.join(output_dir, "TRE_TEMPLATE_ERROR.txt")
    manifest_path = os.path.join(output_dir, "TRE_TEMPLATE_MANIFEST.json")
    for stale in (error_path, manifest_path):
        if os.path.exists(stale):
            os.remove(stale)

    ct_filename = section.get("ct_template_filename", "CT_native_landmarks_UNFILLED.mrk.json")
    mri_filename = section.get("mri_template_filename", "MRI_native_landmarks_UNFILLED.mrk.json")
    ct_output = os.path.join(output_dir, ct_filename)
    mri_output = os.path.join(output_dir, mri_filename)
    labels = [item["label"] for item in spec["landmarks"]]

    def verify_template(path):
        node = slicer.util.loadMarkups(path)
        if not node:
            raise RuntimeError(f"could not reload template: {path}")
        if node.GetTransformNodeID():
            raise RuntimeError(f"template has a parent transform: {path}")
        found = []
        for index in range(node.GetNumberOfControlPoints()):
            found.append(node.GetNthControlPointLabel(index))
            status = node.GetNthControlPointPositionStatus(index)
            if status != slicer.vtkMRMLMarkupsNode.PositionUndefined:
                raise RuntimeError(f"template point is not undefined: {found[-1]}")
        slicer.mrmlScene.RemoveNode(node)
        if found != labels:
            raise RuntimeError(f"template labels changed after reload: {found}")

    def make_template(name, color, expected_source, path):
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", name)
        node.CreateDefaultDisplayNodes()
        node.GetDisplayNode().SetColor(*color)
        node.GetDisplayNode().SetSelectedColor(*color)
        node.SetAttribute("NHPQA.Status", "UNFILLED_INDEPENDENT_TRE_TEMPLATE")
        node.SetAttribute("NHPQA.ExpectedSource", expected_source)
        node.SetAttribute("NHPQA.CoordinatesForCalculation", "Slicer internal world RAS")
        node.SetAttribute("NHPQA.Protocol", spec["protocol_name"])
        for item in spec["landmarks"]:
            index = node.AddControlPoint(vtk.vtkVector3d(0.0, 0.0, 0.0), item["label"])
            node.SetNthControlPointDescription(index, f"side={item['side']}; {item['definition']}")
            node.UnsetNthControlPointPosition(index)
        if not slicer.util.saveNode(node, path):
            raise RuntimeError(f"could not save template: {path}")
        slicer.mrmlScene.RemoveNode(node)
        verify_template(path)

    slicer.mrmlScene.Clear(0)
    make_template("CT_native_landmarks_UNFILLED", (1.0, 0.75, 0.1), ct_source, ct_output)
    make_template("MRI_native_landmarks_UNFILLED", (0.2, 0.65, 1.0), mri_source, mri_output)
    manifest = {
        "schema_version": 1,
        "status": "UNFILLED_INDEPENDENT_TRE_TEMPLATES",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "protocol_name": spec["protocol_name"],
        "approved_by": spec["approved_by"],
        "file_coordinates": "Read each .mrk.json coordinateSystem field; Slicer normally writes LPS.",
        "calculation_coordinates": "Load with Slicer and calculate in internal world RAS.",
        "landmark_spec": {"path": spec_path, "sha256": sha256(spec_path)},
        "sources": {
            "native_ct": {"path": ct_source, "sha256": sha256(ct_source)},
            "native_mri": {"path": mri_source, "sha256": sha256(mri_source)},
        },
        "templates": {
            "ct_blank_template": {"path": ct_output, "sha256": sha256(ct_output)},
            "mri_blank_template": {"path": mri_output, "sha256": sha256(mri_output)},
        },
        "landmarks": spec["landmarks"],
        "warning": "Mark native CT and native MRI independently in separate fresh scenes. Do not view the registered overlay.",
    }
    with open(manifest_path, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    return output_dir


try:
    config_file = config_path()
    with open(config_file, "r", encoding="utf-8") as stream:
        configuration = json.load(stream)
    result_dir = main(configuration)
except Exception:
    try:
        fallback_dir = os.path.abspath(configuration.get("template", {}).get("output_dir", os.getcwd()))
    except Exception:
        fallback_dir = os.getcwd()
    os.makedirs(fallback_dir, exist_ok=True)
    with open(os.path.join(fallback_dir, "TRE_TEMPLATE_ERROR.txt"), "w", encoding="utf-8") as stream:
        stream.write(traceback.format_exc())
    import slicer

    slicer.app.exit(1)
else:
    import slicer

    slicer.app.exit(0)
