# Orientation and biological laterality

## Coordinate layers

- DICOM patient coordinates are normally LPS.
- 3D Slicer calculates in world RAS and converts DICOM/LPS on import.
- NIfTI uses an affine with qform/sform metadata; array index order is not biological orientation.
- Analyze `.img/.hdr` may lack a reliable world orientation. Never infer it from dimensions or screen appearance.
- Screen left/right depends on slice normal and radiological/neurological display convention.

Always distinguish voxel index axes, file/world coordinates, Slicer RAS labels, screen side, and the animal's biological side.

## Hard checks

- Compare qform and sform when present; stop on a material conflict.
- Record affine determinant and axis codes. A negative determinant alone does not prove a biological left-right error.
- Check orthogonal slices against known anterior/posterior, superior/inferior, and asymmetric structures.
- Verify physical side markers or acquisition records independently of the candidate registration.
- Treat user-annotated screenshots as evidence to investigate, not as metadata replacement.

## Prohibited shortcuts

- Do not swap or negate an axis because an overlay looks better.
- Do not name components anatomical left/right by RAS-X centroid alone.
- Do not pair lateralized CT/MRI TRE points until the same biological side is confirmed in both sources.
- Do not attach a corrective transform to the fixed MRI and then forget it in the saved scene.
- Do not name an ear-to-ear direction `ML`, an ear-to-orbit direction `AP`, or a plane normal `DV/SI` until axis signs have independent anatomical or frame evidence.

## Transform bookkeeping

Write direction explicitly:

`p_MRI_RAS = T_CT_to_MRI × p_CT_RAS`

For every node, record whether coordinates are native, transformed by a parent, hardened, or resampled. Reject any workflow in which the same transform may have been applied once through a parent and again numerically.

Assign the locked CT-to-MRI candidate one case-specific `binding_id`. Repeat that exact identifier in every downstream CT-landmark configuration and report. The identifier complements, but never replaces, exact file hashes, matrix values, node names, transform direction, and storage-file binding.

For a CT-derived landmark mapped numerically into MRI world RAS, clear its parent transform. For a native-CT landmark retained under the CT parent transform, do not pre-transform its coordinates. Store the exact point space and transform direction in the report and node attributes.

## Candidate frame labels

Until biological side and axis signs are confirmed, use:

- `ear_coordinate_side_A/B`;
- `orbitale_coordinate_side_A/B`;
- `ear_midpoint_candidate`;
- `side_A_to_B_axis_candidate`;
- `ear_mid_to_orbitale_mid_axis_candidate`;
- `plane_normal_candidate`.

Slicer world RAS axis names describe the image world, not the stereotactic apparatus. A candidate frame must be expressed as an origin plus an orthonormal basis in one physical space; raw RAS component differences are not AP/ML/DV coordinates unless the image has been rigidly aligned to that confirmed basis.

## Laterality record

Require status `CONFIRMED`, confirmer and role, date, evidence, CT and MRI biological-left identification, and unresolved conflicts before anatomical side labels. Until then, use `coordinate_side_A/B` and add a visible warning.
