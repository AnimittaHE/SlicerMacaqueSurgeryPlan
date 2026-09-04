"""Generate a reproducible rectangular brain-contact block in 3D Slicer.

Research geometry only. Every output remains UNVERIFIED_CANDIDATE and requires
slice-by-slice mask review plus mechanical and veterinary/neurosurgical review.

Inputs are two opposite rectangle corners and a directed line, all expressed in
3D Slicer world RAS millimetres.  The directed line points from the outside/top
toward the brain.  The rectangle is aligned to a configurable in-plane reference
axis.  Rays are cast from the complete top grid into a binary brain mask.  The
first-hit depth map is converted to an outer envelope, Gaussian-smoothed, and
clamped so that it cannot pass deeper than the raw brain-mask intersection.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import traceback
from pathlib import Path

import numpy as np
import slicer
import vtk
from scipy import ndimage


ALGORITHM_NAME = "Directed rectangular brain-surface contact envelope"
ALGORITHM_VERSION = "1.0.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _canonical_config_hash(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def _canonical_payload_hash(payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def _as_vec3(value, label: str) -> np.ndarray:
    if value is None or len(value) != 3:
        raise ValueError(f"{label} must contain exactly three numeric RAS coordinates")
    vector = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{label} contains a non-finite value")
    return vector


def _unit(vector: np.ndarray, label: str) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length < 1e-8:
        raise ValueError(f"{label} has zero length")
    return vector / length


def _vtk_matrix_to_numpy(matrix: vtk.vtkMatrix4x4) -> np.ndarray:
    return np.array(
        [[matrix.GetElement(row, col) for col in range(4)] for row in range(4)],
        dtype=float,
    )


def _load_config(config_path=None) -> tuple[dict, Path]:
    override = config_path or os.environ.get("NHP_BRAIN_CONTACT_CONFIG")
    if not override:
        raise RuntimeError(
            "Provide an absolute brain-contact config path to generate(config_path), or set "
            "the NHP_BRAIN_CONTACT_CONFIG environment variable before running this script."
        )
    config_path = Path(override)
    if not config_path.is_absolute():
        raise ValueError("Brain-contact configuration path must be absolute")
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Configuration not found: {config_path}. Copy assets/brain-contact-config.example.json "
            "to a derivative case directory and complete it first."
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("brain-contact config schema_version must be 1")
    if config.get("status") != "UNVERIFIED_CANDIDATE":
        raise ValueError("brain-contact config status must remain UNVERIFIED_CANDIDATE")
    if config.get("research_only") is not True:
        raise ValueError("brain-contact config research_only must be true")
    if not str(config.get("subject_id", "")).strip():
        raise ValueError("brain-contact config subject_id is required")
    if config.get("input", {}).get("coordinate_system") != "3D Slicer world RAS millimetres":
        raise ValueError("input.coordinate_system must be '3D Slicer world RAS millimetres'")
    return config, config_path


def _markup_world_point(node, index: int) -> np.ndarray:
    point = [0.0, 0.0, 0.0]
    node.GetNthControlPointPositionWorld(index, point)
    return np.asarray(point, dtype=float)


def _input_points(config: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str]:
    input_cfg = config["input"]
    mode = input_cfg.get("mode", "coordinates")
    if mode == "coordinates":
        p0 = _as_vec3(input_cfg.get("diagonal_point_0_ras_mm"), "diagonal_point_0_ras_mm")
        p2 = _as_vec3(input_cfg.get("diagonal_point_2_ras_mm"), "diagonal_point_2_ras_mm")
        line0 = _as_vec3(input_cfg.get("direction_line_start_ras_mm"), "direction_line_start_ras_mm")
        line1 = _as_vec3(input_cfg.get("direction_line_end_ras_mm"), "direction_line_end_ras_mm")
        return p0, p2, line0, line1, "coordinates"

    if mode == "markups":
        diagonal_name = input_cfg.get("diagonal_markup_node_name")
        direction_name = input_cfg.get("direction_line_node_name")
        diagonal = slicer.mrmlScene.GetFirstNodeByName(diagonal_name)
        direction = slicer.mrmlScene.GetFirstNodeByName(direction_name)
        if not diagonal or diagonal.GetNumberOfControlPoints() != 2:
            raise RuntimeError(f"Markup {diagonal_name!r} must exist and contain exactly two points")
        if not direction or direction.GetNumberOfControlPoints() != 2:
            raise RuntimeError(f"Direction line {direction_name!r} must exist and contain exactly two points")
        if diagonal.GetParentTransformNode() or direction.GetParentTransformNode():
            raise RuntimeError("Input markup nodes must not have parent transforms")
        return (
            _markup_world_point(diagonal, 0),
            _markup_world_point(diagonal, 1),
            _markup_world_point(direction, 0),
            _markup_world_point(direction, 1),
            "markups",
        )

    raise ValueError("input.mode must be 'coordinates' or 'markups'")


def _brain_mask_node(config: dict):
    mask_cfg = config["brain_mask"]
    node_name = mask_cfg.get("node_name")
    if node_name:
        node = slicer.mrmlScene.GetFirstNodeByName(node_name)
        if node:
            return node, False

    path_value = mask_cfg.get("path")
    if not path_value:
        raise RuntimeError("Brain-mask node was not found and brain_mask.path is empty")
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("brain_mask.path must be absolute")
    if not path.is_file():
        raise FileNotFoundError(f"Brain mask not found: {path}")
    node = slicer.util.loadVolume(str(path))
    if not node:
        raise RuntimeError(f"3D Slicer could not load the brain mask: {path}")
    node.SetName("Brain mask source for contact generator (UNVERIFIED_CANDIDATE)")
    node.SetAttribute("CandidateStatus", "UNVERIFIED_CANDIDATE")
    return node, True


def _bound_mask_storage(mask_node, expected_hash: str) -> tuple[Path, str]:
    expected = str(expected_hash or "").strip()
    if len(expected) != 64 or any(character not in "0123456789abcdefABCDEF" for character in expected):
        raise ValueError("brain_mask.sha256 must be a 64-character SHA-256")
    storage = mask_node.GetStorageNode()
    if not storage or not storage.GetFileName():
        raise RuntimeError("Brain-mask node must have a readable storage file for hash binding")
    source_path = Path(storage.GetFullNameFromFileName())
    if not source_path.is_file():
        raise FileNotFoundError(f"Brain-mask storage file not found: {source_path}")
    observed = _sha256(source_path)
    if observed.casefold() != expected.casefold():
        raise RuntimeError(
            f"Brain-mask SHA-256 mismatch: expected {expected.upper()}, observed {observed}"
        )
    return source_path, observed


def _sample_mask(points_ras: np.ndarray, ras_to_ijk: np.ndarray, mask_zyx: np.ndarray) -> np.ndarray:
    points = np.asarray(points_ras, dtype=float).reshape(-1, 3)
    ijk = points @ ras_to_ijk[:3, :3].T + ras_to_ijk[:3, 3]
    rounded = np.rint(ijk).astype(np.int64)
    size_k, size_j, size_i = mask_zyx.shape
    in_bounds = (
        (rounded[:, 0] >= 0)
        & (rounded[:, 0] < size_i)
        & (rounded[:, 1] >= 0)
        & (rounded[:, 1] < size_j)
        & (rounded[:, 2] >= 0)
        & (rounded[:, 2] < size_k)
    )
    result = np.zeros(points.shape[0], dtype=bool)
    valid = rounded[in_bounds]
    result[in_bounds] = mask_zyx[valid[:, 2], valid[:, 1], valid[:, 0]]
    return result


def _ray_first_hits(
    top_points: np.ndarray,
    direction: np.ndarray,
    ras_to_ijk: np.ndarray,
    mask_zyx: np.ndarray,
    step_mm: float,
    max_distance_mm: float,
    binary_refinement_iterations: int,
) -> tuple[np.ndarray, np.ndarray]:
    flat_top = top_points.reshape(-1, 3)
    if np.any(_sample_mask(flat_top, ras_to_ijk, mask_zyx)):
        count = int(np.count_nonzero(_sample_mask(flat_top, ras_to_ijk, mask_zyx)))
        raise RuntimeError(
            f"The top rectangle is not fully outside the brain mask: {count} sampled top points are inside"
        )

    count = flat_top.shape[0]
    hit = np.zeros(count, dtype=bool)
    t_low = np.zeros(count, dtype=float)
    t_high = np.full(count, np.nan, dtype=float)
    number_of_steps = int(math.ceil(max_distance_mm / step_mm))

    for step_index in range(1, number_of_steps + 1):
        active_indices = np.flatnonzero(~hit)
        if active_indices.size == 0:
            break
        distance = min(step_index * step_mm, max_distance_mm)
        sample_points = flat_top[active_indices] + distance * direction
        inside = _sample_mask(sample_points, ras_to_ijk, mask_zyx)
        newly_hit = active_indices[inside]
        if newly_hit.size:
            hit[newly_hit] = True
            t_low[newly_hit] = max(0.0, distance - step_mm)
            t_high[newly_hit] = distance

    hit_indices = np.flatnonzero(hit)
    for _ in range(binary_refinement_iterations):
        midpoint = (t_low[hit_indices] + t_high[hit_indices]) / 2.0
        sample_points = flat_top[hit_indices] + midpoint[:, None] * direction
        inside = _sample_mask(sample_points, ras_to_ijk, mask_zyx)
        t_high[hit_indices[inside]] = midpoint[inside]
        t_low[hit_indices[~inside]] = midpoint[~inside]

    return t_high.reshape(top_points.shape[:2]), hit.reshape(top_points.shape[:2])


def _odd_window(window_mm: float, spacing_mm: float) -> int:
    size = max(1, int(math.ceil(window_mm / spacing_mm)))
    if size % 2 == 0:
        size += 1
    return size


def _clean_polydata(polydata: vtk.vtkPolyData) -> vtk.vtkPolyData:
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputData(polydata)
    triangles.Update()
    cleaner = vtk.vtkCleanPolyData()
    cleaner.SetInputConnection(triangles.GetOutputPort())
    cleaner.Update()
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(cleaner.GetOutputPort())
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOff()
    normals.Update()
    output = vtk.vtkPolyData()
    output.DeepCopy(normals.GetOutput())
    return output


def _add_triangle(polys: vtk.vtkCellArray, a: int, b: int, c: int) -> None:
    triangle = vtk.vtkTriangle()
    triangle.GetPointIds().SetId(0, a)
    triangle.GetPointIds().SetId(1, b)
    triangle.GetPointIds().SetId(2, c)
    polys.InsertNextCell(triangle)


def _surface_polydata(points_grid: np.ndarray, reverse: bool = False) -> vtk.vtkPolyData:
    rows, cols, _ = points_grid.shape
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(rows * cols)
    for row in range(rows):
        for col in range(cols):
            points.SetPoint(row * cols + col, *[float(v) for v in points_grid[row, col]])
    polys = vtk.vtkCellArray()
    for row in range(rows - 1):
        for col in range(cols - 1):
            p00 = row * cols + col
            p10 = row * cols + col + 1
            p01 = (row + 1) * cols + col
            p11 = (row + 1) * cols + col + 1
            if reverse:
                _add_triangle(polys, p00, p11, p10)
                _add_triangle(polys, p00, p01, p11)
            else:
                _add_triangle(polys, p00, p10, p11)
                _add_triangle(polys, p00, p11, p01)
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetPolys(polys)
    return _clean_polydata(polydata)


def _closed_solid_polydata(top_grid: np.ndarray, bottom_grid: np.ndarray) -> vtk.vtkPolyData:
    rows, cols, _ = top_grid.shape
    layer_size = rows * cols
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(2 * layer_size)

    def point_id(layer: int, row: int, col: int) -> int:
        return layer * layer_size + row * cols + col

    for row in range(rows):
        for col in range(cols):
            points.SetPoint(point_id(0, row, col), *[float(v) for v in bottom_grid[row, col]])
            points.SetPoint(point_id(1, row, col), *[float(v) for v in top_grid[row, col]])

    polys = vtk.vtkCellArray()
    for row in range(rows - 1):
        for col in range(cols - 1):
            b00 = point_id(0, row, col)
            b10 = point_id(0, row, col + 1)
            b01 = point_id(0, row + 1, col)
            b11 = point_id(0, row + 1, col + 1)
            _add_triangle(polys, b00, b11, b10)
            _add_triangle(polys, b00, b01, b11)

            t00 = point_id(1, row, col)
            t10 = point_id(1, row, col + 1)
            t01 = point_id(1, row + 1, col)
            t11 = point_id(1, row + 1, col + 1)
            _add_triangle(polys, t00, t10, t11)
            _add_triangle(polys, t00, t11, t01)

    for col in range(cols - 1):
        for row in (0, rows - 1):
            b0 = point_id(0, row, col)
            b1 = point_id(0, row, col + 1)
            t0 = point_id(1, row, col)
            t1 = point_id(1, row, col + 1)
            if row == 0:
                _add_triangle(polys, b0, b1, t1)
                _add_triangle(polys, b0, t1, t0)
            else:
                _add_triangle(polys, b0, t1, b1)
                _add_triangle(polys, b0, t0, t1)

    for row in range(rows - 1):
        for col in (0, cols - 1):
            b0 = point_id(0, row, col)
            b1 = point_id(0, row + 1, col)
            t0 = point_id(1, row, col)
            t1 = point_id(1, row + 1, col)
            if col == 0:
                _add_triangle(polys, b0, t1, b1)
                _add_triangle(polys, b0, t0, t1)
            else:
                _add_triangle(polys, b0, b1, t1)
                _add_triangle(polys, b0, t1, t0)

    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetPolys(polys)
    return _clean_polydata(polydata)


def _mesh_edge_counts(polydata: vtk.vtkPolyData) -> tuple[int, int]:
    boundary = vtk.vtkFeatureEdges()
    boundary.SetInputData(polydata)
    boundary.BoundaryEdgesOn()
    boundary.FeatureEdgesOff()
    boundary.ManifoldEdgesOff()
    boundary.NonManifoldEdgesOff()
    boundary.Update()

    nonmanifold = vtk.vtkFeatureEdges()
    nonmanifold.SetInputData(polydata)
    nonmanifold.BoundaryEdgesOff()
    nonmanifold.FeatureEdgesOff()
    nonmanifold.ManifoldEdgesOff()
    nonmanifold.NonManifoldEdgesOn()
    nonmanifold.Update()
    return boundary.GetOutput().GetNumberOfCells(), nonmanifold.GetOutput().GetNumberOfCells()


def _bounds_array(polydata: vtk.vtkPolyData) -> np.ndarray:
    return np.asarray(polydata.GetBounds(), dtype=float)


def _reload_model_bounds(path: Path, expected: vtk.vtkPolyData) -> float:
    """Verify Slicer's on-disk LPS convention round-trips back to the same RAS bounds."""
    reloaded = slicer.util.loadModel(str(path))
    if not reloaded:
        raise RuntimeError(f"Failed to reload saved model: {path}")
    try:
        observed = _bounds_array(reloaded.GetPolyData())
        difference = float(np.max(np.abs(observed - _bounds_array(expected))))
    finally:
        slicer.mrmlScene.RemoveNode(reloaded)
    if difference > 0.01:
        raise RuntimeError(
            f"Saved model failed RAS/LPS round-trip validation: {path}; max bounds error={difference:.6f} mm"
        )
    return difference


def _add_model(polydata: vtk.vtkPolyData, name: str, color, opacity: float, visible: bool, attrs: dict):
    node = slicer.modules.models.logic().AddModel(polydata)
    node.SetName(name)
    for key, value in attrs.items():
        node.SetAttribute(key, str(value))
    display = node.GetDisplayNode()
    display.SetColor(*color)
    display.SetOpacity(opacity)
    display.SetVisibility(visible)
    display.SetVisibility2D(False)
    return node


def _add_input_markups(run_name: str, corners: list[np.ndarray], line0: np.ndarray, line1: np.ndarray, attrs: dict):
    footprint = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLMarkupsFiducialNode", f"{run_name} input rectangle corners (UNVERIFIED)"
    )
    for index, point in enumerate(corners):
        control_index = footprint.AddControlPointWorld(vtk.vtkVector3d(*[float(v) for v in point]))
        footprint.SetNthControlPointLabel(control_index, f"corner_{index}")
    direction = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLMarkupsLineNode", f"{run_name} projection direction (UNVERIFIED)"
    )
    for label, point in (("outside_start", line0), ("toward_brain", line1)):
        control_index = direction.AddControlPointWorld(vtk.vtkVector3d(*[float(v) for v in point]))
        direction.SetNthControlPointLabel(control_index, label)
    for node in (footprint, direction):
        for key, value in attrs.items():
            node.SetAttribute(key, str(value))
    return footprint, direction


def generate(config_path=None) -> dict:
    config, config_path = _load_config(config_path)
    config_hash = _canonical_config_hash(config)
    p0, p2, line0, line1, input_mode = _input_points(config)
    direction = _unit(line1 - line0, "projection direction line")
    reference = _unit(_as_vec3(config["geometry"]["plane_u_reference_ras"], "plane_u_reference_ras"), "plane U reference")
    u_axis_unscaled = reference - float(np.dot(reference, direction)) * direction
    if np.linalg.norm(u_axis_unscaled) < 1e-6:
        raise RuntimeError("plane_u_reference_ras is parallel to the projection direction; choose another reference axis")
    u_axis = _unit(u_axis_unscaled, "projected plane U axis")
    v_axis = _unit(np.cross(u_axis, direction), "plane V axis")
    effective_geometry_input = {
        "coordinate_system": "3D Slicer world RAS millimetres",
        "diagonal_point_0_ras_mm": p0.tolist(),
        "diagonal_point_2_ras_mm": p2.tolist(),
        "direction_line_start_ras_mm": line0.tolist(),
        "direction_line_end_ras_mm": line1.tolist(),
        "plane_u_reference_ras": reference.tolist(),
    }
    effective_geometry_hash = _canonical_payload_hash(effective_geometry_input)

    diagonal = p2 - p0
    plane_error = float(np.dot(diagonal, direction))
    tolerance = float(config["geometry"]["max_diagonal_plane_error_mm"])
    if abs(plane_error) > tolerance:
        raise RuntimeError(
            f"The diagonal points are not on one plane perpendicular to the projection direction: "
            f"error={plane_error:.4f} mm, tolerance={tolerance:.4f} mm"
        )

    center = (p0 + p2) / 2.0
    p0_planar = p0 + 0.5 * plane_error * direction
    p2_planar = p2 - 0.5 * plane_error * direction
    planar_diagonal = p2_planar - p0_planar
    width_u = abs(float(np.dot(planar_diagonal, u_axis)))
    width_v = abs(float(np.dot(planar_diagonal, v_axis)))
    minimum_side = float(config["geometry"]["minimum_side_length_mm"])
    if width_u < minimum_side or width_v < minimum_side:
        raise RuntimeError(
            f"Degenerate rectangle after projection: U={width_u:.3f} mm, V={width_v:.3f} mm; "
            f"each side must be at least {minimum_side:.3f} mm"
        )

    requested_sampling = float(config["sampling"]["grid_spacing_mm"])
    if requested_sampling <= 0:
        raise ValueError("sampling.grid_spacing_mm must be positive")
    cols = max(2, int(math.ceil(width_u / requested_sampling)) + 1)
    rows = max(2, int(math.ceil(width_v / requested_sampling)) + 1)
    u_values = np.linspace(-width_u / 2.0, width_u / 2.0, cols)
    v_values = np.linspace(-width_v / 2.0, width_v / 2.0, rows)
    actual_u_spacing = width_u / (cols - 1)
    actual_v_spacing = width_v / (rows - 1)
    uu, vv = np.meshgrid(u_values, v_values)
    top_grid = center + uu[..., None] * u_axis + vv[..., None] * v_axis

    mask_node, mask_loaded_by_script = _brain_mask_node(config)
    if mask_node.GetParentTransformNode():
        raise RuntimeError("Brain-mask node has a parent transform; harden/correct it into MRI world before using this algorithm")
    mask_array = np.asarray(slicer.util.arrayFromVolume(mask_node))
    if mask_array.ndim != 3:
        raise RuntimeError(f"Brain mask must be a 3D volume, got shape {mask_array.shape}")
    threshold = float(config["brain_mask"].get("foreground_threshold", 0.5))
    mask_zyx = mask_array > threshold
    if not np.any(mask_zyx):
        raise RuntimeError("Brain mask contains no foreground voxels")
    mask_source_path, mask_source_hash = _bound_mask_storage(
        mask_node, config["brain_mask"].get("sha256")
    )
    ras_to_ijk_vtk = vtk.vtkMatrix4x4()
    mask_node.GetRASToIJKMatrix(ras_to_ijk_vtk)
    ras_to_ijk = _vtk_matrix_to_numpy(ras_to_ijk_vtk)

    ray_step = float(config["sampling"]["ray_step_mm"])
    max_projection_distance = float(config["sampling"]["max_projection_distance_mm"])
    refinement_iterations = int(config["sampling"]["binary_refinement_iterations"])
    if ray_step <= 0 or max_projection_distance <= 0 or refinement_iterations < 0:
        raise ValueError("ray step/distance must be positive and refinement iterations non-negative")
    raw_depth, hit_mask = _ray_first_hits(
        top_grid,
        direction,
        ras_to_ijk,
        mask_zyx,
        ray_step,
        max_projection_distance,
        refinement_iterations,
    )
    hit_coverage = float(hit_mask.mean())
    min_coverage = float(config["sampling"]["minimum_hit_coverage"])
    if not 0.0 < min_coverage <= 1.0:
        raise ValueError("sampling.minimum_hit_coverage must be in (0, 1]")
    allow_fill = bool(config["sampling"].get("allow_nearest_fill_for_misses", False))
    if hit_coverage < min_coverage:
        raise RuntimeError(
            f"Only {hit_coverage:.2%} of footprint rays hit the brain mask; required {min_coverage:.2%}"
        )
    if not np.all(hit_mask):
        if not allow_fill:
            raise RuntimeError(
                f"{int(np.size(hit_mask) - np.count_nonzero(hit_mask))} rays missed the brain mask. "
                "Nearest fill is disabled to prevent fabricated edge geometry."
            )
        missing = ~hit_mask
        nearest = ndimage.distance_transform_edt(missing, return_distances=False, return_indices=True)
        raw_depth[missing] = raw_depth[tuple(nearest[:, missing])]

    smoothing = config["smoothing"]
    window_mm = float(smoothing["outer_envelope_window_mm"])
    sigma_mm = float(smoothing["gaussian_sigma_mm"])
    if window_mm <= 0 or sigma_mm < 0:
        raise ValueError("outer_envelope_window_mm must be positive and gaussian_sigma_mm non-negative")
    window_rows = _odd_window(window_mm, actual_v_spacing)
    window_cols = _odd_window(window_mm, actual_u_spacing)
    outer_envelope = ndimage.minimum_filter(
        raw_depth,
        size=(window_rows, window_cols),
        mode="nearest",
    )
    smoothed_depth = ndimage.gaussian_filter(
        outer_envelope,
        sigma=(sigma_mm / actual_v_spacing, sigma_mm / actual_u_spacing),
        mode="nearest",
    )
    dura_offset = float(smoothing.get("dura_offset_mm", 0.0))
    if dura_offset < 0:
        raise ValueError("dura_offset_mm must be zero or positive")
    raw_safe_limit = raw_depth - dura_offset
    final_depth = np.minimum(smoothed_depth, raw_safe_limit)

    minimum_depth = float(config["geometry"]["minimum_block_depth_mm"])
    if float(np.min(final_depth)) < minimum_depth:
        raise RuntimeError(
            f"The top plane is too close to the brain/dura envelope: minimum generated depth "
            f"{float(np.min(final_depth)):.3f} mm is below required {minimum_depth:.3f} mm"
        )
    outside_margin = raw_depth - final_depth
    if float(np.min(outside_margin)) < dura_offset - 1e-6:
        raise RuntimeError("Internal safety check failed: smoothed surface would pass inside the permitted envelope")

    bottom_grid = top_grid + final_depth[..., None] * direction
    contact_surface = _surface_polydata(bottom_grid, reverse=True)
    solid = _closed_solid_polydata(top_grid, bottom_grid)
    boundary_edges, nonmanifold_edges = _mesh_edge_counts(solid)
    if boundary_edges or nonmanifold_edges:
        raise RuntimeError(
            f"Closed-solid mesh QA failed: boundary_edges={boundary_edges}, nonmanifold_edges={nonmanifold_edges}"
        )

    output_cfg = config["output"]
    run_name = output_cfg["run_name"]
    if not run_name or Path(run_name).name != run_name:
        raise ValueError("output.run_name must be one non-empty directory name")
    output_root = Path(output_cfg["root"])
    if not output_root.is_absolute():
        raise ValueError("output.root must be an absolute derivative directory")
    run_dir = output_root / run_name
    if run_dir.exists() and any(run_dir.iterdir()) and not output_cfg.get("allow_overwrite", False):
        raise RuntimeError(f"Output directory already contains files and overwrite is disabled: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)

    attrs = {
        "CandidateStatus": "UNVERIFIED_CANDIDATE",
        "CoordinateSpace": "Slicer world RAS millimetres",
        "Algorithm": ALGORITHM_NAME,
        "AlgorithmVersion": ALGORITHM_VERSION,
        "ConfigSHA256": config_hash,
        "EffectiveGeometryInputSHA256": effective_geometry_hash,
        "ReviewRequired": "Brain-mask, contact mechanics, dura offset, and expert review required",
        "AcceptedForSurgicalUse": "false",
    }
    solid_node = _add_model(
        solid,
        f"{run_name} closed contact block (UNVERIFIED_CANDIDATE)",
        (0.10, 0.85, 0.95),
        0.82,
        True,
        attrs,
    )
    contact_node = _add_model(
        contact_surface,
        f"{run_name} contact surface only (UNVERIFIED_CANDIDATE)",
        (1.00, 0.35, 0.15),
        1.0,
        False,
        attrs,
    )

    corners = [
        center - width_u / 2.0 * u_axis - width_v / 2.0 * v_axis,
        center + width_u / 2.0 * u_axis - width_v / 2.0 * v_axis,
        center + width_u / 2.0 * u_axis + width_v / 2.0 * v_axis,
        center - width_u / 2.0 * u_axis + width_v / 2.0 * v_axis,
    ]
    footprint_node, direction_node = _add_input_markups(run_name, corners, line0, line1, attrs)

    solid_path = run_dir / f"{run_name}_closed_block_UNVERIFIED_CANDIDATE.stl"
    contact_path = run_dir / f"{run_name}_contact_surface_UNVERIFIED_CANDIDATE.stl"
    footprint_path = run_dir / f"{run_name}_input_rectangle_UNVERIFIED.mrk.json"
    direction_path = run_dir / f"{run_name}_projection_direction_UNVERIFIED.mrk.json"
    depth_maps_path = run_dir / f"{run_name}_depth_maps_raw_outer_gaussian_final_mm.npy"
    for node, path in (
        (solid_node, solid_path),
        (contact_node, contact_path),
        (footprint_node, footprint_path),
        (direction_node, direction_path),
    ):
        if not slicer.util.saveNode(node, str(path)):
            raise RuntimeError(f"Failed to save {path}")

    solid_reload_bounds_error = _reload_model_bounds(solid_path, solid)
    contact_reload_bounds_error = _reload_model_bounds(contact_path, contact_surface)
    np.save(
        depth_maps_path,
        np.stack((raw_depth, outer_envelope, smoothed_depth, final_depth), axis=0),
        allow_pickle=False,
    )

    report = {
        "status": "UNVERIFIED_CANDIDATE",
        "accepted_for_surgical_use": False,
        "subject_id": config["subject_id"],
        "research_warning": "Not a surgical implant, trajectory, craniotomy plan, pressure prescription, or safety clearance.",
        "algorithm": ALGORITHM_NAME,
        "algorithm_version": ALGORITHM_VERSION,
        "config_file": str(config_path),
        "config_sha256": config_hash,
        "effective_geometry_input_sha256": effective_geometry_hash,
        "input_mode": input_mode,
        "coordinate_system": "3D Slicer world RAS, millimetres",
        "diagonal_points_input_ras_mm": [p0.tolist(), p2.tolist()],
        "diagonal_plane_error_mm": plane_error,
        "projection_line_ras_mm": [line0.tolist(), line1.tolist()],
        "projection_direction_unit_ras": direction.tolist(),
        "plane_u_axis_unit_ras": u_axis.tolist(),
        "plane_v_axis_unit_ras": v_axis.tolist(),
        "rectangle_side_lengths_mm": {"u": width_u, "v": width_v},
        "grid": {
            "rows": rows,
            "columns": cols,
            "actual_u_spacing_mm": actual_u_spacing,
            "actual_v_spacing_mm": actual_v_spacing,
        },
        "brain_mask": {
            "node_name": mask_node.GetName(),
            "loaded_by_script": mask_loaded_by_script,
            "storage_path": str(mask_source_path),
            "sha256": mask_source_hash,
            "foreground_threshold": threshold,
            "ras_to_ijk": ras_to_ijk.tolist(),
        },
        "ray_cast": {
            "hit_coverage": hit_coverage,
            "raw_first_hit_depth_mm_min": float(np.min(raw_depth)),
            "raw_first_hit_depth_mm_max": float(np.max(raw_depth)),
        },
        "smoothing": {
            "method": "minimum-depth outer envelope, Gaussian smoothing, then no-penetration clamp",
            "outer_envelope_window_mm": window_mm,
            "outer_envelope_window_samples": [window_rows, window_cols],
            "gaussian_sigma_mm": sigma_mm,
            "dura_offset_mm_along_negative_projection_direction": dura_offset,
            "final_depth_mm_min": float(np.min(final_depth)),
            "final_depth_mm_max": float(np.max(final_depth)),
            "raw_minus_final_mm_min": float(np.min(outside_margin)),
            "raw_minus_final_mm_max": float(np.max(outside_margin)),
        },
        "mesh_qa": {
            "solid_points": solid.GetNumberOfPoints(),
            "solid_polygons": solid.GetNumberOfPolys(),
            "boundary_edges": boundary_edges,
            "nonmanifold_edges": nonmanifold_edges,
            "solid_stl_reload_max_bounds_error_mm": solid_reload_bounds_error,
            "contact_stl_reload_max_bounds_error_mm": contact_reload_bounds_error,
        },
        "outputs": {},
        "required_review": [
            "Verify the brain-mask boundary slice by slice under the entire rectangle.",
            "Verify the projection direction and all coordinates in the intended MRI world space.",
            "Measure and approve artificial-dura thickness/compression before using a nonzero offset.",
            "Review edge pressure, compression, hard stops, wall thickness, fixation, and manufacturing tolerance.",
        ],
    }
    for label, path in (
        ("closed_block_stl", solid_path),
        ("contact_surface_stl", contact_path),
        ("input_rectangle_markups", footprint_path),
        ("projection_direction_markups", direction_path),
        ("depth_maps_npy", depth_maps_path),
    ):
        report["outputs"][label] = {"path": str(path), "sha256": _sha256(path)}
    report["outputs"]["depth_maps_npy"]["layer_order"] = [
        "raw_first_hit_depth_mm",
        "minimum_filter_outer_envelope_depth_mm",
        "gaussian_smoothed_depth_before_clamp_mm",
        "final_no_penetration_clamped_depth_mm",
    ]

    report_path = run_dir / f"{run_name}_provenance_UNVERIFIED_CANDIDATE.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "run_directory": str(run_dir),
        "closed_block": str(solid_path),
        "contact_surface": str(contact_path),
        "provenance": str(report_path),
    }, indent=2, ensure_ascii=False))
    return report


if __name__ == "__main__":
    exit_when_done = os.environ.get("NHP_BRAIN_CONTACT_EXIT_WHEN_DONE") == "1"
    try:
        generate(os.environ.get("NHP_BRAIN_CONTACT_CONFIG"))
    except Exception:
        traceback.print_exc()
        if exit_when_done:
            slicer.app.exit(1)
        else:
            raise
    else:
        if exit_when_done:
            slicer.app.exit(0)
