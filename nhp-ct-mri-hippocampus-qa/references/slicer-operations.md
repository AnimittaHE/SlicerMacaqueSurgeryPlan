# 3D Slicer operations

## Import and inspection

- Import CT through the DICOM database when possible; record the selected series UID.
- Load MRI only after companion/header checks pass.
- Inspect Volumes information, IJK-to-RAS matrices, dimensions, spacing, scalar type, and full coverage.
- Keep source nodes read-only in practice by saving all derived data under a separate root.

## Registration

- Prefer BRAINSFit or SlicerElastix for standard rigid/affine registration when their behavior fits the protocol.
- Set fixed T1 MRI, moving CT, and explicit initialization.
- Save every transform as a separate node/file. Do not harden a transform onto the fixed MRI.
- For custom multi-start scripts, record all matrices and choose by a predeclared consensus rule.

## Visual QA

- Link slices and use foreground/background opacity flicker.
- Show edge or contour overlays at multiple levels.
- Capture full-volume axial/coronal/sagittal views plus temporal-lobe-focused views.
- In 3D, display a clearly labeled candidate bone/braincase surface and colored hippocampal candidates. Do not treat a thresholded skull surface as a safety-distance model.

## Segmentation

- Set MRI as the reference geometry.
- Use separate segments; preserve subregion labels for audit.
- Use nearest-neighbor when resampling labels.
- Display 2D fill/outline and 3D surfaces with transparent context, but verify voxel labels independently of rendering.

## Smooth skull-curvature model

- Use the selected existing smooth Skull closed surface. Audit stored labelmap geometry and parents together; registration may already be embedded in geometry.
- Record footprint corners, projection line, and in-plane reference vector in Slicer world RAS millimetres.
- Follow `references/skull-blender-modeling.md`: export world-space skull/prism, execute Blender Exact intersection, fit the inner-wall curvature and build a STEP solid with the requested minimum thickness.
- Keep the generated closed block and contact-only surface free of parent transforms. Save through Slicer so STL LPS storage round-trips to the same RAS position.
- Display the input rectangle, direction line, mask/brain context, registered skull context, and candidate together. Review the full footprint in linked slices.
- Record surface fitting and axial thickness independently from artificial-dura mechanics. Verify continuous extrema for minimum thickness and preserve the bottom during height-only edits.

## Cranial-landmark markups and CT rendering

- Review bony EAM and inferior orbital rim on the original thin-slice CT with bone window/level and volume rendering; do not rely on MRI globe or lens boundaries for orbitale.
- Keep native-CT candidate extraction in the original CT grid. Use the registered CT or its parent transform only for common-space visualization.
- For a markup already expressed in MRI world RAS, set no parent transform. For a markup expressed in native CT RAS, attach the CT-to-MRI transform only once and record that choice.
- Label all generated nodes `UNVERIFIED`; use coordinate-side A/B until biological laterality is confirmed.
- Show candidates in 2D and 3D with point labels, but also inspect voxel coordinates and source-space slices independently of rendering.
- Preserve old candidate nodes for audit outside the review scene. Do not leave competing hidden points in the packaged review scene.
- Create midpoint and line/axis nodes only from frozen common-space points. Store source point IDs, report hashes, coordinate convention, and candidate status as node attributes when practical.
- Save landmark markups explicitly as `.mrk.json`; saving only the `.mrml` scene is insufficient for a portable, auditable package.

## Headless Windows execution

Slicer command-line behavior varies by installation. A robust Windows pattern is:

```powershell
& 'C:\path\to\Slicer.exe' --no-splash --no-main-window --python-code "exec(open(r'C:\path\script.py', encoding='utf-8').read())"
```

Run GUI/headless Slicer only with required host permission. Confirm a script-created report or marker file; do not trust launcher exit code alone.

## Scene hygiene

- Remove processing history/CLI nodes, temporary masks, rejected candidates, and external storage references.
- Keep critical fixed MRI, registered CT, segmentation, world-coordinate landmark, and QA nodes without parent transforms.
- Save a self-contained scene, reload it, and enumerate every storage node.
- Validate arrays and geometry against the packaged files after reload.
